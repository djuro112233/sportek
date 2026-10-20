"""Validation gate: the low_relevance rule and the relevance field."""

from __future__ import annotations

from app.config import Settings
from app.core.gate import REASON_LOW_RELEVANCE, ValidationGate
from app.core.types import AnswerSentence, RetrievedChunk


def _chunk() -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id="c",
        source_id="s",
        source_title="t",
        source_version="v",
        text="evidence",
        review_status="reviewed",
    )


def _supported() -> AnswerSentence:
    return AnswerSentence(text="evidence.", citations=["S1"], supported=True, support_score=1.0)


def test_low_relevance_withholds_and_is_recorded() -> None:
    gate = ValidationGate(min_relevance=0.35)
    decision = gate.decide([_supported()], [_chunk()], relevance=0.2)
    assert decision.status == "withheld" and REASON_LOW_RELEVANCE in decision.reasons
    assert decision.relevance == 0.2


def test_relevance_at_threshold_passes_and_none_is_skipped() -> None:
    gate = ValidationGate(min_relevance=0.35)
    assert gate.decide([_supported()], [_chunk()], relevance=0.35).status == "approved"
    decision = gate.decide([_supported()], [_chunk()])
    assert decision.status == "approved" and decision.relevance is None


def test_from_settings_reads_the_relevance_threshold() -> None:
    gate = ValidationGate.from_settings(Settings(gate_min_relevance=0.9, database_url="sqlite:///:memory:"))
    assert gate.min_relevance == 0.9
    assert gate.decide([_supported()], [_chunk()], relevance=0.8).status == "withheld"
