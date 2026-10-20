"""Validation gate: approve or withhold the whole answer, with stable reason codes.

The gate is the last check before an answer reaches the user. It works on the sentences the
verifier produced and never looks at the raw text. A withheld answer is never shown in part;
the API replaces it with the localised refusal and a referral. Every decision is persisted as
a :class:`GateRecord` (reasons and counts only, no text) by :func:`record_decision`.
"""

from __future__ import annotations

from statistics import fmean

from sqlalchemy.orm import Session as DbSession

from app.config import Settings
from app.core.types import AnswerSentence, GateDecision, RetrievedChunk
from app.core.verifier import REASON_MEDICATION, REASON_UNKNOWN_CITATION, REASON_UNSUPPORTED
from app.models import GateRecord

GATE_VERSION = "1.0.0"

REASON_NO_SENTENCES = "no_sentences"
REASON_NO_CITATIONS = "no_citations"
REASON_MEDICATION_OR_DOSE = "medication_or_dose"
REASON_LOW_SUPPORT_RATIO = "low_support_ratio"
REASON_LOW_CONFIDENCE = "low_confidence"
REASON_UNREVIEWED_OUTSIDE_DEMO = "unreviewed_source_outside_demo"
REASON_LOW_RELEVANCE = "low_relevance"
WITHHOLD_REASONS: tuple[str, ...] = (
    REASON_NO_SENTENCES,
    REASON_NO_CITATIONS,
    REASON_MEDICATION_OR_DOSE,
    REASON_LOW_SUPPORT_RATIO,
    REASON_LOW_CONFIDENCE,
    REASON_UNREVIEWED_OUTSIDE_DEMO,
)

SUPPORT_RATIO_WEIGHT = 0.7
KEPT_SUPPORT_WEIGHT = 0.3


class ValidationGate:
    """Decide whether a verified answer may be shown.

    * ``kept`` = sentences that are supported, not flagged for medication and cite at least one
      retrieved chunk (a "supported" sentence without a resolvable citation is contradictory
      and is removed with reason ``unknown_citation``); ``removed`` = the rest, each with a
      non-empty reason.
    * ``support_ratio`` = supported sentences / all sentences (0 when there are none).
    * ``confidence`` = ``0.7 * support_ratio + 0.3 * mean(support_score of kept)``.
    * Withhold reasons, several may apply: ``no_sentences`` (nothing came in; the only reason
      then), ``no_citations`` (no kept sentence cites a retrieved chunk), ``medication_or_dose``
      (any input sentence is flagged; one dosing sentence withholds the whole answer),
      ``low_support_ratio``, ``low_confidence`` and ``unreviewed_source_outside_demo`` (a chunk
      cited by any sentence is not ``reviewed`` while ``demo_mode`` is off).
    """

    def __init__(
        self,
        min_support_ratio: float = 0.6,
        min_confidence: float = 0.35,
        demo_mode: bool = True,
        min_relevance: float = 0.35,
    ) -> None:
        self.min_support_ratio = min_support_ratio
        self.min_confidence = min_confidence
        self.demo_mode = demo_mode
        self.min_relevance = min_relevance

    @classmethod
    def from_settings(cls, settings: Settings) -> ValidationGate:
        """Gate with the thresholds and demo flag from the settings."""
        return cls(
            min_support_ratio=settings.gate_min_support_ratio,
            min_confidence=settings.gate_min_confidence,
            demo_mode=settings.demo_mode,
            min_relevance=settings.gate_min_relevance,
        )

    def decide(
        self,
        sentences: list[AnswerSentence],
        chunks: list[RetrievedChunk],
        *,
        relevance: float | None = None,
    ) -> GateDecision:
        """Approve or withhold. ``relevance`` is the question coverage of the cited evidence
        (:func:`app.core.relevance.question_relevance`); ``None`` means not assessable and the
        relevance rule is skipped."""
        if not sentences:
            return GateDecision(status="withheld", gate_version=GATE_VERSION, reasons=[REASON_NO_SENTENCES])

        kept: list[AnswerSentence] = []
        removed: list[AnswerSentence] = []
        for sentence in sentences:
            cites_chunk = bool(_resolve(sentence.citations, len(chunks)))
            if sentence.supported and not sentence.flagged_medication and cites_chunk:
                kept.append(sentence.model_copy(update={"reason": ""}))
            else:
                if sentence.flagged_medication:
                    reason = REASON_MEDICATION
                elif sentence.supported and not cites_chunk:
                    reason = REASON_UNKNOWN_CITATION
                else:
                    reason = sentence.reason or REASON_UNSUPPORTED
                removed.append(sentence.model_copy(update={"reason": reason}))

        support_ratio = sum(1 for s in sentences if s.supported) / len(sentences)
        kept_support = fmean(s.support_score for s in kept) if kept else 0.0
        confidence = SUPPORT_RATIO_WEIGHT * support_ratio + KEPT_SUPPORT_WEIGHT * kept_support

        reasons: list[str] = []
        if not kept:
            reasons.append(REASON_NO_CITATIONS)
        if any(s.flagged_medication for s in sentences):
            reasons.append(REASON_MEDICATION_OR_DOSE)
        if support_ratio < self.min_support_ratio:
            reasons.append(REASON_LOW_SUPPORT_RATIO)
        if confidence < self.min_confidence:
            reasons.append(REASON_LOW_CONFIDENCE)
        if not self.demo_mode and any(
            c.review_status != "reviewed" for c in _cited_chunks(sentences, chunks)
        ):
            reasons.append(REASON_UNREVIEWED_OUTSIDE_DEMO)
        if relevance is not None and relevance < self.min_relevance:
            reasons.append(REASON_LOW_RELEVANCE)

        return GateDecision(
            status="approved" if not reasons else "withheld",
            gate_version=GATE_VERSION,
            reasons=reasons,
            support_ratio=round(support_ratio, 4),
            confidence=round(confidence, 4),
            relevance=relevance,
            kept=kept,
            removed=removed,
        )


def _resolve(markers: list[str], n_chunks: int) -> list[int]:
    """Chunk indices the markers point to (``S1`` → 0), in order, without duplicates or misses."""
    indices: list[int] = []
    for marker in markers:
        digits = marker[1:]
        if not digits.isdigit():
            continue
        index = int(digits) - 1
        if 0 <= index < n_chunks and index not in indices:
            indices.append(index)
    return indices


def _cited_chunks(sentences: list[AnswerSentence], chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """Chunks cited by any sentence (kept or removed), in marker order, without duplicates."""
    indices: list[int] = []
    for sentence in sentences:
        for index in _resolve(sentence.citations, len(chunks)):
            if index not in indices:
                indices.append(index)
    return [chunks[i] for i in indices]


def record_decision(db: DbSession, decision: GateDecision, event_id: int | None = None) -> GateRecord:
    """Persist the decision (status, reasons, ratios, counts; never text) and return the row."""
    record = GateRecord(
        event_id=event_id,
        gate_version=decision.gate_version,
        status=decision.status,
        reasons=list(decision.reasons),
        support_ratio=decision.support_ratio,
        confidence=decision.confidence,
        n_sentences_in=len(decision.kept) + len(decision.removed),
        n_sentences_kept=len(decision.kept),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record
