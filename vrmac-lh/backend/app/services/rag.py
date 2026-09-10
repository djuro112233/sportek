"""Grounded answers or refusal — innovation claim #2.

The claim has **two real controls**, both exercised by :func:`ask`:

a. **Human approval before publication.** Only *approved* heritage entries are ever indexed
   (services/indexing.py) and retrieval runs through the *visitor* database role
   (``get_public_db`` / ``PublicSessionLocal``: read-only + row-level security) **and** the explicit
   ``validation.approved_only`` filter. An entry that leaves ``approved`` disappears from the index
   within the same transaction, so the gate is dynamic, not a snapshot.

b. **An automatic support check per answer.** Every sentence of a generated answer must be
   attributable to a cited approved passage (``providers/support.py``, conservative threshold
   ``SUPPORT_MIN_SCORE``). Unsupported sentences are *removed*; if nothing survives, the answer is
   withheld with ``refusal_reason="unsupported_answer"`` and an ``answer_withheld`` event.

Pipeline of :func:`ask`:

1. **Language** — ``lang`` from the request, otherwise a deterministic heuristic (Montenegrin
   diacritics č ć š ž đ or common function words → ``cnr``, else ``en``). The answer, the refusal
   and the pause message are in the question's language.
2. **Cache** — exact ``question_hash`` (sha256 of the normalised question + language), then a
   semantic hit computed in SQL with pgvector (cosine ≥ ``CACHE_SEMANTIC_MIN_SIMILARITY``). A hit
   is only valid while every cited entry still has the recorded version and is still approved, and
   while the row is younger than ``CACHE_MAX_AGE_DAYS``; otherwise the row is marked invalidated
   (with a reason) and the question is answered again.
3. **Spend cap** — ``budget.guard`` before any paid model call. When the monthly cap is reached the
   assistant serves a valid cache entry, and otherwise pauses politely
   (``refusal_reason="assistant_paused"``, events ``assistant_paused`` + ``answer_withheld``).
   It never falls back to unsourced text.
4. **Retrieval** — the question is embedded and matched against ``entry_chunks`` by pgvector cosine
   distance, joined to approved entries and their village. Chunks in the question's language are
   preferred by a small ranking bonus; the other language is not excluded (the corpus is bilingual).
5. **Confidence gate** — provider-agnostic and deterministic: the chunk that would be cited must
   satisfy ``similarity ≥ min_similarity()`` **and** ``coverage ≥ RAG_MIN_COVERAGE``. Coverage is
   the IDF-weighted share of the question's content-word stems found in the chunk (stems = first
   ``STEM_LEN`` characters of a diacritic-folded token, which handles fešta/fešte, crkva/crkve,
   century/centuries). Failing the gate withholds ``low_confidence`` — or ``no_approved_source``
   when nothing was retrieved or nothing of the question occurs in the corpus at all.
6. **Answer** — with an LLM the model answers ONLY from the numbered sources and cites ``[n]``;
   a ``NOT_IN_SOURCES`` reply is a refusal (``llm_declined``). Without an LLM
   (``LLM_PROVIDER=none``, what CI runs) or when it is unavailable, the answer is *extractive*:
   the 1–2 most relevant sentences of the best chunk(s), each followed by ``[n]``.
7. **Support check** — see (b). Citations are pruned to the passages still cited by the surviving
   sentences and renumbered.
8. **Records** — a pseudonymised ``answer_served`` / ``answer_withheld`` event (never the question
   text) plus an :class:`~app.models.AnswerRecord` row that deliberately carries *no* session,
   device or actor pseudonym, so the monthly human review sample (services/review.py) cannot be
   tied back to the person who asked.

:func:`run_grounding_test` runs the per-language question sets
(``seed_data/grounding_questions.<lang>.json``) through exactly the same function and writes an
auditable report (JSON + Markdown) to ``docs/test-results/``.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import statistics
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import BACKEND_DIR, PROTOTYPE_LABEL, settings
from ..db import PublicSessionLocal
from ..events import emit_event
from ..models import AnswerRecord, EntryChunk, HeritageEntry, ResponseCache, Village, utcnow
from ..providers import embeddings as embeddings_provider
from ..providers import llm as llm_provider
from ..providers.embeddings import content_tokens, get_embeddings, normalize
from ..providers.llm import LLMResult, LLMUnavailable, get_llm, llm_enabled
from ..providers.support import SupportVerdict, get_support_checker
from ..schemas import Citation, SupportResult
from . import budget
from .budget import SpendCapReached
from .indexing import strip_title_prefix
from .validation import approved_only

log = logging.getLogger(__name__)

# --- constants -------------------------------------------------------------------------------
LOCAL_LANG: str = settings.local_language  # "cnr" — Montenegrin, Latin script
SUPPORTED_LANGS: tuple[str, str] = (LOCAL_LANG, "en")
CHUNK_LANG_BY_QUESTION_LANG: dict[str, str] = {LOCAL_LANG: "local", "en": "en"}
QUESTION_LANG_BY_CHUNK_LANG: dict[str, str] = {"local": LOCAL_LANG, "en": "en"}
LANGUAGE_NAMES: dict[str, str] = {LOCAL_LANG: "Montenegrin (Latin script)", "en": "English"}

#: Ranking bonus for chunks written in the question's language (ranking only, never the gate).
LANG_PREFERENCE_BONUS: float = 0.05
#: Weight of lexical coverage in the ranking score. Vector similarity alone likes long chunks that
#: share a topic; coverage says whether the chunk actually contains what was asked, so it is worth
#: about a quarter of the score. Ranking only — the gate still uses the raw signals.
COVERAGE_RANK_WEIGHT: float = 0.25
#: Tokens are compared on their first STEM_LEN characters (inflection-tolerant matching).
STEM_LEN: int = 4
MAX_EXCERPT_CHARS: int = 200
MAX_ANSWER_SENTENCES: int = 2
MAX_SOURCES: int = 4
NOT_IN_SOURCES: str = "NOT_IN_SOURCES"
CACHE_SEMANTIC_CANDIDATES: int = 5

REFUSAL_LOW_CONFIDENCE = "low_confidence"
REFUSAL_NO_SOURCE = "no_approved_source"
REFUSAL_LLM_DECLINED = "llm_declined"
REFUSAL_UNSUPPORTED = "unsupported_answer"
REFUSAL_PAUSED = "assistant_paused"

REFUSAL_MESSAGES: dict[str, str] = {
    LOCAL_LANG: (
        "Nemam potvrđen izvor za ovo pitanje. "
        "Odgovaram samo na osnovu odobrenih unosa o Vrmcu i njegovim selima."
    ),
    "en": (
        "I have no validated source for this question. "
        "I only answer from approved entries about Vrmac and its villages."
    ),
}
PAUSED_MESSAGES: dict[str, str] = {
    LOCAL_LANG: (
        "Asistent je privremeno pauziran zbog mjesečnog budžeta. "
        "Prikazujem samo ranije provjerene odgovore."
    ),
    "en": (
        "The assistant is paused for this month because the monthly budget is used up. "
        "Only previously checked answers are shown."
    ),
}

#: Question words that ``providers.embeddings._STOPWORDS`` does not cover. They say nothing about
#: *what* is asked, so they are excluded from coverage scoring.
EXTRA_STOPWORDS: frozenset[str] = frozenset(
    {
        # Montenegrin / Serbian / Croatian (diacritics folded)
        "kojoj", "kojem", "kojim", "kojih", "koju", "koga", "kojom", "cija", "ciji", "cije", "cijem",
        "zasto", "otkad", "otkada", "kuda", "odakle", "dokle", "dokad", "dokada", "kolikoj", "kolikih",
        "kolike", "koliku", "ce", "biti", "bice", "bit", "nam", "nas", "vam", "vas", "ih", "im", "ga",
        "mu", "joj", "tu", "tamo", "ovdje", "ovde", "evo", "eto", "dakle", "zar", "jel", "jeli",
        "postoje", "postoji", "zove", "zovu", "kojeg", "sada", "ovog", "ovom", "svega", "uopste",
        # English
        "should", "could", "would", "will", "have", "has", "had", "been", "being", "am", "into",
        "onto", "than", "then", "so", "if", "not", "no", "yes", "up", "down", "out", "just", "also",
        "very", "really", "exactly", "like", "called", "name", "named", "there", "still", "get",
        # English locative / existential frames: "where is X located" says nothing about X
        "located", "situated", "lies", "lie", "stands", "stand", "take", "takes",
    }
)

_DIACRITICS = frozenset("čćšžđČĆŠŽĐ")
_CNR_HINTS = frozenset(
    {
        "je", "li", "da", "se", "su", "sam", "smo", "ste", "kada", "kad", "gdje", "gde", "koliko",
        "koji", "koja", "koje", "kojoj", "kojeg", "kog", "sta", "kako", "zasto", "ima", "od", "do",
        "za", "na", "u", "i", "ili", "godine", "godina", "vijeka", "crkva", "koju", "ko", "ne", "biti",
        "bio", "bila", "ce", "nalazi", "kojem", "kojim", "iz", "sa", "po", "prema", "danas", "sjutra",
        "sutra", "vrijeme", "vise", "opstini", "opstina", "selo", "sela",
    }
)
_EN_HINTS = frozenset(
    {
        "the", "is", "are", "what", "when", "where", "which", "who", "how", "does", "do", "did", "of",
        "in", "on", "to", "a", "an", "and", "was", "were", "many", "much", "from", "at", "for", "it",
        "there", "that", "this", "with", "have", "has", "can", "will", "be", "by", "or", "any", "today",
        "tomorrow", "since", "until", "century", "year", "village", "church", "high", "cost",
    }
)

# Sentence boundary: end punctuation (or a closing citation marker, which belongs to the sentence
# it follows) + whitespace + an upper-case/quote/digit start. It does not split after 1–2 digit
# ordinals ("14. vijeka", "7. avgusta", "53. fešta") nor after "Sv."/"St." — both are frequent in
# this corpus, and a mis-split fragment would be judged as a sentence of its own by the support
# check. ``providers.support.split_sentences`` is deliberately not reused here: it has no rule for
# "Sv. Marija" / "St. Vitus" and would cut the name in half.
_SENTENCE_SPLIT = re.compile(
    r"(?:(?<=\])|(?<=[.!?])(?<!\b\d\.)(?<!\b\d\d\.)(?<!\bSv\.)(?<!\bsv\.)(?<!\bSt\.))"
    r"\s+(?=[\"„“(A-ZČĆŠŽĐ0-9])"
)
_CITATION_MARKER = re.compile(r"\[(\d+)\]")

SYSTEM_PROMPT = (
    "You are the visitor assistant of the Vrmac Living Heritage prototype (the Vrmac plateau above "
    "Tivat and Kotor, Montenegro). Answer the question using ONLY the numbered sources provided by "
    "the user. After every claim add the number of the source it comes from in square brackets, "
    "e.g. [1]. Never use knowledge that is not in the sources and never guess. "
    f"If the sources do not contain the answer, reply with exactly {NOT_IN_SOURCES} and nothing else. "
    "Answer in {language}, in at most three short sentences."
)


# --- language, tokens, stems -----------------------------------------------------------------
def detect_lang(text: str) -> str:
    """Detect the question's language deterministically.

    Function words decide first: they are the strongest signal and cannot appear by accident.
    Diacritics only break a tie, and then only when they occur in a **lower-case** word — an English
    question naming Lovćen or Njegoš carries diacritics in proper nouns alone and must stay English.
    Ties with no such evidence resolve to ``en``.
    """
    tokens = normalize(text).split()
    cnr_hits = sum(1 for t in tokens if t in _CNR_HINTS)
    en_hits = sum(1 for t in tokens if t in _EN_HINTS)
    if cnr_hits != en_hits:
        return LOCAL_LANG if cnr_hits > en_hits else "en"
    lowercase_diacritic = any(
        not word[:1].isupper() and any(ch in _DIACRITICS for ch in word) for word in text.split()
    )
    return LOCAL_LANG if lowercase_diacritic else "en"


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


def question_digest(question: str) -> str:
    """Deliberately unused for the event stream — see :func:`_event_props`.

    Kept only for local debugging. An **unkeyed** digest of the question is a join key: anyone
    holding both tables can hash every ``answer_records.question`` and match it against an event,
    which re-identifies the review sample that is meant to be unlinkable and links two anonymous
    sessions that happened to ask the same thing. Events therefore carry no digest at all.
    """
    return hashlib.sha256(question.encode("utf-8")).hexdigest()[:16]


def question_hash(question: str, lang: str) -> str:
    """Exact-cache key: sha256 of the *normalised* question plus the language."""
    return hashlib.sha256(f"{normalize(question)}|{lang}".encode("utf-8")).hexdigest()


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
    so ubiquitous words (Gornja, Lastva, godine) count little and specific ones (Stoliv, 1687,
    ferry) count a lot — which is exactly what separates an answerable question from a question
    whose subject the approved corpus does not contain."""
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
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


# --- retrieval -------------------------------------------------------------------------------
@dataclass
class RetrievedChunk:
    chunk_id: uuid.UUID
    entry_id: uuid.UUID
    slug: str
    title_local: str
    title_en: str
    entry_status: str
    entry_version: int
    village_slug: str | None
    municipality: str | None
    source: str
    chunk_lang: str  # "local" | "en"
    chunk_index: int
    text: str
    similarity: float
    same_lang: bool
    #: IDF-weighted coverage of the question over title **and** body — the entry-level match, and
    #: what the confidence gate and the reported confidence use.
    coverage: float = 0.0
    coverage_plain: float = 0.0
    #: The same measure over the chunk's own body only — what *ranks* the chunks (see rank_score).
    body_coverage: float = 0.0
    body_coverage_plain: float = 0.0
    stems: set[str] = field(default_factory=set)
    body_stems: set[str] = field(default_factory=set)
    title_stems: set[str] = field(default_factory=set)

    def title(self, lang: str) -> str:
        return self.title_local if lang == LOCAL_LANG else self.title_en

    def own_title(self) -> str:
        """The title in the chunk's own language — the one ``build_chunks`` prepended."""
        return self.title_local if self.chunk_lang == "local" else self.title_en

    def body(self) -> str:
        """Chunk text without the prepended entry title (see services.indexing.build_chunks)."""
        return strip_title_prefix(self.text, self.own_title())

    @property
    def rank_score(self) -> float:
        """Ranking score. Deliberately **body** coverage, not full-text coverage.

        ``build_chunks`` prepends the entry title to every chunk, so the title is a constant across
        the entry's chunks: it says the question is about this *entry*, never which *chunk* answers
        it. Scoring a chunk on the full text let a chunk whose body is one line of boilerplate
        ("Coordinates are approximate (village location).") reach coverage 1.000 on a question about
        the entry, because the title alone matched every question word, and then outrank the chunk
        that actually holds the answer. Ranking on the body fixes that; retrieval of a short
        question naming the entry is unaffected, because the SQL candidate set comes from the
        embedding of the full chunk text (title included) and the confidence gate still uses the
        entry-level ``coverage``.
        """
        return (
            self.similarity
            + (LANG_PREFERENCE_BONUS if self.same_lang else 0.0)
            + COVERAGE_RANK_WEIGHT * self.body_coverage
        )


#: A stem counts as decisive when its IDF weight is within this fraction of the question's maximum.
DECISIVE_TOLERANCE = 0.999


def min_similarity() -> float:
    """``RAG_MIN_SIMILARITY`` when set, else the provider default.

    Calibration on the two 30-question sets found no reason to override
    ``providers.embeddings.DEFAULT_MIN_SIMILARITY`` for any provider: the offline ``hash`` default
    of 0.35 sits in the gap between the answerable questions (lowest top similarity 0.42) and the
    unanswerable ones (see docs/grounding.md). This indirection stays so a future provider can be
    corrected here rather than in the shared provider module."""
    if settings.rag_min_similarity is not None:
        return settings.rag_min_similarity
    return embeddings_provider.min_similarity()


def min_coverage() -> float:
    return settings.rag_min_coverage


def retrieve(
    public_db: Session, question: str, lang: str, top_k: int | None = None, vector: list[float] | None = None
) -> list[RetrievedChunk]:
    """Top-``k`` chunks per language by pgvector cosine similarity — approved entries only (the
    visitor role's row-level security *and* ``approved_only``). Coverage is added by
    :func:`rank_candidates`."""
    top_k = top_k or settings.rag_top_k
    if vector is None:
        vector = get_embeddings().embed([question])[0]
    wanted = CHUNK_LANG_BY_QUESTION_LANG.get(lang, "en")
    out: list[RetrievedChunk] = []
    for chunk_lang in (wanted, "en" if wanted == "local" else "local"):
        distance = EntryChunk.embedding.cosine_distance(vector).label("distance")
        stmt = (
            select(EntryChunk, HeritageEntry, Village, distance)
            .join(HeritageEntry, HeritageEntry.id == EntryChunk.entry_id)
            .join(Village, Village.id == HeritageEntry.village_id)
            .where(EntryChunk.lang == chunk_lang)
        )
        stmt = approved_only(stmt, HeritageEntry).order_by(distance, EntryChunk.id).limit(top_k)
        for chunk, entry, village, dist in public_db.execute(stmt):
            out.append(
                RetrievedChunk(
                    chunk_id=chunk.id,
                    entry_id=entry.id,
                    slug=entry.slug,
                    title_local=entry.title_local,
                    title_en=entry.title_en,
                    entry_status=entry.status,
                    entry_version=entry.version,
                    village_slug=village.slug if village else None,
                    municipality=village.municipality if village else None,
                    source=chunk.source or entry.source,
                    chunk_lang=chunk.lang,
                    chunk_index=chunk.chunk_index,
                    text=chunk.text,
                    similarity=max(0.0, min(1.0, round(1.0 - float(dist), 6))),
                    same_lang=(chunk.lang == wanted),
                )
            )
    for c in out:
        title = c.own_title()
        c.title_stems = text_stems(title)
        c.body_stems = text_stems(strip_title_prefix(c.text, title))
        c.stems = c.title_stems | c.body_stems
    return out


def rank_candidates(candidates: list[RetrievedChunk], q_stems: list[str], idf: Idf, top_k: int) -> list[RetrievedChunk]:
    for c in candidates:
        c.coverage, c.coverage_plain = coverage_of(q_stems, c.stems, idf)
        c.body_coverage, c.body_coverage_plain = coverage_of(q_stems, c.body_stems, idf)
    candidates.sort(key=lambda c: (-c.rank_score, -c.similarity, c.slug, c.chunk_lang, c.chunk_index))
    return candidates[:top_k]


def decisive_stems(q_stems: list[str], idf: Idf) -> list[str]:
    """The question's rarest stems, reported in ``debug`` for auditing.

    They are **not** used as a gate. Requiring their literal presence was measured on the 60-question
    set and rejected: the rarest stem of a question is usually a framing word the descriptive corpus
    never uses ("dana", "nalazi", "day", "year"), so the rule refused 11 of 40 answerable questions
    while the withholding rate stayed at 100 %. See docs/grounding.md, "Relevance versus attribution".
    """
    if not q_stems:
        return []
    weights = {s: idf.weight(s) for s in set(q_stems)}
    top = max(weights.values(), default=0.0)
    if top <= 0:
        return []
    return sorted(s for s, w in weights.items() if w >= top * DECISIVE_TOLERANCE)


def _passes_gate(c: RetrievedChunk, min_sim: float, min_cov: float) -> bool:
    return c.similarity >= min_sim and c.coverage >= min_cov


# --- answer composition ------------------------------------------------------------------------
def _complete_and_record(db: Session, system: str, user: str, purpose: str, **kwargs) -> LLMResult:
    """One real model call, priced into ``llm_usage`` whatever the outcome of the caller."""
    result = get_llm().complete(system, user, **kwargs)
    budget.record(db, result, purpose)
    return result


class _RecordingLLM:
    """Transparent proxy that captures every :class:`LLMResult` for the spend accounting."""

    def __init__(self, inner, sink: list[LLMResult]):
        self._inner = inner
        self._sink = sink
        self.name = getattr(inner, "name", settings.llm_provider)
        self.model = getattr(inner, "model", settings.llm_model)
        self.billable = getattr(inner, "billable", False)

    def complete(self, system, user, **kwargs) -> LLMResult:
        result = self._inner.complete(system, user, **kwargs)
        self._sink.append(result)
        return result


_LLM_SWAP_LOCK = threading.Lock()


@contextmanager
def _account_nested_llm_calls(db: Session, purpose: str):
    """Account for model calls made *inside* ``providers/support.py``.

    The support checker resolves its model through ``providers.llm.get_llm()`` and reports no token
    counts, so the only way to price its calls without editing that shared module is to swap in a
    recording proxy for the duration of the check. See docs/grounding.md — the clean fix is for
    ``providers/support.py`` to accept an injected LLM (reported, not made, by this module)."""
    captured: list[LLMResult] = []
    with _LLM_SWAP_LOCK:
        original = get_llm()
        llm_provider._instance = _RecordingLLM(original, captured)
        try:
            yield
        finally:
            llm_provider._instance = original
    for result in captured:
        budget.record(db, result, purpose)


def extractive_answer(
    sources: list[RetrievedChunk], q_stems: list[str], idf: Idf
) -> tuple[str, list[tuple[RetrievedChunk, str]]]:
    """1–2 sentences of the best passage, each followed by ``[1]``; plus one sentence of a second
    passage ``[2]`` when it covers a question word the best passage lacks. Every sentence is taken
    verbatim from an approved passage, which is why the extractive path is always attributable."""
    best = sources[0]
    chosen = pick_sentences(split_sentences(best.body()), q_stems, idf, MAX_ANSWER_SENTENCES)
    parts = [f"{s} [1]" for s in chosen]
    cited: list[tuple[RetrievedChunk, str]] = [(best, " ".join(chosen))]
    uncovered = [s for s in q_stems if s not in best.stems]
    if uncovered:
        for other in sources[1:]:
            if other.entry_id == best.entry_id or not any(s in other.stems for s in uncovered):
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
    db: Session, question: str, lang: str, sources: list[RetrievedChunk]
) -> tuple[str, list[tuple[RetrievedChunk, str]]] | None:
    """Ask the model to answer from the numbered sources. ``None`` when it declines
    (``NOT_IN_SOURCES``). Raises :class:`LLMUnavailable` when the provider cannot be reached."""
    system = SYSTEM_PROMPT.format(language=LANGUAGE_NAMES.get(lang, "English"))
    blocks = [f"[{i}] {c.title(lang)} — source: {c.source}\n{c.body()}" for i, c in enumerate(sources, 1)]
    user = "Sources:\n\n" + "\n\n".join(blocks) + f"\n\nQuestion: {question}"
    reply = _complete_and_record(db, system, user, "answer", max_tokens=400, temperature=0.0).text.strip()
    compact = re.sub(r"[^A-Z_]", "", reply.upper())
    if not reply or compact == NOT_IN_SOURCES or reply.upper().startswith(NOT_IN_SOURCES):
        return None
    refs: list[int] = []
    for m in _CITATION_MARKER.findall(reply):
        r = int(m)
        if 1 <= r <= len(sources) and r not in refs:
            refs.append(r)
    if not refs:  # answered from the sources but forgot the marker → cite the best source
        reply = f"{reply} [1]"
        refs = [1]
    renumber = {old: new for new, old in enumerate(refs, 1)}
    text = _CITATION_MARKER.sub(lambda m: f"[{renumber[int(m.group(1))]}]" if int(m.group(1)) in renumber else "", reply)
    return " ".join(text.split()), [(sources[old - 1], sources[old - 1].body()) for old in refs]


def compose_answer(
    *,
    question: str,
    lang: str,
    sources: list[RetrievedChunk],
    q_stems: list[str],
    idf: Idf,
    db: Session,
) -> tuple[str, list[tuple[RetrievedChunk, str]], bool] | None:
    """The single seam that produces a candidate answer before the support check.

    Returns ``(answer, cited, generated)``. ``generated`` is true when a model wrote the sentences
    and false when they were quoted verbatim from an approved passage — the support check needs the
    difference, because a quotation cannot invent anything while a generated sentence can.
    ``None`` means the model declined because the sources do not contain the answer.
    """
    if llm_enabled():
        try:
            written = llm_answer(db, question, lang, sources[:MAX_SOURCES])
            if written is None:
                return None
            answer, cited = written
            return answer, cited, True
        except (LLMUnavailable, SpendCapReached) as exc:
            log.warning("LLM unavailable for answering (%s) — extractive fallback", exc.__class__.__name__)
    quoted = extractive_answer(sources, q_stems, idf)
    if quoted is None:
        return None
    answer, cited = quoted
    return answer, cited, False


# --- support check ------------------------------------------------------------------------------
def check_support(
    db: Session, answer: str, passages: list[str], *, generated: bool = True
) -> list[SupportVerdict]:
    """One verdict per answer sentence against the cited approved passages (claim 2b).

    When the configured check is ``llm_judge`` and the monthly cap stops it from running, the
    verdict depends on where the sentences came from:

    * **quoted** (extractive) — the lexical check is enough, because the sentence is a verbatim span
      of the cited passage and cannot contain anything the passage does not;
    * **generated** — every sentence is marked unsupported, so the answer is withheld. The lexical
      check is *not* a safe substitute here: a model can recombine the passage's own words and
      numbers into a false claim ("iz 9. vijeka" becoming "9 metara") that a bag-of-words check
      accepts. Withholding is the behaviour the brief requires; a weaker check is not.
    """
    checker = get_support_checker()
    sentences = split_sentences(answer)
    verdicts: list[SupportVerdict] = []
    if settings.support_check_provider == "llm_judge" and getattr(get_llm(), "billable", False):
        try:
            budget.guard(db, "support_check")
        except SpendCapReached:
            from ..providers.support import LexicalSupport

            if generated:
                log.warning("spend cap reached during a generated answer — withholding it")
                return [
                    SupportVerdict(
                        sentence=sentence,
                        supported=False,
                        score=0.0,
                        method="withheld_cap_reached",
                        reason="the monthly budget stopped the support check; a generated answer is "
                               "never served on a weaker check",
                    )
                    for sentence in sentences
                ]
            checker = LexicalSupport(settings.support_min_score)
            log.warning("spend cap reached — quoted answer checked lexically")
    if getattr(checker, "name", "") == "llm_judge":
        with _account_nested_llm_calls(db, "support_check"):
            for sentence in sentences:
                verdicts.append(checker.check(sentence, passages))
    else:
        for sentence in sentences:
            verdicts.append(checker.check(sentence, passages))
    return verdicts


def _prune_to_supported(
    verdicts: list[SupportVerdict], cited: list[tuple[RetrievedChunk, str]]
) -> tuple[str, list[tuple[RetrievedChunk, str]], int]:
    """Drop unsupported sentences, then keep and renumber only the passages still cited."""
    kept = [v.sentence for v in verdicts if v.supported]
    dropped = len(verdicts) - len(kept)
    if not kept:
        return "", [], dropped
    used: list[int] = []
    for sentence in kept:
        for m in _CITATION_MARKER.findall(sentence):
            n = int(m)
            if 1 <= n <= len(cited) and n not in used:
                used.append(n)
    if not used:  # a surviving sentence without a marker still stands on the best passage
        used = [1]
        kept = [f"{s} [1]" if not _CITATION_MARKER.search(s) else s for s in kept]
    renumber = {old: new for new, old in enumerate(sorted(used), 1)}
    text = " ".join(
        _CITATION_MARKER.sub(lambda m: f"[{renumber[int(m.group(1))]}]" if int(m.group(1)) in renumber else "", s)
        for s in kept
    )
    return " ".join(text.split()), [cited[old - 1] for old in sorted(used)], dropped


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
        entry_version=c.entry_version,
        village_slug=c.village_slug,
    )


# --- response cache -----------------------------------------------------------------------------
@dataclass
class CacheHit:
    row: ResponseCache
    kind: str  # "exact" | "semantic"
    similarity: float


def _cache_row_invalid_reason(db: Session, row: ResponseCache) -> str:
    """Empty string when the row may still be served."""
    age = utcnow() - row.created_at
    if age > timedelta(days=settings.cache_max_age_days):
        return f"older than {settings.cache_max_age_days} days"
    for entry_id, version in (row.entry_versions or {}).items():
        try:
            entry = db.get(HeritageEntry, uuid.UUID(str(entry_id)))
        except ValueError:
            return "unreadable entry id"
        if entry is None:
            return f"cited entry {entry_id} no longer exists"
        if entry.status != "approved":
            return f"cited entry {entry.slug} is {entry.status}, no longer approved"
        if int(entry.version) != int(version):
            return f"cited entry {entry.slug} moved from version {version} to {entry.version}"
    return ""


def _invalidate(db: Session, row: ResponseCache, reason: str) -> None:
    row.invalidated_at = utcnow()
    row.invalidation_reason = reason[:120]
    db.add(row)
    db.flush()
    log.info("cache row %s invalidated: %s", row.id, reason)


def cache_lookup(db: Session, question: str, lang: str, vector: list[float]) -> CacheHit | None:
    """Exact hash hit first, then a semantic hit computed in SQL with pgvector. Rows that are no
    longer valid (entry version bumped, entry unapproved, too old) are marked invalidated here."""
    if not settings.cache_enabled:
        return None
    q_hash = question_hash(question, lang)
    exact = db.scalars(
        select(ResponseCache)
        .where(
            ResponseCache.question_hash == q_hash,
            ResponseCache.lang == lang,
            ResponseCache.invalidated_at.is_(None),
        )
        .order_by(ResponseCache.created_at.desc())
    ).all()
    for row in exact:
        reason = _cache_row_invalid_reason(db, row)
        if reason:
            _invalidate(db, row, reason)
            continue
        return CacheHit(row, "exact", 1.0)

    distance = ResponseCache.embedding.cosine_distance(vector).label("distance")
    stmt = (
        select(ResponseCache, distance)
        .where(ResponseCache.lang == lang, ResponseCache.invalidated_at.is_(None))
        .order_by(distance, ResponseCache.id)
        .limit(CACHE_SEMANTIC_CANDIDATES)
    )
    for row, dist in db.execute(stmt):
        similarity = 1.0 - float(dist)
        if similarity < settings.cache_semantic_min_similarity:
            break
        reason = _cache_row_invalid_reason(db, row)
        if reason:
            _invalidate(db, row, reason)
            continue
        return CacheHit(row, "semantic", round(similarity, 6))
    return None


def cache_store(
    db: Session, question: str, lang: str, vector: list[float], answer: str,
    citations: list[Citation], confidence: float,
) -> ResponseCache | None:
    if not settings.cache_enabled or not citations:
        return None
    entry_versions = {str(c.entry_id): int(c.entry_version) for c in citations}
    q_hash = question_hash(question, lang)
    row = db.scalars(
        select(ResponseCache).where(
            ResponseCache.question_hash == q_hash,
            ResponseCache.lang == lang,
            ResponseCache.invalidated_at.is_(None),
        )
    ).first()
    if row is None:
        row = ResponseCache(question_hash=q_hash, lang=lang, embedding=vector)
        db.add(row)
    row.question_norm = normalize(question)
    row.embedding = vector
    row.answer = answer
    row.citations = [c.model_dump(mode="json") for c in citations]
    row.confidence = confidence
    row.entry_versions = entry_versions
    row.created_at = utcnow()
    row.last_used_at = utcnow()
    row.invalidated_at = None
    row.invalidation_reason = ""
    db.flush()
    return row


# --- the public entry point ----------------------------------------------------------------------
@dataclass
class AskResult:
    answered: bool
    answer: str | None
    citations: list[Citation]
    confidence: float
    support: list[SupportResult]
    dropped_sentences: int
    refusal_reason: str | None
    refusal_message: str | None
    served_from_cache: bool
    event: str
    lang: str
    provider: dict[str, str]
    debug: dict[str, Any]


def providers_info() -> dict[str, str]:
    return {
        "llm": settings.llm_provider,
        "embeddings": settings.embeddings_provider,
        "support_check": settings.support_check_provider,
    }


def _record_answer(
    db: Session, *, lang: str, question: str, result_answer: str, answered: bool,
    refusal_reason: str | None, confidence: float, citations: list[Citation],
    support: list[SupportResult], dropped: int, served_from_cache: bool,
) -> AnswerRecord:
    """The unlinked row the monthly human review sample draws from — no session, device or actor
    pseudonym is stored, by design (see app/models.py: AnswerRecord)."""
    record = AnswerRecord(
        lang=lang,
        question=question,
        answer=result_answer or "",
        answered=answered,
        refusal_reason=refusal_reason,
        confidence=confidence,
        citations=[c.model_dump(mode="json") for c in citations],
        support_results=[s.model_dump(mode="json") for s in support],
        dropped_sentences=dropped,
        llm_provider=settings.llm_provider,
        support_provider=settings.support_check_provider,
        served_from_cache=served_from_cache,
    )
    db.add(record)
    db.flush()
    return record


def _village_of(db: Session, citations: list[Citation]) -> Village | None:
    if not citations:
        return None
    entry = db.get(HeritageEntry, citations[0].entry_id)
    return db.get(Village, entry.village_id) if entry is not None else None


def ask(
    db_public: Session,
    db_app: Session,
    question: str,
    lang: str | None = None,
    session_id: str | None = None,
    device_id: str | None = None,
    *,
    use_cache: bool = True,
) -> AskResult:
    """Answer a visitor question from approved entries only, or refuse — see the module docstring.

    ``db_public`` (visitor role, RLS) retrieves; ``db_app`` (application role) reads the cache and
    writes the event, the usage rows and the unlinked answer record. Both the API router and the
    grounding-test runner call exactly this function.

    ``use_cache=False`` neither reads nor writes the response cache. Only the grounding-test runner
    sets it, so that the report measures retrieval, the gate and the support check on every run
    instead of replaying the previous run's answers (the cache has its own tests).
    """
    question = " ".join((question or "").split())
    lang = normalize_lang(lang) or detect_lang(question)
    refusal_message = REFUSAL_MESSAGES.get(lang, REFUSAL_MESSAGES["en"])
    # No digest of the question reaches the event stream: it would be a join key into
    # answer_records, whose whole point is that it cannot be tied back to a session or a device.
    # The coarse length is enough for the KPI specs that use it.
    base_props = {"lang": lang, "question_len": len(question)}
    debug: dict[str, Any] = {"lang": lang, "mode": "llm" if llm_enabled() else "extractive"}
    vector = get_embeddings().embed([question])[0]

    def withhold(
        reason: str,
        confidence: float,
        *,
        message: str | None = None,
        paused: bool = False,
        support: list[SupportResult] | None = None,
        dropped: int = 0,
    ) -> AskResult:
        """Refuse. ``support``/``dropped`` carry the per-sentence verdicts when the refusal is the
        result of the support check, so the response and the review sheet show why."""
        support = support or []
        msg = message or refusal_message
        if paused:
            emit_event(
                db_app, "assistant_paused", session_id=session_id, device_id=device_id,
                reason=reason, cap_eur=settings.llm_monthly_cap_eur,
                spent_eur=round(budget.spent_this_month(db_app), 4), **base_props,
            )
        emit_event(
            db_app, "answer_withheld", session_id=session_id, device_id=device_id,
            confidence=confidence, reason=reason, **base_props,
        )
        _record_answer(
            db_app, lang=lang, question=question, result_answer="", answered=False, refusal_reason=reason,
            confidence=confidence, citations=[], support=support, dropped=dropped, served_from_cache=False,
        )
        db_app.commit()
        return AskResult(
            answered=False, answer=None, citations=[], confidence=confidence, support=support,
            dropped_sentences=dropped, refusal_reason=reason, refusal_message=msg, served_from_cache=False,
            event="answer_withheld", lang=lang, provider=providers_info(), debug=debug,
        )

    def serve(
        answer: str, citations: list[Citation], confidence: float, support: list[SupportResult],
        dropped: int, from_cache: bool,
    ) -> AskResult:
        entry_ids: list[str] = []
        village_slugs: list[str] = []
        for c in citations:
            if str(c.entry_id) not in entry_ids:
                entry_ids.append(str(c.entry_id))
            if c.village_slug and c.village_slug not in village_slugs:
                village_slugs.append(c.village_slug)
        village = _village_of(db_app, citations)
        emit_event(
            db_app, "answer_served", session_id=session_id, device_id=device_id,
            item_type="heritage_entry", item_id=citations[0].entry_id if citations else None,
            village=village, confidence=confidence, n_citations=len(citations), entry_ids=entry_ids,
            served_from_cache=from_cache, dropped_sentences=dropped,
            support_provider=settings.support_check_provider, village_slugs=village_slugs, **base_props,
        )
        _record_answer(
            db_app, lang=lang, question=question, result_answer=answer, answered=True, refusal_reason=None,
            confidence=confidence, citations=citations, support=support, dropped=dropped,
            served_from_cache=from_cache,
        )
        db_app.commit()
        return AskResult(
            answered=True, answer=answer, citations=citations, confidence=confidence, support=support,
            dropped_sentences=dropped, refusal_reason=None, refusal_message=None, served_from_cache=from_cache,
            event="answer_served", lang=lang, provider=providers_info(), debug=debug,
        )

    # 1. cache (exact, then semantic) -------------------------------------------------------
    hit = cache_lookup(db_app, question, lang, vector) if use_cache else None
    if hit is not None:
        hit.row.hits += 1
        hit.row.last_used_at = utcnow()
        db_app.add(hit.row)
        citations = [Citation.model_validate(c) for c in (hit.row.citations or [])]
        debug.update({"cache": hit.kind, "cache_similarity": hit.similarity})
        return serve(hit.row.answer, citations, hit.row.confidence, [], 0, True)

    # 2. spend cap: no cache, no budget → pause politely, never unsourced text ----------------
    try:
        budget.guard(db_app, "answer")
    except SpendCapReached as exc:
        debug["spend_cap"] = {"spent_eur": round(exc.spent, 4), "cap_eur": exc.cap}
        return withhold(
            REFUSAL_PAUSED, 0.0, message=PAUSED_MESSAGES.get(lang, PAUSED_MESSAGES["en"]), paused=True
        )

    # 3. retrieval + 4. confidence gate --------------------------------------------------------
    q_stems = question_stems(question)
    idf = corpus_idf(db_public)
    top_k = settings.rag_top_k
    candidates = rank_candidates(retrieve(db_public, question, lang, top_k, vector), q_stems, idf, top_k)
    min_sim, min_cov = min_similarity(), min_coverage()
    debug.update(
        {
            "question_stems": q_stems,
            "min_similarity": min_sim,
            "min_coverage": min_cov,
            "top_similarity": max((c.similarity for c in candidates), default=0.0),
            "similarity": candidates[0].similarity if candidates else 0.0,
            "coverage": round(candidates[0].coverage, 4) if candidates else 0.0,
            "coverage_plain": round(candidates[0].coverage_plain, 4) if candidates else 0.0,
            "candidates": [
                {
                    "slug": c.slug, "lang": QUESTION_LANG_BY_CHUNK_LANG.get(c.chunk_lang, c.chunk_lang),
                    "chunk_index": c.chunk_index, "similarity": round(c.similarity, 4),
                    "coverage": round(c.coverage, 4), "coverage_plain": round(c.coverage_plain, 4),
                }
                for c in candidates
            ],
        }
    )
    if not candidates:
        return withhold(REFUSAL_NO_SOURCE, 0.0)
    best = candidates[0]
    confidence = round(0.5 * best.similarity + 0.5 * best.coverage, 3)
    debug["confidence"] = confidence
    debug["decisive_stems"] = decisive_stems(q_stems, idf)
    if not _passes_gate(best, min_sim, min_cov):
        reason = REFUSAL_NO_SOURCE if best.coverage_plain == 0.0 else REFUSAL_LOW_CONFIDENCE
        return withhold(reason, confidence)

    # 5. answer -------------------------------------------------------------------------------
    sources = [c for c in candidates if _passes_gate(c, min_sim, min_cov)] or [best]
    composed = compose_answer(
        question=question, lang=lang, sources=sources, q_stems=q_stems, idf=idf, db=db_app
    )
    if composed is None:
        return withhold(REFUSAL_LLM_DECLINED, confidence)
    answer, cited, was_generated = composed
    debug["answer_written_by"] = "model" if was_generated else "quotation"

    # 6. support check: every sentence must be attributable to a cited approved passage --------
    passages = [chunk.body() for chunk, _ in cited]
    verdicts = check_support(db_app, answer, passages, generated=was_generated)
    support = [SupportResult(**v.as_dict()) for v in verdicts]
    answer, cited, dropped = _prune_to_supported(verdicts, cited)
    debug.update({"dropped_sentences": dropped, "support_provider": settings.support_check_provider})
    if not answer or not cited:
        # Every sentence failed the attributability check: refuse, and keep the verdicts so the
        # response and the monthly review sheet show exactly what was dropped and why.
        return withhold(REFUSAL_UNSUPPORTED, confidence, support=support, dropped=dropped)

    citations = [_citation(chunk, lang, excerpt) for chunk, excerpt in cited]
    if use_cache:
        cache_store(db_app, question, lang, vector, answer, citations, confidence)
    return serve(answer, citations, confidence, support, dropped, False)


# --- automated grounding test --------------------------------------------------------------------
def questions_path_for(lang: str) -> Path:
    return Path(settings.seed_dir) / f"grounding_questions.{lang}.json"


DEFAULT_RESULTS_PATH = BACKEND_DIR.parent / "docs" / "test-results" / "grounding_results.json"
#: The brief's hard floor for answerable questions; the definition of done aims at 100 %.
ANSWERABLE_FLOOR = 0.90


def _distribution(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"min": None, "median": None, "max": None, "n": 0}
    return {
        "min": round(min(values), 4), "median": round(statistics.median(values), 4),
        "max": round(max(values), 4), "n": len(values),
    }


def evaluate_question(item: dict[str, Any], result: AskResult) -> dict[str, Any]:
    """One row of the report. Pass criteria: expected ``withhold`` → not answered; expected
    ``answer`` → answered, with ≥1 citation of an approved entry that has a non-empty source and
    (when given) one of the ``expected_slugs``."""
    expected = item["expected"]
    cited_slugs: list[str] = []
    for c in result.citations:
        if c.slug not in cited_slugs:
            cited_slugs.append(c.slug)
    expected_slugs = list(item.get("expected_slugs") or [])
    slug_ok = (not expected_slugs) or any(s in expected_slugs for s in cited_slugs)
    if expected == "withhold":
        passed = not result.answered
    else:
        passed = (
            result.answered and bool(result.citations)
            and all(c.source for c in result.citations) and slug_ok
        )
    return {
        "id": item["id"],
        "lang": item.get("lang") or result.lang,
        "detected_lang": result.lang,
        "question": item["question"],
        "expected": expected,
        "expected_slugs": expected_slugs,
        "expected_answer": item.get("expected_answer", ""),
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
        "supported_sentences": sum(1 for s in result.support if s.supported),
        "dropped_sentences": result.dropped_sentences,
        "served_from_cache": result.served_from_cache,
        "answer": result.answer,
        "citations": [c.model_dump(mode="json") for c in result.citations],
        "support": [s.model_dump(mode="json") for s in result.support],
    }


def run_grounding_test(
    db: Session,
    questions_path: str | Path | None = None,
    out_path: str | Path | None = None,
    lang: str | None = None,
) -> dict[str, Any]:
    """Run the launch-language question sets through :func:`ask` and write the auditable report.

    ``lang=None`` runs every launch language (cnr and en); a language runs its own file
    ``seed_data/grounding_questions.<lang>.json`` unless ``questions_path`` names one explicitly.
    Retrieval uses a fresh visitor-role session; events and answer records are written with ``db``.
    Returns ``{"summary": {...}, "results": [...]}`` and writes ``out_path`` (JSON, default
    ``docs/test-results/grounding_results.json``) plus a Markdown table next to it.
    """
    langs = [normalize_lang(lang) or lang] if lang else list(SUPPORTED_LANGS)
    files: list[tuple[str, Path]] = []
    for lg in langs:
        files.append((lg, Path(questions_path) if questions_path else questions_path_for(lg)))
    o_path = Path(out_path) if out_path else DEFAULT_RESULTS_PATH

    results: list[dict[str, Any]] = []
    with PublicSessionLocal() as public_db:
        for lg, path in files:
            data = json.loads(path.read_text(encoding="utf-8"))
            items = data["questions"] if isinstance(data, dict) else data
            for item in items:
                res = ask(
                    public_db, db, item["question"], lang=item.get("lang") or lg,
                    session_id="grounding-test", device_id="grounding-test", use_cache=False,
                )
                row = evaluate_question(item, res)
                row["set_lang"] = lg
                results.append(row)

    summary = _summarise(results, [(lg, str(p)) for lg, p in files])
    report = {"summary": summary, "results": results}
    o_path.parent.mkdir(parents=True, exist_ok=True)
    o_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    o_path.with_suffix(".md").write_text(_markdown_report(report), encoding="utf-8")
    log.info("grounding test: %s", {k: summary[k] for k in ("passed", "answered_ok", "withheld_ok", "total")})
    return report


def _summarise(results: list[dict[str, Any]], files: list[tuple[str, str]]) -> dict[str, Any]:
    answerable = [r for r in results if r["expected"] == "answer"]
    unanswerable = [r for r in results if r["expected"] == "withhold"]
    answered_ok = sum(1 for r in answerable if r["passed"])
    withheld_ok = sum(1 for r in unanswerable if r["passed"])
    per_language: dict[str, Any] = {}
    lang_pass = True
    for lg, path in files:
        rows = [r for r in results if r["set_lang"] == lg]
        a = [r for r in rows if r["expected"] == "answer"]
        u = [r for r in rows if r["expected"] == "withhold"]
        a_ok = sum(1 for r in a if r["passed"])
        u_ok = sum(1 for r in u if r["passed"])
        rate_a = (a_ok / len(a)) if a else 0.0
        rate_u = (u_ok / len(u)) if u else 0.0
        ok = bool(a) and bool(u) and rate_a >= ANSWERABLE_FLOOR and rate_u == 1.0
        lang_pass = lang_pass and ok
        per_language[lg] = {
            "questions_file": path,
            "total": len(rows),
            "answerable": len(a),
            "unanswerable": len(u),
            "answered_ok": a_ok,
            "withheld_ok": u_ok,
            "answerable_rate": round(rate_a, 4),
            "withheld_rate": round(rate_u, 4),
            "passed": ok,
            "failures": [r["id"] for r in rows if not r["passed"]],
            "similarity": {
                "answerable": _distribution([r["similarity"] for r in a]),
                "unanswerable": _distribution([r["similarity"] for r in u]),
            },
            "coverage": {
                "answerable": _distribution([r["coverage"] for r in a]),
                "unanswerable": _distribution([r["coverage"] for r in u]),
            },
            "confidence": {
                "answerable": _distribution([r["confidence"] for r in a]),
                "unanswerable": _distribution([r["confidence"] for r in u]),
            },
        }
    return {
        "passed": bool(results) and lang_pass,
        "total": len(results),
        "answerable": len(answerable),
        "unanswerable": len(unanswerable),
        "answered_ok": answered_ok,
        "withheld_ok": withheld_ok,
        "answerable_rate": round(answered_ok / len(answerable), 4) if answerable else 0.0,
        "withheld_rate": round(withheld_ok / len(unanswerable), 4) if unanswerable else 0.0,
        "answerable_floor": ANSWERABLE_FLOOR,
        "languages": per_language,
        "failures": [r["id"] for r in results if not r["passed"]],
        "thresholds": {
            "min_similarity": min_similarity(),
            "min_coverage": min_coverage(),
            "stem_len": STEM_LEN,
            "lang_preference_bonus": LANG_PREFERENCE_BONUS,
            "coverage_rank_weight": COVERAGE_RANK_WEIGHT,
            "support_min_score": settings.support_min_score,
            "cache_semantic_min_similarity": settings.cache_semantic_min_similarity,
        },
        "providers": {
            "llm": settings.llm_provider,
            "llm_model": settings.llm_model if llm_enabled() else "-",
            "embeddings": settings.embeddings_provider,
            "embeddings_model": get_embeddings().model,
            "embedding_dim": settings.embedding_dim,
            "support_check": settings.support_check_provider,
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
        "prototype": PROTOTYPE_LABEL,
    }


def _md_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _markdown_report(report: dict[str, Any]) -> str:
    s = report["summary"]
    th, pv = s["thresholds"], s["providers"]
    lines = [
        "# Grounding test results — grounded answers or refusal",
        "",
        f"*{s['prototype']}* — generated {s['generated_at']} by `python -m app.cli grounding-test` / "
        "`tests/test_grounding.py`.",
        "",
        f"**Result: {'PASS' if s['passed'] else 'FAIL'}** — answerable {s['answered_ok']}/{s['answerable']} "
        f"({s['answerable_rate']:.0%}, floor {s['answerable_floor']:.0%}) answered with an approved "
        f"citation; unanswerable {s['withheld_ok']}/{s['unanswerable']} ({s['withheld_rate']:.0%}) withheld.",
        "",
        f"Providers: embeddings `{pv['embeddings']}` (`{pv['embeddings_model']}`, {pv['embedding_dim']}-d, "
        f"top-k {pv['top_k']}), LLM `{pv['llm']}`"
        f"{'' if pv['llm_model'] == '-' else ' (`' + pv['llm_model'] + '`)'}, "
        f"support check `{pv['support_check']}` (min score {th['support_min_score']}).",
        "",
        f"Gate: similarity ≥ {th['min_similarity']} AND IDF-weighted coverage ≥ {th['min_coverage']} "
        f"(stems: first {th['stem_len']} characters; language bonus {th['lang_preference_bonus']}, "
        f"coverage rank weight {th['coverage_rank_weight']}).",
        "",
        "## Per launch language",
        "",
        "| language | answerable answered | rate | unanswerable withheld | rate | pass |",
        "|---|---|---|---|---|---|",
    ]
    for lg, d in s["languages"].items():
        lines.append(
            f"| {lg} | {d['answered_ok']}/{d['answerable']} | {d['answerable_rate']:.0%} | "
            f"{d['withheld_ok']}/{d['unanswerable']} | {d['withheld_rate']:.0%} | "
            f"{'PASS' if d['passed'] else 'FAIL'} |"
        )
    lines += [
        "",
        "## Signal distribution (how the thresholds were calibrated)",
        "",
        "| signal | set | n | min | median | max |",
        "|---|---|---|---|---|---|",
    ]
    for signal in ("similarity", "coverage", "confidence"):
        for group in ("answerable", "unanswerable"):
            d = s[signal][group]
            lines.append(f"| {signal} | {group} | {d['n']} | {d['min']} | {d['median']} | {d['max']} |")
    for lg, ld in s["languages"].items():
        lines += ["", f"### {lg}", "", "| signal | set | n | min | median | max |", "|---|---|---|---|---|---|"]
        for signal in ("similarity", "coverage", "confidence"):
            for group in ("answerable", "unanswerable"):
                d = ld[signal][group]
                lines.append(f"| {signal} | {group} | {d['n']} | {d['min']} | {d['median']} | {d['max']} |")
    lines += [
        "",
        "## Questions",
        "",
        "| id | lang | question | expected | outcome | conf. | sim. | cov. | cited slugs | supported | dropped | pass |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in report["results"]:
        lines.append(
            "| " + " | ".join(
                _md_cell(v) for v in (
                    r["id"], r["lang"], r["question"], r["expected"], r["outcome"], f"{r['confidence']:.3f}",
                    f"{r['similarity']:.3f}", f"{r['coverage']:.3f}", ", ".join(r["cited_slugs"]) or "—",
                    r["supported_sentences"], r["dropped_sentences"], "PASS" if r["passed"] else "FAIL",
                )
            ) + " |"
        )
    lines += ["", "## Answers against the independently prepared reference", ""]
    for r in report["results"]:
        if r["outcome"] == "answer":
            lines.append(f"- **{r['id']}** — {_md_cell(r['answer'])}")
        else:
            lines.append(f"- **{r['id']}** — withheld (`{r['refusal_reason']}`)")
        if r["expected_answer"]:
            lines.append(f"  - *expected:* {_md_cell(r['expected_answer'])}")
    return "\n".join(lines) + "\n"
