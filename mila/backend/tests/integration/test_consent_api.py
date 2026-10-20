"""Integration tests for /api/consent, /api/consent/text and /api/session/{id} (happy paths)."""

from __future__ import annotations

import re

from sqlalchemy import func, select

from app.core.consent_texts import ADULT_ITEM_KEYS, MINOR_ITEM_KEY
from app.models import Event, SavedQuestion, Session

LATIN_LETTER_RE = re.compile(r"[A-Za-zčćšžđČĆŠŽĐ]")
CONSENT_RESPONSE_KEYS = {
    "session_id",
    "consent_version",
    "lang",
    "script",
    "region",
    "is_minor",
    "save_questions",
}
SESSION_INFO_KEYS = {
    "consent_version","exists", "consent_given", "lang", "script", "region", "is_minor", "save_questions"}


def _consent(client, settings, **overrides):
    body = {"lang": "sr", "is_minor": False, "accepted": True, "consent_version": settings.consent_version}
    body.update(overrides)
    return client.post("/api/consent", json=body)


def _count(db, model, **where) -> int:
    stmt = select(func.count()).select_from(model)
    for column, value in where.items():
        stmt = stmt.where(getattr(model, column) == value)
    return int(db.scalar(stmt))


# --- GET /consent/text -------------------------------------------------------------------------
def test_consent_text_sr_latin(client, settings):
    r = client.get("/api/consent/text", params={"lang": "sr", "script": "latin", "is_minor": "false"})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"version", "text", "spoken_text", "items", "lang", "script"}
    assert body["version"] == settings.consent_version
    assert body["lang"] == "sr" and body["script"] == "latin"
    assert [item["key"] for item in body["items"]] == list(ADULT_ITEM_KEYS)
    assert all(set(item) == {"key", "text"} for item in body["items"])
    assert "ljekar" in body["text"] and "124" in body["spoken_text"]


def test_consent_text_sr_cyrillic_has_no_latin_letters(client):
    r = client.get("/api/consent/text", params={"lang": "sr", "script": "cyrillic"})
    assert r.status_code == 200
    body = r.json()
    assert not LATIN_LETTER_RE.search(body["text"])
    assert not LATIN_LETTER_RE.search(body["spoken_text"])
    assert "124" in body["text"]
    assert body["script"] == "cyrillic"


def test_consent_text_en(client):
    r = client.get("/api/consent/text", params={"lang": "en", "script": "cyrillic"})
    assert r.status_code == 200
    body = r.json()
    assert "not a doctor" in body["text"]
    assert "I am MILA" in body["spoken_text"]


def test_consent_text_minor_adds_trusted_adult_item(client):
    adult = client.get("/api/consent/text", params={"lang": "bs", "is_minor": "false"}).json()
    minor = client.get("/api/consent/text", params={"lang": "bs", "is_minor": "true"}).json()
    assert [i["key"] for i in minor["items"]] == [*ADULT_ITEM_KEYS, MINOR_ITEM_KEY]
    assert minor["items"][:-1] == adult["items"]
    assert "18" in minor["text"]


def test_consent_text_defaults_to_serbian_latin_adult(client):
    body = client.get("/api/consent/text").json()
    assert body["lang"] == "sr" and body["script"] == "latin"
    assert len(body["items"]) == len(ADULT_ITEM_KEYS)


def test_consent_text_rejects_unknown_language_or_script(client):
    assert client.get("/api/consent/text", params={"lang": "xx"}).status_code == 422
    assert client.get("/api/consent/text", params={"lang": "sr", "script": "glagolitic"}).status_code == 422


# --- POST /consent -----------------------------------------------------------------------------
def test_consent_happy_path_sr(client, settings, db):
    r = _consent(client, settings)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == CONSENT_RESPONSE_KEYS
    assert body["consent_version"] == settings.consent_version
    assert body["lang"] == "sr" and body["script"] == "latin"
    assert body["region"] == settings.default_region
    assert body["is_minor"] is False and body["save_questions"] is False

    sess = db.get(Session, body["session_id"])
    assert sess is not None
    assert sess.consent_given is True
    assert sess.consent_given_at is not None
    assert sess.consent_version == settings.consent_version
    assert sess.consent_save_questions is False
    assert sess.is_minor is False

    events = db.scalars(select(Event).where(Event.session_id == sess.id)).all()
    assert [e.type for e in events] == ["consent"]
    assert events[0].payload == {"is_minor": False, "save_questions": False}
    assert events[0].lang == "sr"


def test_consent_happy_path_sr_cyrillic(client, settings, db):
    r = _consent(client, settings, script="cyrillic")
    assert r.status_code == 200
    assert r.json()["script"] == "cyrillic"
    assert db.get(Session, r.json()["session_id"]).script == "cyrillic"


def test_consent_happy_path_en_minor_with_save_questions(client, settings, db):
    r = _consent(client, settings, lang="en", region="ME", is_minor=True, save_questions=True)
    assert r.status_code == 200
    body = r.json()
    assert body["lang"] == "en" and body["region"] == "ME"
    assert body["is_minor"] is True and body["save_questions"] is True
    sess = db.get(Session, body["session_id"])
    assert sess.is_minor is True and sess.consent_save_questions is True and sess.region == "ME"
    event = db.scalars(select(Event).where(Event.session_id == sess.id)).one()
    assert event.payload == {"is_minor": True, "save_questions": True}


def test_consent_region_is_normalised_to_upper_case(client, settings):
    r = _consent(client, settings, region=" me ")
    assert r.status_code == 200
    assert r.json()["region"] == "ME"


def test_each_consent_creates_a_distinct_random_session(client, settings):
    ids = {_consent(client, settings).json()["session_id"] for _ in range(5)}
    assert len(ids) == 5
    assert all(len(sid) == 32 for sid in ids)


# --- GET /session/{id} -------------------------------------------------------------------------
def test_get_session_known(client, settings):
    sid = _consent(client, settings, lang="hr", script="latin", region="BA", is_minor=True).json()[
        "session_id"
    ]
    r = client.get(f"/api/session/{sid}")
    assert r.status_code == 200
    assert r.json() == {
        "exists": True,
        "consent_version": "2026-10-01",
        "consent_given": True,
        "lang": "hr",
        "script": "latin",
        "region": "BA",
        "is_minor": True,
        "save_questions": False,
    }
    assert set(r.json()) == SESSION_INFO_KEYS


# --- POST /session/{id}/preferences ------------------------------------------------------------
def test_preferences_update_lang_script_region_and_minor_flag(client, settings, db):
    sid = _consent(client, settings).json()["session_id"]
    r = client.post(
        f"/api/session/{sid}/preferences",
        json={"lang": "me", "script": "cyrillic", "region": "me", "is_minor": True},
    )
    assert r.status_code == 200
    assert r.json()["lang"] == "me" and r.json()["script"] == "cyrillic"
    assert r.json()["region"] == "ME" and r.json()["is_minor"] is True
    db.expire_all()
    sess = db.get(Session, sid)
    assert (sess.lang, sess.script, sess.region, sess.is_minor) == ("me", "cyrillic", "ME", True)


def test_preferences_partial_update_leaves_other_fields(client, settings):
    sid = _consent(client, settings, lang="bs", region="ME").json()["session_id"]
    r = client.post(f"/api/session/{sid}/preferences", json={"script": "cyrillic"})
    assert r.status_code == 200
    assert r.json()["lang"] == "bs" and r.json()["region"] == "ME" and r.json()["script"] == "cyrillic"


def test_preferences_save_questions_on_then_off_wipes_saved_rows(client, settings, db):
    sid = _consent(client, settings).json()["session_id"]
    r = client.post(f"/api/session/{sid}/preferences", json={"save_questions": True})
    assert r.status_code == 200 and r.json()["save_questions"] is True

    db.add(SavedQuestion(session_id=sid, text="kada je prvi ultrazvuk", lang="sr", outcome="answered"))
    db.add(SavedQuestion(session_id=sid, text="koliko traje babinje", lang="sr", outcome="answered"))
    db.commit()
    assert _count(db, SavedQuestion, session_id=sid) == 2

    r = client.post(f"/api/session/{sid}/preferences", json={"save_questions": False})
    assert r.status_code == 200 and r.json()["save_questions"] is False
    assert _count(db, SavedQuestion, session_id=sid) == 0
    db.expire_all()
    assert db.get(Session, sid).consent_save_questions is False


def test_preferences_ignore_ui_only_fields(client, settings):
    sid = _consent(client, settings).json()["session_id"]
    r = client.post(f"/api/session/{sid}/preferences", json={"low_bandwidth": True})
    assert r.status_code == 200
    assert r.json()["exists"] is True


def test_preferences_reject_invalid_values(client, settings):
    sid = _consent(client, settings).json()["session_id"]
    assert client.post(f"/api/session/{sid}/preferences", json={"region": "Bosna"}).status_code == 422
    assert client.post(f"/api/session/{sid}/preferences", json={"lang": "de"}).status_code == 422


# --- DELETE /session/{id} ----------------------------------------------------------------------
def test_delete_session_returns_counts_and_logs_an_anonymous_delete_event(client, settings, db):
    sid = _consent(client, settings, save_questions=True).json()["session_id"]
    db.add(SavedQuestion(session_id=sid, text="pitanje", lang="sr"))
    db.commit()

    r = client.delete(f"/api/session/{sid}")
    assert r.status_code == 200
    assert r.json() == {
        "deleted": {"saved_questions": 1, "gate_records": 0, "events": 1, "sessions": 1, "audio_tokens": 0}
    }

    db.expire_all()
    assert db.get(Session, sid) is None
    assert _count(db, Event, session_id=sid) == 0
    assert _count(db, SavedQuestion, session_id=sid) == 0
    delete_events = db.scalars(select(Event).where(Event.type == "delete")).all()
    assert len(delete_events) == 1
    assert delete_events[0].session_id is None
    assert delete_events[0].payload == {}
    assert client.get(f"/api/session/{sid}").json()["exists"] is False
