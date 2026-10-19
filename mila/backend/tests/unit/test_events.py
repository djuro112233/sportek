"""Unit tests for app.core.events: aggregate-only event logging and topic classification."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.core.events import classify_topic, log_event
from app.core.types import TOPIC_CLASSES
from app.models import Event


def _event_count(db) -> int:
    return int(db.scalar(select(func.count()).select_from(Event)))


# --- log_event ---------------------------------------------------------------------------------
def test_log_event_persists_aggregate_fields(db):
    ev = log_event(
        db,
        type="ask",
        session_id="abc",
        lang="sr",
        topic_class="pregnancy",
        outcome="answered",
        latency_ms=420,
        support_ratio=0.8,
        redflag_category="",
        input_mode="voice",
        payload={"translated": True, "n_citations": 2},
    )
    stored = db.get(Event, ev.id)
    assert stored is not None
    assert stored.type == "ask"
    assert stored.session_id == "abc"
    assert stored.lang == "sr"
    assert stored.topic_class == "pregnancy"
    assert stored.outcome == "answered"
    assert stored.latency_ms == 420
    assert stored.support_ratio == 0.8
    assert stored.input_mode == "voice"
    assert stored.payload == {"translated": True, "n_citations": 2}
    assert stored.created_at is not None


def test_log_event_defaults(db):
    ev = log_event(db, type="consent", session_id=None)
    assert ev.session_id is None
    assert ev.lang == "" and ev.topic_class == "" and ev.outcome == "" and ev.redflag_category == ""
    assert ev.latency_ms is None and ev.support_ratio is None
    assert ev.input_mode == "text"
    assert ev.payload == {}


@pytest.mark.parametrize("key", ["text", "Question", "TRANSCRIPT", "audio", "Ip", "email", "PHONE", "Name"])
def test_log_event_rejects_user_content_keys_case_insensitively(db, key: str):
    with pytest.raises(ValueError, match="user content"):
        log_event(db, type="ask", session_id=None, payload={key: "anything"})
    assert _event_count(db) == 0


def test_log_event_rejects_mixed_payload_entirely(db):
    with pytest.raises(ValueError):
        log_event(db, type="ask", session_id=None, payload={"translated": True, "text": "boli me"})
    assert _event_count(db) == 0


def test_log_event_error_message_names_the_bad_keys_only(db):
    with pytest.raises(ValueError, match=r"\['phone', 'text'\]"):
        log_event(db, type="ask", session_id=None, payload={"Text": "x", "phone": "y", "ok": 1})


def test_log_event_does_not_mutate_caller_payload(db):
    payload = {"translated": False}
    log_event(db, type="ask", session_id=None, payload=payload)
    assert payload == {"translated": False}


def test_log_event_coerces_unknown_topic_to_other(db):
    ev = log_event(db, type="ask", session_id=None, topic_class="astrology")
    assert ev.topic_class == "other"


@pytest.mark.parametrize("topic", TOPIC_CLASSES)
def test_log_event_keeps_known_topics(db, topic: str):
    assert log_event(db, type="ask", session_id=None, topic_class=topic).topic_class == topic


def test_log_event_keeps_empty_topic_empty(db):
    assert log_event(db, type="speak", session_id=None).topic_class == ""


def test_log_event_rows_accumulate(db):
    for _ in range(3):
        log_event(db, type="ask", session_id="s", outcome="withheld")
    assert _event_count(db) == 3
    assert set(db.scalars(select(Event.outcome))) == {"withheld"}


# --- classify_topic ----------------------------------------------------------------------------
PHRASES = [
    ("Koje su nuspojave pilule za kontracepciju?", "contraception"),
    ("How does the morning after pill work?", "contraception"),
    ("Kada ići na prvi ultrazvuk u trudnoći?", "antenatal_care"),
    ("Kada je prva kontrola u trudnoći?", "antenatal_care"),
    ("Folna kiselina prije začeća", "antenatal_care"),
    ("Kako se dojenje odvija u prvim danima?", "postnatal"),
    ("Koliko dugo traje babinje?", "postnatal"),
    ("Test na trudnoću je pozitivan", "pregnancy"),
    ("When are my fertile days?", "pregnancy"),
    ("Menstruacija mi kasni dvije sedmice", "menstruation"),
    ("Imam iscjedak i svrab", "sti"),
    ("Where can I get a chlamydia test?", "sti"),
    ("Osjećam se depresivno i anksiozno", "mental_health"),
    ("I am a teenager and this is my first time", "adolescent"),
    ("Kada počinje pubertet?", "adolescent"),
    ("Kako da napravim palačinke", "other"),
    ("", "other"),
]


@pytest.mark.parametrize(("phrase", "expected"), PHRASES)
def test_classify_topic(phrase: str, expected: str):
    assert classify_topic(phrase) == expected


def test_classify_topic_handles_cyrillic_input():
    assert classify_topic("Хоћу да питам о контрацепцији") == "contraception"
    assert classify_topic("Крварење у трудноћи") == "pregnancy"


def test_classify_topic_specific_class_wins_over_generic():
    # breastfeeding (postnatal) is more specific than contraception for this question
    assert classify_topic("Which contraception is safe while breastfeeding?") == "postnatal"


def test_classify_topic_always_returns_a_known_class():
    for text in ("lorem ipsum", "123", "???", "Dobar dan"):
        assert classify_topic(text) in TOPIC_CLASSES
