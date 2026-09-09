"""Claim #5 — the visitor-request lifecycle: sent → confirmed | refused → completed | cancelled | expired.

No bookings and no payments: a confirmation is a message. The visitor stays anonymous — the host
never sees the random ``session_id`` the browser keeps, and the event stream stores only its keyed
pseudonym.
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models import Event, Listing, User, Village, VisitorRequest
from app.pseudonym import SESSION as SESSION_KIND, pseudonymise
from app.services import requests_lifecycle as lifecycle

SESSION = "test-session-request-00000001"
OTHER_SESSION = "test-session-request-00000002"
LISTING = "konoba-maslina-sample"  # host1@example.org, Gornja Lastva
HOST2_LISTING = "apartman-lastva-sample"  # host2@example.org, Donja Lastva


def _send(client, listing: str = LISTING, session: str = SESSION, **extra) -> dict:
    body = {
        "listing_id": listing,
        "message": "Dobar dan, da li je moguća posjeta u subotu? (uzorak)",
        "session_id": session,
        "party_size": 2,
    }
    body.update(extra)
    r = client.post("/api/requests", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _events(db, event_type: str, session: str = SESSION) -> list[Event]:
    return list(
        db.scalars(
            select(Event)
            .where(Event.event_type == event_type)
            .order_by(Event.occurred_at, Event.id)
        )
    )


# --- send ------------------------------------------------------------------------------------
def test_sending_a_request_creates_it_and_emits_request_sent(client, db):
    before = len(_events(db, "request_sent"))
    body = _send(client, device_id="test-device-request-0001")
    assert body["status"] == "sent"
    assert body["listing"]["slug"] == LISTING
    assert body["village_slug"] == "gornja-lastva" and body["municipality"] == "Tivat"
    assert body["party_size"] == 2 and body["expires_at"], "an unanswered request expires by itself"
    assert body["no_booking"] is True and body["message_to_visitor"]

    req = db.get(VisitorRequest, uuid.UUID(body["id"]))
    assert req.status == "sent" and req.visitor_session_id == SESSION
    expected = req.created_at + timedelta(days=lifecycle.DEFAULT_TTL_DAYS)
    assert abs((req.expires_at - expected).total_seconds()) < 2

    events = _events(db, "request_sent")
    assert len(events) == before + 1
    ev = events[-1]
    assert ev.session_pseudonym == pseudonymise(SESSION_KIND, SESSION)
    assert SESSION not in json.dumps(ev.properties)
    assert ev.item_type == "listing" and ev.municipality == "Tivat"
    assert ev.properties["party_size"] == 2 and ev.properties["has_requested_date"] is False


def test_a_requested_date_shortens_the_expiry():
    created = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)
    assert lifecycle.default_expiry(created, date(2026, 9, 20)) == datetime(
        2026, 9, 21, 0, 0, tzinfo=timezone.utc
    )
    assert lifecycle.default_expiry(created, None) == created + timedelta(days=30)


def test_mine_returns_only_the_visitors_own_requests(client):
    sent = _send(client)
    mine = client.get("/api/requests/mine", params={"session_id": SESSION}).json()
    assert sent["id"] in [r["id"] for r in mine]
    assert all(r["listing"]["slug"] for r in mine)
    other = client.get("/api/requests/mine", params={"session_id": OTHER_SESSION}).json()
    assert sent["id"] not in [r["id"] for r in other]
    assert client.get("/api/requests/mine").status_code == 422  # session_id is required


def test_a_request_to_a_draft_listing_is_404(client, db):
    host = db.scalars(select(User).where(User.email == "host1@example.org")).one()
    village = db.scalars(select(Village).where(Village.slug == "gornja-lastva")).one()
    draft = db.scalars(select(Listing).where(Listing.slug == "test-draft-listing")).first()
    if draft is None:
        draft = Listing(
            slug="test-draft-listing", host_user_id=host.id, village_id=village.id, category="food",
            title_local="Nacrt ponude (test)", title_en="Draft listing (test)", status="draft", version=1,
        )
        db.add(draft)
        db.commit()
    r = client.post(
        "/api/requests",
        json={"listing_id": str(draft.id), "message": "hello", "session_id": SESSION},
    )
    assert r.status_code == 404
    assert client.post(
        "/api/requests", json={"listing_id": "no-such-listing", "message": "hello", "session_id": SESSION}
    ).status_code == 404


def test_input_validation(client):
    too_long = {"listing_id": LISTING, "message": "x" * 2001, "session_id": SESSION}
    assert client.post("/api/requests", json=too_long).status_code == 422
    assert client.post("/api/requests", json={"listing_id": LISTING, "message": "hi"}).status_code == 422
    assert client.post(
        "/api/requests", json={"listing_id": LISTING, "message": "", "session_id": SESSION}
    ).status_code == 422
    assert client.post(
        "/api/requests", json={"listing_id": LISTING, "message": "hi", "session_id": "short"}
    ).status_code == 422


# --- host side --------------------------------------------------------------------------------
def test_host_sees_own_requests_without_any_visitor_session_id(client, login):
    sent = _send(client)
    rows = client.get("/api/requests/host", headers=login("host")).json()
    mine = [r for r in rows if r["id"] == sent["id"]]
    assert mine, "host1 owns the konoba listing"
    assert SESSION not in json.dumps(rows), "the visitor's session id must never reach the host"
    assert "visitor_session_id" not in json.dumps(rows)
    assert mine[0]["message"] and mine[0]["can_respond"] is True

    other_host = client.get("/api/requests/host", headers=login("host2")).json()
    assert sent["id"] not in [r["id"] for r in other_host]
    assert client.get("/api/requests/host").status_code == 401


def test_a_host_may_not_answer_another_hosts_request(client, login):
    sent = _send(client)
    r = client.post(
        f"/api/requests/{sent['id']}/respond",
        json={"status": "confirmed", "reply": "no"},
        headers=login("host2"),
    )
    assert r.status_code == 403
    r2 = client.post(
        f"/api/requests/{sent['id']}/close", json={"status": "completed"}, headers=login("host2")
    )
    assert r2.status_code == 403


def test_confirm_then_complete(client, login, db):
    sent = _send(client, requested_date="2026-10-03")
    confirmed = client.post(
        f"/api/requests/{sent['id']}/respond",
        json={"status": "confirmed", "reply": "Dobrodošli u subotu u 10h. (uzorak)"},
        headers=login("host"),
    )
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert body["status"] == "confirmed" and body["responded_at"] and body["host_reply"]
    assert body["no_booking_note"]

    completed = client.post(
        f"/api/requests/{sent['id']}/close", json={"status": "completed", "note": "Posjeta obavljena."},
        headers=login("host"),
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed" and completed.json()["closed_at"]

    # a closed request cannot be reopened or closed twice
    again = client.post(
        f"/api/requests/{sent['id']}/close", json={"status": "completed"}, headers=login("host")
    )
    assert again.status_code == 409

    for event_type in ("request_confirmed", "request_completed"):
        ev = _events(db, event_type)[-1]
        assert ev.item_type == "listing" and ev.municipality == "Tivat"
        assert ev.actor_role == "host" and ev.actor_pseudonym
        assert ev.session_pseudonym is None, "a host action never carries the visitor's session"
    assert _events(db, "request_confirmed")[-1].properties["from_status"] == "sent"


def test_host_refuses_a_request(client, login, db):
    sent = _send(client)
    refused = client.post(
        f"/api/requests/{sent['id']}/respond",
        json={"status": "refused", "reply": "Nažalost, popunjeni smo tog dana. (uzorak)"},
        headers=login("host"),
    )
    assert refused.status_code == 200 and refused.json()["status"] == "refused"
    assert _events(db, "request_refused")[-1].properties["closed_by"] == "host"
    # refusing twice is a conflict, not a silent no-op
    assert client.post(
        f"/api/requests/{sent['id']}/respond", json={"status": "refused"}, headers=login("host")
    ).status_code == 409


# --- visitor cancels ---------------------------------------------------------------------------
def test_a_visitor_cancels_only_their_own_request(client, db):
    sent = _send(client)
    wrong = client.post(f"/api/requests/{sent['id']}/cancel", json={"session_id": OTHER_SESSION})
    assert wrong.status_code == 403

    ok = client.post(f"/api/requests/{sent['id']}/cancel", json={"session_id": SESSION})
    assert ok.status_code == 200 and ok.json()["status"] == "cancelled"
    assert ok.json()["closed_at"] and ok.json()["can_cancel"] is False

    ev = _events(db, "request_cancelled")[-1]
    assert ev.properties["closed_by"] == "visitor"
    assert ev.session_pseudonym == pseudonymise(SESSION_KIND, SESSION)
    assert ev.actor_pseudonym is None

    assert client.post(
        f"/api/requests/{sent['id']}/cancel", json={"session_id": SESSION}
    ).status_code == 409
    assert client.post(
        "/api/requests/00000000-0000-0000-0000-000000000000/cancel", json={"session_id": SESSION}
    ).status_code == 404


# --- expiry ------------------------------------------------------------------------------------
def test_expire_stale_requests_closes_overdue_rows(client, db):
    sent = _send(client, session=OTHER_SESSION)
    req = db.get(VisitorRequest, uuid.UUID(sent["id"]))
    req.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    db.commit()

    before = len(_events(db, "request_expired"))
    result = lifecycle.expire_stale_requests(db)
    assert result["expired"] >= 1 and sent["id"] in result["ids"]

    db.expire_all()
    assert db.get(VisitorRequest, req.id).status == "expired"
    assert db.get(VisitorRequest, req.id).closed_at is not None
    events = _events(db, "request_expired")
    assert len(events) == before + result["expired"]
    assert events[-1].properties["closed_by"] == "system"
    assert events[-1].actor_pseudonym is None

    # idempotent: a second run closes nothing
    assert lifecycle.expire_stale_requests(db)["expired"] == 0

    # an expired request can no longer be answered
    r = client.post(f"/api/requests/{sent['id']}/cancel", json={"session_id": OTHER_SESSION})
    assert r.status_code == 409


def test_the_lifecycle_map_matches_the_models(db):
    from app.models import REQUEST_STATUS_EVENT, REQUEST_STATUS_VALUES

    assert set(lifecycle.REQUEST_TRANSITIONS) == set(REQUEST_STATUS_EVENT)
    assert set(REQUEST_STATUS_VALUES) == {"sent"} | set(lifecycle.REQUEST_TRANSITIONS)
    for to_status, froms in lifecycle.REQUEST_TRANSITIONS.items():
        assert froms and set(froms) <= set(lifecycle.OPEN_STATUSES)
