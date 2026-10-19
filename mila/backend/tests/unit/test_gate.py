"""Tests for app.core.gate: decision rules, reason codes, confidence, persistence."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import make_test_settings
from sqlalchemy import select

from app.core.gate import (
    GATE_VERSION,
    REASON_LOW_CONFIDENCE,
    REASON_LOW_SUPPORT_RATIO,
    REASON_MEDICATION_OR_DOSE,
    REASON_NO_CITATIONS,
    REASON_NO_SENTENCES,
    REASON_UNREVIEWED_OUTSIDE_DEMO,
    WITHHOLD_REASONS,
    ValidationGate,
    record_decision,
)
from app.core.types import AnswerSentence, GateDecision, RetrievedChunk
from app.models import Event, GateRecord


def _sentence(
    text: str = "A claim.",
    *,
    supported: bool = True,
    score: float = 1.0,
    flagged: bool = False,
    citations: list[str] | None = None,
    reason: str = "",
) -> AnswerSentence:
    return AnswerSentence(
        text=text,
        citations=["S1"] if citations is None else citations,
        supported=supported,
        support_score=score,
        flagged_medication=flagged,
        reason=reason,
    )


def _chunks(statuses: tuple[str, ...] = ("reviewed",)) -> list[RetrievedChunk]:
    return [
        RetrievedChunk(
            chunk_id=f"doc{i}:abcdef12:{i}",
            source_id=f"doc{i}",
            source_title=f"Document {i}",
            source_version="abcdef12",
            text=f"Evidence {i}.",
            review_status=status,
        )
        for i, status in enumerate(statuses, start=1)
    ]


def test_constants_match_the_contract() -> None:
    assert GATE_VERSION == "1.0.0"
    assert set(WITHHOLD_REASONS) == {
        "no_sentences",
        "low_support_ratio",
        "medication_or_dose",
        "low_confidence",
        "no_citations",
        "unreviewed_source_outside_demo",
    }
    gate = ValidationGate()
    assert (gate.min_support_ratio, gate.min_confidence, gate.demo_mode) == (0.6, 0.35, True)


def test_no_sentences_is_the_only_reason_for_an_empty_input() -> None:
    decision = ValidationGate().decide([], _chunks())
    assert decision == GateDecision(
        status="withheld", gate_version=GATE_VERSION, reasons=[REASON_NO_SENTENCES]
    )


def test_fully_supported_answer_is_approved() -> None:
    sentences = [_sentence("One.", score=1.0), _sentence("Two.", score=0.8, citations=["S2"])]
    decision = ValidationGate().decide(sentences, _chunks(("reviewed", "reviewed")))
    assert decision.status == "approved" and decision.reasons == []
    assert decision.kept == sentences and decision.removed == []
    assert decision.support_ratio == 1.0
    assert decision.confidence == pytest.approx(0.7 + 0.3 * 0.9)
    assert decision.gate_version == GATE_VERSION


def test_kept_and_removed_partition_with_reasons() -> None:
    sentences = [
        _sentence("kept", reason="stale reason"),
        _sentence("unsupported", supported=False, score=0.2, reason="unsupported"),
        _sentence("no reason given", supported=False, score=0.0),
        _sentence("flagged", flagged=True, reason="medication_or_dose"),
    ]
    decision = ValidationGate().decide(sentences, _chunks())
    assert [s.text for s in decision.kept] == ["kept"] and decision.kept[0].reason == ""
    assert [(s.text, s.reason) for s in decision.removed] == [
        ("unsupported", "unsupported"),
        ("no reason given", "unsupported"),
        ("flagged", "medication_or_dose"),
    ]
    assert sentences[0].reason == "stale reason", "inputs are not mutated"


def test_support_ratio_and_confidence_formula() -> None:
    sentences = [
        _sentence(score=0.9),
        _sentence(score=0.7),
        _sentence(supported=False, score=0.4),
        _sentence(supported=False, score=0.0),
    ]
    decision = ValidationGate().decide(sentences, _chunks())
    assert decision.support_ratio == 0.5
    assert decision.confidence == pytest.approx(0.7 * 0.5 + 0.3 * 0.8)
    assert decision.status == "withheld" and decision.reasons == [REASON_LOW_SUPPORT_RATIO]


def test_support_ratio_exactly_at_threshold_is_approved() -> None:
    sentences = [_sentence()] * 3 + [_sentence(supported=False, score=0.1)] * 2
    decision = ValidationGate().decide(sentences, _chunks())
    assert decision.support_ratio == 0.6 and decision.status == "approved" and decision.reasons == []
    ten = [_sentence()] * 6 + [_sentence(supported=False)] * 4
    assert ValidationGate().decide(ten, _chunks()).status == "approved"


def test_support_ratio_just_below_threshold_is_withheld() -> None:
    sentences = [_sentence()] * 5 + [_sentence(supported=False)] * 4
    decision = ValidationGate().decide(sentences, _chunks())
    assert decision.support_ratio == pytest.approx(5 / 9, abs=1e-4)
    assert decision.status == "withheld" and REASON_LOW_SUPPORT_RATIO in decision.reasons


def test_any_flagged_sentence_withholds_the_whole_answer() -> None:
    sentences = [_sentence("fine")] * 4 + [_sentence("dose", flagged=True)]
    decision = ValidationGate().decide(sentences, _chunks())
    assert decision.status == "withheld" and decision.reasons == [REASON_MEDICATION_OR_DOSE]
    assert decision.support_ratio == 1.0
    assert [s.text for s in decision.kept] == ["fine"] * 4
    assert [s.text for s in decision.removed] == ["dose"]


def test_no_citations_when_nothing_is_kept() -> None:
    sentences = [_sentence(supported=False, citations=[], reason="no_citation")]
    decision = ValidationGate().decide(sentences, _chunks())
    assert decision.status == "withheld"
    assert decision.reasons == [REASON_NO_CITATIONS, REASON_LOW_SUPPORT_RATIO, REASON_LOW_CONFIDENCE]
    assert decision.confidence == 0.0


@pytest.mark.parametrize("citations", [[], ["S9"], ["S0"], ["Sx"]])
def test_supported_sentence_without_a_resolvable_citation_is_not_kept(citations: list[str]) -> None:
    decision = ValidationGate().decide([_sentence(citations=citations)], _chunks())
    assert decision.kept == [] and decision.removed[0].reason == "unknown_citation"
    assert decision.status == "withheld" and REASON_NO_CITATIONS in decision.reasons


def test_low_confidence_can_fire_alone_with_a_strict_threshold() -> None:
    sentences = [_sentence(score=0.5), _sentence(score=0.5)]
    decision = ValidationGate(min_confidence=0.9).decide(sentences, _chunks())
    assert decision.confidence == pytest.approx(0.85)
    assert decision.status == "withheld" and decision.reasons == [REASON_LOW_CONFIDENCE]


@pytest.mark.parametrize(
    ("demo_mode", "statuses", "citations", "expected"),
    [
        (False, ("public_unreviewed",), ["S1"], "withheld"),
        (False, ("reviewed", "public_unreviewed"), ["S2"], "withheld"),
        (False, ("reviewed", "public_unreviewed"), ["S1"], "approved"),
        (False, ("reviewed",), ["S1"], "approved"),
        (True, ("public_unreviewed",), ["S1"], "approved"),
        (True, ("blocked",), ["S1"], "approved"),
    ],
)
def test_unreviewed_source_outside_demo(
    demo_mode: bool, statuses: tuple[str, ...], citations: list[str], expected: str
) -> None:
    decision = ValidationGate(demo_mode=demo_mode).decide([_sentence(citations=citations)], _chunks(statuses))
    assert decision.status == expected
    assert (REASON_UNREVIEWED_OUTSIDE_DEMO in decision.reasons) == (expected == "withheld")


def test_unreviewed_check_also_counts_chunks_cited_by_removed_sentences() -> None:
    sentences = [_sentence(citations=["S1"]), _sentence(supported=False, citations=["S2"])]
    decision = ValidationGate(demo_mode=False, min_support_ratio=0.5).decide(
        sentences, _chunks(("reviewed", "public_unreviewed"))
    )
    assert REASON_UNREVIEWED_OUTSIDE_DEMO in decision.reasons


def test_from_settings(tmp_path: Path) -> None:
    settings = make_test_settings(
        tmp_path, gate_min_support_ratio=0.8, gate_min_confidence=0.5, demo_mode=False
    )
    gate = ValidationGate.from_settings(settings)
    assert (gate.min_support_ratio, gate.min_confidence, gate.demo_mode) == (0.8, 0.5, False)


def test_record_decision_persists_counts_and_reasons_only(db) -> None:
    sentences = [_sentence("secret sentence text"), _sentence("dose", flagged=True)]
    decision = ValidationGate().decide(sentences, _chunks())
    record = record_decision(db, decision)
    assert record.id is not None and record.event_id is None
    stored = db.get(GateRecord, record.id)
    assert stored.gate_version == GATE_VERSION and stored.status == "withheld"
    assert stored.reasons == [REASON_MEDICATION_OR_DOSE]
    assert stored.support_ratio == 1.0 and stored.confidence == 1.0
    assert stored.n_sentences_in == 2 and stored.n_sentences_kept == 1
    assert "secret" not in repr(stored.__dict__)


def test_record_decision_links_to_an_event(db) -> None:
    event = Event(session_id=None, type="ask", outcome="answered")
    db.add(event)
    db.commit()
    decision = ValidationGate().decide([_sentence()], _chunks())
    record = record_decision(db, decision, event_id=event.id)
    assert record.event_id == event.id
    assert db.scalar(select(GateRecord).where(GateRecord.event_id == event.id)) is record
