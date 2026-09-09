"""KPI computation from the event stream (innovation claim 4: *events → KPIs*).

Every KPI is derived from the ``events`` table for one period ``[period_start, period_end]``.
Nothing in this module carries a literal KPI value: change the events and the table changes.

* **Person-level KPIs** (hosts, listings, onboarding timings) are published for the dimensions
  ``total``, ``sex=F``, ``sex=M``, ``sex=X``. A cell is published only when at least
  ``settings.kpi_k_min`` distinct persons stand behind it (*primary suppression*, note ``k<{k}``).
  When exactly one sex cell of a KPI is suppressed while the total is published, the smallest
  remaining sex cell is suppressed as well so the hidden value cannot be recovered by subtraction
  (*secondary suppression*, note ``secondary``).
* **Non-person KPIs** (visitor activity, answers, requests…) carry the ``total`` dimension only and
  ``n_persons = None``.
* **Heat map**: ``visit_recorded`` and ``trail_report`` events with coordinates are aggregated on a
  0.001° grid (≈ 100 m); only cells with at least ``k_min`` distinct sessions are stored.

Each computation is a *run* (``run_id``) of ``kpi_aggregates`` + ``kpi_heat_cells`` rows. Old runs
are kept (an audit trail of what was published when). The dashboard reads those two tables only —
never raw events, session ids or user ids.
"""
from __future__ import annotations

import math
import statistics
import uuid
from collections import defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Event, HeatCell, KpiAggregate, Listing, User, utcnow

# --- dimensions & constants --------------------------------------------------------------------

TOTAL = "total"
SEX_DIMENSIONS: tuple[str, ...] = ("sex=F", "sex=M", "sex=X")
DIMENSIONS: tuple[str, ...] = (TOTAL, *SEX_DIMENSIONS)

#: events that identify an anonymous visitor session
VISITOR_EVENT_TYPES: tuple[str, ...] = (
    "answer_served", "answer_withheld", "itinerary_generated", "request_sent", "trail_report", "visit_recorded",
)
#: events that feed the heat map (they carry lat/lng)
HEAT_EVENT_TYPES: tuple[str, ...] = ("visit_recorded", "trail_report")
#: grid cell size in degrees (≈ 111 m north–south, ≈ 82 m east–west at 42.4° N)
HEAT_CELL_SIZE_DEG = 0.001

NOTE_PRIMARY = "k<{k}"
NOTE_SECONDARY = "secondary"
NOTE_NO_EVENTS = "no events"

UNIT_COUNT = "count"
UNIT_PERSONS = "persons"
UNIT_SESSIONS = "sessions"
UNIT_MINUTES = "minutes"
UNIT_SHARE = "share"

# --- KPI catalogue ------------------------------------------------------------------------------

KPI_DEFINITIONS: list[dict[str, Any]] = [
    {
        "key": "hosts_onboarded",
        "label_en": "Hosts onboarded",
        "label_local": "Uključeni domaćini",
        "formula": "Number of distinct hosts with an onboarding_started event in the period",
        "unit": UNIT_PERSONS,
        "person_level": True,
        "event_types": ["onboarding_started"],
    },
    {
        "key": "listings_confirmed",
        "label_en": "Listings confirmed by hosts",
        "label_local": "Ponude koje su domaćini potvrdili",
        "formula": "Number of listing_confirmed events in the period",
        "unit": UNIT_COUNT,
        "person_level": True,
        "event_types": ["listing_confirmed"],
    },
    {
        "key": "listings_approved",
        "label_en": "Listings approved (validation gate)",
        "label_local": "Odobrene ponude (validaciona kapija)",
        "formula": "Number of entry_approved events with item_type = listing; sex is the sex of the listing's host",
        "unit": UNIT_COUNT,
        "person_level": True,
        "event_types": ["entry_approved"],
    },
    {
        "key": "onboarding_duration_median_min",
        "label_en": "Onboarding duration, median",
        "label_local": "Trajanje uključivanja, medijana",
        "formula": "Median of listing_confirmed.duration_seconds ÷ 60",
        "unit": UNIT_MINUTES,
        "person_level": True,
        "event_types": ["listing_confirmed"],
    },
    {
        "key": "onboarding_duration_mean_min",
        "label_en": "Onboarding duration, mean",
        "label_local": "Trajanje uključivanja, prosjek",
        "formula": "Mean of listing_confirmed.duration_seconds ÷ 60",
        "unit": UNIT_MINUTES,
        "person_level": True,
        "event_types": ["listing_confirmed"],
    },
    {
        "key": "onboarding_within_target_share",
        "label_en": "Onboardings within the target time",
        "label_local": "Uključivanja završena u ciljanom vremenu",
        "formula": "Share of listing_confirmed events with within_target = true (target = ONBOARDING_TARGET_MINUTES)",
        "unit": UNIT_SHARE,
        "person_level": True,
        "event_types": ["listing_confirmed"],
    },
    {
        "key": "entries_approved",
        "label_en": "Heritage entries approved",
        "label_local": "Odobreni zapisi baštine",
        "formula": "Number of entry_approved events with item_type = heritage_entry",
        "unit": UNIT_COUNT,
        "person_level": False,
        "event_types": ["entry_approved"],
    },
    {
        "key": "answers_served",
        "label_en": "Grounded answers served",
        "label_local": "Isporučeni odgovori sa citatima",
        "formula": "Number of answer_served events",
        "unit": UNIT_COUNT,
        "person_level": False,
        "event_types": ["answer_served"],
    },
    {
        "key": "answers_withheld",
        "label_en": "Answers withheld",
        "label_local": "Uskraćeni odgovori",
        "formula": "Number of answer_withheld events",
        "unit": UNIT_COUNT,
        "person_level": False,
        "event_types": ["answer_withheld"],
    },
    {
        "key": "answer_withhold_rate",
        "label_en": "Answer withhold rate",
        "label_local": "Stopa uskraćivanja odgovora",
        "formula": "answers_withheld ÷ (answers_served + answers_withheld)",
        "unit": UNIT_SHARE,
        "person_level": False,
        "event_types": ["answer_served", "answer_withheld"],
    },
    {
        "key": "itineraries_generated",
        "label_en": "Itineraries generated",
        "label_local": "Generisani itinereri",
        "formula": "Number of itinerary_generated events",
        "unit": UNIT_COUNT,
        "person_level": False,
        "event_types": ["itinerary_generated"],
    },
    {
        "key": "requests_sent",
        "label_en": "Visitor requests sent",
        "label_local": "Poslati upiti posjetilaca",
        "formula": "Number of request_sent events",
        "unit": UNIT_COUNT,
        "person_level": False,
        "event_types": ["request_sent"],
    },
    {
        "key": "requests_confirmed",
        "label_en": "Requests confirmed by hosts",
        "label_local": "Upiti koje su domaćini potvrdili",
        "formula": "Number of request_confirmed events",
        "unit": UNIT_COUNT,
        "person_level": False,
        "event_types": ["request_confirmed"],
    },
    {
        "key": "request_confirmation_rate",
        "label_en": "Request confirmation rate",
        "label_local": "Stopa potvrđivanja upita",
        "formula": "requests_confirmed ÷ requests_sent",
        "unit": UNIT_SHARE,
        "person_level": False,
        "event_types": ["request_sent", "request_confirmed"],
    },
    {
        "key": "trail_reports",
        "label_en": "Trail condition reports",
        "label_local": "Prijave stanja staza",
        "formula": "Number of trail_report events",
        "unit": UNIT_COUNT,
        "person_level": False,
        "event_types": ["trail_report"],
    },
    {
        "key": "visits_recorded",
        "label_en": "Visits recorded",
        "label_local": "Zabilježene posjete",
        "formula": "Number of visit_recorded events",
        "unit": UNIT_COUNT,
        "person_level": False,
        "event_types": ["visit_recorded"],
    },
    {
        "key": "visitor_sessions_active",
        "label_en": "Active visitor sessions",
        "label_local": "Aktivne sesije posjetilaca",
        "formula": "Number of distinct anonymous session ids across visitor events "
                   "(answer_served, answer_withheld, itinerary_generated, request_sent, trail_report, visit_recorded)",
        "unit": UNIT_SESSIONS,
        "person_level": False,
        "event_types": list(VISITOR_EVENT_TYPES),
    },
]

KPI_KEYS: tuple[str, ...] = tuple(d["key"] for d in KPI_DEFINITIONS)
_DEF_BY_KEY: dict[str, dict[str, Any]] = {d["key"]: d for d in KPI_DEFINITIONS}


def definition(key: str) -> dict[str, Any]:
    return _DEF_BY_KEY[key]


# --- row model ----------------------------------------------------------------------------------


@dataclass
class KpiRow:
    """One published cell. Never carries ids of persons or sessions."""

    kpi_key: str
    dimension: str
    value: float | None
    unit: str
    n_persons: int | None
    n_events: int
    suppressed: bool = False
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class _Obs:
    """A person-level observation: who (opaque key), their sex snapshot, and the event."""

    person: uuid.UUID | str | None
    sex: str | None
    event: Event


ValueFn = Callable[[list[_Obs]], float | None]


# --- helpers ------------------------------------------------------------------------------------


def _prop(e: Event, name: str, default: Any = None) -> Any:
    props = e.properties or {}
    return props.get(name, default)


def _sex_of(dimension: str) -> str:
    return dimension.split("=", 1)[1]


def _round(x: float | None, digits: int = 4) -> float | None:
    return None if x is None else round(float(x), digits)


def _count(obs: list[_Obs]) -> float | None:
    return float(len(obs))


def _distinct_persons(obs: list[_Obs]) -> float | None:
    return float(len({o.person for o in obs if o.person is not None}))


def _durations_min(obs: list[_Obs]) -> list[float]:
    out: list[float] = []
    for o in obs:
        d = _prop(o.event, "duration_seconds")
        if isinstance(d, (int, float)) and not isinstance(d, bool):
            out.append(float(d) / 60.0)
    return out


def _median_duration(obs: list[_Obs]) -> float | None:
    d = _durations_min(obs)
    return _round(statistics.median(d), 2) if d else None


def _mean_duration(obs: list[_Obs]) -> float | None:
    d = _durations_min(obs)
    return _round(statistics.fmean(d), 2) if d else None


def _within_target_share(obs: list[_Obs]) -> float | None:
    flags = [bool(_prop(o.event, "within_target", False)) for o in obs]
    return _round(sum(flags) / len(flags)) if flags else None


def _person_rows(key: str, obs: list[_Obs], value_fn: ValueFn, k: int) -> list[KpiRow]:
    """Cells for a person-level KPI with primary and secondary suppression applied."""
    unit = definition(key)["unit"]
    rows: list[KpiRow] = []
    for dim in DIMENSIONS:
        subset = obs if dim == TOTAL else [o for o in obs if o.sex == _sex_of(dim)]
        n_persons = len({o.person for o in subset if o.person is not None})
        row = KpiRow(kpi_key=key, dimension=dim, value=None, unit=unit, n_persons=n_persons, n_events=len(subset))
        if n_persons < k:
            row.suppressed = True
            row.note = NOTE_PRIMARY.format(k=k)
        else:
            row.value = value_fn(subset)
            if row.value is None:
                row.note = NOTE_NO_EVENTS
        rows.append(row)
    _secondary_suppression(rows)
    return rows


def _secondary_suppression(rows: list[KpiRow]) -> None:
    """If exactly one sex cell is suppressed and the total is published, hide the smallest remaining
    sex cell too (otherwise the hidden cell = total − published cells)."""
    by_dim = {r.dimension: r for r in rows}
    total = by_dim.get(TOTAL)
    if total is None or total.suppressed:
        return
    sex_rows = [by_dim[d] for d in SEX_DIMENSIONS if d in by_dim]
    suppressed = [r for r in sex_rows if r.suppressed]
    published = [r for r in sex_rows if not r.suppressed]
    if len(suppressed) != 1 or not published:
        return
    victim = min(published, key=lambda r: (r.n_persons or 0, r.n_events, SEX_DIMENSIONS.index(r.dimension)))
    victim.value = None
    victim.suppressed = True
    victim.note = NOTE_SECONDARY


def _total_row(key: str, value: float | None, n_events: int, *, note: str = "") -> KpiRow:
    return KpiRow(kpi_key=key, dimension=TOTAL, value=value, unit=definition(key)["unit"],
                  n_persons=None, n_events=n_events, suppressed=False, note=note)


def _count_row(key: str, events: list[Event]) -> KpiRow:
    return _total_row(key, float(len(events)), len(events))


def _rate_row(key: str, numerator: int, denominator: int, n_events: int) -> KpiRow:
    if denominator <= 0:
        return _total_row(key, None, n_events, note=NOTE_NO_EVENTS)
    return _total_row(key, _round(numerator / denominator), n_events)


def _host_sex_lookup(db: Session, listing_ids: set[uuid.UUID]) -> dict[uuid.UUID, tuple[uuid.UUID, str | None]]:
    """listing id → (host user id, host sex) for ``listings_approved``."""
    if not listing_ids:
        return {}
    stmt = (
        select(Listing.id, Listing.host_user_id, User.sex)
        .join(User, User.id == Listing.host_user_id)
        .where(Listing.id.in_(listing_ids))
    )
    return {lid: (hid, sex) for lid, hid, sex in db.execute(stmt)}


# --- heat map -----------------------------------------------------------------------------------


def cell_index(lat: float, lng: float, size: float = HEAT_CELL_SIZE_DEG) -> tuple[int, int]:
    """Grid indices of the cell containing (lat, lng)."""
    return math.floor(lat / size + 1e-9), math.floor(lng / size + 1e-9)


def cell_centre(index: tuple[int, int], size: float = HEAT_CELL_SIZE_DEG) -> tuple[float, float]:
    """(lat, lng) of the centre of a grid cell."""
    i, j = index
    return round(i * size + size / 2, 7), round(j * size + size / 2, 7)


def _heat_identity(e: Event) -> str | None:
    """Opaque per-visitor key used only to count distinct sessions; never stored."""
    if e.session_id:
        return f"s:{e.session_id}"
    if e.actor_user_id:
        return f"u:{e.actor_user_id}"
    return None


def aggregate_heat_cells(events: list[Event], k: int, size: float = HEAT_CELL_SIZE_DEG) -> list[dict[str, Any]]:
    """Grid aggregation of geotagged visitor events; only cells with ≥ k distinct sessions survive."""
    cells: dict[tuple[int, int], dict[str, Any]] = {}
    for e in events:
        if e.event_type not in HEAT_EVENT_TYPES or e.lat is None or e.lng is None:
            continue
        ident = _heat_identity(e)
        if ident is None:
            continue
        cell = cells.setdefault(cell_index(e.lat, e.lng, size), {"n_visits": 0, "idents": set()})
        cell["n_visits"] += 1
        cell["idents"].add(ident)
    out: list[dict[str, Any]] = []
    for idx in sorted(cells):
        n_sessions = len(cells[idx]["idents"])
        if n_sessions < k:
            continue
        lat, lng = cell_centre(idx, size)
        out.append({
            "cell_lat": lat, "cell_lng": lng, "cell_size_deg": size,
            "n_visits": cells[idx]["n_visits"], "n_sessions": n_sessions,
        })
    return out


# --- computation --------------------------------------------------------------------------------


def compute_rows(db: Session, events: list[Event], k: int) -> list[KpiRow]:
    """Pure KPI computation over a list of events (already limited to the period)."""
    by_type: dict[str, list[Event]] = defaultdict(list)
    for e in events:
        by_type[e.event_type].append(e)

    def actor_obs(evs: list[Event]) -> list[_Obs]:
        return [_Obs(person=e.actor_user_id, sex=e.actor_sex, event=e) for e in evs]

    rows: list[KpiRow] = []

    # person-level
    onboarding = actor_obs(by_type["onboarding_started"])
    rows += _person_rows("hosts_onboarded", onboarding, _distinct_persons, k)

    confirmed = actor_obs(by_type["listing_confirmed"])
    rows += _person_rows("listings_confirmed", confirmed, _count, k)

    approved_listings = [e for e in by_type["entry_approved"] if e.item_type == "listing"]
    hosts = _host_sex_lookup(db, {e.item_id for e in approved_listings if e.item_id is not None})
    approved_obs = [
        _Obs(person=hosts[e.item_id][0] if e.item_id in hosts else None,
             sex=hosts[e.item_id][1] if e.item_id in hosts else None, event=e)
        for e in approved_listings
    ]
    rows += _person_rows("listings_approved", approved_obs, _count, k)

    rows += _person_rows("onboarding_duration_median_min", confirmed, _median_duration, k)
    rows += _person_rows("onboarding_duration_mean_min", confirmed, _mean_duration, k)
    rows += _person_rows("onboarding_within_target_share", confirmed, _within_target_share, k)

    # non-person
    rows.append(_count_row("entries_approved", [e for e in by_type["entry_approved"] if e.item_type == "heritage_entry"]))
    served, withheld = by_type["answer_served"], by_type["answer_withheld"]
    rows.append(_count_row("answers_served", served))
    rows.append(_count_row("answers_withheld", withheld))
    rows.append(_rate_row("answer_withhold_rate", len(withheld), len(served) + len(withheld), len(served) + len(withheld)))
    rows.append(_count_row("itineraries_generated", by_type["itinerary_generated"]))
    sent, conf = by_type["request_sent"], by_type["request_confirmed"]
    rows.append(_count_row("requests_sent", sent))
    rows.append(_count_row("requests_confirmed", conf))
    rows.append(_rate_row("request_confirmation_rate", len(conf), len(sent), len(sent) + len(conf)))
    rows.append(_count_row("trail_reports", by_type["trail_report"]))
    rows.append(_count_row("visits_recorded", by_type["visit_recorded"]))
    visitor_events = [e for t in VISITOR_EVENT_TYPES for e in by_type[t] if e.session_id]
    rows.append(_total_row("visitor_sessions_active", float(len({e.session_id for e in visitor_events})), len(visitor_events)))

    assert [r.kpi_key for r in rows if r.dimension == TOTAL] == list(KPI_KEYS), "KPI catalogue and computation differ"
    return rows


def _as_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def compute_kpis(db: Session, period_days: int = 365, now: datetime | None = None) -> dict[str, Any]:
    """Compute one KPI run from the events in ``[now − period_days, now]`` and persist it.

    Deletes nothing: every run is appended (``run_id``). Returns a summary that contains the
    published rows only (no ids of persons or sessions).
    """
    if period_days < 1:
        raise ValueError("period_days must be >= 1")
    period_end = _as_utc(now) if now is not None else utcnow()
    period_start = period_end - timedelta(days=period_days)
    k = settings.kpi_k_min

    events = list(
        db.scalars(
            select(Event)
            .where(Event.occurred_at >= period_start, Event.occurred_at <= period_end)
            .order_by(Event.occurred_at, Event.id)
        )
    )
    rows = compute_rows(db, events, k)
    cells = aggregate_heat_cells(events, k)

    run_id = uuid.uuid4()
    computed_at = utcnow()
    for r in rows:
        db.add(KpiAggregate(run_id=run_id, computed_at=computed_at, period_start=period_start,
                            period_end=period_end, **r.as_dict()))
    for c in cells:
        db.add(HeatCell(run_id=run_id, computed_at=computed_at, **c))
    db.commit()

    return {
        "run_id": run_id,
        "computed_at": computed_at,
        "period_start": period_start,
        "period_end": period_end,
        "k_min": k,
        "n_events": len(events),
        "rows": [r.as_dict() for r in rows],
        "heat_cells": len(cells),
    }


# --- reading the latest run ---------------------------------------------------------------------


@dataclass(frozen=True)
class RunInfo:
    run_id: uuid.UUID
    computed_at: datetime
    period_start: datetime
    period_end: datetime


def latest_run(db: Session) -> RunInfo | None:
    """The most recent run, or None when nothing has been computed yet."""
    row = db.execute(
        select(KpiAggregate.run_id, KpiAggregate.computed_at, KpiAggregate.period_start, KpiAggregate.period_end)
        .order_by(KpiAggregate.computed_at.desc())
        .limit(1)
    ).first()
    return RunInfo(*row) if row else None


def run_rows(db: Session, run_id: uuid.UUID) -> list[KpiRow]:
    """Published rows of a run, in catalogue order."""
    order = {key: i for i, key in enumerate(KPI_KEYS)}
    dim_order = {d: i for i, d in enumerate(DIMENSIONS)}
    aggs = list(db.scalars(select(KpiAggregate).where(KpiAggregate.run_id == run_id)))
    aggs.sort(key=lambda a: (order.get(a.kpi_key, len(order)), dim_order.get(a.dimension, len(dim_order))))
    return [
        KpiRow(kpi_key=a.kpi_key, dimension=a.dimension, value=a.value, unit=a.unit, n_persons=a.n_persons,
               n_events=a.n_events, suppressed=a.suppressed, note=a.note)
        for a in aggs
    ]


def run_heat_cells(db: Session, run_id: uuid.UUID) -> list[HeatCell]:
    return list(db.scalars(select(HeatCell).where(HeatCell.run_id == run_id).order_by(HeatCell.cell_lat, HeatCell.cell_lng)))


def heat_cell_polygon(lat: float, lng: float, size: float) -> dict[str, Any]:
    """GeoJSON Polygon (lng, lat order) of a square cell centred on (lat, lng)."""
    h = size / 2
    ring = [[lng - h, lat - h], [lng + h, lat - h], [lng + h, lat + h], [lng - h, lat + h], [lng - h, lat - h]]
    return {"type": "Polygon", "coordinates": [[[round(x, 7), round(y, 7)] for x, y in ring]]}
