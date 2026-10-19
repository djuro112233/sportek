"""Unit tests for app.core.privacy: redaction, k-anonymity, secure deletion, session erasure, ids."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.core.events import log_event
from app.core.privacy import (
    RedactionFilter,
    delete_session_data,
    k_anonymize,
    new_session_id,
    redact,
    secure_delete,
    suppress_small,
)
from app.models import Event, GateRecord, SavedQuestion, Session


# --- redaction ---------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "mask", "secret"),
    [
        ("Authorization: Bearer abcdef1234567890token", "Bearer [REDACTED]", "abcdef1234567890token"),
        ("api_key=sk-ABCDEFGHIJKLMNOP1234", "[REDACTED]", "ABCDEFGHIJKLMNOP1234"),
        ("token: ZXCVBNMASDFGHJ123 was sent", "token=[REDACTED]", "ZXCVBNMASDFGHJ123"),
        ("secret='s3cr3tvalue99' leaked", "secret=[REDACTED]", "s3cr3tvalue99"),
        ("contact ana.petrovic@example.org now", "[EMAIL]", "ana.petrovic"),
        ("call +387 61 123 456 today", "[PHONE]", "61 123 456"),
        ("broj 061/123-456", "[PHONE]", "123-456"),
        ("jmbg 0101990123456 ok", "[ID13]", "0101990123456"),
        ("from 192.168.1.25 port 443", "[IP]", "192.168.1.25"),
    ],
)
def test_redact_masks_secrets_and_identifiers(raw: str, mask: str, secret: str):
    out = redact(raw)
    assert mask in out
    assert secret not in out


def test_redact_masks_several_identifiers_in_one_message():
    out = redact("user mina@example.com, tel +382 67 123 456, ip 10.0.0.7, id 1234567890123")
    assert out == "user [EMAIL], tel [PHONE], ip [IP], id [ID13]"


def test_redact_leaves_normal_text_alone():
    text = "Krvarenje u 12. nedjelji trudnoće, temperatura 38.5, pozovi 124. Boli me stomak 3 dana."
    assert redact(text) == text


def test_redact_leaves_cyrillic_text_alone():
    text = "Крварење у трудноћи, температура 38,5, позови 124."
    assert redact(text) == text


def test_redact_is_idempotent():
    once = redact("mail a@b.org tel 061 123 456")
    assert redact(once) == once


def test_redaction_filter_rewrites_records_on_a_real_logger(caplog: pytest.LogCaptureFixture):
    logger = logging.getLogger("mila.test.redaction")
    flt = RedactionFilter()
    logger.addFilter(flt)
    try:
        with caplog.at_level(logging.INFO, logger="mila.test.redaction"):
            logger.info("user %s called from %s", "mina@example.com", "10.0.0.7")
    finally:
        logger.removeFilter(flt)
    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.getMessage() == "user [EMAIL] called from [IP]"
    assert record.args == ()
    assert "mina@example.com" not in caplog.text
    assert "10.0.0.7" not in caplog.text


def test_redaction_filter_never_drops_records(caplog: pytest.LogCaptureFixture):
    logger = logging.getLogger("mila.test.redaction.keep")
    flt = RedactionFilter()
    logger.addFilter(flt)
    try:
        with caplog.at_level(logging.WARNING, logger="mila.test.redaction.keep"):
            logger.warning("plain message without identifiers")
            logger.warning("bearer %s", "XyZ1234567890abcdef")
    finally:
        logger.removeFilter(flt)
    messages = [r.getMessage() for r in caplog.records]
    assert messages == ["plain message without identifiers", "bearer [REDACTED]"]


# --- k-anonymity -------------------------------------------------------------------------------
def test_k_anonymize_drops_rows_below_k_and_keeps_the_rest_in_order():
    rows = [
        {"topic": "a", "count": 4},
        {"topic": "b", "count": 5},
        {"topic": "c", "count": 6},
        {"topic": "d"},
    ]
    assert k_anonymize(rows, "count", 5) == [{"topic": "b", "count": 5}, {"topic": "c", "count": 6}]


def test_k_anonymize_missing_count_is_treated_as_zero():
    assert k_anonymize([{"topic": "a"}], "count", 1) == []
    assert k_anonymize([{"topic": "a"}], "count", 0) == [{"topic": "a"}]


def test_k_anonymize_does_not_mutate_input():
    rows = [{"count": 1}, {"count": 9}]
    k_anonymize(rows, "count", 5)
    assert rows == [{"count": 1}, {"count": 9}]


@pytest.mark.parametrize(
    ("value", "k", "expected"),
    [(4, 5, None), (5, 5, 5), (6, 5, 6), (0, 5, None), (0, 1, None), (1, 1, 1), (0, 0, 0)],
)
def test_suppress_small_boundaries(value: int, k: int, expected: int | None):
    assert suppress_small(value, k) == expected


# --- secure deletion ---------------------------------------------------------------------------
def test_secure_delete_removes_the_file(tmp_path: Path):
    path = tmp_path / "upload.wav"
    path.write_bytes(b"RIFF" * 256)
    secure_delete(path)
    assert not path.exists()


def test_secure_delete_on_missing_path_is_a_noop(tmp_path: Path):
    path = tmp_path / "missing.wav"
    secure_delete(path)
    assert not path.exists()


def test_secure_delete_accepts_string_paths(tmp_path: Path):
    path = tmp_path / "upload.wav"
    path.write_bytes(b"x")
    secure_delete(str(path))  # type: ignore[arg-type]
    assert not path.exists()


def test_secure_delete_empty_file(tmp_path: Path):
    path = tmp_path / "empty.wav"
    path.touch()
    secure_delete(path)
    assert not path.exists()


# --- delete_session_data -----------------------------------------------------------------------
def _seed_session(db, session_id: str, *, n_events: int = 2, n_saved: int = 2) -> None:
    db.add(Session(id=session_id, consent_given=True, consent_save_questions=True))
    db.commit()
    events = [log_event(db, type="ask", session_id=session_id, outcome="answered") for _ in range(n_events)]
    db.add(GateRecord(event_id=events[0].id, gate_version="1.0.0", status="approved", reasons=[]))
    for i in range(n_saved):
        db.add(SavedQuestion(session_id=session_id, text=f"saved question {i}", lang="sr"))
    db.commit()


def _count(db, model, **where) -> int:
    stmt = select(func.count()).select_from(model)
    for column, value in where.items():
        stmt = stmt.where(getattr(model, column) == value)
    return int(db.scalar(stmt))


def test_delete_session_data_removes_everything_and_keeps_other_sessions(db):
    _seed_session(db, "victim")
    _seed_session(db, "other")
    other_event_ids = list(db.scalars(select(Event.id).where(Event.session_id == "other")))

    counts = delete_session_data(db, "victim")

    assert counts == {"saved_questions": 2, "gate_records": 1, "events": 2, "sessions": 1}
    assert db.get(Session, "victim") is None
    assert _count(db, Event, session_id="victim") == 0
    assert _count(db, SavedQuestion, session_id="victim") == 0
    assert db.get(Session, "other") is not None
    assert _count(db, Event, session_id="other") == 2
    assert _count(db, SavedQuestion, session_id="other") == 2
    assert _count(db, GateRecord, event_id=other_event_ids[0]) == 1


def test_delete_session_data_unknown_id_returns_zero_counts(db):
    assert delete_session_data(db, "no-such-session") == {
        "saved_questions": 0,
        "gate_records": 0,
        "events": 0,
        "sessions": 0,
    }


def test_delete_session_data_is_idempotent(db):
    _seed_session(db, "once")
    first = delete_session_data(db, "once")
    second = delete_session_data(db, "once")
    assert first["sessions"] == 1
    assert second == {"saved_questions": 0, "gate_records": 0, "events": 0, "sessions": 0}


# --- session ids -------------------------------------------------------------------------------
def test_new_session_id_length_and_charset():
    sid = new_session_id()
    assert len(sid) == 32  # token_urlsafe(24): 192 bits, base64url without padding
    assert re.fullmatch(r"[A-Za-z0-9_-]+", sid)


def test_new_session_id_is_unique():
    ids = {new_session_id() for _ in range(2000)}
    assert len(ids) == 2000
