"""Disclosure control: the review step that stands between a computed run and the dashboard.

Two levels:

* unit — the three rules on constructed cells (no database, no KPI file);
* end to end — the same three rules proven on a **constructed set of events** run through the real
  engine with its own definition file, so what is asserted is what ``compute_kpis`` would publish.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.config import settings
from app.events import emit_event
from app.models import KpiRun
from app.services import disclosure
from app.services.disclosure import Cell
from app.services.kpi import compute_kpis, load_definitions, rows_for_run

K = settings.kpi_k_min
TAG = "disclosure-test"


# =================================================================================================
# the rules on constructed cells
# =================================================================================================


def _cell(key: str, dimension: str, kind: str, value: float, n_persons: int | None) -> Cell:
    return Cell(
        kpi_key=key, kpi_label=key, dimension=dimension, dimension_kind=kind,
        value=value, unit="count", n_persons=n_persons, n_events=int(value),
    )


def test_primary_suppression_hides_cells_below_k():
    cells = [
        _cell("T01", "total", disclosure.KIND_TOTAL, 30, 30),
        _cell("T01", "female", disclosure.KIND_GENDER, 12, 12),
        _cell("T01", "male", disclosure.KIND_GENDER, 14, 14),
        _cell("T01", "other", disclosure.KIND_GENDER, K - 1, K - 1),
        _cell("T01", "gornja-lastva", disclosure.KIND_VILLAGE, 2, 2),
        # not backed by individuals (a validator's decision): the k-rule does not apply
        _cell("T02", "total", disclosure.KIND_TOTAL, 3, None),
    ]
    hit = disclosure.apply_primary(cells, K)

    assert {(c.kpi_key, c.dimension) for c in hit} == {("T01", "other"), ("T01", "gornja-lastva")}
    for c in hit:
        assert c.value is None and c.suppressed
        assert c.suppression_reason == f"k<{K}"
    assert cells[0].value == 30 and not cells[0].suppressed
    assert cells[-1].value == 3 and not cells[-1].suppressed, "a cell with no persons behind it stays"


def test_secondary_suppression_prevents_recovery_by_subtraction():
    cells = [
        _cell("T01", "total", disclosure.KIND_TOTAL, 40, 40),
        _cell("T01", "female", disclosure.KIND_GENDER, 14, 14),
        _cell("T01", "male", disclosure.KIND_GENDER, 12, 12),           # the smallest survivor
        _cell("T01", "not_reported", disclosure.KIND_GENDER, 13, 13),
        _cell("T01", "other", disclosure.KIND_GENDER, 1, 1),            # hidden by the k-rule
    ]
    disclosure.apply_primary(cells, K)
    hit = disclosure.apply_secondary(cells, K)

    assert [c.dimension for c in hit] == ["male"]
    male = next(c for c in cells if c.dimension == "male")
    assert male.value is None and male.suppression_reason == disclosure.SECONDARY
    published = [c for c in cells if c.dimension_kind == disclosure.KIND_GENDER and not c.suppressed]
    assert sum(c.value for c in published) < cells[0].value, "the total must not equal the published cells"


def test_secondary_suppression_does_not_fire_when_two_cells_are_already_hidden():
    cells = [
        _cell("T01", "total", disclosure.KIND_TOTAL, 30, 30),
        _cell("T01", "female", disclosure.KIND_GENDER, 26, 26),
        _cell("T01", "male", disclosure.KIND_GENDER, 2, 2),
        _cell("T01", "other", disclosure.KIND_GENDER, 2, 2),
    ]
    disclosure.apply_primary(cells, K)
    assert disclosure.apply_secondary(cells, K) == []
    assert next(c for c in cells if c.dimension == "female").value == 26


def test_small_cell_rule_removes_every_date_activity_gender_cell_below_k():
    cells = [
        _cell("T01", "2026-07-01|listing_confirmed|female", disclosure.KIND_ACTIVITY, K, K),
        _cell("T01", "2026-07-01|listing_confirmed|male", disclosure.KIND_ACTIVITY, K - 1, K - 1),
        _cell("T01", "2026-07-02|listing_confirmed|other", disclosure.KIND_ACTIVITY, 1, 1),
    ]
    hit = disclosure.apply_small_cell(cells, K)

    assert len(hit) == 2
    assert all(c.suppression_reason == disclosure.SMALL_CELL and c.value is None for c in hit)
    assert cells[0].value == K, "a cell that reaches k survives"


def test_review_summary_counts_every_rule_for_the_human_reviewer():
    cells = [
        _cell("T01", "total", disclosure.KIND_TOTAL, 30, 30),
        _cell("T01", "female", disclosure.KIND_GENDER, 14, 14),
        _cell("T01", "male", disclosure.KIND_GENDER, 13, 13),
        _cell("T01", "other", disclosure.KIND_GENDER, 3, 3),
        _cell("T01", "2026-07-01|listing_confirmed|other", disclosure.KIND_ACTIVITY, 1, 1),
        _cell("T02", "total", disclosure.KIND_TOTAL, 2, 2),
    ]
    summary = disclosure.apply_disclosure_control(cells, K)

    assert summary["k_min"] == K
    assert summary["n_cells"] == len(cells)
    assert summary["by_rule"] == {f"k<{K}": 2, disclosure.SECONDARY: 1, disclosure.SMALL_CELL: 1}
    assert summary["n_suppressed"] == 4 and summary["n_published"] == len(cells) - 4
    assert summary["by_dimension_kind"] == {"activity_date_gender": 1, "gender": 2, "total": 1}
    assert summary["kpis_with_suppressed_cells"] == ["T01", "T02"]
    assert summary["kpis_fully_suppressed"] == ["T02"], "every cell of T02 is hidden"


def test_unsupported_specs_are_listed_for_the_reviewer():
    cell = _cell("T09", "total", disclosure.KIND_TOTAL, 0, None)
    cell.value, cell.note = None, disclosure.UNSUPPORTED
    summary = disclosure.review_summary([cell], k_min=K)
    assert summary["kpis_unsupported_spec"] == ["T09"]


# =================================================================================================
# the same rules on a constructed set of events, through the real engine
# =================================================================================================


class Actor:
    """A pseudonymous person: ``emit_event`` only reads these four attributes."""

    def __init__(self, label: str, gender: str, self_reported: bool):
        self.id = uuid.uuid5(uuid.NAMESPACE_URL, f"disclosure-test:{label}")
        self.role = "host"
        self.gender = gender
        self.gender_self_reported = self_reported


#: one event per person: "other" is the only gender cell below k, "not_reported" the smallest above
POPULATION: list[tuple[str, bool, int]] = [
    ("female", True, K + 3),
    ("male", True, K + 2),
    ("other", True, K - 3),
    ("undisclosed", False, K + 1),
]
N_PEOPLE = sum(count for _, _, count in POPULATION)


@pytest.fixture(scope="module")
def definitions_file(tmp_path_factory):
    """A definition file of our own: the engine must execute *this*, not anything hard-coded."""
    path = tmp_path_factory.mktemp("kpi") / "disclosure_test.json"
    path.write_text(
        json.dumps(
            {
                "version": "disclosure-test-1",
                "status": "TEST FIXTURE — not SIP Draft §11",
                "kpis": [
                    {
                        "key": "T01",
                        "label_en": "Tagged trail reports",
                        "unit": "count",
                        "person_level": True,
                        "gender_disaggregated": True,
                        "provisional": True,
                        "spec": {
                            "type": "count_events",
                            "event_types": ["trail_report"],
                            "filters": {"properties.demo_tag": TAG},
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture(scope="module")
def constructed_run(database, definitions_file):
    """Emit the population's events on one day, then compute a run over them alone."""
    from app.db import SessionLocal

    day = datetime.now(timezone.utc).replace(hour=11, minute=0, second=0, microsecond=0) - timedelta(days=2)
    with SessionLocal() as db:
        n = 0
        for gender, self_reported, count in POPULATION:
            for i in range(count):
                emit_event(
                    db, "trail_report", actor=Actor(f"{gender}-{i}", gender, self_reported),
                    occurred_at=day + timedelta(minutes=n), demo_tag=TAG, condition="good",
                    report_id=str(uuid.uuid4()), synthetic=True,
                )
                n += 1
        db.commit()
        defs = load_definitions(definitions_file, refresh=True)
        result = compute_kpis(db, period_days=30, definitions=defs)
        run = db.get(KpiRun, uuid.UUID(result["run_id"]))
        rows = {(r.dimension_kind, r.dimension): r for r in rows_for_run(db, run)}
    return result, rows, day


def test_events_reach_the_gender_cells_they_belong_to(constructed_run):
    _, rows, _ = constructed_run
    total = rows[("total", "total")]

    assert total.value == N_PEOPLE and total.n_persons == N_PEOPLE
    assert rows[("gender", "female")].value == K + 3
    assert rows[("gender", "male")].value == K + 2
    # the people who did not self-report are counted, but never in a gender cell
    assert rows[("gender", "not_reported")].n_events == K + 1


def test_primary_and_secondary_suppression_on_the_constructed_events(constructed_run):
    _, rows, _ = constructed_run
    other = rows[("gender", "other")]

    assert other.value is None and other.suppression_reason == f"k<{K}"
    assert other.n_persons == K - 3, "the count is kept for the reviewer, the value is not published"

    secondary = [r for r in rows.values() if r.suppression_reason == disclosure.SECONDARY]
    assert len(secondary) == 1, "exactly one hidden gender cell must trigger the second rule"
    assert secondary[0].dimension == "not_reported" and secondary[0].value is None

    published = [r.value for (kind, _), r in rows.items() if kind == "gender" and not r.suppressed]
    assert sum(published) < rows[("total", "total")].value


def test_small_cells_are_not_even_stored(constructed_run):
    result, rows, day = constructed_run
    activity = {dim: r for (kind, dim), r in rows.items() if kind == "activity_date_gender"}
    date = day.date().isoformat()

    assert f"{date}|trail_report|female" in activity, "a cell with k persons is published"
    assert f"{date}|trail_report|other" not in activity, "a cell below k is dropped, not stored"
    assert activity and all(r.n_persons >= K for r in activity.values())
    assert result["n_small_cells_dropped"] >= 1
    assert result["disclosure"]["by_rule"][disclosure.SMALL_CELL] >= 1


def test_the_review_summary_matches_the_stored_rows(constructed_run):
    result, rows, _ = constructed_run
    summary = result["disclosure"]
    stored_suppressed = sum(1 for r in rows.values() if r.suppressed)

    assert summary["n_suppressed"] == stored_suppressed + summary["by_rule"][disclosure.SMALL_CELL]
    assert summary["by_rule"][f"k<{K}"] >= 1
    assert summary["by_rule"][disclosure.SECONDARY] == 1
    assert result["definitions_version"] == "disclosure-test-1"
    assert result["status"] == "computed", "a computed run is never published on its own"
