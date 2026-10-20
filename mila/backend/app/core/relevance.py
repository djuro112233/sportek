"""Question relevance: does the evidence behind an answer actually address the question?

The verifier checks that every sentence is *supported* by its cited chunk. It does not check
that the chunk is *about the question*: an extractive or drifting model can answer "what is
good for knee pain" with verbatim, well-cited sentences about pain in pregnancy. This module
scores how much of the question's content the cited evidence covers, weighting each question
term by its rarity in the knowledge base (a question term the knowledge base never uses is
strong evidence that the question is off the knowledge base).

``relevance = sum(idf(term) for matched terms) / sum(idf(term) for all question terms)``

Terms are 5-character stems of :func:`app.core.verifier.content_tokens` minus question words.
``None`` means "not assessable": the question has no content terms, or the evidence is in a
different language family than the question (cross-lingual relevance needs the LLM judge;
documented in docs/safety.md).
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Iterable

from app.core.i18n import coerce_lang, is_bcms
from app.core.types import AnswerSentence, RetrievedChunk
from app.core.verifier import content_tokens

STEM_LEN = 5

# Question words and generic verbs that carry no topic (normalised, diacritic-free).
QUESTION_WORDS: frozenset[str] = frozenset(
    {
        "sta", "sto", "kako", "zasto", "gdje", "gde", "kada", "koliko", "koji", "koja", "koje", "koju",
        "kojim", "kojih", "mogu", "moze", "mozes", "mozemo", "moci", "treba", "trebam", "trebalo",
        "imam", "imas", "ima", "imati", "imala", "imao", "radim", "raditi", "uradim", "uraditi",
        "uradila", "smijem", "smem", "smije", "sme", "normalno", "dobro", "lose", "znaci", "pitanje",
        "molim", "hvala", "zanima", "interesuje", "reci", "kazi", "kazes", "jesam", "jeste", "jesu",
        "bude", "biti", "bila", "bilo", "bio", "nesto", "nekad", "ponekad", "uvijek", "uvek", "danas",
        "jutros", "sinoc", "sutra", "juce", "jucer", "godin", "godina", "godine", "dana", "dan",
        "what", "which", "how", "why", "where", "when", "who", "should", "could", "would", "can",
        "may", "need", "want", "know", "tell", "please", "thanks", "thank", "okay", "normal", "good",
        "bad", "mean", "means", "something", "anything", "really", "just", "like", "get", "got",
        "make", "made", "take", "took", "think", "feel", "felt", "say", "said", "does", "doing",
        "done", "being", "year", "years", "day", "days", "today", "yesterday", "tomorrow",
        "znam", "znas", "znati", "znamo", "uzme", "uzmem", "uzeti", "uzima", "uzimati", "uzimam",
        "koristi", "koristim", "koristiti", "use", "using", "used",
    }
)  # fmt: skip

# A question term the knowledge base never uses is strong evidence the question is off the
# knowledge base; relevance is multiplied by this factor when such a term stays unmatched.
UNKNOWN_TERM_PENALTY = 0.75

IdfFn = Callable[[str], float]


_YAT_RE = re.compile(r"(?<=[bcdfghklmnprstvz])i?je")


def fold_yat(token: str) -> str:
    """Fold ijekavian reflexes onto the ekavian form so dialect variants share a stem.

    ``nedjelja``/``nedelja`` → ``nedelja``, ``poslije``/``posle`` → ``posle``, ``mlijeko`` →
    ``mleko``, ``ljekar``/``lijecnik``/``lekar`` → ``lekar``/``lecnik``. Only ``je``/``ije``
    after a consonant is folded, so ``jedan`` and ``jesam`` are untouched.
    """
    return _YAT_RE.sub("e", token)


def stems(text: str) -> list[str]:
    """Ordered, de-duplicated stems of the content tokens of ``text`` (question words removed)."""
    seen: list[str] = []
    for tok in content_tokens(text):
        if tok in QUESTION_WORDS:
            continue
        stem = fold_yat(tok)[:STEM_LEN]
        if stem not in seen:
            seen.append(stem)
    return seen


def make_idf(documents: Iterable[Iterable[str]]) -> IdfFn:
    """Inverse document frequency over stem sets. Unknown stems get the maximum idf."""
    df: dict[str, int] = {}
    n_docs = 0
    for doc in documents:
        n_docs += 1
        for stem in set(doc):
            df[stem] = df.get(stem, 0) + 1
    ceiling = math.log(1.0 + (n_docs + 0.5) / 0.5) if n_docs else 1.0

    def idf(stem: str) -> float:
        n = df.get(stem)
        if n is None:
            return ceiling
        return math.log(1.0 + (n_docs - n + 0.5) / (n + 0.5))

    idf.ceiling = ceiling  # type: ignore[attr-defined]  # stems at the ceiling are unknown to the corpus
    return idf


def coverage(
    question: str,
    evidence_texts: Iterable[str],
    idf: IdfFn | None = None,
    *,
    unknown_term_penalty: float = UNKNOWN_TERM_PENALTY,
) -> float | None:
    """Rarity-weighted share of the question's stems that occur in the evidence; ``None`` if no stems.

    When ``idf`` knows the corpus (see :func:`make_idf`) and a question stem is both unknown to
    the corpus and unmatched, the score is multiplied by ``unknown_term_penalty``.
    """
    q = stems(question)
    if not q:
        return None
    weight: IdfFn = idf or (lambda _s: 1.0)
    evidence = set()
    for text in evidence_texts:
        evidence.update(stems(text))
    total = sum(weight(s) for s in q)
    if total <= 0.0:
        return None
    matched = sum(weight(s) for s in q if s in evidence)
    score = matched / total
    ceiling = getattr(idf, "ceiling", None)
    if ceiling is not None and any(s not in evidence and weight(s) >= ceiling - 1e-9 for s in q):
        score *= unknown_term_penalty
    return round(score, 4)


def question_relevance(
    question: str,
    lang: str,
    sentences: list[AnswerSentence],
    chunks: list[RetrievedChunk],
    idf: IdfFn | None = None,
    *,
    unknown_term_penalty: float = UNKNOWN_TERM_PENALTY,
) -> float | None:
    """Relevance of the evidence behind the supported sentences to the question.

    Evidence = the supported sentences' texts plus the heading path and text of every chunk
    they cite. Returns ``None`` when nothing is supported, when the question has no content
    terms, or when no cited chunk shares the question's language family.
    """
    supported = [s for s in sentences if s.supported and not s.flagged_medication]
    if not supported:
        return None
    cited: list[RetrievedChunk] = []
    for sentence in supported:
        for marker in sentence.citations:
            digits = marker[1:]
            if digits.isdigit() and 0 < int(digits) <= len(chunks):
                chunk = chunks[int(digits) - 1]
                if chunk not in cited:
                    cited.append(chunk)
    if not cited:
        return None
    family_bcms = is_bcms(coerce_lang(lang))
    same_family = [c for c in cited if is_bcms(coerce_lang(c.lang)) == family_bcms]
    if not same_family:
        return None
    texts = [s.text for s in supported] + [f"{c.heading_path} {c.text}" for c in same_family]
    return coverage(question, texts, idf, unknown_term_penalty=unknown_term_penalty)
