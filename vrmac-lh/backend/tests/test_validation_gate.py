"""Claim 1 — the validation gate, proven against PostgreSQL.

Every content item is ``draft | reviewed | approved | rejected`` with a provenance record, and only
``approved`` items reach the visitor side. The gate is enforced in the **data layer**, not in the UI:

* the visitor role (``public_db``) may only ``SELECT``, and row-level security limits every content
  table to ``status='approved'`` — writes and the private tables are refused by PostgreSQL itself;
* the services filter ``status == 'approved'`` explicitly on top of that;
* CHECK constraints refuse an invalid status, a version below 1 and impossible coordinates.

The tests below also cover the two rules that keep unvalidated claims out of the site: a listing
cannot be approved without a consent record, and an item whose facts are not verified can never be
approved at all.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from app.models import (
    AuditLog,
    ConsentRecord,
    EntryChunk,
    HeritageEntry,
    Listing,
    Provenance,
    TrailReport,
    TrailSegment,
    User,
    Village,
)
from app.services import indexing

def hidden_slugs(db) -> list[str]:
    """Every seeded content item that is not approved, read from the database rather than listed.

    A hardcoded list silently stops covering new sample content: it named four slugs while the seed
    carries six, so the two draft trail segments were never checked.
    """
    slugs: list[str] = []
    for model in (HeritageEntry, Listing, TrailSegment):
        slugs += list(db.scalars(select(model.slug).where(model.status != "approved")))
    assert len(slugs) >= 6, "the seed must keep exercising the gate with non-approved content"
    return slugs


#: Content tables the visitor role may read (approved rows only).
GATED_TABLES = ("heritage_entries", "listings", "trail_segments", "trail_reports")

#: Reference tables the visitor role may read in full (they carry no unvalidated claim).
PUBLIC_REFERENCE_TABLES = ("villages",)


def private_tables() -> list[str]:
    """Every other table in the schema, derived from the models.

    Also derived rather than listed: the previous fixed tuple named 9 of the schema's 20 tables, so
    kpi_runs, kpi_heat_cells, response_cache, stt_evaluations and visitor_requests were never tested
    against the visitor role, and any table added later would have been missed too.
    """
    from app import models as _models  # noqa: F401 - registers every table on the metadata
    from app.db import Base

    known = set(GATED_TABLES) | set(PUBLIC_REFERENCE_TABLES) | {"entry_chunks"}
    tables = sorted(set(Base.metadata.tables) - known)
    assert len(tables) >= 10, "the schema should have more private tables than this"
    return tables


def _denied(session, statement: str) -> None:
    """The statement must be refused by PostgreSQL; the session is rolled back afterwards."""
    with pytest.raises(ProgrammingError) as excinfo:
        session.execute(text(statement))
    assert "permission denied" in str(excinfo.value).lower(), statement
    session.rollback()


def _chunk_count(db, entry_id: uuid.UUID) -> int:
    return db.scalar(select(func.count()).select_from(EntryChunk).where(EntryChunk.entry_id == entry_id))


def _entry(db, slug: str) -> HeritageEntry:
    return db.scalars(select(HeritageEntry).where(HeritageEntry.slug == slug)).one()


# --- 1. the public API returns approved content only -------------------------------------------
def test_public_heritage_api_returns_approved_entries_only(client, db):
    r = client.get("/api/heritage")
    assert r.status_code == 200, r.text
    entries = r.json()
    assert entries, "the seed must publish approved sample entries"
    assert {e["status"] for e in entries} == {"approved"}

    published = {e["slug"] for e in entries}
    for slug in hidden_slugs(db):
        assert slug not in published, f"{slug} must not be listed"
        assert client.get(f"/api/heritage/{slug}").status_code == 404, f"{slug} must 404"

    # …while the rows do exist in the database: they are gated, not missing.
    hidden = hidden_slugs(db)
    for model in (HeritageEntry, Listing, TrailSegment):
        rows = list(db.scalars(select(model).where(model.slug.in_(hidden))))
        assert all(r.status != "approved" for r in rows)
    hidden_entries = list(db.scalars(select(HeritageEntry).where(HeritageEntry.slug.in_(hidden))))
    assert {e.status for e in hidden_entries} == {"draft", "reviewed", "rejected"}, (
        "the seed must exercise every non-approved status"
    )

    # The gate holds for the other public collections too.
    for path in ("/api/listings", "/api/trails"):
        r = client.get(path)
        if r.status_code == 404:  # pragma: no cover - the trails router is built in parallel
            continue
        assert r.status_code == 200, r.text
        assert all(item.get("status", "approved") == "approved" for item in r.json())


def test_the_calendar_only_lists_approved_events(client):
    r = client.get("/api/heritage/calendar")
    assert r.status_code == 200, r.text
    events = r.json()
    assert events, "the seed has approved sample events"
    assert {e["kind"] for e in events} == {"event"}
    assert {e["status"] for e in events} == {"approved"}
    dated = [e["event_date"] for e in events if e["event_date"]]
    assert dated == sorted(dated)  # nulls (recurring events) sort last
    assert [e["event_date"] for e in events][: len(dated)] == dated


# --- 2. the data layer: the visitor role cannot see or change anything else ---------------------
def test_visitor_role_reads_approved_rows_only(public_db):
    for table in GATED_TABLES:
        statuses = public_db.execute(text(f"SELECT status FROM {table}")).scalars().all()
        assert statuses, f"{table}: the visitor role must see the approved sample rows"
        assert set(statuses) == {"approved"}, f"{table} leaked non-approved rows"
        public_db.rollback()


def test_visitor_role_sees_reports_of_approved_segments_only(public_db, db):
    """A report is only public when its segment is public too (RLS ``EXISTS`` clause)."""
    visible = set(public_db.execute(text("SELECT segment_id FROM trail_reports")).scalars().all())
    public_db.rollback()
    approved_segments = set(db.scalars(select(TrailSegment.id).where(TrailSegment.status == "approved")))
    assert visible <= approved_segments


def test_visitor_role_sees_chunks_of_approved_entries_only(public_db, db):
    entry_ids = set(public_db.execute(text("SELECT DISTINCT entry_id FROM entry_chunks")).scalars().all())
    public_db.rollback()
    assert entry_ids, "approved entries are indexed for retrieval"
    approved = set(db.scalars(select(HeritageEntry.id).where(HeritageEntry.status == "approved")))
    assert entry_ids <= approved


def test_visitor_role_cannot_write(public_db):
    for table in GATED_TABLES + ("entry_chunks", "villages"):
        _denied(public_db, f"INSERT INTO {table} DEFAULT VALUES")
        _denied(public_db, f"UPDATE {table} SET id = id")
        _denied(public_db, f"DELETE FROM {table}")


def test_visitor_role_cannot_read_the_private_tables(public_db):
    for table in private_tables():
        _denied(public_db, f"SELECT * FROM {table} LIMIT 1")


def test_visitor_role_may_read_villages_as_reference_data(public_db):
    n = public_db.execute(text("SELECT count(*) FROM villages")).scalar()
    assert n == 6
    public_db.rollback()


# --- 3. bypass attempt: stale chunks of a draft entry stay invisible ----------------------------
def test_chunks_of_a_draft_entry_are_unreachable(db, public_db):
    """Index a draft entry through the application role, then check the visitor still sees nothing.

    This simulates the worst case — an indexing job that ran while the entry was approved and left
    chunks behind after it was withdrawn. The row-level-security policy on ``entry_chunks`` joins
    back to ``heritage_entries``, so the chunks disappear with the entry's status.
    """
    entry = _entry(db, "sample-draft-zlatno-zvono")
    assert entry.status == "draft"
    try:
        entry.status = "approved"  # flip only to make the indexer write chunks
        db.flush()
        written = indexing.reindex_entry(db, entry.id)
        assert written > 0
        entry.status = "draft"
        db.commit()

        assert _chunk_count(db, entry.id) == written, "the chunks are still in the table"

        public_db.rollback()
        visible = public_db.execute(
            text("SELECT count(*) FROM entry_chunks WHERE entry_id = :e"), {"e": str(entry.id)}
        ).scalar()
        assert visible == 0, "the visitor role must not reach chunks of a non-approved entry"
        public_db.rollback()
    finally:
        indexing.remove_entry_index(db, entry.id)
        entry.status = "draft"
        db.commit()
    assert _chunk_count(db, entry.id) == 0


# --- 4. the state machine, end to end -----------------------------------------------------------
def test_state_machine_approve_and_withdraw(client, db, login):
    slug = "sample-draft-zlatno-zvono"
    entry = _entry(db, slug)
    path = f"/api/validation/items/heritage_entry/{entry.id}/transition"
    assert entry.status == "draft" and entry.facts_verified is False
    try:
        # A host may not approve anything.
        r = client.post(path, json={"to_status": "approved"}, headers=login("host"))
        assert r.status_code == 403, r.text

        # Neither may a validator, while the facts of the entry are unverified.
        r = client.post(path, json={"to_status": "approved"}, headers=login("validator"))
        assert r.status_code == 409, r.text
        assert "verif" in r.json()["detail"].lower()

        # The ambassador verifies the facts against the cited source and records that.
        entry.facts_verified = True
        entry.verification_note = "verified against the cited source (test)"
        db.commit()

        r = client.post(
            path, json={"to_status": "approved", "note": "checked the source"}, headers=login("validator")
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "approved" and r.json()["approved_at"]

        # Visible to visitors, and indexed for retrieval.
        assert client.get(f"/api/heritage/{slug}").status_code == 200
        assert slug in {e["slug"] for e in client.get("/api/heritage").json()}
        db.expire_all()
        assert _chunk_count(db, entry.id) > 0, "an approved entry is indexed"

        # The provenance trail grew with the actor's role, the version and the new status.
        trail = client.get(f"/api/heritage/{entry.id}/provenance", headers=login("validator")).json()
        approved = [p for p in trail if p["action"] == "approved"]
        assert approved, trail
        assert approved[-1]["actor_role"] == "validator"
        assert approved[-1]["to_status"] == "approved" and approved[-1]["from_status"] == "draft"
        assert approved[-1]["version"] == entry.version
        assert approved[-1]["note"] == "checked the source"

        # …and so did the audit log.
        db.expire_all()
        actions = set(
            db.scalars(select(AuditLog.action).where(AuditLog.resource_id == str(entry.id))).all()
        )
        assert "heritage_entry.approved" in actions

        # Withdrawn again: invisible, and the index is cleaned up.
        r = client.post(
            path, json={"to_status": "draft", "note": "withdrawn in the test"}, headers=login("validator")
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "draft"
        assert client.get(f"/api/heritage/{slug}").status_code == 404
        assert slug not in {e["slug"] for e in client.get("/api/heritage").json()}
        db.expire_all()
        assert _chunk_count(db, entry.id) == 0, "a withdrawn entry leaves no chunks behind"

        trail = client.get(f"/api/heritage/{entry.id}/provenance", headers=login("validator")).json()
        assert trail[-1]["action"] == "returned_to_draft" and trail[-1]["to_status"] == "draft"
        assert [p["action"] for p in trail][:1] == ["created"]
        db.expire_all()
        actions = set(
            db.scalars(select(AuditLog.action).where(AuditLog.resource_id == str(entry.id))).all()
        )
        assert {"heritage_entry.approved", "heritage_entry.returned_to_draft"} <= actions
    finally:
        db.expire_all()
        entry = _entry(db, slug)
        entry.facts_verified = False
        entry.verification_note = "Sample content for the validation-gate test; never approved."
        entry.status = "draft"
        indexing.remove_entry_index(db, entry.id)
        db.commit()


def test_a_rejected_entry_cannot_jump_to_approved(client, db, login):
    entry = _entry(db, "sample-rejected-rimska-vila")
    assert entry.status == "rejected"
    r = client.post(
        f"/api/validation/items/heritage_entry/{entry.id}/transition",
        json={"to_status": "approved"},
        headers=login("validator"),
    )
    assert r.status_code == 409, r.text
    assert "not allowed" in r.json()["detail"]
    db.expire_all()
    assert _entry(db, "sample-rejected-rimska-vila").status == "rejected"


def test_new_entries_need_a_citation_and_a_village_and_start_as_drafts(client, db, login):
    """Nothing enters the site unvalidated, and nothing is stored without a source or a village."""
    base = {
        "village": "gornja-lastva",
        "kind": "tradition",
        "title_local": "UZORAK: novi unos (test kapije)",
        "title_en": "GATE TEST: new entry",
        "summary_local": "Uzorak.",
        "summary_en": "Sample.",
        "source": "test: cited source of the gate test",
    }
    headers = login("ambassador")
    assert client.post("/api/heritage", json={k: v for k, v in base.items() if k != "source"},
                       headers=headers).status_code == 422
    assert client.post("/api/heritage", json={**base, "source": "   "}, headers=headers).status_code == 422
    assert client.post("/api/heritage", json={**base, "village": ""}, headers=headers).status_code == 422
    r = client.post("/api/heritage", json={**base, "village": "no-such-village"}, headers=headers)
    assert r.status_code == 422 and "village" in r.json()["detail"]

    r = client.post("/api/heritage", json=base, headers=headers)
    assert r.status_code == 201, r.text
    created = r.json()
    entry_id = created["id"]
    try:
        assert created["status"] == "draft" and created["version"] == 1
        assert created["village_id"] == str(db.scalar(select(Village.id).where(Village.slug == "gornja-lastva")))
        assert created["source"] == base["source"]

        # Invisible to visitors until a validator approves it.
        assert client.get(f"/api/heritage/{created['slug']}").status_code == 404
        assert created["slug"] not in {e["slug"] for e in client.get("/api/heritage").json()}

        # It carries provenance from the first second of its life…
        trail = client.get(f"/api/heritage/{entry_id}/provenance", headers=headers).json()
        assert [p["action"] for p in trail] == ["created"]
        assert trail[0]["actor_role"] == "ambassador" and trail[0]["to_status"] == "draft"
        assert trail[0]["source"] == base["source"] and trail[0]["version"] == 1

        # …and it appears in the validator's queue with its territory.
        queue = client.get("/api/validation/queue", headers=login("validator")).json()
        row = next(q for q in queue if q["id"] == entry_id)
        assert row["village"] == "gornja-lastva" and row["municipality"] == "Tivat"

        # An edit bumps the version and is recorded.
        r = client.put(
            f"/api/heritage/{entry_id}",
            json={"summary_en": "Sample, corrected.", "note": "typo"},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["version"] == 2 and r.json()["status"] == "draft"
        trail = client.get(f"/api/heritage/{entry_id}/provenance", headers=headers).json()
        assert [p["action"] for p in trail] == ["created", "edited"]
    finally:
        db.rollback()
        db.execute(text("DELETE FROM provenance WHERE item_id = :i"), {"i": entry_id})
        db.execute(text("DELETE FROM heritage_entries WHERE id = :i"), {"i": entry_id})
        db.commit()


# --- 5. CHECK constraints -----------------------------------------------------------------------
def _insert_entry(db, **overrides) -> None:
    village_id = db.scalar(select(Village.id).where(Village.slug == "gornja-lastva"))
    fields = dict(
        slug=f"ck-test-{uuid.uuid4().hex[:8]}",
        village_id=village_id,
        kind="place",
        title_local="CHECK constraint test",
        title_en="CHECK constraint test",
        source="test",
        status="draft",
        version=1,
    )
    fields.update(overrides)
    try:
        with pytest.raises(IntegrityError):
            db.add(HeritageEntry(**fields))
            db.flush()
    finally:
        db.rollback()


def test_database_refuses_an_invented_status(db):
    _insert_entry(db, status="published")


def test_database_refuses_a_version_below_one(db):
    _insert_entry(db, version=0)


def test_database_refuses_impossible_coordinates(db):
    _insert_entry(db, lat=95.0, lng=18.7)


def test_no_content_row_carries_an_invalid_status(db):
    """Belt and braces: the whole seed satisfies the state machine's vocabulary."""
    for model in (HeritageEntry, Listing, TrailSegment, TrailReport):
        statuses = set(db.scalars(select(model.status)).all())
        assert statuses <= {"draft", "reviewed", "approved", "rejected"}, model.__tablename__


# --- 6. a listing needs consent before it can be published --------------------------------------
@pytest.fixture()
def listing_without_consent(db):
    """A fresh draft listing of the sample host, deliberately without a consent record."""
    host = db.scalars(select(User).where(User.email == "host1@example.org")).one()
    village_id = db.scalar(select(Village.id).where(Village.slug == "gornja-lastva"))
    listing = Listing(
        slug=f"gate-test-{uuid.uuid4().hex[:8]}",
        host_user_id=host.id,
        village_id=village_id,
        category="food",
        title_local="UZORAK: kapija validacije",
        title_en="SAMPLE: validation gate",
        description_local="Uzorak za test kapije.",
        description_en="Sample for the gate test.",
        status="draft",
        version=1,
        is_sample=True,
    )
    db.add(listing)
    db.commit()
    yield listing
    db.rollback()
    db.execute(text("DELETE FROM provenance WHERE item_id = :i"), {"i": str(listing.id)})
    consent_id = db.scalar(select(Listing.consent_record_id).where(Listing.id == listing.id))
    db.execute(text("DELETE FROM listings WHERE id = :i"), {"i": str(listing.id)})
    if consent_id:
        db.execute(text("DELETE FROM consent_records WHERE id = :i"), {"i": str(consent_id)})
    db.commit()


def test_listing_gate_consent_then_publish_then_edit(client, db, login, listing_without_consent):
    listing = listing_without_consent
    path = f"/api/validation/items/listing/{listing.id}/transition"

    # 1. no consent record → the validator cannot approve it
    r = client.post(path, json={"to_status": "approved"}, headers=login("validator"))
    assert r.status_code == 409, r.text
    assert "consent" in r.json()["detail"].lower()
    db.expire_all()
    assert db.get(Listing, listing.id).status == "draft"

    # 2. the host gives consent → approval publishes it
    consent = ConsentRecord(
        host_user_id=listing.host_user_id, consent_text_version="v1", consent_given=True,
        method="checkbox", listing_id=listing.id,
    )
    db.add(consent)
    db.flush()
    db.get(Listing, listing.id).consent_record_id = consent.id
    db.commit()

    r = client.post(path, json={"to_status": "approved"}, headers=login("validator"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "approved" and body["published_at"]
    assert listing.slug in {l["slug"] for l in client.get("/api/listings").json()}
    assert client.get(f"/api/listings/{listing.slug}").status_code == 200

    # 3. an edit returns it to draft — it leaves the public site until it is validated again
    r = client.put(
        f"/api/listings/{listing.id}",
        json={"capacity": 8, "note": "host corrected the capacity"},
        headers=login("host"),
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "draft" and r.json()["version"] == 2
    assert r.json()["capacity"] == 8
    assert listing.slug not in {l["slug"] for l in client.get("/api/listings").json()}
    assert client.get(f"/api/listings/{listing.slug}").status_code == 404

    trail = client.get(f"/api/listings/{listing.id}/provenance", headers=login("validator")).json()
    assert [p["action"] for p in trail][-2:] == ["approved", "edited"]
    assert trail[-1]["to_status"] == "draft"


# --- 7. unverified facts are never published ----------------------------------------------------
def test_unverified_facts_cannot_be_approved(client, db, login):
    entry = _entry(db, "gornji-stoliv")
    assert entry.facts_verified is False and entry.status == "draft"

    r = client.post(
        f"/api/validation/items/heritage_entry/{entry.id}/transition",
        json={"to_status": "approved"},
        headers=login("validator"),
    )
    assert r.status_code == 409, r.text
    assert "verif" in r.json()["detail"].lower()

    db.expire_all()
    assert _entry(db, "gornji-stoliv").status == "draft"
    assert "gornji-stoliv" not in {e["slug"] for e in client.get("/api/heritage").json()}
    assert client.get("/api/heritage/gornji-stoliv").status_code == 404
    # It is in the validator's queue instead, flagged for verification.
    queue = client.get("/api/validation/queue", headers=login("validator")).json()
    row = next(q for q in queue if q["id"] == str(entry.id))
    assert row["facts_verified"] is False
    assert row["village"] == "gornji-stoliv" and row["municipality"] == "Kotor"
    assert row["status"] == "draft" and row["source"]


def test_the_queue_carries_the_territory_of_every_waiting_item(client, login):
    queue = client.get("/api/validation/queue", headers=login("validator")).json()
    assert queue, "the seed leaves sample items in the queue"
    for row in queue:
        assert row["item_type"] in ("heritage_entry", "listing", "trail_segment", "trail_report")
        assert row["status"] in ("draft", "reviewed")
        assert row["municipality"] in ("Tivat", "Kotor")
        assert row["village"] and row["title"]
        assert isinstance(row["facts_verified"], bool)
    filtered = client.get(
        "/api/validation/queue", params={"village": "gornji-stoliv"}, headers=login("validator")
    ).json()
    assert filtered and {r["village"] for r in filtered} == {"gornji-stoliv"}


# --- 8. every approved item was approved by a validator, on the record ---------------------------
def test_every_approved_item_has_an_approval_provenance_record(db):
    types = {
        "heritage_entry": HeritageEntry,
        "listing": Listing,
        "trail_segment": TrailSegment,
        "trail_report": TrailReport,
    }
    checked = 0
    for item_type, model in types.items():
        for item in db.scalars(select(model).where(model.status == "approved")):
            records = db.scalars(
                select(Provenance).where(
                    Provenance.item_type == item_type,
                    Provenance.item_id == item.id,
                    Provenance.action == "approved",
                )
            ).all()
            assert records, f"{item_type} {item.id} is approved without a provenance record"
            assert any(r.actor_role == "validator" for r in records), f"{item_type} {item.id}"
            assert all(r.to_status == "approved" and r.version >= 1 for r in records)
            assert item.approved_by is not None and item.approved_at is not None
            checked += 1
    assert checked >= 15, "the seed publishes approved sample content of every type"
