"""Hybrid retrieval over the knowledge base: dense cosine + BM25, fused with reciprocal rank fusion.

Only chunks of *current* source versions whose source ``review_status`` is in
``allowed_statuses`` are candidates; ``blocked`` sources are never returned, whatever the
caller passes. Dense scores are cosine similarities between the query embedding and
``Chunk.embedding`` (computed in numpy over the candidates; the SQLite path is the one
tests cover). Lexical scores are BM25Okapi (k1=1.5, b=0.75) over ``tokenize(heading_path + text)``.
The two rankings are fused with RRF (k=60) and the fused score is multiplied by 1.3 for
chunks whose language matches the query language (sr/bs/me/hr count as one family).
"""

from __future__ import annotations

import logging
import math
from collections import Counter
from dataclasses import dataclass

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.config import Settings
from app.core.i18n import is_bcms, tokenize
from app.core.types import RetrievedChunk
from app.kb.embed import Embedder
from app.models import Chunk, Source, SourceVersion

log = logging.getLogger("mila.retrieval")

RRF_K = 60
_IDF_CACHE: dict[tuple, object] = {}
LANG_BOOST = 1.3
BM25_K1 = 1.5
BM25_B = 0.75
_NEVER_RETURNED = ("blocked",)


class BM25Okapi:
    """BM25 (Okapi) with the non-negative ``log(1 + (N - n + 0.5) / (n + 0.5))`` idf."""

    def __init__(self, corpus: list[list[str]], k1: float = BM25_K1, b: float = BM25_B) -> None:
        self.k1 = k1
        self.b = b
        self.doc_freqs: list[Counter[str]] = [Counter(doc) for doc in corpus]
        self.doc_lens = [len(doc) for doc in corpus]
        n_docs = len(corpus)
        self.avg_len = (sum(self.doc_lens) / n_docs) if n_docs else 0.0
        df: Counter[str] = Counter()
        for freqs in self.doc_freqs:
            df.update(freqs.keys())
        self.idf = {term: math.log(1.0 + (n_docs - n + 0.5) / (n + 0.5)) for term, n in df.items()}

    def get_scores(self, query: list[str]) -> list[float]:
        """BM25 score of every corpus document for the query tokens (0.0 when nothing matches)."""
        scores = [0.0] * len(self.doc_freqs)
        if not self.doc_freqs or not query:
            return scores
        for term in query:
            idf = self.idf.get(term)
            if idf is None:
                continue
            for idx, freqs in enumerate(self.doc_freqs):
                tf = freqs.get(term, 0)
                if not tf:
                    continue
                norm = 1.0 - self.b + self.b * (self.doc_lens[idx] / self.avg_len if self.avg_len else 0.0)
                scores[idx] += idf * tf * (self.k1 + 1.0) / (tf + self.k1 * norm)
        return scores


Ranking = list[tuple[int, float]]  # (candidate index, score), best first


def reciprocal_rank_fusion(rankings: list[Ranking], k: int = RRF_K) -> dict[int, float]:
    """Fuse score-ordered ``(index, score)`` lists: ``score(i) = sum over lists of 1 / (k + rank_i)``.

    Equal scores share a rank (competition ranking 1, 1, 3), so candidates that are
    indistinguishable to a ranker fuse to identical values and the order between them is
    left to the language boost and the deterministic tie-break on chunk id.
    """
    fused: dict[int, float] = {}
    for ranking in rankings:
        rank = 0
        previous: float | None = None
        for position, (idx, score) in enumerate(ranking, start=1):
            if previous is None or score != previous:
                rank = position
                previous = score
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (k + rank)
    return fused


def same_language_family(a: str, b: str) -> bool:
    return a == b or (is_bcms(a) and is_bcms(b))


@dataclass
class _Candidate:
    chunk: Chunk
    source: Source
    version: SourceVersion


class Retriever:
    """Hybrid (dense + BM25, RRF-fused) retriever over current, allowed knowledge-base chunks."""

    def __init__(self, db: DbSession, embedder: Embedder, settings: Settings) -> None:
        self.db = db
        self.embedder = embedder
        self.settings = settings

    def default_statuses(self) -> tuple[str, ...]:
        return ("reviewed", "public_unreviewed") if self.settings.demo_mode else ("reviewed",)

    def _candidates(self, statuses: tuple[str, ...], topic: str | None) -> list[_Candidate]:
        stmt = (
            select(Chunk, Source, SourceVersion)
            .join(SourceVersion, Chunk.version_id == SourceVersion.id)
            .join(Source, Chunk.source_id == Source.id)
            .where(SourceVersion.is_current)
            .where(Source.review_status.in_(statuses))
            .order_by(Chunk.id)
        )
        rows = [_Candidate(chunk=c, source=s, version=v) for c, s, v in self.db.execute(stmt).all()]
        if topic:
            # Sources that declare topics are restricted to them; sources with no declared topics
            # always qualify. A topic with no matching source falls back to the full candidate set,
            # so a wrong keyword classification cannot empty the retrieval.
            on_topic = [r for r in rows if not r.source.allowed_topics or topic in r.source.allowed_topics]
            if on_topic:
                rows = on_topic
        return rows

    def _dense_ranking(self, query: str, rows: list[_Candidate]) -> Ranking:
        dim = self.embedder.dim
        usable = [i for i, r in enumerate(rows) if r.chunk.embedding and len(r.chunk.embedding) == dim]
        if not usable:
            if rows:
                log.warning("retrieval: no chunk embeddings of dim %d; using BM25 only", dim)
            return []
        query_vec = np.asarray(self.embedder.embed([query])[0], dtype=np.float64)
        q_norm = float(np.linalg.norm(query_vec))
        if q_norm == 0.0:
            return []
        matrix = np.asarray([rows[i].chunk.embedding for i in usable], dtype=np.float64)
        norms = np.linalg.norm(matrix, axis=1)
        norms[norms == 0.0] = 1.0
        sims = (matrix @ query_vec) / (norms * q_norm)
        order = sorted(range(len(usable)), key=lambda j: (-float(sims[j]), usable[j]))
        return [(usable[j], float(sims[j])) for j in order]

    def stem_idf(self, allowed_statuses: tuple[str, ...] | None = None):
        """Inverse document frequency over 5-character stems of every current chunk.

        Used by :mod:`app.core.relevance`. Cached per (database, chunk count, newest version)
        so the corpus is tokenised once per ingest, not once per request.
        """
        from app.core.relevance import make_idf, stems

        wanted = self.default_statuses() if allowed_statuses is None else allowed_statuses
        statuses = tuple(s for s in wanted if s not in _NEVER_RETURNED)
        bind = self.db.get_bind()
        n_chunks = self.db.execute(select(func.count(Chunk.id))).scalar_one()
        newest = self.db.execute(select(func.max(SourceVersion.id))).scalar_one()
        key = (str(getattr(bind, "url", bind)), statuses, int(n_chunks or 0), int(newest or 0))
        cached = _IDF_CACHE.get(key)
        if cached is not None:
            return cached
        rows = self._candidates(statuses, None)
        idf = make_idf(stems(f"{r.chunk.heading_path} {r.chunk.text}") for r in rows)
        if len(_IDF_CACHE) >= 8:
            _IDF_CACHE.clear()
        _IDF_CACHE[key] = idf
        return idf

    @staticmethod
    def _bm25_ranking(query_tokens: list[str], rows: list[_Candidate]) -> Ranking:
        corpus = [tokenize(f"{r.chunk.heading_path} {r.chunk.text}") for r in rows]
        scores = BM25Okapi(corpus).get_scores(query_tokens)
        scored = [i for i, s in enumerate(scores) if s > 0.0]
        return [(i, scores[i]) for i in sorted(scored, key=lambda i: (-scores[i], i))]

    def search(
        self,
        query: str,
        *,
        lang: str | None = None,
        top_k: int | None = None,
        allowed_statuses: tuple[str, ...] | None = None,
        topic: str | None = None,
    ) -> list[RetrievedChunk]:
        """Return the ``top_k`` best chunks for ``query`` (default ``settings.retrieval_top_k``)."""
        if not query or not query.strip():
            return []
        wanted = self.default_statuses() if allowed_statuses is None else allowed_statuses
        statuses = tuple(s for s in wanted if s not in _NEVER_RETURNED)
        if not statuses:
            return []
        limit = top_k if top_k is not None else self.settings.retrieval_top_k
        if limit <= 0:
            return []
        rows = self._candidates(statuses, topic)
        if not rows:
            return []

        rankings = [self._dense_ranking(query, rows), self._bm25_ranking(tokenize(query), rows)]
        fused = reciprocal_rank_fusion([r for r in rankings if r])
        if lang:
            for idx in fused:
                if same_language_family(rows[idx].chunk.lang, lang):
                    fused[idx] *= LANG_BOOST
        ordered = sorted(fused, key=lambda i: (-fused[i], rows[i].chunk.id))[:limit]
        return [self._to_retrieved(rows[i], fused[i]) for i in ordered]

    @staticmethod
    def _to_retrieved(row: _Candidate, score: float) -> RetrievedChunk:
        return RetrievedChunk(
            chunk_id=row.chunk.id,
            source_id=row.source.id,
            source_title=row.source.title,
            source_version=row.version.version_hash[:8],
            published_on=row.version.published_on or "",
            page=row.chunk.page,
            heading_path=row.chunk.heading_path or "",
            text=row.chunk.text,
            lang=row.chunk.lang,
            score=round(score, 6),
            review_status=row.source.review_status,
        )
