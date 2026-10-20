"""Integration tests for GET /api/referral: lazy seeding, filters, rendering, event logging."""

from __future__ import annotations

from sqlalchemy import func, select

from app.core.i18n import t
from app.core.referral import seed_points
from app.db import session_factory
from app.models import Event, ReferralPoint


def _db():
    return session_factory()()


def test_default_request_returns_general_referral_for_default_region(client, settings):
    response = client.get("/api/referral")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"emergency", "message", "points"}
    assert body["emergency"] is False
    assert body["message"] == t("referral_general", "sr")
    assert body["points"] and all(p["region"] == settings.default_region for p in body["points"])
    assert body["points"][0]["kind"] == "clinic"


def test_table_is_seeded_lazily_on_first_request(client):
    db = _db()
    try:
        assert db.scalar(select(func.count()).select_from(ReferralPoint)) == 0
        client.get("/api/referral")
        assert db.scalar(select(func.count()).select_from(ReferralPoint)) == len(seed_points())
        client.get("/api/referral")
        assert db.scalar(select(func.count()).select_from(ReferralPoint)) == len(seed_points())
    finally:
        db.close()


def test_emergency_category_puts_ambulance_first(client):
    body = client.get(
        "/api/referral", params={"region": "BA", "category": "bleeding_pregnancy", "lang": "bs"}
    ).json()
    assert body["emergency"] is True
    assert body["message"] == t("redflag_emergency", "bs")
    first = body["points"][0]
    assert first["kind"] == "er" and first["phone"] == "124" and first["emergency"] is True


def test_violence_for_a_minor_includes_sos_line_police_and_child_line(client):
    body = client.get(
        "/api/referral",
        params={"region": "ME", "category": "violence_coercion", "minor": "true", "lang": "me"},
    ).json()
    kinds = [p["kind"] for p in body["points"]]
    assert kinds[0] == "violence" and "child_protection" in kinds
    assert any(p["name"] == "Policija 122" for p in body["points"])
    assert all(p["region"] == "ME" for p in body["points"])
    assert body["message"] == t("redflag_support", "me")


def test_child_protection_category(client):
    body = client.get("/api/referral", params={"category": "minor_sexual_adult", "minor": "true"}).json()
    assert body["points"][0]["kind"] == "child_protection"
    assert body["message"] == t("redflag_child_protection", "sr")


def test_cyrillic_script_renders_message_for_bcms_only(client):
    cyr = client.get("/api/referral", params={"lang": "sr", "script": "cyrillic"}).json()
    assert cyr["message"] == t("referral_general", "sr", "cyrillic")
    en = client.get("/api/referral", params={"lang": "en", "script": "cyrillic"}).json()
    assert en["message"] == t("referral_general", "en")


def test_unknown_region_is_rejected(client):
    assert client.get("/api/referral", params={"region": "XX", "category": "fever_pregnancy"}).status_code == 422
    body = client.get("/api/referral", params={"region": "ME", "category": "fever_pregnancy"}).json()
    assert body["points"] and body["points"][0]["kind"] == "er"
    pairs = [(p["name"], p["phone"]) for p in body["points"]]
    assert len(pairs) == len(set(pairs))
    assert all("notes" not in p for p in body["points"])


def test_region_is_case_insensitive(client):
    body = client.get("/api/referral", params={"region": "me"}).json()
    assert body["points"] and all(p["region"] == "ME" for p in body["points"])


def test_invalid_category_and_script_are_rejected(client):
    assert client.get("/api/referral", params={"category": "diagnosis"}).status_code == 422
    assert client.get("/api/referral", params={"script": "greek"}).status_code == 422
    assert client.get("/api/referral", params={"minor": "maybe"}).status_code == 422


def test_seed_numbers_are_only_the_standard_emergency_numbers(client):
    points = []
    for region in ("BA", "ME"):
        points += client.get("/api/referral", params={"region": region, "category": "minor_sexual_adult"}).json()["points"]
    for point in points:
        assert point["verified_on"] == ""
        assert point["phone"] in {"", "124", "122"}


def test_referral_view_event_is_logged_without_any_text(client):
    client.get(
        "/api/referral",
        params={"region": "BA", "category": "suicidal_ideation", "minor": "true", "lang": "hr"},
    )
    db = _db()
    try:
        events = list(db.scalars(select(Event).where(Event.type == "referral_view")))
    finally:
        db.close()
    assert len(events) == 1
    event = events[0]
    assert event.session_id is None
    assert event.lang == "hr" and event.outcome == "ok" and event.redflag_category == "suicidal_ideation"
    assert event.payload == {
        "region": "BA",
        "minor": True,
        "emergency": True,
        "n_points": event.payload["n_points"],
    }
    assert not {"text", "question", "transcript", "ip", "phone", "name"} & set(event.payload)
    assert event.topic_class == "" and event.support_ratio is None


def test_every_request_logs_one_event(client):
    for _ in range(3):
        client.get("/api/referral")
    db = _db()
    try:
        assert db.scalar(select(func.count()).select_from(Event).where(Event.type == "referral_view")) == 3
    finally:
        db.close()
