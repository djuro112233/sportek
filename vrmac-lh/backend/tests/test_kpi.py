"""K01–K23 computed from the event stream only.

`tests/test_disclosure.py` proves the suppression rules on a constructed population. This file
proves the other half of innovation claim #4: the figures come from events and from the definition
*file*, nothing is hard-coded, the special K11 rule holds, gender comes only from a voluntary
self-report, and nothing reaches the dashboard before a human publishes the run.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, time as dt_time, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.config import settings
from app.events import emit_event
from app.models import Event, HeatCell, KpiAggregate, KpiRun, User, utcnow
from app.services import kpi as kpi_service


@pytest.fixture()
def validator(db) -> User:
    return db.scalars(select(User).where(User.email == "validator1@example.org")).one()


def rows_of(db, run_id) -> list[KpiAggregate]:
    return list(db.scalars(select(KpiAggregate).where(KpiAggregate.run_id == uuid.UUID(str(run_id)))))


def total_of(db, run_id, key: str) -> KpiAggregate | None:
    return next((r for r in rows_of(db, run_id) if r.kpi_key == key and r.dimension == "total"), None)


# --- the definition file is what the engine executes ---------------------------------------------
def test_every_defined_kpi_is_computed_and_marked_provisional(db):
    defs = kpi_service.load_definitions(refresh=True)
    keys = [k["key"] for k in defs.kpis]
    assert keys == [f"K{i:02d}" for i in range(1, 24)], "the brief names K01–K23"

    result = kpi_service.compute_kpis(db, period_days=365)
    assert result["definitions_version"] == defs.version
    assert result["definitions_provisional"] is True, "SIP Draft §11 was not available to this build"

    computed = {r.kpi_key for r in rows_of(db, result["run_id"])}
    assert computed == set(keys), f"missing: {sorted(set(keys) - computed)}"

    # K11's rule is given in the brief itself, so it is the one definition that is not provisional.
    k11 = next(k for k in defs.kpis if k["key"] == "K11")
    assert k11["provisional"] is False
    assert all(r.provisional_definition for r in rows_of(db, result["run_id"]) if r.kpi_key != "K11")


def test_changing_the_definition_file_changes_the_figure_without_touching_code(db, tmp_path):
    """The engine reads the file. Point it at a different one and the numbers follow."""
    path = tmp_path / "alternative.json"
    path.write_text(
        json.dumps(
            {
                "version": "alternative-test-1",
                "status": "TEST FIXTURE — not SIP Draft §11",
                "kpis": [
                    {
                        "key": "K01", "label_en": "Trail reports counted as K01", "label_local": "—",
                        "definition": "test", "unit": "count", "person_level": False,
                        "gender_disaggregated": False, "provisional": True,
                        "spec": {"type": "count_events", "event_types": ["trail_report"]},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    alternative = kpi_service.load_definitions(path, refresh=True)
    result = kpi_service.compute_kpis(db, period_days=365, definitions=alternative)
    assert result["definitions_version"] == "alternative-test-1"

    reports = db.scalar(select(func.count(Event.id)).where(Event.event_type == "trail_report"))
    assert total_of(db, result["run_id"], "K01").value == pytest.approx(float(reports))
    kpi_service.load_definitions(refresh=True)  # restore the real file for the other tests


# --- no hard-coded numbers -----------------------------------------------------------------------
def test_adding_events_moves_the_figures_by_exactly_that_many(db):
    before = kpi_service.compute_kpis(db, period_days=365)
    withheld_before = total_of(db, before["run_id"], "K12").value or 0.0
    served_before = total_of(db, before["run_id"], "K10").value or 0.0

    for i in range(3):
        emit_event(
            db, "answer_withheld", session_id=f"kpi-test-{i}", device_id=f"kpi-test-device-{i}",
            lang="cnr", confidence=0.1, reason="no_approved_source", question_len=20,
            question_sha256="0" * 16,
        )
    db.commit()

    after = kpi_service.compute_kpis(db, period_days=365)
    assert (total_of(db, after["run_id"], "K12").value or 0.0) == withheld_before + 3
    assert (total_of(db, after["run_id"], "K10").value or 0.0) == served_before, "K10 must not move"

    # K13 is a rate over the same events, so it must move with them rather than stay put.
    rate_before = total_of(db, before["run_id"], "K13").value
    rate_after = total_of(db, after["run_id"], "K13").value
    if rate_before is not None and rate_after is not None:
        assert rate_after > rate_before


def test_an_empty_period_produces_an_empty_table_not_a_remembered_one(db):
    """Compute over a window with no events: every count must be zero or absent, never yesterday's."""
    far_future = utcnow() + timedelta(days=3650)
    result = kpi_service.compute_kpis(db, period_days=1, now=far_future)
    assert result["n_events"] == 0
    for row in rows_of(db, result["run_id"]):
        assert row.value in (None, 0.0), f"{row.kpi_key}/{row.dimension} = {row.value} with no events"


# --- K11: the one rule the brief states itself ---------------------------------------------------
def test_k11_deduplicates_a_device_once_per_180_days(db):
    """A device counts once per deduplication window: twice across 200 days, once across 10."""
    dedup = settings.k11_dedup_days
    # Windows are counted from the pilot start; events before it fold into window 0, so the test
    # must live inside the pilot period.
    pilot_start = kpi_service.pilot_start()
    base = datetime.combine(pilot_start, dt_time(12, 0), tzinfo=timezone.utc) + timedelta(days=1)

    def k11_for(device: str, gaps: list[int]) -> float:
        marker = f"k11-{device}"
        for gap in gaps:
            emit_event(
                db, "visit_recorded", session_id=marker, device_id=marker,
                occurred_at=base + timedelta(days=gap), lat=42.4425, lng=18.6919,
            )
        db.commit()
        result = kpi_service.compute_kpis(db, period_days=3650, now=base + timedelta(days=400))
        return total_of(db, result["run_id"], "K11").value or 0.0

    baseline = kpi_service.compute_kpis(db, period_days=3650, now=base + timedelta(days=400))
    start = total_of(db, baseline["run_id"], "K11").value or 0.0

    near = k11_for("near", [0, 10])          # same window → one distinct device
    assert near == start + 1, "two visits ten days apart are the same person returning"

    far = k11_for("far", [0, dedup + 20])    # two windows → counted again
    assert far == near + 2, f"a device seen again after {dedup} days counts once per window"


# --- gender comes only from a voluntary self-report ----------------------------------------------
def test_gender_cells_contain_only_self_reported_people(db):
    result = kpi_service.compute_kpis(db, period_days=365)
    rows = [r for r in rows_of(db, result["run_id"]) if r.dimension_kind == "gender"]
    assert rows, "person-level KPIs must be disaggregated"

    dimensions = {r.dimension for r in rows}
    assert "not_reported" in dimensions, (
        "people who did not answer must be visible as 'not reported', not silently dropped"
    )
    assert not {d for d in dimensions if "undisclosed" in d or "prefer_not_to_say" in d}, (
        "a non-answer is never a gender category"
    )

    # Every event behind a gender cell carries the self-report flag.
    for gender in ("female", "male", "other"):
        events = db.scalars(
            select(Event).where(Event.actor_gender == gender, Event.gender_self_reported.is_(False))
        ).all()
        assert not events, f"{gender} events exist without a self-report"


def test_suppressed_cells_carry_no_value(db):
    result = kpi_service.compute_kpis(db, period_days=365)
    suppressed = [r for r in rows_of(db, result["run_id"]) if r.suppressed]
    assert suppressed, "the sample population must exercise suppression"
    for row in suppressed:
        assert row.value is None and row.suppression_reason


# --- heat map ------------------------------------------------------------------------------------
def test_heat_cells_never_fall_below_the_threshold(db):
    result = kpi_service.compute_kpis(db, period_days=365)
    cells = list(db.scalars(select(HeatCell).where(HeatCell.run_id == uuid.UUID(result["run_id"]))))
    assert cells, "the synthetic visit history must produce cells"
    for cell in cells:
        assert cell.n_devices >= settings.kpi_k_min
        assert cell.n_visits >= cell.n_devices


# --- nothing is published without a human ---------------------------------------------------------
def test_a_computed_run_is_invisible_until_the_review_publishes_it(db, client, login, validator):
    fresh = kpi_service.compute_kpis(db, period_days=365)
    assert fresh["status"] == "computed"

    headers = login("institution")
    table = client.get("/api/kpi", headers=headers).json()
    assert table["run_id"] != fresh["run_id"], "an unreviewed run must not reach the dashboard"

    published = client.post(
        f"/api/kpi/runs/{fresh['run_id']}/review",
        json={"decision": "publish", "note": "test: reviewed and published"},
        headers=login("validator"),
    )
    assert published.status_code == 200, published.text

    table = client.get("/api/kpi", headers=headers).json()
    assert table["run_id"] == fresh["run_id"]
    assert table["definitions_provisional"] is True
    assert table["rows"], "a published run must carry its rows"


def test_a_rejected_run_never_becomes_visible(db, client, login):
    run = kpi_service.compute_kpis(db, period_days=365)
    client.post(
        f"/api/kpi/runs/{run['run_id']}/review",
        json={"decision": "reject", "note": "test: too many small cells"},
        headers=login("validator"),
    )
    stored = db.get(KpiRun, uuid.UUID(run["run_id"]))
    db.refresh(stored)
    assert stored.status == "rejected"
    table = client.get("/api/kpi", headers=login("institution")).json()
    assert table["run_id"] != run["run_id"]


# --- the API surface -------------------------------------------------------------------------------
def test_roles_and_public_definitions(client, login):
    assert client.get("/api/kpi").status_code == 401
    assert client.get("/api/kpi", headers=login("host")).status_code == 403
    assert client.post("/api/kpi/compute", headers=login("host")).status_code == 403

    defs = client.get("/api/kpi/definitions")
    assert defs.status_code == 200, "the definitions are public so anyone can check them"
    body = defs.json()
    assert len(body["kpis"]) == 23
    assert "§11" in body["warning"], "the warning must name the section the definitions must come from"
    assert "PROVISIONAL" in body["status"].upper()


def test_quality_endpoint_reports_the_three_internal_metrics(client, login):
    body = client.get("/api/kpi/quality", headers=login("institution")).json()
    assert set(body) >= {"stt_wer", "cache", "budget"}
    assert body["budget"]["cap_eur"] == settings.llm_monthly_cap_eur
    if body["stt_wer"].get("available"):
        assert body["stt_wer"]["is_synthetic"] is True, "the sample set is synthetic until recorded"


def test_published_rows_carry_no_identifier(db, client, login):
    body = client.get("/api/kpi", headers=login("institution")).json()
    blob = json.dumps(body)
    for column in ("session_pseudonym", "device_pseudonym", "actor_pseudonym", "user_id", "email"):
        assert column not in blob
    for row in body["rows"]:
        assert set(row) >= {"kpi_key", "dimension", "value", "unit", "suppressed"}
        assert not any(isinstance(v, str) and "@" in v for v in row.values())


def test_events_endpoint_accepts_only_the_visitor_event(client):
    ok = client.post(
        "/api/events",
        json={"event_type": "visit_recorded", "session_id": "visitor-session-1",
              "device_id": "visitor-device-1", "lat": 42.4425, "lng": 18.6919},
    )
    assert ok.status_code == 201, ok.text

    refused = client.post(
        "/api/events",
        json={"event_type": "answer_served", "session_id": "visitor-session-1",
              "lat": 42.4425, "lng": 18.6919},
    )
    assert refused.status_code == 422, "only the client-side visit event may be posted"


def test_posted_events_are_stored_pseudonymised(db, client):
    client.post(
        "/api/events",
        json={"event_type": "visit_recorded", "session_id": "leaky-session-42",
              "device_id": "leaky-device-42", "lat": 42.4425, "lng": 18.6919},
    )
    latest = db.scalars(
        select(Event).where(Event.event_type == "visit_recorded").order_by(Event.occurred_at.desc())
    ).first()
    stored = f"{latest.session_pseudonym}{latest.device_pseudonym}{latest.properties}"
    assert "leaky-session-42" not in stored and "leaky-device-42" not in stored
