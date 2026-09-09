"""Grounded answers or refusal — innovation claim #2.

Pipeline of :func:`ask`:

1. **Language** — ``lang`` from the request, otherwise a small deterministic heuristic
   (diacritics č ć š ž đ or common Montenegrin function words → ``cnr``, else ``en``).
   The answer (or the refusal) is in the question's language.
2. **Retrieval** — the question is embedded with the configured provider and matched against
   ``entry_chunks`` by pgvector cosine distance. The query runs through the *visitor* DB role
   (row-level security → approved entries only) **and** applies ``validation.approved_only``
   (belt and braces). Chunks in the question's language are preferred through a small ranking
   bonus; the other language is not excluded.
3. **Confidence gate** — deterministic and provider-agnostic. The chunk that would be cited must
   satisfy ``similarity ≥ min_similarity()`` **and** ``coverage ≥ settings.rag_min_coverage``.
   Coverage is the IDF-weighted share of the question's content-word stems that occur in the
   chunk (stems = first ``STEM_LEN`` characters of a diacritic-folded token, which handles
   inflection such as fešta/fešte, crkva/crkve, century/centuries).
4. **Answer** — with an LLM configured, the model phrases the answer from numbered sources and
   cites them as ``[n]``; a ``NOT_IN_SOURCES`` reply is a refusal (``llm_declined``). Without an
   LLM (``LLM_PROVIDER=none``) or when it is unavailable, the answer is *extractive*: the 1–2
   most relevant sentences of the best chunk(s), each followed by ``[n]``.
5. **Events** — ``answer_served`` / ``answer_withheld`` are written with the application engine
   (the visitor role cannot write). They carry a hash and the length of the question, never the
   question text itself.

:func:`run_grounding_test` runs the 30-question set in ``seed_data/grounding_questions.json``
through exactly the same function and writes an auditable report (JSON + Markdown).
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import statistics
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import BACKEND_DIR, PROTOTYPE_LABEL, settings
from ..db import PublicSessionLocal
from ..events import emit_event
from ..models import EntryChunk, HeritageEntry
from ..providers import embeddings as embeddings_provider
from ..providers.embeddings import content_tokens, get_embeddings, normalize
from ..providers.llm import LLMUnavailable, get_llm, llm_enabled
from ..schemas import Citation
from .validation import approved_only

log = logging.getLogger(__name__)

# --- constants -----------------------------------------------------------------------------
LOCAL_LANG: str = settings.local_language  # "cnr" — Montenegrin, Latin script
SUPPORTED_LANGS: tuple[str, str] = (LOCAL_LANG, "en")
CHUNK_LANG_BY_QUESTION_LANG: dict[str, str] = {LOCAL_LANG: "local", "en": "en"}
QUESTION_LANG_BY_CHUNK_LANG: dict[str, str] = {"local": LOCAL_LANG, "en": "en"}
LANGUAGE_NAMES: dict[str, str] = {LOCAL_LANG: "Montenegrin (Latin script)", "en": "English"}

#: Default similarity threshold for the offline ``hash`` embeddings provider. Calibrated on the
#: 30-question grounding set (see docs/grounding.md and docs/test-results/grounding_results.md).
#: It overrides ``providers.embeddings.DEFAULT_MIN_SIMILARITY["hash"]`` only while
#: ``settings.rag_min_similarity`` is unset; move it there once agreed.
HASH_DEFAULT_MIN_SIMILARITY: float = 0.30
#: Ranking bonus for chunks written in the question's language (ranking only, not the gate).
LANG_PREFERENCE_BONUS: float = 0.05
#: Weight of lexical coverage in the ranking score (breaks near-ties in favour of the chunk that
#: actually contains the question's words; the gate still uses the raw signals).
COVERAGE_RANK_WEIGHT: float = 0.10
#: Tokens are compared on their first STEM_LEN characters (inflection-tolerant matching).
STEM_LEN: int = 4
MAX_EXCERPT_CHARS: int = 200
MAX_ANSWER_SENTENCES: int = 2
MAX_LLM_SOURCES: int = 4
NOT_IN_SOURCES: str = "NOT_IN_SOURCES"

REFUSAL_REASON_LOW_CONFIDENCE = "low_confidence"
REFUSAL_REASON_NO_SOURCE = "no_approved_source"
REFUSAL_REASON_LLM_DECLINED = "llm_declined"

REFUSAL_MESSAGES: dict[str, str] = {
    LOCAL_LANG: (
        "Nemam potvrđen izvor za ovo pitanje. "
        "Odgovaram samo na osnovu odobrenih unosa o Gornjoj Lastvi i Vrmcu."
    ),
    "en": (
        "I have no validated source for this question. "
        "I only answer from approved entries about Gornja Lastva and Vrmac."
    ),
}

#: Question words that ``providers.embeddings._STOPWORDS`` does not cover. They carry no
#: information about *what* is asked, so they are excluded from coverage scoring.
EXTRA_STOPWORDS: frozenset[str] = frozenset(
    {
        # Montenegrin / Serbian / Croatian (diacritics folded)
        "kojoj", "kojem", "kojim", "kojih", "koju", "koga", "kojom", "cija", "ciji", "cije", "cijem",
        "zasto", "otkad", "otkada", "kuda", "odakle", "dokle", "dokad", "dokada", "kolikoj", "kolikih",
        "kolike", "koliku", "ce", "biti", "bice", "bit", "nam", "nas", "vam", "vas", "ih", "im", "ga",
        "mu", "joj", "tu", "tamo", "ovdje", "ovde", "evo", "eto", "dakle", "zar", "jel", "jeli",
        # English
        "should", "could", "would", "will", "have", "has", "had", "been", "being", "am", "into",
        "onto", "than", "then", "so", "if", "not", "no", "yes", "up", "down", "out", "just", "also",
        "very", "really", "exactly", "like",
    }
)

_DIACRITICS = frozenset("čćšžđČĆŠŽĐ")
_CNR_HINTS = frozenset(
    {
        "je", "li", "da", "se", "su", "sam", "smo", "ste", "kada", "kad", "gdje", "gde", "koliko",
        "koji", "koja", "koje", "kojoj", "kojeg", "kog", "sta", "kako", "zasto", "ima", "od", "do",
        "za", "na", "u", "i", "ili", "godine", "godina", "vijeka", "crkva", "koju", "ko", "ne", "biti",
        "bio", "bila", "ce", "nalazi", "kojem", "kojim", "iz", "sa", "po", "prema", "danas", "sutra",
    }
)
_EN_HINTS = frozenset(
    {
        "the", "is", "are", "what", "when", "where", "which", "who", "how", "does", "do", "did", "of",
        "in", "on", "to", "a", "an", "and", "was", "were", "many", "much", "from", "at", "for", "it",
        "there", "that", "this", "with", "have", "has", "can", "will", "be", "by", "or", "any", "today",
        "tomorrow", "since", "until",
    }
)

# Sentence boundary: punctuation + whitespace + an upper-case/quote/digit start. Does not split
# after 1–2 digit ordinals ("14. vijeka", "7. avgusta", "53. fešta") nor after "Sv."/"St.".
_SENTENCE_SPLIT = re.compile(
    r"(?<=[.!?])(?<!\b\d\.)(?<!\b\d\d\.)(?<!\bSv\.)(?<!\bsv\.)(?<!\bSt\.)\s+(?=[\"„“(A-ZČĆŠŽĐ0-9])"
)
_CITATION_MARKER = re.compile(r"\[(\d+)\]")

SYSTEM_PROMPT = (
    "You are the visitor assistant of the Vrmac Living Heritage prototype (Gornja Lastva, Vrmac, "
    "Montenegro). Answer the question using ONLY the numbered sources provided by the user. "
    "After every claim add the number of the source it comes from in square brackets, e.g. [1]. "
    "Never use knowledge that is not in the sources and never guess. "
    f"If the sources do not contain the answer, reply with exactly {NOT_IN_SOURCES} and nothing else. "
    "Answer in {language}, in at most three short sentences."
)


# --- language, tokens, stems ----------------------------------------------------------------
def detect_lang(text: str) -> str:
    """``cnr`` when the text has Montenegrin diacritics or more Montenegrin than English function
    words, otherwise ``en``. Deterministic; ties resolve to ``en``."""
    if any(ch in _DIACRITICS for ch in text):
        return LOCAL_LANG
    tokens = normalize(text).split()
    cnr_hits = sum(1 for t in tokens if t in _CNR_HINTS)
    en_hits = sum(1 for t in tokens if t in _EN_HINTS)
    return LOCAL_LANG if cnr_hits > en_hits else "en"


def normalize_lang(lang: str | None) -> str | None:
    if lang is None:
        return None
    lang = lang.strip().lower()
    if lang in ("local", "me", "sr", "hr", "bs", "cnr"):
        return LOCAL_LANG
    if lang.startswith("en"):
        return "en"
    return None


def stem(token: str) -> str:
    return token[:STEM_LEN]


def question_stems(text: str) -> list[str]:
    """Unique stems of the question's content words, in order of appearance."""
    out: list[str] = []
    for tok in content_tokens(text):
        if tok in EXTRA_STOPWORDS:
            continue
        s = stem(tok)
        if s not in out:
            out.append(s)
    return out


def text_stems(text: str) -> set[str]:
    return {stem(t) for t in content_tokens(text)}


@dataclass(frozen=True)
class Idf:
    """Inverse document frequency of stems over the approved chunk corpus (smoothed)."""

    n_docs: int
    df: dict[str, int]

    def weight(self, s: str) -> float:
        return 1.0 + math.log((self.n_docs + 1) / (self.df.get(s, 0) + 1))


def corpus_idf(public_db: Session) -> Idf:
    """Document frequencies over the approved chunks visible to the visitor role."""
    stmt = approved_only(
        select(EntryChunk.text).join(HeritageEntry, HeritageEntry.id == EntryChunk.entry_id), HeritageEntry
    )
    df: dict[str, int] = {}
    n = 0
    for (text,) in public_db.execute(stmt):
        n += 1
        for s in text_stems(text):
            df[s] = df.get(s, 0) + 1
    return Idf(n_docs=n, df=df)


def coverage_of(q_stems: list[str], chunk_stems: set[str], idf: Idf) -> tuple[float, float]:
    """``(weighted, plain)`` share of the question stems present in the chunk. *weighted* uses IDF
    so that ubiquitous words (Gornja, Lastva, godine) count little and specific words count a lot."""
    if not q_stems:
        return 0.0, 0.0
    matched = [s for s in q_stems if s in chunk_stems]
    plain = len(matched) / len(q_stems)
    total = sum(idf.weight(s) for s in q_stems)
    got = sum(idf.weight(s) for s in matched)
    return (got / total if total else 0.0), plain


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(text.strip()) if s.strip()]


def pick_sentences(sentences: list[str], q_stems: list[str], idf: Idf, max_n: int) -> list[str]:
    """The ``max_n`` sentences with the highest IDF-weighted overlap with the question, in their
    original order. Falls back to the first sentence when nothing overlaps."""
    if not sentences:
        return []
    scored: list[tuple[float, int]] = []
    for i, sent in enumerate(sentences):
        st = text_stems(sent)
        score = sum(idf.weight(s) for s in q_stems if s in st)
        if score > 0:
            scored.append((-score, i))
    if not scored:
        return [sentences[0]]
    scored.sort()
    chosen = sorted(i for _, i in scored[:max_n])
    return [sentences[i] for i in chosen]


def _truncate(text: str, limit: int = MAX_EXCERPT_CHARS) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def question_digest(question: str) -> str:
    """First 16 hex characters of SHA-256 of the question — enough to spot repeats, not reversible."""
    return hashlib.sha256(question.encode("utf-8")).hexdigest()[:16]


# --- retrieval ----------------------------------------------------------------------------
@dataclass
class RetrievedChunk:
    chunk_id: uuid.UUID
    entry_id: uuid.UUID
    slug: str
    title_local: str
    title_en: str
    entry_status: str
    source: str
    chunk_lang: str  # "local" | "en"
    chunk_index: int
    text: str
    similarity: float
    same_lang: bool
    coverage: float = 0.0
    coverage_plain: float = 0.0
    stems: set[str] = field(default_factory=set)

    def title(self, lang: str) -> str:
        return self.title_local if lang == LOCAL_LANG else self.title_en

    def body(self) -> str:
        """Chunk text without the prepended entry title (see services.indexing.build_chunks)."""
        own_title = self.title_local if self.chunk_lang == "local" else self.title_en
        prefix = f"{own_title}. "
        return self.text[len(prefix):] if self.text.startswith(prefix) else self.text

    @property
    def rank_score(self) -> float:
        return (
            self.similarity
            + (LANG_PREFERENCE_BONUS if self.same_lang else 0.0)
            + COVERAGE_RANK_WEIGHT * self.coverage
        )


def min_similarity() -> float:
    """Similarity threshold: ``RAG_MIN_SIMILARITY`` if set, else the provider default (with the
    calibrated override for the offline hash provider)."""
    if settings.rag_min_similarity is not None:
        return settings.rag_min_similarity
    if settings.embeddings_provider == "hash":
        return HASH_DEFAULT_MIN_SIMILARITY
    return embeddings_provider.min_similarity()


def min_coverage() -> float:
    return settings.rag_min_coverage


def retrieve(public_db: Session, question: str, lang: str, top_k: int | None = None) -> list[RetrievedChunk]:
    """Top-``k`` chunks per language by cosine similarity, approved entries only (RLS role + filter).
    Coverage is not computed here — see :func:`rank_candidates`."""
    top_k = top_k or settings.rag_top_k
    vector = get_embeddings().embed([question])[0]
    wanted = CHUNK_LANG_BY_QUESTION_LANG.get(lang, "en")
    out: list[RetrievedChunk] = []
    for chunk_lang in (wanted, "en" if wanted == "local" else "local"):
        distance = EntryChunk.embedding.cosine_distance(vector).label("distance")
        stmt = (
            select(EntryChunk, HeritageEntry, distance)
            .join(HeritageEntry, HeritageEntry.id == EntryChunk.entry_id)
            .where(EntryChunk.lang == chunk_lang)
        )
        stmt = approved_only(stmt, HeritageEntry).order_by(distance, EntryChunk.id).limit(top_k)
        for chunk, entry, dist in public_db.execute(stmt):
            similarity = 1.0 - float(dist)
            out.append(
                RetrievedChunk(
                    chunk_id=chunk.id,
                    entry_id=entry.id,
                    slug=entry.slug,
                    title_local=entry.title_local,
                    title_en=entry.title_en,
                    entry_status=entry.status,
                    source=chunk.source,
                    chunk_lang=chunk.lang,
                    chunk_index=chunk.chunk_index,
                    text=chunk.text,
                    similarity=max(0.0, min(1.0, round(similarity, 6))),
                    same_lang=(chunk.lang == wanted),
                    stems=text_stems(chunk.text),
                )
            )
    return out


def rank_candidates(candidates: list[RetrievedChunk], q_stems: list[str], idf: Idf, top_k: int) -> list[RetrievedChunk]:
    for c in candidates:
        c.coverage, c.coverage_plain = coverage_of(q_stems, c.stems, idf)
    candidates.sort(key=lambda c: (-c.rank_score, -c.similarity, c.slug, c.chunk_lang, c.chunk_index))
    return candidates[:top_k]


# --- answering ----------------------------------------------------------------------------
@dataclass
class AskResult:
    answered: bool
    answer: str | None
    citations: list[Citation]
    confidence: float
    refusal_reason: str | None
    refusal_message: str | None
    event: str
    lang: str
    debug: dict[str, Any]


def _citation(c: RetrievedChunk, lang: str, excerpt: str) -> Citation:
    if c.entry_status != "approved":  # belt, braces and a third strap
        raise RuntimeError(f"refusing to cite non-approved entry {c.slug} ({c.entry_status})")
    return Citation(
        entry_id=c.entry_id,
        slug=c.slug,
        title=c.title(lang),
        source=c.source,
        lang=QUESTION_LANG_BY_CHUNK_LANG.get(c.chunk_lang, c.chunk_lang),
        chunk_index=c.chunk_index,
        score=round(c.similarity, 4),
        excerpt=_truncate(excerpt or c.body()),
    )


def _passes_gate(c: RetrievedChunk, min_sim: float, min_cov: float) -> bool:
    return c.similarity >= min_sim and c.coverage >= min_cov


def extractive_answer(
    candidates: list[RetrievedChunk], q_stems: list[str], idf: Idf, min_sim: float, min_cov: float
) -> tuple[str, list[tuple[RetrievedChunk, str]]]:
    """1–2 sentences of the best chunk, each followed by ``[1]``; plus one sentence of a second
    chunk ``[2]`` when it passes the gate on its own and covers a question word the best chunk lacks."""
    best = candidates[0]
    chosen = pick_sentences(split_sentences(best.body()), q_stems, idf, MAX_ANSWER_SENTENCES)
    parts = [f"{s} [1]" for s in chosen]
    cited: list[tuple[RetrievedChunk, str]] = [(best, " ".join(chosen))]
    uncovered = [s for s in q_stems if s not in best.stems]
    if uncovered:
        for other in candidates[1:]:
            if not _passes_gate(other, min_sim, min_cov) or not any(s in other.stems for s in uncovered):
                continue
            extra = [
                s for s in pick_sentences(split_sentences(other.body()), q_stems, idf, 1)
                if any(u in text_stems(s) for u in uncovered)
            ]
            if extra:
                parts.append(f"{extra[0]} [2]")
                cited.append((other, extra[0]))
                break
    return " ".join(parts), cited


def llm_answer(
    question: str, lang: str, sources: list[RetrievedChunk]
) -> tuple[str, list[tuple[RetrievedChunk, str]]] | None:
    """Ask the LLM to answer from numbered sources. Returns ``None`` when it declines
    (``NOT_IN_SOURCES``). Raises :class:`LLMUnavailable` when the provider cannot be reached."""
    llm = get_llm()
    system = SYSTEM_PROMPT.format(language=LANGUAGE_NAMES.get(lang, "English"))
    blocks = [f"[{i}] {c.title(lang)} — source: {c.source}\n{c.body()}" for i, c in enumerate(sources, 1)]
    user = "Sources:\n\n" + "\n\n".join(blocks) + f"\n\nQuestion: {question}"
    reply = llm.complete(system, user, max_tokens=400, temperature=0.0).strip()
    compact = re.sub(r"[^A-Z_]", "", reply.upper())
    if not reply or compact == NOT_IN_SOURCES or reply.upper().startswith(NOT_IN_SOURCES):
        return None
    refs = [int(m) for m in _CITATION_MARKER.findall(reply)]
    valid: list[int] = []
    for r in refs:
        if 1 <= r <= len(sources) and r not in valid:
            valid.append(r)
    if not valid:  # the model answered from the sources but forgot the marker → cite the best source
        reply = f"{reply} [1]"
        valid = [1]
    renumber = {old: new for new, old in enumerate(valid, 1)}
    text = _CITATION_MARKER.sub(lambda m: f"[{renumber[int(m.group(1))]}]" if int(m.group(1)) in renumber else "", reply)
    text = " ".join(text.split())
    return text, [(sources[old - 1], sources[old - 1].body()) for old in valid]


def ask(
    public_db: Session,
    db: Session,
    question: str,
    lang: str | None = None,
    session_id: str | None = None,
) -> AskResult:
    """Answer a visitor question from approved entries only, or refuse.

    ``public_db`` (visitor role) is used for retrieval; ``db`` (application role) writes the event
    and commits it. The same function serves the API router and the grounding test.
    """
    question = " ".join(question.split())
    lang = normalize_lang(lang) or detect_lang(question)
    q_stems = question_stems(question)
    idf = corpus_idf(public_db)
    top_k = settings.rag_top_k
    candidates = rank_candidates(retrieve(public_db, question, lang, top_k), q_stems, idf, top_k)
    min_sim, min_cov = min_similarity(), min_coverage()
    refusal_message = REFUSAL_MESSAGES.get(lang, REFUSAL_MESSAGES["en"])
    base_props = {"lang": lang, "question_len": len(question), "question_sha256": question_digest(question)}

    debug: dict[str, Any] = {
        "lang": lang,
        "question_stems": q_stems,
        "min_similarity": min_sim,
        "min_coverage": min_cov,
        "top_similarity": max((c.similarity for c in candidates), default=0.0),
        "similarity": candidates[0].similarity if candidates else 0.0,
        "coverage": round(candidates[0].coverage, 4) if candidates else 0.0,
        "coverage_plain": round(candidates[0].coverage_plain, 4) if candidates else 0.0,
        "mode": "llm" if llm_enabled() else "extractive",
        "candidates": [
            {
                "slug": c.slug, "lang": QUESTION_LANG_BY_CHUNK_LANG.get(c.chunk_lang, c.chunk_lang),
                "chunk_index": c.chunk_index, "similarity": round(c.similarity, 4),
                "coverage": round(c.coverage, 4), "coverage_plain": round(c.coverage_plain, 4),
            }
            for c in candidates
        ],
    }

    def withhold(reason: str, confidence: float) -> AskResult:
        emit_event(db, "answer_withheld", session_id=session_id, confidence=confidence, reason=reason, **base_props)
        db.commit()
        return AskResult(
            answered=False, answer=None, citations=[], confidence=confidence, refusal_reason=reason,
            refusal_message=refusal_message, event="answer_withheld", lang=lang, debug=debug,
        )

    if not candidates:
        return withhold(REFUSAL_REASON_NO_SOURCE, 0.0)
    best = candidates[0]
    confidence = round(0.5 * best.similarity + 0.5 * best.coverage, 3)
    debug["confidence"] = confidence
    if not _passes_gate(best, min_sim, min_cov):
        reason = REFUSAL_REASON_NO_SOURCE if best.coverage_plain == 0.0 else REFUSAL_REASON_LOW_CONFIDENCE
        return withhold(reason, confidence)

    answer: str | None = None
    cited: list[tuple[RetrievedChunk, str]] = []
    if llm_enabled():
        sources = [c for c in candidates if c.similarity >= min_sim][:MAX_LLM_SOURCES] or [best]
        try:
            generated = llm_answer(question, lang, sources)
        except LLMUnavailable as exc:
            log.warning("LLM unavailable (%s); falling back to extractive answer", exc)
            debug["mode"] = "extractive_fallback"
        else:
            if generated is None:
                debug["mode"] = "llm"
                return withhold(REFUSAL_REASON_LLM_DECLINED, confidence)
            answer, cited = generated
            debug["mode"] = "llm"
    if answer is None:
        answer, cited = extractive_answer(candidates, q_stems, idf, min_sim, min_cov)

    citations = [_citation(c, lang, excerpt) for c, excerpt in cited]
    entry_ids: list[str] = []
    for c in citations:
        if str(c.entry_id) not in entry_ids:
            entry_ids.append(str(c.entry_id))
    emit_event(
        db, "answer_served", session_id=session_id, item_type="heritage_entry", item_id=citations[0].entry_id,
        confidence=confidence, n_citations=len(citations), entry_ids=entry_ids, **base_props,
    )
    db.commit()
    return AskResult(
        answered=True, answer=answer, citations=citations, confidence=confidence, refusal_reason=None,
        refusal_message=None, event="answer_served", lang=lang, debug=debug,
    )


# --- automated grounding test ---------------------------------------------------------------
DEFAULT_QUESTIONS_PATH = Path(settings.seed_dir) / "grounding_questions.json"
DEFAULT_RESULTS_PATH = BACKEND_DIR.parent / "docs" / "test-results" / "grounding_results.json"


def _distribution(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"min": None, "median": None, "max": None, "n": 0}
    return {
        "min": round(min(values), 4), "median": round(statistics.median(values), 4),
        "max": round(max(values), 4), "n": len(values),
    }


def evaluate_question(item: dict[str, Any], result: AskResult) -> dict[str, Any]:
    """One row of the report. Pass criteria: expected ``withhold`` → not answered; expected
    ``answer`` → answered with ≥1 citation of an approved entry and (if given) one of the
    ``expected_slugs``."""
    expected = item["expected"]
    cited_slugs = []
    for c in result.citations:
        if c.slug not in cited_slugs:
            cited_slugs.append(c.slug)
    expected_slugs = list(item.get("expected_slugs") or [])
    slug_ok = (not expected_slugs) or any(s in expected_slugs for s in cited_slugs)
    if expected == "withhold":
        passed = not result.answered
    else:
        passed = result.answered and bool(result.citations) and all(c.source for c in result.citations) and slug_ok
    return {
        "id": item["id"],
        "lang": item.get("lang") or result.lang,
        "detected_lang": result.lang,
        "question": item["question"],
        "expected": expected,
        "expected_slugs": expected_slugs,
        "note": item.get("note", ""),
        "outcome": "answer" if result.answered else "withhold",
        "passed": passed,
        "confidence": result.confidence,
        "similarity": result.debug.get("similarity", 0.0),
        "top_similarity": result.debug.get("top_similarity", 0.0),
        "coverage": result.debug.get("coverage", 0.0),
        "coverage_plain": result.debug.get("coverage_plain", 0.0),
        "refusal_reason": result.refusal_reason,
        "cited_slugs": cited_slugs,
        "slug_ok": slug_ok,
        "answer": result.answer,
        "citations": [c.model_dump(mode="json") for c in result.citations],
    }


def run_grounding_test(
    db: Session, questions_path: str | Path | None = None, out_path: str | Path | None = None
) -> dict[str, Any]:
    """Run every question of the grounding set through :func:`ask` and write the report.

    Retrieval uses a fresh visitor-role session (``PublicSessionLocal``); events are written with
    ``db``. Returns ``{"summary": {...}, "results": [...]}`` and writes ``out_path`` (JSON, default
    ``docs/test-results/grounding_results.json``) plus a Markdown table next to it.
    """
    q_path = Path(questions_path) if questions_path else DEFAULT_QUESTIONS_PATH
    o_path = Path(out_path) if out_path else DEFAULT_RESULTS_PATH
    data = json.loads(q_path.read_text(encoding="utf-8"))
    questions: list[dict[str, Any]] = data["questions"] if isinstance(data, dict) else data

    results: list[dict[str, Any]] = []
    with PublicSessionLocal() as public_db:
        for item in questions:
            res = ask(public_db, db, item["question"], lang=item.get("lang"), session_id="grounding-test")
            results.append(evaluate_question(item, res))

    answerable = [r for r in results if r["expected"] == "answer"]
    unanswerable = [r for r in results if r["expected"] == "withhold"]
    answered_ok = sum(1 for r in answerable if r["passed"])
    withheld_ok = sum(1 for r in unanswerable if r["passed"])
    summary: dict[str, Any] = {
        "passed": answered_ok == len(answerable) and withheld_ok == len(unanswerable) and bool(results),
        "total": len(results),
        "answerable": len(answerable),
        "unanswerable": len(unanswerable),
        "answered_ok": answered_ok,
        "withheld_ok": withheld_ok,
        "failures": [r["id"] for r in results if not r["passed"]],
        "thresholds": {
            "min_similarity": min_similarity(),
            "min_coverage": min_coverage(),
            "stem_len": STEM_LEN,
            "lang_preference_bonus": LANG_PREFERENCE_BONUS,
            "coverage_rank_weight": COVERAGE_RANK_WEIGHT,
        },
        "providers": {
            "llm": settings.llm_provider,
            "llm_model": settings.llm_model if llm_enabled() else "-",
            "embeddings": settings.embeddings_provider,
            "embeddings_model": get_embeddings().model,
            "embedding_dim": settings.embedding_dim,
            "top_k": settings.rag_top_k,
        },
        "similarity": {
            "answerable": _distribution([r["similarity"] for r in answerable]),
            "unanswerable": _distribution([r["similarity"] for r in unanswerable]),
        },
        "coverage": {
            "answerable": _distribution([r["coverage"] for r in answerable]),
            "unanswerable": _distribution([r["coverage"] for r in unanswerable]),
        },
        "confidence": {
            "answerable": _distribution([r["confidence"] for r in answerable]),
            "unanswerable": _distribution([r["confidence"] for r in unanswerable]),
        },
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "questions_file": str(q_path),
        "prototype": PROTOTYPE_LABEL,
    }
    report = {"summary": summary, "results": results}
    o_path.parent.mkdir(parents=True, exist_ok=True)
    o_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    o_path.with_suffix(".md").write_text(_markdown_report(report), encoding="utf-8")
    log.info("grounding test: %s", {k: summary[k] for k in ("passed", "answered_ok", "withheld_ok", "total")})
    return report


def _md_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _markdown_report(report: dict[str, Any]) -> str:
    s = report["summary"]
    th = s["thresholds"]
    pv = s["providers"]
    lines = [
        "# Grounding test results — grounded answers or refusal",
        "",
        f"*{s['prototype']}* — generated {s['generated_at']} by `python -m app.cli grounding-test` / "
        "`tests/test_grounding.py`.",
        "",
        f"**Result: {'PASS' if s['passed'] else 'FAIL'}** — answerable {s['answered_ok']}/{s['answerable']} "
        f"answered with an approved citation; unanswerable {s['withheld_ok']}/{s['unanswerable']} withheld.",
        "",
        f"Providers: embeddings `{pv['embeddings']}` (`{pv['embeddings_model']}`, {pv['embedding_dim']}-d, "
        f"top-k {pv['top_k']}), LLM `{pv['llm']}`{'' if pv['llm_model'] == '-' else ' (`' + pv['llm_model'] + '`)'}.",
        "",
        f"Gate: similarity ≥ {th['min_similarity']} AND IDF-weighted coverage ≥ {th['min_coverage']} "
        f"(stems: first {th['stem_len']} characters; language bonus {th['lang_preference_bonus']}, "
        f"coverage rank weight {th['coverage_rank_weight']}).",
        "",
        "## Signal distribution (auditable thresholds)",
        "",
        "| signal | set | n | min | median | max |",
        "|---|---|---|---|---|---|",
    ]
    for signal in ("similarity", "coverage", "confidence"):
        for group in ("answerable", "unanswerable"):
            d = s[signal][group]
            lines.append(f"| {signal} | {group} | {d['n']} | {d['min']} | {d['median']} | {d['max']} |")
    lines += [
        "",
        "## Questions",
        "",
        "| id | lang | question | expected | outcome | confidence | similarity | coverage | cited slugs | pass |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in report["results"]:
        lines.append(
            "| " + " | ".join(
                _md_cell(v) for v in (
                    r["id"], r["lang"], r["question"], r["expected"], r["outcome"], f"{r['confidence']:.3f}",
                    f"{r['similarity']:.3f}", f"{r['coverage']:.3f}", ", ".join(r["cited_slugs"]) or "—",
                    "PASS" if r["passed"] else "FAIL",
                )
            ) + " |"
        )
    lines += ["", "## Answers", ""]
    for r in report["results"]:
        if r["outcome"] == "answer":
            lines.append(f"- **{r['id']}** — {_md_cell(r['answer'])}")
        else:
            lines.append(f"- **{r['id']}** — withheld (`{r['refusal_reason']}`)")
    return "\n".join(lines) + "\n"
