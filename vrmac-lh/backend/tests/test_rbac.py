"""Role-based access control on every write endpoint of the validation-gate module.

For each write: no token → 401, wrong role → 403. Plus the two rules that are easy to get wrong:

* the validator's queue and audit trail are not readable by a host;
* nobody can file a gender self-report on behalf of somebody else.

Every call in this file is expected to be refused, so the database is left untouched — the last
test checks that explicitly.
"""
from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.config import settings
from app.models import AuditLog, HeritageEntry, Listing, Provenance, User


@pytest.fixture(scope="module")
def ids(client):
    """Ids of a seeded heritage entry and of the two hosts' listings."""
    from app.db import SessionLocal

    with SessionLocal() as db:
        entry = db.scalars(select(HeritageEntry).where(HeritageEntry.slug == "gornja-lastva")).one()
        listing = db.scalars(select(Listing).where(Listing.slug == "konoba-maslina-sample")).one()
        other = db.scalars(select(Listing).where(Listing.slug == "apartman-lastva-sample")).one()
        host1 = db.scalars(select(User).where(User.email == "host1@example.org")).one()
        return {
            "entry": str(entry.id),
            "listing_of_host1": str(listing.id),
            "listing_of_host2": str(other.id),
            "host1": str(host1.id),
        }


NEW_ENTRY = {
    "village": "gornja-lastva",
    "kind": "place",
    "title_local": "RBAC test",
    "title_en": "RBAC test",
    "source": "test",
}


# --- heritage ----------------------------------------------------------------------------------
def test_create_heritage_entry_requires_a_token(client):
    assert client.post("/api/heritage", json=NEW_ENTRY).status_code == 401


@pytest.mark.parametrize("role", ["host", "institution"])
def test_create_heritage_entry_refuses_the_wrong_role(client, login, role):
    r = client.post("/api/heritage", json=NEW_ENTRY, headers=login(role))
    assert r.status_code == 403, r.text


def test_update_heritage_entry_requires_a_token(client, ids):
    assert client.put(f"/api/heritage/{ids['entry']}", json={"title_en": "x"}).status_code == 401


@pytest.mark.parametrize("role", ["host", "institution"])
def test_update_heritage_entry_refuses_the_wrong_role(client, login, ids, role):
    r = client.put(f"/api/heritage/{ids['entry']}", json={"title_en": "x"}, headers=login(role))
    assert r.status_code == 403, r.text


def test_heritage_provenance_refuses_a_host(client, login, ids):
    assert client.get(f"/api/heritage/{ids['entry']}/provenance").status_code == 401
    r = client.get(f"/api/heritage/{ids['entry']}/provenance", headers=login("host"))
    assert r.status_code == 403, r.text


# --- listings ----------------------------------------------------------------------------------
def test_update_listing_requires_a_token(client, ids):
    assert client.put(f"/api/listings/{ids['listing_of_host1']}", json={"capacity": 2}).status_code == 401


@pytest.mark.parametrize("role", ["validator", "institution"])
def test_update_listing_refuses_the_wrong_role(client, login, ids, role):
    r = client.put(f"/api/listings/{ids['listing_of_host1']}", json={"capacity": 2}, headers=login(role))
    assert r.status_code == 403, r.text


def test_a_host_cannot_edit_another_hosts_listing(client, login, ids):
    r = client.put(f"/api/listings/{ids['listing_of_host2']}", json={"capacity": 2}, headers=login("host"))
    assert r.status_code == 403, r.text


def test_my_listings_is_host_only(client, login):
    assert client.get("/api/listings/mine").status_code == 401
    for role in ("ambassador", "validator", "institution"):
        assert client.get("/api/listings/mine", headers=login(role)).status_code == 403


def test_a_host_only_sees_their_own_listings(client, login, ids):
    r = client.get("/api/listings/mine", headers=login("host"))
    assert r.status_code == 200, r.text
    slugs = {l["slug"] for l in r.json()}
    assert "konoba-maslina-sample" in slugs
    assert "apartman-lastva-sample" not in slugs


# --- validation --------------------------------------------------------------------------------
def test_validation_queue_is_not_readable_by_a_host(client, login):
    assert client.get("/api/validation/queue").status_code == 401
    r = client.get("/api/validation/queue", headers=login("host"))
    assert r.status_code == 403, r.text
    assert client.get("/api/validation/queue", headers=login("institution")).status_code == 403
    assert client.get("/api/validation/queue", headers=login("validator")).status_code == 200


def test_validation_item_view_is_staff_only(client, login, ids):
    path = f"/api/validation/items/heritage_entry/{ids['entry']}"
    assert client.get(path).status_code == 401
    assert client.get(path, headers=login("host")).status_code == 403
    assert client.get(path, headers=login("validator")).status_code == 200


def test_transitions_require_a_token_and_an_allowed_role(client, login, ids):
    path = f"/api/validation/items/heritage_entry/{ids['entry']}/transition"
    assert client.post(path, json={"to_status": "draft"}).status_code == 401
    # ('approved' → 'draft') is a validator's step: a host and an institution are refused.
    for role in ("host", "institution"):
        r = client.post(path, json={"to_status": "draft", "note": "rbac"}, headers=login(role))
        assert r.status_code == 403, r.text


def test_audit_trail_is_validator_or_institution_only(client, login):
    assert client.get("/api/validation/audit").status_code == 401
    for role in ("host", "ambassador"):
        assert client.get("/api/validation/audit", headers=login(role)).status_code == 403
    for role in ("validator", "institution"):
        r = client.get("/api/validation/audit", headers=login(role))
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), list)


# --- gender self-report ---------------------------------------------------------------------------
def test_gender_cannot_be_reported_for_another_user(client, login, db, ids):
    """The self-report has no subject parameter, and smuggling one in is refused."""
    host9 = db.scalars(select(User).where(User.email == "host9@example.org")).one()
    before = (host9.gender, host9.gender_self_reported)

    for body in (
        {"gender": "female", "user_id": ids["host1"]},
        {"gender": "female", "email": "host9@example.org"},
        {"gender": "female", "id": str(host9.id)},
    ):
        r = client.post("/api/auth/me/gender", json=body, headers=login("ambassador"))
        assert r.status_code == 422, r.text

    db.expire_all()
    host9 = db.scalars(select(User).where(User.email == "host9@example.org")).one()
    assert (host9.gender, host9.gender_self_reported) == before

    # A valid self-report only ever changes the caller's own row.
    ambassador = db.scalars(select(User).where(User.email == "ambassador1@example.org")).one()
    r = client.post("/api/auth/me/gender", json={"gender": "female"}, headers=login("ambassador"))
    assert r.status_code == 200 and r.json()["id"] == str(ambassador.id)


def test_refused_calls_wrote_nothing(client, db, ids):
    """None of the refusals above created content, provenance or audit noise."""
    assert db.scalar(select(func.count()).select_from(HeritageEntry).where(
        HeritageEntry.title_en == "RBAC test")) == 0
    assert db.scalar(select(func.count()).select_from(Provenance).where(
        Provenance.note == "rbac")) == 0
    assert db.scalar(select(func.count()).select_from(AuditLog).where(
        AuditLog.resource_id.in_((ids["entry"], ids["listing_of_host1"], ids["listing_of_host2"])),
        AuditLog.action.in_(("heritage_entry.create", "heritage_entry.update", "listing.update")),
    )) == 0
    # The sample listing is untouched: still approved, still version 1.
    listing = db.scalars(select(Listing).where(Listing.slug == "konoba-maslina-sample")).one()
    assert listing.status == "approved" and listing.version == 1


def test_every_sample_account_can_sign_in(client):
    """RBAC is about roles, not about broken accounts: each sample role authenticates."""
    from tests.conftest import SAMPLE_ACCOUNTS

    for role, email in SAMPLE_ACCOUNTS.items():
        r = client.post("/api/auth/login", json={"email": email, "password": settings.seed_password})
        assert r.status_code == 200, f"{role}: {r.text}"
