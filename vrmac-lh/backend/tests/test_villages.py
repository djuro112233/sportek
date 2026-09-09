"""The territory model: villages, municipalities and where the approved content actually is.

The prototype covers the rural plateau of Vrmac on **both sides of the ridge**, so these tests check
that the API can answer "which villages are there, in which municipality, and what is published in
them" — and that every approved item really does belong to a village with a municipality.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.models import HeritageEntry, Listing, TrailSegment, Village

SEEDED_SLUGS = {
    "gornja-lastva", "donja-lastva", "sveti-vid", "tivat", "gornji-stoliv", "pasiglav",
}
#: Villages whose public sources could not be checked in the build environment.
UNVERIFIED_SLUGS = {"gornji-stoliv", "pasiglav"}


@pytest.fixture(scope="module")
def villages_client(client):
    """The API client, with the villages router registered.

    ``app/main.py`` includes the router itself; the fallback keeps this file runnable while the
    routers are wired up in parallel, and does nothing once the include is in place.
    """
    if client.get("/api/villages").status_code == 404:  # pragma: no cover - wiring fallback
        from app.main import app
        from app.routers import villages as villages_router

        app.include_router(villages_router.router)
    return client


def _villages(client, **params) -> list[dict]:
    r = client.get("/api/villages", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_six_seeded_villages_with_their_municipality(villages_client):
    body = _villages(villages_client)
    assert {v["slug"] for v in body} == SEEDED_SLUGS
    assert len(body) == 6
    for v in body:
        assert v["municipality"] in ("Tivat", "Kotor")
        assert v["name_local"] and v["name_en"]
        assert v["ridge_side"] in ("tivat", "kotor", "ridge")
        assert v["coords_approximate"] is True  # sample coordinates are approximate on purpose
        assert set(v) >= {"facts_verified", "verification_note", "n_approved_items", "counts"}


def test_municipality_filter_returns_the_kotor_side(villages_client):
    kotor = _villages(villages_client, municipality="Kotor")
    assert [v["slug"] for v in kotor] == ["gornji-stoliv"]
    assert kotor[0]["municipality"] == "Kotor"

    tivat = _villages(villages_client, municipality="Tivat")
    assert {v["slug"] for v in tivat} == SEEDED_SLUGS - {"gornji-stoliv"}
    assert len(tivat) == 5

    # A typo is reported rather than silently answered with an empty list.
    assert villages_client.get("/api/villages", params={"municipality": "Budva"}).status_code == 422


def test_unverified_villages_are_flagged_not_hidden(villages_client):
    by_slug = {v["slug"]: v for v in _villages(villages_client)}
    for slug in UNVERIFIED_SLUGS:
        village = by_slug[slug]
        assert village["facts_verified"] is False
        assert village["verification_note"], "an unverified village must say what has to be checked"
        assert "UNVERIFIED" in village["source"].upper()
        # Nothing is published about a village whose facts could not be checked.
        assert village["n_approved_items"] == 0
    for slug in SEEDED_SLUGS - UNVERIFIED_SLUGS:
        assert by_slug[slug]["facts_verified"] is True


def test_village_detail_by_slug_and_by_id(villages_client):
    r = villages_client.get("/api/villages/gornja-lastva")
    assert r.status_code == 200, r.text
    village = r.json()
    assert village["municipality"] == "Tivat" and village["name_en"] == "Gornja Lastva"

    same = villages_client.get(f"/api/villages/{village['id']}")
    assert same.status_code == 200 and same.json() == village

    assert villages_client.get("/api/villages/no-such-village").status_code == 404


def test_approved_counts_match_the_database(villages_client, db):
    """``n_approved_items`` = approved heritage entries + listings + trail segments of the village."""
    for village in _villages(villages_client):
        village_id = uuid.UUID(village["id"])
        expected = {}
        for model, key in (
            (HeritageEntry, "heritage_entries"),
            (Listing, "listings"),
            (TrailSegment, "trail_segments"),
        ):
            expected[key] = db.scalar(
                select(func.count())
                .select_from(model)
                .where(model.village_id == village_id, model.status == "approved")
            )
        assert village["counts"] == expected, village["slug"]
        assert village["n_approved_items"] == sum(expected.values())


def test_multi_village_itineraries_are_possible_on_the_tivat_side(villages_client):
    """At least three Tivat-side villages hold approved content, so an itinerary can span villages."""
    tivat = [v for v in _villages(villages_client, municipality="Tivat") if v["n_approved_items"] > 0]
    assert len(tivat) >= 3, [v["slug"] for v in tivat]


def test_every_approved_item_has_a_village_and_a_resolvable_municipality(villages_client):
    villages = {v["id"]: v for v in _villages(villages_client)}
    for path in ("/api/heritage", "/api/listings"):
        r = villages_client.get(path)
        assert r.status_code == 200, r.text
        items = r.json()
        assert items, f"{path} must return approved sample content"
        for item in items:
            assert item["village_id"], f"{path}: {item['slug']} has no village"
            village = villages.get(item["village_id"])
            assert village is not None, f"{path}: {item['slug']} points at an unknown village"
            assert village["municipality"] in ("Tivat", "Kotor")


def test_content_filters_by_village_and_municipality(villages_client):
    entries = villages_client.get("/api/heritage", params={"village": "gornja-lastva"}).json()
    assert entries and {e["slug"] for e in entries} <= {
        e["slug"] for e in villages_client.get("/api/heritage").json()
    }
    village_id = {v["slug"]: v["id"] for v in _villages(villages_client)}["gornja-lastva"]
    assert all(e["village_id"] == village_id for e in entries)

    # Nothing is published on the Kotor side yet — the one Kotor entry is an unverified draft.
    assert villages_client.get("/api/heritage", params={"municipality": "Kotor"}).json() == []
    assert villages_client.get("/api/listings", params={"municipality": "Kotor"}).json() == []

    tivat_entries = villages_client.get("/api/heritage", params={"municipality": "Tivat"}).json()
    assert len(tivat_entries) == len(villages_client.get("/api/heritage").json())


def test_villages_are_reference_data_the_visitor_role_may_read(public_db):
    """Villages carry no claim of their own, so the visitor DB role reads them in full."""
    slugs = set(public_db.scalars(select(Village.slug)))
    assert slugs == SEEDED_SLUGS
