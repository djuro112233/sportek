"""Claim #5 — the **multi-village** itinerary.

The definition of done requires an itinerary that spans villages: the plan walks from the shore in
Donja Lastva up to Gornja Lastva and the ridge, every stop names its village and municipality, and
the emitted ``itinerary_generated`` event carries ``multi_village`` (KPI K15 reads that property).
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Event
from app.pseudonym import SESSION as SESSION_KIND, pseudonymise
from app.services import geo

SESSION = "test-session-itinerary-000001"
DEVICE = "test-device-itinerary-000001"


def _plan(client, **body) -> dict:
    payload = {"hours": 3, "lang": "en", "session_id": SESSION, "device_id": DEVICE}
    payload.update(body)
    r = client.post("/api/itinerary", json=payload)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def default_plan(client) -> dict:
    return _plan(client)


def test_three_hours_from_donja_lastva_gives_a_walkable_plan(default_plan):
    plan = default_plan
    assert len(plan["stops"]) >= 2
    assert plan["est_hours"] <= plan["hours"] == 3.0
    assert plan["total_km"] > 0
    assert plan["route"]["type"] == "LineString"
    assert len(plan["route"]["coordinates"]) == len(plan["stops"]) + 1, "start + one point per stop"
    assert plan["route"]["coordinates"][0] == [geo.DEFAULT_START[1], geo.DEFAULT_START[0]]
    assert plan["start"] == {"lat": 42.44, "lng": 18.685}

    orders = [s["order"] for s in plan["stops"]]
    assert orders == list(range(1, len(orders) + 1))
    for stop in plan["stops"]:
        assert stop["item_type"] in ("heritage_entry", "listing")
        assert stop["directions_url"] == (
            f"https://www.google.com/maps/dir/?api=1&destination={stop['lat']},{stop['lng']}&travelmode=walking"
        )
        assert stop["minutes_from_previous"] >= 0
        assert stop["why"] and stop["title"] and stop["slug"]
        assert isinstance(stop["coords_approximate"], bool)
    ids = [s["id"] for s in plan["stops"]]
    assert len(ids) == len(set(ids)), "no stop twice"


def test_the_default_itinerary_spans_at_least_two_villages(default_plan):
    plan = default_plan
    assert plan["multi_village"] is True
    assert len(plan["villages"]) >= 2, plan["villages"]
    assert "donja-lastva" in plan["villages"] and "gornja-lastva" in plan["villages"]
    assert plan["municipalities"] == ["Tivat"]
    for stop in plan["stops"]:
        assert stop["village_slug"], stop
        assert stop["village_name"]
        assert stop["municipality"] in ("Tivat", "Kotor")
    assert {s["village_slug"] for s in plan["stops"]} == set(plan["villages"])


def test_the_plan_is_deterministic(client, default_plan):
    again = _plan(client)
    assert [s["slug"] for s in again["stops"]] == [s["slug"] for s in default_plan["stops"]]
    assert again["total_km"] == default_plan["total_km"]


def test_event_carries_n_stops_and_multi_village(db, default_plan):
    # the seed carries a synthetic event history for the KPI demo, so select this session's own event
    events = db.scalars(
        select(Event)
        .where(
            Event.event_type == "itinerary_generated",
            Event.session_pseudonym == pseudonymise(SESSION_KIND, SESSION),
        )
        .order_by(Event.occurred_at)
    ).all()
    assert events, "an itinerary must emit itinerary_generated"
    ev = events[0]
    assert ev.properties["n_stops"] == len(default_plan["stops"])
    assert ev.properties["multi_village"] is True
    assert ev.properties["hours"] == 3.0
    assert ev.properties["total_km"] == default_plan["total_km"]
    assert ev.properties["interests"] == []
    assert ev.village_id is not None and ev.municipality == "Tivat"
    assert ev.session_pseudonym and SESSION not in str(ev.session_pseudonym)
    assert "session_id" not in ev.properties and "device_id" not in ev.properties


def test_interests_narrow_the_result(client, default_plan):
    churches = _plan(client, interests=["church"])
    assert 0 < len(churches["stops"]) < len(default_plan["stops"])
    assert {s["kind"] for s in churches["stops"]} == {"church"}
    assert {s["slug"] for s in churches["stops"]} <= {"crkva-sv-marije", "crkva-sv-vida"}
    assert churches["n_candidates"] == len(churches["stops"])
    # the two churches sit in two different villages — still multi-village
    assert churches["multi_village"] is True

    food = _plan(client, interests=["food", "craft"])
    assert {s["item_type"] for s in food["stops"]} == {"listing"}
    assert client.post("/api/itinerary", json={"interests": ["dragons"], "hours": 3}).status_code == 422


def test_village_filter_returns_stops_from_that_village_only(client):
    plan = _plan(client, villages=["gornja-lastva"])
    assert plan["stops"], "Gornja Lastva has approved content"
    assert {s["village_slug"] for s in plan["stops"]} == {"gornja-lastva"}
    assert plan["villages"] == ["gornja-lastva"]
    assert plan["multi_village"] is False
    assert plan["municipalities"] == ["Tivat"]

    two = _plan(client, villages=["gornja-lastva", "donja-lastva"])
    assert {s["village_slug"] for s in two["stops"]} == {"gornja-lastva", "donja-lastva"}
    assert two["multi_village"] is True

    # Kotor has no approved content yet (Gornji Stoliv is unverified and stays a draft).
    empty = _plan(client, municipality="Kotor")
    assert empty["stops"] == [] and empty["villages"] == [] and empty["multi_village"] is False
    assert empty["route"]["coordinates"] == [[geo.DEFAULT_START[1], geo.DEFAULT_START[0]]]


def test_input_validation(client):
    assert client.post("/api/itinerary", json={"hours": 0}).status_code == 422
    assert client.post("/api/itinerary", json={"hours": 13}).status_code == 422
    assert client.post("/api/itinerary", json={"hours": 3, "lang": "de"}).status_code == 422
    assert client.post("/api/itinerary", json={"hours": 3, "municipality": "Budva"}).status_code == 422
    assert client.post("/api/itinerary", json={"hours": 3, "villages": ["atlantis"]}).status_code == 404
    assert client.post(
        "/api/itinerary", json={"hours": 3, "start": {"lat": 95, "lng": 18.6}}
    ).status_code == 422


def test_a_short_walk_from_the_ridge_starts_at_the_nearest_stop(client):
    plan = _plan(client, hours=1, start={"lat": 42.4468, "lng": 18.6985})
    assert plan["stops"], "one hour is enough for the church on the ridge"
    assert plan["stops"][0]["slug"] == "crkva-sv-vida"
    assert plan["stops"][0]["village_slug"] == "sveti-vid"
    assert plan["est_hours"] <= 1.0


def test_the_interest_vocabulary_is_published(client):
    r = client.get("/api/itinerary/interests")
    assert r.status_code == 200
    body = r.json()
    values = {i["value"] for i in body["interests"]}
    assert {"church", "food", "landscape", "guiding"} <= values
    assert body["max_hours"] == 12
    assert body["default_start"]["village_slug"] == "donja-lastva"
