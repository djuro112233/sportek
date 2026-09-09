"""Support check — the second, automatic control of innovation claim #2.

The first control is human: an entry must be *approved* before it can be retrieved. The second is
per answer: **every sentence of an answer must be attributable to a cited approved passage**. A
sentence that is not attributable is removed; if nothing survives, the answer is withheld and an
``answer_withheld`` event is logged.

Two implementations behind one interface (``SUPPORT_CHECK_PROVIDER``):

* ``lexical`` — deterministic entailment proxy, and the conservative default in tests and whenever a
  model is unavailable. A sentence is supported only when

  1. **every number, year and price in the sentence occurs in the passage** (a hard gate: invented
     dates or amounts can never pass), and
  2. the share of the sentence's content-word stems found in the passage reaches
     ``SUPPORT_MIN_SCORE``.

* ``llm_judge`` — the configured model judges each sentence against the cited passages and answers
  with strict JSON. It can only ever *lower* the verdict: the lexical check runs first and the
  sentence must pass both. Any parse error, unavailability or exhausted spend cap degrades to the
  lexical verdict (recorded as ``lexical_fallback``), never to "supported".
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Protocol

from ..config import settings
from .embeddings import content_tokens, normalize
from .llm import LLMUnavailable, get_llm, parse_json_object

log = logging.getLogger(__name__)

STEM_LEN = 5
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


@dataclass
class SupportVerdict:
    sentence: str
    supported: bool
    score: float
    method: str
    passage_index: int | None = None
    reason: str = ""

    def as_dict(self) -> dict:
        return {
            "sentence": self.sentence,
            "supported": self.supported,
            "score": round(self.score, 3),
            "method": self.method,
            "passage_index": self.passage_index,
            "reason": self.reason,
        }


def _stems(text: str) -> set[str]:
    return {t[:STEM_LEN] for t in content_tokens(text)}


def _numbers(text: str) -> set[str]:
    """Numbers normalised so that 1974, 1.974 and 1,974 compare equal."""
    return {n.replace(",", ".").rstrip("0").rstrip(".") if "." in n or "," in n else n for n in _NUMBER.findall(text)}


_SENTENCE = re.compile(r"[^.!?]*[.!?]+(?:\s*\[\d+\])*|[^.!?]+$")
_ORDINAL_END = re.compile(r"\d+\.$")


def split_sentences(text: str) -> list[str]:
    """Split an answer into sentences, keeping trailing citation markers such as ``[1]`` attached.

    Two details matter for the support check, which judges one sentence at a time:

    * a citation marker belongs to the sentence it follows, so ``"A. [1] B. [2]"`` is two sentences,
      each carrying its own marker;
    * an ordinal written with a full stop (Montenegrin ``1974. godine``, ``14. vijeka``) is not a
      sentence end, so such a fragment is merged with the one that follows it.
    """
    text = (text or "").strip()
    if not text:
        return []
    parts = [m.group().strip() for m in _SENTENCE.finditer(text)]
    merged: list[str] = []
    for part in (p for p in parts if p):
        stripped = re.sub(r"(?:\s*\[\d+\])*$", "", part).strip()
        if merged and _ORDINAL_END.search(re.sub(r"(?:\s*\[\d+\])*$", "", merged[-1]).strip()) and part[:1].islower():
            merged[-1] = f"{merged[-1]} {part}"
        elif merged and stripped and merged[-1].endswith(("[", " ")):
            merged[-1] = f"{merged[-1]}{part}"
        else:
            merged.append(part)
    return merged


class SupportChecker(Protocol):
    name: str

    def check(self, sentence: str, passages: list[str]) -> SupportVerdict: ...


class LexicalSupport:
    """Deterministic attributability check (numbers gate + content-stem coverage)."""

    name = "lexical"

    def __init__(self, min_score: float):
        self.min_score = min_score

    def check(self, sentence: str, passages: list[str]) -> SupportVerdict:
        clean = re.sub(r"\[\d+\]", " ", sentence)
        sent_stems = _stems(clean)
        sent_numbers = _numbers(normalize(clean))
        best = SupportVerdict(sentence, False, 0.0, self.name, None, "no cited passage")
        for i, passage in enumerate(passages):
            p_stems = _stems(passage)
            p_numbers = _numbers(normalize(passage))
            missing = sent_numbers - p_numbers
            if missing:
                if best.score == 0.0:
                    best = SupportVerdict(
                        sentence, False, 0.0, self.name, i,
                        f"number(s) not in the cited passage: {', '.join(sorted(missing))}",
                    )
                continue
            coverage = 1.0 if not sent_stems else len(sent_stems & p_stems) / len(sent_stems)
            if coverage > best.score:
                best = SupportVerdict(
                    sentence, coverage >= self.min_score, coverage, self.name, i,
                    "" if coverage >= self.min_score else f"only {coverage:.0%} of the words occur in the passage",
                )
        return best


_JUDGE_SYSTEM = (
    "You verify attribution. Given SOURCES and one SENTENCE, decide whether the sentence is fully "
    "supported by the sources. Be strict: any detail (number, date, name, place, claim) that is not "
    "in the sources means it is NOT supported. Paraphrase of the sources is supported. "
    'Answer with JSON only: {"supported": true|false, "score": 0.0-1.0, "source": <1-based index or null>, '
    '"reason": "<short>"}'
)


class LLMJudgeSupport:
    """Model-judged attribution on top of the lexical gate (it can only lower the verdict)."""

    name = "llm_judge"

    def __init__(self, min_score: float):
        self.min_score = min_score
        self.lexical = LexicalSupport(min_score)

    def check(self, sentence: str, passages: list[str]) -> SupportVerdict:
        base = self.lexical.check(sentence, passages)
        if not base.supported:
            return base  # the lexical gate already refused; the judge cannot raise it
        sources = "\n".join(f"[{i + 1}] {p}" for i, p in enumerate(passages))
        try:
            result = get_llm().complete(
                _JUDGE_SYSTEM,
                f"SOURCES:\n{sources}\n\nSENTENCE:\n{re.sub(r'\\[\\d+\\]', '', sentence).strip()}",
                json_mode=True,
                max_tokens=160,
                temperature=0.0,
            )
            data = parse_json_object(result.text)
        except (LLMUnavailable, ValueError, KeyError) as exc:
            log.info("support judge unavailable (%s) — keeping the lexical verdict", exc.__class__.__name__)
            return SupportVerdict(
                sentence, base.supported, base.score, "lexical_fallback", base.passage_index, base.reason
            )
        supported = bool(data.get("supported"))
        try:
            score = float(data.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        score = min(base.score, max(0.0, min(1.0, score)))
        idx = data.get("source")
        passage_index = (int(idx) - 1) if isinstance(idx, (int, float)) and int(idx) >= 1 else base.passage_index
        return SupportVerdict(
            sentence,
            supported and score >= self.min_score,
            score,
            self.name,
            passage_index,
            str(data.get("reason", ""))[:200] if not supported else "",
        )


_instance: SupportChecker | None = None


def get_support_checker() -> SupportChecker:
    global _instance
    if _instance is None:
        p = settings.support_check_provider
        if p == "lexical":
            _instance = LexicalSupport(settings.support_min_score)
        elif p == "llm_judge":
            _instance = LLMJudgeSupport(settings.support_min_score)
        else:
            raise ValueError(f"unknown SUPPORT_CHECK_PROVIDER {p}")
    return _instance


def reset_support_cache() -> None:
    global _instance
    _instance = None
