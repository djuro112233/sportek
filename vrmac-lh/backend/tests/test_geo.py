"""Claim #5 — map features, Google Maps deep links, GPX trails and geotagged condition reports.

The gate is the point of these tests: only *approved* items reach the map, a GPX download or the
condition of a trail, and a report submitted by a visitor stays invisible until a validator approves
it. Every feature must also carry its territory (village + municipality), because the prototype
covers Vrmac on both sides of the ridge and not a single village.
"""
from __future__ import annotations

import contextlib
import re
import uuid

import gpxpy
import pytest
from sqlalchemy import select

from app.models import Event, HeritageEntry, Listing, TrailReport, TrailSegment, User, Village
from app.services import geo, validation

NON_APPROVED_SLUGS = {
    "sample-draft-zlatno-zvono",
    "sample-reviewed-stara-skola",
    "sample-rejected-rimska-vila",
    "gornji-stoliv",
    "sample-draft-segment",
    "sveti-vid-gornji-stoliv",
}
APPROVED_TRAILS = {"donja-gornja-lastva", "gornja-lastva-sv-vid"}
REPORT_SESSION = "test-session-trail-report-0001"


@pytest.fixture(scope="module")
def features(client) -> dict:
    r = client.get("/api/map/features")
    assert r.status_code == 200, r.text
    return r.json()


def _props(collection: dict) -> dict[tuple[str, str], dict]:
    return {(f["properties"]["item_type"], f["properties"]["slug"]): f["properties"] for f in collection["features"]}


@contextlib.contextmanager
def temporarily_approved_segment(db, slug: str):
    """Approve a seeded **draft** segment for the duration of a test, then put it back.

    The seed publishes nothing on the Kotor side, so a Kotor filter that is never given anything to
    match cannot tell a working filter from a broken one. This approves the ridge crossing (which
    starts in Tivat and ends in Kotor) through the real validation gate, hands it to the test and
    returns it to ``draft`` afterwards, so every later test sees the seeded state again.
    """
    segment = db.scalars(select(TrailSegment).where(TrailSegment.slug == slug)).one()
    validator = db.scalars(select(User).where(User.email == "validator1@example.org")).one()
    assert segment.status == "draft", "the fixture approves a draft, not something already published"
    validation.transition(db, "trail_segment", segment.id, "approved", actor=validator,
                          note="temporary: exercising the municipality filter")
    try:
        yield segment
    finally:
        validation.transition(db, "trail_segment", segment.id, "draft", actor=validator,
                              note="temporary approval withdrawn: end of test")
        db.expire_all()


def _expected(db) -> set[tuple[str, str]]:
    entries = db.scalars(
        select(HeritageEntry.slug).where(
            HeritageEntry.status == "approved", HeritageEntry.lat.is_not(None), HeritageEntry.lng.is_not(None)
        )
    ).all()
    listings = db.scalars(
        select(Listing.slug).where(
            Listing.status == "approved", Listing.lat.is_not(None), Listing.lng.is_not(None)
        )
    ).all()
    segments = db.scalars(select(TrailSegment.slug).where(TrailSegment.status == "approved")).all()
    return (
        {("heritage_entry", s) for s in entries}
        | {("listing", s) for s in listings}
        | {("trail_segment", s) for s in segments}
    )


# --- (1) exactly the approved, coordinate-carrying items -----------------------------------------
def test_features_are_exactly_the_approved_items_with_coordinates(db, features):
    assert features["type"] == "FeatureCollection"
    keys = [(f["properties"]["item_type"], f["properties"]["slug"]) for f in features["features"]]
    assert len(keys) == len(set(keys)), "one feature per item"
    assert set(keys) == _expected(db)
    assert APPROVED_TRAILS == {slug for kind, slug in keys if kind == "trail_segment"}
    assert not {slug for _, slug in keys} & NON_APPROVED_SLUGS


def test_every_feature_carries_directions_territory_and_the_approximate_flag(features):
    for f in features["features"]:
        p = f["properties"]
        assert p["village_slug"] and p["village_name_local"] and p["village_name_en"]
        assert p["municipality"] in ("Tivat", "Kotor")
        assert isinstance(p["coords_approximate"], bool)
        assert "coords_source" in p
        if f["geometry"]["type"] == "Point":
            lng, lat = f["geometry"]["coordinates"][:2]
        else:  # a trail's links point at the start of the track
            lng, lat = f["geometry"]["coordinates"][0][:2]
        assert p["directions_walking"] == (
            f"https://www.google.com/maps/dir/?api=1&destination={lat},{lng}&travelmode=walking"
        )
        assert p["directions_driving"] == (
            f"https://www.google.com/maps/dir/?api=1&destination={lat},{lng}&travelmode=driving"
        )


def test_feature_properties_are_type_specific(features):
    props = _props(features)
    church = props[("heritage_entry", "crkva-sv-vida")]
    assert church["kind"] == "church" and church["summary_en"]
    assert church["village_slug"] == "sveti-vid" and church["municipality"] == "Tivat"
    assert church["coords_approximate"] is True
    assert church["directions_walking"] == (
        "https://www.google.com/maps/dir/?api=1&destination=42.4468,18.6985&travelmode=walking"
    )
    konoba = props[("listing", "konoba-maslina-sample")]
    assert konoba["category"] == "food" and konoba["is_sample"] is True
    assert konoba["currency"] == "EUR"
    for field in ("price_min", "price_max", "season_from", "season_to", "season_all_year", "capacity",
                  "accessibility_step_free", "accessibility_note_local", "accessibility_note_en", "photo_url"):
        assert field in konoba
    trail = props[("trail_segment", "donja-gornja-lastva")]
    assert trail["gpx_url"] == "/api/trails/donja-gornja-lastva/gpx"
    assert trail["length_m"] and trail["ascent_m"] and trail["difficulty"]
    assert trail["latest_report"]["condition"] == "caution"


# --- (2) territory filters ------------------------------------------------------------------------
def test_filter_by_village_and_municipality(client, db):
    gornja = client.get("/api/map/features", params={"village": "gornja-lastva"}).json()
    slugs = {f["properties"]["slug"] for f in gornja["features"]}
    assert {"crkva-sv-marije", "konoba-maslina-sample"} <= slugs
    assert all(
        p["village_slug"] == "gornja-lastva" or "gornja-lastva" in p.get("village_slugs", [])
        for p in (f["properties"] for f in gornja["features"])
    )
    # a trail is matched on every village it connects, not only on the one it starts in
    assert "donja-gornja-lastva" in slugs

    tivat = client.get("/api/map/features", params={"municipality": "Tivat"}).json()
    assert {f["properties"]["municipality"] for f in tivat["features"]} == {"Tivat"}

    # Nothing is published for Kotor yet: the Gornji Stoliv entry and the ridge crossing are drafts
    # because their facts could not be verified. An empty map is the correct answer.
    kotor = client.get("/api/map/features", params={"municipality": "Kotor"}).json()
    assert kotor["features"] == []
    assert kotor["bbox"] is None

    # ...but an empty answer proves nothing about the filter itself, so publish something on the
    # Kotor side for the length of this block. The ridge crossing *starts* in Sveti Vid (Tivat) and
    # ends in Gornji Stoliv (Kotor): it must appear on both sides, because the filter matches every
    # village a trail connects, not only the one it starts in.
    with temporarily_approved_segment(db, "sveti-vid-gornji-stoliv"):
        kotor_now = client.get("/api/map/features", params={"municipality": "Kotor"}).json()
        assert [f["properties"]["slug"] for f in kotor_now["features"]] == ["sveti-vid-gornji-stoliv"]
        assert kotor_now["bbox"] is not None
        crossing = kotor_now["features"][0]["properties"]
        assert crossing["village_slug"] == "sveti-vid" and crossing["municipality"] == "Tivat"
        # the property a client needs in order to filter the same way this endpoint does
        assert crossing["municipalities"] == ["Tivat", "Kotor"]
        assert "gornji-stoliv" in crossing["village_slugs"]

        tivat_now = client.get("/api/map/features", params={"municipality": "Tivat"}).json()
        assert "sveti-vid-gornji-stoliv" in {f["properties"]["slug"] for f in tivat_now["features"]}

        kotor_village = client.get("/api/map/features", params={"village": "gornji-stoliv"}).json()
        assert [f["properties"]["slug"] for f in kotor_village["features"]] == ["sveti-vid-gornji-stoliv"]

        # /api/trails answers the same question the same way
        assert [t["slug"] for t in client.get("/api/trails", params={"municipality": "Kotor"}).json()] == [
            "sveti-vid-gornji-stoliv"
        ]

    # the seeded state is back: the crossing is a draft again and Kotor is empty
    assert client.get("/api/trails/sveti-vid-gornji-stoliv").status_code == 404
    assert client.get("/api/map/features", params={"municipality": "Kotor"}).json()["features"] == []

    only_trails = client.get("/api/map/features", params={"item_type": "trail_segment"}).json()
    assert {f["properties"]["item_type"] for f in only_trails["features"]} == {"trail_segment"}
    assert client.get("/api/map/features", params={"item_type": "nonsense"}).status_code == 422
    assert client.get("/api/map/features", params={"municipality": "Podgorica"}).status_code == 422


# --- (3) trails: latest APPROVED report, villages connected ---------------------------------------
def test_trail_list_shows_only_approved_segments_and_the_latest_approved_report(client):
    trails = client.get("/api/trails").json()
    assert {t["slug"] for t in trails} == APPROVED_TRAILS
    by_slug = {t["slug"]: t for t in trails}

    lastva = by_slug["donja-gornja-lastva"]
    assert lastva["village_slugs"] == ["donja-lastva", "gornja-lastva"], "the segment connects two villages"
    assert lastva["latest_report"]["condition"] == "caution", "newest approved report, not the draft one"
    assert lastva["latest_report"]["reported_at"].startswith("2026-09-01")
    assert lastva["municipality"] == "Tivat"

    detail = client.get("/api/trails/donja-gornja-lastva").json()
    conditions = [r["condition"] for r in detail["reports"]]
    assert conditions == ["caution", "good"], "approved reports, newest first"
    assert "blocked" not in conditions, "the draft report must not be visible"
    assert detail["latest_report"]["id"] == detail["reports"][0]["id"]

    assert client.get("/api/trails/sample-draft-segment").status_code == 404
    assert client.get("/api/trails/sveti-vid-gornji-stoliv").status_code == 404


def test_every_trail_carries_usable_start_coordinates(client, features):
    """``GET /api/trails`` must carry the start point, not only the two ready-made deep links.

    The visitor app offers "how to get there" for a trail exactly as it does for a heritage entry or
    a listing, from ``lat``/``lng``; without them the button has nothing to point at.
    """
    trails = client.get("/api/trails").json()
    assert {t["slug"] for t in trails} == APPROVED_TRAILS
    for trail in trails:
        lat, lng = trail["lat"], trail["lng"]
        assert isinstance(lat, (int, float)) and not isinstance(lat, bool), f"{trail['slug']}: no start latitude"
        assert isinstance(lng, (int, float)) and not isinstance(lng, bool), f"{trail['slug']}: no start longitude"
        assert -90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0
        first = trail["geometry"]["coordinates"][0]
        assert (lat, lng) == pytest.approx((first[1], first[0])), "the start point is the first vertex of the track"
        assert trail["directions_walking"] == geo.directions_url(lat, lng, "walking")
        assert trail["directions_driving"] == geo.directions_url(lat, lng, "driving")
        assert trail["municipalities"] and trail["municipality"] in trail["municipalities"]

    detail = client.get("/api/trails/donja-gornja-lastva").json()
    assert detail["lat"] == pytest.approx(42.44, abs=0.05) and detail["lng"] == pytest.approx(18.69, abs=0.05)

    # the same point travels on the map feature
    trail_props = _props(features)[("trail_segment", "donja-gornja-lastva")]
    assert trail_props["lat"] == detail["lat"] and trail_props["lng"] == detail["lng"]
    assert trail_props["municipalities"] == ["Tivat"]


def test_trail_list_can_be_filtered_by_village(client):
    sveti_vid = client.get("/api/trails", params={"village": "sveti-vid"}).json()
    assert {t["slug"] for t in sveti_vid} == {"gornja-lastva-sv-vid"}
    assert client.get("/api/trails", params={"municipality": "Kotor"}).json() == []


# --- (4) GPX --------------------------------------------------------------------------------------
def test_gpx_endpoint_serves_the_seed_file_and_generates_one_from_geometry(client):
    r = client.get("/api/trails/donja-gornja-lastva/gpx")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/gpx+xml")
    assert r.headers["x-gpx-origin"] == "file"
    points = gpxpy.parse(r.text).tracks[0].segments[0].points
    assert len(points) >= 10
    assert all(41.0 < p.latitude < 44.0 and 18.0 < p.longitude < 20.0 for p in points)

    r2 = client.get("/api/trails/gornja-lastva-sv-vid/gpx")
    assert r2.status_code == 200
    assert r2.headers["x-gpx-origin"] == "generated"
    gpx2 = gpxpy.parse(r2.text)
    assert len(gpx2.tracks[0].segments[0].points) == 4
    assert "approximate" in (gpx2.description or "").lower()

    assert client.get("/api/trails/sample-draft-segment/gpx").status_code == 404
    assert client.get("/api/trails/sveti-vid-gornji-stoliv/gpx").status_code == 404


def test_a_gpx_file_name_with_a_path_separator_is_never_opened(db):
    seg = db.scalars(select(TrailSegment).where(TrailSegment.slug == "donja-gornja-lastva")).one()
    assert geo.safe_gpx_path(seg.gpx_file) is not None
    for evil in ("../../../../etc/passwd", "/etc/passwd", "..", "sub/dir.gpx", "nope.txt", None, ""):
        assert geo.safe_gpx_path(evil) is None


# --- (5) a visitor's condition report goes through the gate ---------------------------------------
def test_submitted_report_is_a_draft_invisible_until_a_validator_approves_it(client, db):
    before = client.get("/api/trails/donja-gornja-lastva").json()
    r = client.post(
        "/api/trails/donja-gornja-lastva/reports",
        json={
            "lat": 42.4415, "lng": 18.6893, "condition": "good",
            "note": "Prolaz očišćen, staza suva.", "lang": "cnr",
            "session_id": REPORT_SESSION, "device_id": "test-device-trail-0001",
        },
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == "draft" and body["visible_after_validation"] is True
    assert "validator" in body["message"] or "validatora" in body["message"]
    assert body["village_slug"] == "donja-lastva" and body["municipality"] == "Tivat"
    report_id = body["id"]

    report = db.get(TrailReport, uuid.UUID(report_id))
    assert report is not None and report.status == "draft"
    assert report.village_id is not None and report.reporter_role == "visitor"

    event = db.scalars(
        select(Event).where(Event.event_type == "trail_report", Event.item_id == report.id)
    ).one()
    assert event.lat == pytest.approx(42.4415) and event.lng == pytest.approx(18.6893)
    assert event.properties["condition"] == "good"
    assert event.municipality == "Tivat" and event.village_id == report.village_id
    assert event.session_pseudonym and REPORT_SESSION not in str(event.session_pseudonym)

    still = client.get("/api/trails/donja-gornja-lastva").json()
    assert report_id not in [x["id"] for x in still["reports"]]
    assert still["latest_report"]["id"] == before["latest_report"]["id"]

    validator = db.scalars(select(User).where(User.email == "validator1@example.org")).one()
    validation.transition(db, "trail_report", report.id, "approved", actor=validator, note="test approval")

    after = client.get("/api/trails/donja-gornja-lastva").json()
    assert after["latest_report"]["id"] == report_id
    assert after["latest_report"]["condition"] == "good"
    assert report_id in [x["id"] for x in after["reports"]]


def test_a_report_on_a_draft_segment_is_a_404(client):
    payload = {"lat": 42.44, "lng": 18.69, "condition": "blocked", "session_id": REPORT_SESSION}
    assert client.post("/api/trails/sample-draft-segment/reports", json=payload).status_code == 404
    assert client.post("/api/trails/sveti-vid-gornji-stoliv/reports", json=payload).status_code == 404


def test_report_input_is_validated(client):
    bad = [
        {"lat": 95.0, "lng": 18.69, "condition": "good", "session_id": REPORT_SESSION},
        {"lat": 42.44, "lng": 18.69, "condition": "impassable", "session_id": REPORT_SESSION},
        {"lat": 42.44, "lng": 18.69, "condition": "good"},  # neither a session nor an account
    ]
    for payload in bad:
        assert client.post("/api/trails/donja-gornja-lastva/reports", json=payload).status_code == 422


# --- (6) directions ---------------------------------------------------------------------------------
def test_directions_endpoint_and_its_validation(client):
    r = client.get("/api/map/directions", params={"lat": 42.4468, "lng": 18.6985, "mode": "walking"})
    assert r.status_code == 200
    assert r.json()["url"] == (
        "https://www.google.com/maps/dir/?api=1&destination=42.4468,18.6985&travelmode=walking"
    )
    driving = client.get("/api/map/directions", params={"lat": 42.44, "lng": 18.685, "mode": "driving"}).json()
    assert driving["url"].endswith("&travelmode=driving")
    assert "destination=42.44,18.685" in driving["url"]

    assert client.get("/api/map/directions", params={"lat": 95, "lng": 18.6, "mode": "walking"}).status_code == 422
    assert client.get("/api/map/directions", params={"lat": 42.4, "lng": 200, "mode": "walking"}).status_code == 422
    assert client.get("/api/map/directions", params={"lat": 42.4, "lng": 18.6, "mode": "flying"}).status_code == 422
    assert client.get("/api/map/directions", params={"lng": 18.6}).status_code == 422

    with pytest.raises(ValueError):
        geo.directions_url(42.4, 18.6, "teleport")
    with pytest.raises(ValueError):
        geo.directions_url(95.0, 18.6, "walking")


PLAIN_DECIMAL = re.compile(r"^-?\d+\.\d{1,6}$")


def test_directions_coordinates_are_always_plain_decimals(client):
    """A coordinate very close to zero must not be written as ``1e-06``: Google will not parse it.

    Null Island is off Vrmac, but the formatter is the one every deep link and every itinerary stop
    goes through, and a coordinate arrives from the query string of ``/api/map/directions`` and from
    a visitor's device — not only from the seed.
    """
    for lat, lng in [(4e-7, 9e-7), (0.0, 0.0), (-1e-9, -2.5e-8), (1e-7, -1e-7), (42.4468, 18.6985)]:
        url = geo.directions_url(lat, lng)
        destination = url.split("&destination=")[1].split("&")[0]
        assert "e" not in destination.lower(), f"scientific notation in {url}"
        for part in destination.split(","):
            assert PLAIN_DECIMAL.match(part), f"{part!r} is not a plain decimal ({url})"

    assert geo.directions_url(4e-7, 9e-7).startswith(
        "https://www.google.com/maps/dir/?api=1&destination=0.0,0.000001&"
    )
    assert geo.directions_url(-1e-9, -2.5e-8, "driving") == (
        "https://www.google.com/maps/dir/?api=1&destination=0.0,0.0&travelmode=driving"
    )
    # the ordinary case is unchanged: rounded to 6 decimals, no trailing zeros
    assert geo.format_coord(42.4468) == "42.4468" and geo.format_coord(18.685) == "18.685"
    assert geo.format_coord(42.0) == "42.0" and geo.format_coord(42.44680049) == "42.4468"

    tiny = client.get("/api/map/directions", params={"lat": 4e-7, "lng": 9e-7, "mode": "walking"}).json()
    assert tiny["url"].endswith("&destination=0.0,0.000001&travelmode=walking")


def test_haversine_matches_the_seed_loader(db):
    from app.seed.loader import haversine_m as loader_haversine

    a, b = (42.4400, 18.6850), (42.4425, 18.6919)
    assert geo.haversine_m(a, b) == pytest.approx(loader_haversine(a, b), rel=1e-9)
    assert geo.haversine_m(a, a) == 0.0
    village = db.scalars(select(Village).where(Village.slug == "gornja-lastva")).one()
    assert geo.haversine_m(a, (village.lat, village.lng)) == pytest.approx(650, abs=150)
