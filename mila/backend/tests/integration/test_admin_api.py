"""Integration tests for /api/admin/*: token gate, source review flow, gate records, referral seed."""

from __future__ import annotations

import sys
import types
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models import Chunk, GateRecord, Source, SourceVersion
from tests.conftest import make_test_settings

ADMIN = {"X-Admin-Token": "test-admin-token"}
ROUTES = [
    ("get", "/api/admin/sources"),
    ("post", "/api/admin/sources/any/review"),
    ("get", "/api/admin/gate/records"),
    ("post", "/api/admin/referral/seed"),
    ("get", "/api/metrics/internal"),
]


@pytest.fixture
def disabled_client(tmp_path):
    """An app with no admin token configured: admin routes must not exist."""
    with TestClient(create_app(make_test_settings(tmp_path, admin_token=""))) as c:
        yield c


def _seed_source(
    db, source_id: str = "who-fp-handbook", *, n_chunks: int = 3, old_version: bool = True
) -> Source:
    source = Source(
        id=source_id,
        title="Family planning handbook",
        publisher="WHO",
        year=2022,
        url="https://example.org/fp",
        licence="CC BY-NC-SA 3.0 IGO",
        lang="en",
        allowed_topics=["contraception"],
        review_status="public_unreviewed",
    )
    db.add(source)
    db.flush()
    if old_version:
        db.add(
            SourceVersion(
                source_id=source_id,
                version_hash="a" * 64,
                file_name="old.pdf",
                n_chunks=1,
                is_current=False,
                ingested_at=datetime.now(UTC) - timedelta(days=1),
            )
        )
    current = SourceVersion(
        source_id=source_id,
        version_hash="b" * 64,
        file_name="fp.pdf",
        published_on="2022-01-01",
        n_chunks=n_chunks,
        is_current=True,
    )
    db.add(current)
    db.flush()
    for i in range(n_chunks):
        db.add(
            Chunk(
                id=f"{source_id}:bbbbbbbb:{i}",
                source_id=source_id,
                version_id=current.id,
                text=f"chunk {i}",
                lang="en",
            )
        )
    db.commit()
    return source


def _parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


# --- token gate --------------------------------------------------------------------------------
@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_admin_routes_are_404_when_no_token_is_configured(disabled_client, method: str, path: str):
    assert disabled_client.request(method, path, headers=ADMIN, json={}).status_code == 404


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_admin_routes_are_403_with_wrong_token(client, method: str, path: str):
    assert client.request(method, path, headers={"X-Admin-Token": "nope"}, json={}).status_code == 403


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_admin_routes_are_403_without_token(client, method: str, path: str):
    assert client.request(method, path, json={}).status_code == 403


# --- sources -----------------------------------------------------------------------------------
def test_list_sources_empty(client):
    r = client.get("/api/admin/sources", headers=ADMIN)
    assert r.status_code == 200 and r.json() == []


def test_list_sources_with_versions_and_chunk_counts(client, db):
    _seed_source(db, "who-fp-handbook", n_chunks=3)
    _seed_source(db, "demo-note", n_chunks=0, old_version=False)
    r = client.get("/api/admin/sources", headers=ADMIN)
    assert r.status_code == 200
    rows = {row["id"]: row for row in r.json()}
    assert list(rows) == ["demo-note", "who-fp-handbook"]
    who = rows["who-fp-handbook"]
    assert who["title"] == "Family planning handbook" and who["publisher"] == "WHO" and who["year"] == 2022
    assert (
        who["review_status"] == "public_unreviewed"
        and who["reviewed_by"] == ""
        and who["reviewed_on"] is None
    )
    assert who["allowed_topics"] == ["contraception"]
    assert who["chunk_count"] == 3 and who["n_versions"] == 2
    assert who["current_version"]["version_hash"] == "b" * 64
    assert who["current_version"]["n_chunks"] == 3 and who["current_version"]["is_current"] is True
    assert who["current_version"]["published_on"] == "2022-01-01"
    demo = rows["demo-note"]
    assert demo["chunk_count"] == 0 and demo["n_versions"] == 1


def test_list_sources_without_any_version(client, db):
    db.add(Source(id="bare", title="Bare"))
    db.commit()
    row = client.get("/api/admin/sources", headers=ADMIN).json()[0]
    assert row["current_version"] is None and row["n_versions"] == 0 and row["chunk_count"] == 0


# --- review flow -------------------------------------------------------------------------------
def test_review_flow_sets_status_reviewer_and_time(client, db):
    _seed_source(db)
    before = datetime.now(UTC)
    r = client.post(
        "/api/admin/sources/who-fp-handbook/review",
        headers=ADMIN,
        json={"reviewed_by": "Dr A. Marković", "status": "reviewed", "note": "sections 1-3 checked"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["note"] == "sections 1-3 checked"
    src = body["source"]
    assert src["id"] == "who-fp-handbook"
    assert src["review_status"] == "reviewed" and src["reviewed_by"] == "Dr A. Marković"
    assert (
        before - timedelta(seconds=5)
        <= _parse_dt(src["reviewed_on"])
        <= datetime.now(UTC) + timedelta(seconds=5)
    )
    assert src["chunk_count"] == 3 and src["current_version"]["is_current"] is True

    listed = client.get("/api/admin/sources", headers=ADMIN).json()[0]
    assert listed["review_status"] == "reviewed" and listed["reviewed_by"] == "Dr A. Marković"
    db.expire_all()
    assert db.get(Source, "who-fp-handbook").review_status == "reviewed"

    r = client.post(
        "/api/admin/sources/who-fp-handbook/review",
        headers=ADMIN,
        json={"reviewed_by": "maintainer", "status": "blocked"},
    )
    assert r.status_code == 200
    assert r.json()["source"]["review_status"] == "blocked" and r.json()["note"] is None
    db.expire_all()
    assert db.get(Source, "who-fp-handbook").review_status == "blocked"


def test_review_unknown_source_is_404(client):
    r = client.post(
        "/api/admin/sources/ghost/review", headers=ADMIN, json={"reviewed_by": "x", "status": "reviewed"}
    )
    assert r.status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"reviewed_by": "x", "status": "approved"},
        {"reviewed_by": "", "status": "reviewed"},
        {"status": "reviewed"},
        {"reviewed_by": "x", "status": "reviewed", "age": 30},
        {"reviewed_by": "x", "status": "reviewed", "note": "n" * 501},
    ],
)
def test_review_rejects_invalid_bodies(client, db, body: dict):
    _seed_source(db)
    assert (
        client.post("/api/admin/sources/who-fp-handbook/review", headers=ADMIN, json=body).status_code == 422
    )
    db.expire_all()
    assert db.get(Source, "who-fp-handbook").review_status == "public_unreviewed"


# --- gate records ------------------------------------------------------------------------------
def test_gate_records_newest_first_with_limit(client, db):
    base = datetime.now(UTC) - timedelta(minutes=10)
    for i in range(6):
        db.add(
            GateRecord(
                gate_version="1.0.0",
                status="withheld" if i % 2 else "approved",
                reasons=["low_support_ratio"] if i % 2 else [],
                support_ratio=0.5,
                confidence=0.4,
                n_sentences_in=4,
                n_sentences_kept=2,
                created_at=base + timedelta(minutes=i),
            )
        )
    db.commit()
    r = client.get("/api/admin/gate/records", headers=ADMIN, params={"limit": 4})
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 4
    stamps = [_parse_dt(row["created_at"]) for row in rows]
    assert stamps == sorted(stamps, reverse=True)
    assert set(rows[0]) == {
        "id",
        "event_id",
        "gate_version",
        "status",
        "reasons",
        "support_ratio",
        "confidence",
        "n_sentences_in",
        "n_sentences_kept",
        "created_at",
    }
    assert rows[0]["status"] == "withheld" and rows[0]["reasons"] == ["low_support_ratio"]
    assert len(client.get("/api/admin/gate/records", headers=ADMIN).json()) == 6


def test_gate_records_limit_bounds(client):
    assert client.get("/api/admin/gate/records", headers=ADMIN, params={"limit": 0}).status_code == 422
    assert client.get("/api/admin/gate/records", headers=ADMIN, params={"limit": 501}).status_code == 422


# --- referral seed -----------------------------------------------------------------------------
def test_referral_seed_is_501_when_module_is_missing(client, monkeypatch):
    monkeypatch.setitem(sys.modules, "app.core.referral", None)
    r = client.post("/api/admin/referral/seed", headers=ADMIN)
    assert r.status_code == 501
    assert r.json() == {"detail": "referral module not available"}


def test_referral_seed_calls_the_referral_module(client, monkeypatch):
    calls: list[object] = []

    def seed_referral_points(db) -> int:
        calls.append(db)
        return 7

    fake = types.ModuleType("app.core.referral")
    fake.seed_referral_points = seed_referral_points  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.core.referral", fake)
    r = client.post("/api/admin/referral/seed", headers=ADMIN)
    assert r.status_code == 200
    assert r.json() == {"seeded": 7}
    assert len(calls) == 1 and hasattr(calls[0], "execute")
