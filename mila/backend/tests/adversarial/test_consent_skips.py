"""Adversarial tests: attempts to skip, forge or over-share consent must store nothing.

Every negative case also asserts that no session and no event was written, because an error
response that leaves a half-created session behind would be a consent bypass.
"""

from __future__ import annotations

import json

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.api.deps import require_consented_session
from app.models import Event, SavedQuestion, Session

IDENTIFYING_COLUMN_WORDS = frozenset(
    {
        "age",
        "birth",
        "birthdate",
        "dob",
        "name",
        "phone",
        "tel",
        "email",
        "mail",
        "ip",
        "device",
        "address",
        "jmbg",
    }
)


def _body(settings, **overrides) -> dict:
    body = {"lang": "sr", "is_minor": False, "accepted": True, "consent_version": settings.consent_version}
    body.update(overrides)
    return body


def _count(db, model, **where) -> int:
    stmt = select(func.count()).select_from(model)
    for column, value in where.items():
        stmt = stmt.where(getattr(model, column) == value)
    return int(db.scalar(stmt))


def _assert_nothing_stored(db) -> None:
    assert _count(db, Session) == 0
    assert _count(db, Event) == 0


# --- refusing consent --------------------------------------------------------------------------
def test_not_accepted_is_403_and_nothing_is_stored(client, settings, db):
    r = client.post("/api/consent", json=_body(settings, accepted=False))
    assert r.status_code == 403
    assert r.json() == {"detail": "consent_required"}
    _assert_nothing_stored(db)


def test_not_accepted_wins_even_with_save_questions_on(client, settings, db):
    r = client.post("/api/consent", json=_body(settings, accepted=False, save_questions=True))
    assert r.status_code == 403
    _assert_nothing_stored(db)


def test_missing_accepted_is_422(client, settings, db):
    body = _body(settings)
    del body["accepted"]
    assert client.post("/api/consent", json=body).status_code == 422
    _assert_nothing_stored(db)


# --- minors ------------------------------------------------------------------------------------
def test_missing_is_minor_is_422(client, settings, db):
    body = _body(settings)
    del body["is_minor"]
    r = client.post("/api/consent", json=body)
    assert r.status_code == 422
    _assert_nothing_stored(db)


def test_is_minor_must_be_a_yes_no_not_an_age(client, settings, db):
    assert client.post("/api/consent", json=_body(settings, is_minor=15)).status_code == 422
    _assert_nothing_stored(db)


# --- extra fields ------------------------------------------------------------------------------
def test_age_field_is_rejected(client, settings, db):
    r = client.post("/api/consent", json=_body(settings, age=15))
    assert r.status_code == 422
    assert r.json()["detail"][0]["type"] == "extra_forbidden"
    _assert_nothing_stored(db)


def test_name_field_is_rejected(client, settings, db):
    r = client.post("/api/consent", json=_body(settings, name="Mina"))
    assert r.status_code == 422
    _assert_nothing_stored(db)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("birth_date", "2011-05-04"),
        ("phone", "+387 61 123 456"),
        ("email", "mina@example.org"),
        ("device_id", "a1b2c3"),
        ("ip", "10.0.0.7"),
        ("jmbg", "0405011123456"),
        ("session_id", "forged-id-000000000000000000000"),
    ],
)
def test_identifying_fields_are_rejected(client, settings, db, field: str, value: str):
    r = client.post("/api/consent", json=_body(settings, **{field: value}))
    assert r.status_code == 422
    _assert_nothing_stored(db)


# --- versions and values -----------------------------------------------------------------------
def test_outdated_version_is_409_with_the_current_version(client, settings, db):
    r = client.post("/api/consent", json=_body(settings, consent_version="2020-01-01"))
    assert r.status_code == 409
    assert r.json() == {"detail": "consent_version_outdated", "current": settings.consent_version}
    _assert_nothing_stored(db)


def test_empty_version_is_422(client, settings, db):
    assert client.post("/api/consent", json=_body(settings, consent_version="")).status_code == 422
    _assert_nothing_stored(db)


@pytest.mark.parametrize(
    "overrides", [{"region": "Bosna"}, {"region": "B1"}, {"lang": "de"}, {"script": "runic"}]
)
def test_invalid_region_lang_or_script_is_422(client, settings, db, overrides: dict):
    assert client.post("/api/consent", json=_body(settings, **overrides)).status_code == 422
    _assert_nothing_stored(db)


# --- forged sessions ---------------------------------------------------------------------------
def test_forged_session_get_reports_not_exists_without_error(client, db):
    r = client.get("/api/session/forged-session-id-0000000000000000")
    assert r.status_code == 200
    assert r.json() == {
        "exists": False,
        "consent_given": None,
        "lang": None,
        "script": None,
        "region": None,
        "is_minor": None,
        "save_questions": None,
    }
    _assert_nothing_stored(db)


def test_forged_session_delete_is_200_with_zero_counts(client, db):
    r = client.delete("/api/session/forged-session-id-0000000000000000")
    assert r.status_code == 200
    assert r.json() == {"deleted": {"saved_questions": 0, "gate_records": 0, "events": 0, "sessions": 0}}
    assert _count(db, Session) == 0
    assert _count(db, Event, type="delete") == 1  # the deletion attempt itself is counted anonymously


def test_forged_session_preferences_is_403(client, db):
    r = client.post(
        "/api/session/forged-session-id-0000000000000000/preferences", json={"save_questions": True}
    )
    assert r.status_code == 403
    _assert_nothing_stored(db)


def test_oversized_session_id_is_rejected(client):
    sid = "x" * 65
    assert client.get(f"/api/session/{sid}").status_code == 422
    assert client.delete(f"/api/session/{sid}").status_code == 422


def test_require_consented_session_raises_403_for_unknown_session(db):
    with pytest.raises(HTTPException) as exc:
        require_consented_session("no-such-session", db)
    assert exc.value.status_code == 403


def test_require_consented_session_raises_403_without_consent(db):
    db.add(Session(id="half-session", consent_given=False))
    db.commit()
    with pytest.raises(HTTPException) as exc:
        require_consented_session("half-session", db)
    assert exc.value.status_code == 403


def test_require_consented_session_returns_the_consented_session(db):
    db.add(Session(id="ok-session", consent_given=True))
    db.commit()
    assert require_consented_session("ok-session", db).id == "ok-session"


# --- what the consent act stores ---------------------------------------------------------------
def test_consent_event_carries_no_text(client, settings, db):
    r = client.post("/api/consent", json=_body(settings, lang="en", is_minor=True))
    assert r.status_code == 200
    event = db.scalars(select(Event).where(Event.type == "consent")).one()
    assert set(event.payload) == {"is_minor", "save_questions"}
    assert all(isinstance(v, bool) for v in event.payload.values())
    assert event.topic_class == "" and event.outcome == "" and event.redflag_category == ""
    assert event.latency_ms is None and event.support_ratio is None
    # no free text anywhere in the payload: only the two boolean flags
    assert not any(isinstance(v, str) for v in event.payload.values())
    assert json.loads(json.dumps(event.payload)) == {"is_minor": True, "save_questions": False}


def test_repeated_delete_is_idempotent(client, settings, db):
    sid = client.post("/api/consent", json=_body(settings)).json()["session_id"]
    first = client.delete(f"/api/session/{sid}")
    second = client.delete(f"/api/session/{sid}")
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["deleted"]["sessions"] == 1
    assert second.json()["deleted"] == {"saved_questions": 0, "gate_records": 0, "events": 0, "sessions": 0}
    assert client.get(f"/api/session/{sid}").json()["exists"] is False
    assert _count(db, Session) == 0


def test_preferences_off_wipes_saved_questions_immediately(client, settings, db):
    sid = client.post("/api/consent", json=_body(settings, save_questions=True)).json()["session_id"]
    db.add(SavedQuestion(session_id=sid, text="kada je prvi ultrazvuk", lang="sr"))
    db.add(SavedQuestion(session_id=sid, text="koliko traje babinje", lang="sr"))
    db.commit()
    assert _count(db, SavedQuestion, session_id=sid) == 2

    r = client.post(f"/api/session/{sid}/preferences", json={"save_questions": False})
    assert r.status_code == 200 and r.json()["save_questions"] is False
    assert _count(db, SavedQuestion, session_id=sid) == 0
    assert client.get(f"/api/session/{sid}").json()["exists"] is True


def test_preferences_cannot_grant_consent_or_change_the_id(client, settings, db):
    sid = client.post("/api/consent", json=_body(settings)).json()["session_id"]
    r = client.post(
        f"/api/session/{sid}/preferences", json={"consent_given": False, "id": "other", "age": 15}
    )
    assert r.status_code == 200
    db.expire_all()
    assert db.get(Session, sid).consent_given is True
    assert db.get(Session, "other") is None
    assert _count(db, Session) == 1


# --- schema ------------------------------------------------------------------------------------
def test_session_table_has_no_identifying_columns():
    columns = {c.name for c in Session.__table__.columns}
    assert "age" not in columns
    for column in columns:
        words = set(column.lower().split("_"))
        assert words.isdisjoint(IDENTIFYING_COLUMN_WORDS), column
    assert "is_minor" in columns


def test_event_table_has_no_text_or_identifier_columns():
    columns = {c.name for c in Event.__table__.columns}
    assert columns.isdisjoint(
        {"text", "question", "transcript", "audio", "ip", "email", "phone", "name", "age"}
    )


def test_consent_response_does_not_echo_anything_the_server_did_not_store(client, settings):
    body = client.post("/api/consent", json=_body(settings)).json()
    assert set(body) == {
        "session_id",
        "consent_version",
        "lang",
        "script",
        "region",
        "is_minor",
        "save_questions",
    }
