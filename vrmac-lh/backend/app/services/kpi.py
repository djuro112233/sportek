"""KPI engine — innovation claim 4: *every step emits a pseudonymised event; K01–K23 are computed
from that stream and published only after a disclosure review.*

**No KPI is defined in this file.** The definitions live in
``backend/kpi_definitions/sip_section_11.json`` (``settings.kpi_definitions_path``), which carries a
machine-readable ``spec`` per KPI. This module is a generic evaluator for those specs, so replacing
the file with the wording of SIP Draft §11 changes every published number without a code change.
Until that transcription happens the file is flagged ``provisional`` and every aggregate row carries
``provisional_definition = true``.

Supported ``spec.type`` values (see ``spec_reference`` in the definition file):

``count_events``, ``count_distinct_actors``, ``count_distinct_devices`` (with ``dedup_days``),
``count_distinct_villages``, ``count_distinct_property``, ``median_property``, ``mean_property``,
``share_property_true``, ``ratio_events``, ``count_items``.

An unknown ``spec.type`` never crashes a run: the row is stored with ``value = null`` and the note
``unsupported spec``, and the review summary lists the KPI.

Dimensions written per KPI:

* ``total`` — always;
* ``gender`` — ``female | male | other`` for KPIs flagged ``gender_disaggregated``, computed **only**
  from events whose actor *voluntarily self-reported* their gender, plus a ``not_reported`` cell
  carrying the same measure over the events whose actor did not, so the total reconciles;
* ``village`` — one row per village that appears in the KPI's events (dimension = village slug);
* ``activity_date_gender`` — for person-level KPIs, the ``date × activity × gender`` cells, stored
  **only** when they survive the small-cell rule (``services/disclosure.py``).

Every run is a row in ``kpi_runs`` with status ``computed`` → ``published`` | ``rejected``. The
dashboard reads ``kpi_aggregates`` and ``kpi_heat_cells`` of a **published** run only; it never sees
raw events, and no aggregate carries a session, device or user identifier.
"""
from __future__ import annotations

import json
import logging
import math
import statistics
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    Event,
    HeatCell,
    KpiAggregate,
    KpiRun,
    ResponseCache,
    SttEvaluation,
    User,
    Village,
    utcnow,
)
from . import disclosure
from .disclosure import (
    GENDER_CELLS,
    KIND_ACTIVITY,
    KIND_GENDER,
    KIND_TOTAL,
    KIND_VILLAGE,
    NOT_REPORTED,
    TOTAL,
    UNSUPPORTED,
    Cell,
)

log = logging.getLogger(__name__)

#: events that feed the heat map (they carry coordinates)
HEAT_EVENT_TYPES: tuple[str, ...] = ("visit_recorded", "trail_report")
#: grid cell size in degrees ≈ 111 m north–south, ≈ 82 m east–west at 42.4° N
HEAT_CELL_SIZE_DEG = 0.001

NOTE_NO_EVENTS = "no events"
RUN_STATUSES = ("computed", "reviewed", "published", "rejected")


# =================================================================================================
# definitions file
# =================================================================================================


@dataclass(frozen=True)
class Definitions:
    """The parsed definition file. ``provisional`` is true while it is not the §11 wording."""

    path: str
    version: str
    provisional: bool
    status: str
    warning: str
    replace_instructions: str
    spec_reference: dict[str, str]
    kpis: tuple[dict[str, Any], ...]
    raw: dict[str, Any]

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(k["key"] for k in self.kpis)

    def get(self, key: str) -> dict[str, Any] | None:
        for k in self.kpis:
            if k["key"] == key:
                return k
        return None

    def public_dict(self) -> dict[str, Any]:
        """What ``GET /api/kpi/definitions`` returns: the file plus the provisional warning."""
        doc = dict(self.raw)
        doc["provisional"] = self.provisional
        doc["definitions_version"] = self.version
        doc["source_file"] = Path(self.path).name
        return doc


_cache: dict[str, tuple[tuple[float, int], Definitions]] = {}


def definitions_path(path: str | Path | None = None) -> Path:
    return Path(path or settings.kpi_definitions_path)


def load_definitions(path: str | Path | None = None, *, refresh: bool = False) -> Definitions:
    """Read (and cache) the KPI definition file. Re-read automatically when the file changes."""
    p = definitions_path(path)
    try:
        stat = p.stat()
    except OSError as exc:  # loud: a KPI run without definitions is meaningless
        raise RuntimeError(
            f"KPI definition file not found: {p} — set KPI_DEFINITIONS_PATH or restore the file"
        ) from exc
    stamp = (stat.st_mtime, stat.st_size)
    key = str(p.resolve())
    if not refresh and key in _cache and _cache[key][0] == stamp:
        return _cache[key][1]

    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"KPI definition file {p} is not valid JSON: {exc}") from exc
    kpis = tuple(raw.get("kpis") or ())
    if not kpis:
        raise RuntimeError(f"KPI definition file {p} defines no KPIs")
    missing = [k for k in kpis if not k.get("key") or not k.get("spec")]
    if missing:
        raise RuntimeError(f"KPI definition file {p}: every KPI needs a 'key' and a 'spec'")
    status = str(raw.get("status", ""))
    provisional = bool(
        raw.get("provisional", any(bool(k.get("provisional", True)) for k in kpis))
        or status.upper().startswith("PROVISIONAL")
    )
    defs = Definitions(
        path=str(p),
        version=str(raw.get("version", "unversioned")),
        provisional=provisional,
        status=status,
        warning=str(raw.get("warning", "")),
        replace_instructions=str(raw.get("replace_instructions", "")),
        spec_reference=dict(raw.get("spec_reference") or {}),
        kpis=kpis,
        raw=raw,
    )
    _cache[key] = (stamp, defs)
    return defs


def clear_definitions_cache() -> None:
    _cache.clear()


# =================================================================================================
# spec evaluation (generic; nothing here knows what K07 means)
# =================================================================================================


def _prop(ev: Event, name: str) -> Any:
    return (ev.properties or {}).get(name)


def _matches(ev: Event, filters: dict[str, Any]) -> bool:
    for field, expected in (filters or {}).items():
        if field.startswith("properties."):
            actual = _prop(ev, field.split(".", 1)[1])
        elif field in ("event_type", "item_type", "actor_role", "municipality", "actor_gender"):
            actual = getattr(ev, field)
        else:
            actual = _prop(ev, field)
        if isinstance(expected, (list, tuple)):
            if actual not in expected:
                return False
        elif actual != expected:
            return False
    return True


def _filter(events: Sequence[Event], types: Iterable[str] | None, filters: dict | None) -> list[Event]:
    wanted = set(types or ())
    return [
        e for e in events
        if (not wanted or e.event_type in wanted) and _matches(e, filters or {})
    ]


def _select(spec: dict, scope: Sequence[Event]) -> tuple[list[Event], tuple[list[Event], list[Event]] | None]:
    """Events the spec touches (for ``n_events``/``n_persons``) and, for ratios, its two parts."""
    if spec.get("type") == "ratio_events":
        num = _filter(scope, spec.get("numerator_event_types"), spec.get("filters"))
        den = _filter(scope, spec.get("denominator_event_types"), spec.get("filters"))
        return num + den, (num, den)
    return _filter(scope, spec.get("event_types"), spec.get("filters")), None


def pilot_start() -> date:
    try:
        return date.fromisoformat(settings.pilot_start_date)
    except ValueError:
        log.warning("PILOT_START_DATE %r is not a date; falling back to 1970-01-01", settings.pilot_start_date)
        return date(1970, 1, 1)


def dedup_window(when: datetime, dedup_days: int, start: date | None = None) -> int:
    """Index of the deduplication window a timestamp falls in (K11: one 180-day window)."""
    if dedup_days <= 0:
        return 0
    anchor = start or pilot_start()
    return (when.astimezone(timezone.utc).date() - anchor).days // dedup_days


def _numeric_values(events: Sequence[Event], prop: str, scale: float) -> list[float]:
    out: list[float] = []
    for e in events:
        v = _prop(e, prop)
        if isinstance(v, bool) or v is None:
            continue
        try:
            out.append(float(v) * scale)
        except (TypeError, ValueError):
            continue
    return out


def _hashable(value: Any) -> Any:
    return json.dumps(value, sort_keys=True, default=str) if isinstance(value, (list, dict)) else value


def _op_count_events(spec, touched, parts) -> float:
    return float(len(touched))


def _op_count_distinct_actors(spec, touched, parts) -> float:
    return float(len({e.actor_pseudonym for e in touched if e.actor_pseudonym}))


def _op_count_distinct_devices(spec, touched, parts) -> float:
    """K11: distinct device pseudonyms, deduplicated once per ``dedup_days``.

    A device that comes back after the window has passed counts again; every visit inside one
    window counts once.
    """
    dedup_days = int(spec.get("dedup_days") or settings.k11_dedup_days)
    anchor = pilot_start()
    seen = {
        (e.device_pseudonym, dedup_window(e.occurred_at, dedup_days, anchor))
        for e in touched
        if e.device_pseudonym
    }
    return float(len(seen))


def _op_count_distinct_villages(spec, touched, parts) -> float:
    return float(len({e.village_id for e in touched if e.village_id}))


def _op_count_distinct_property(spec, touched, parts) -> float:
    prop = spec.get("property", "")
    return float(len({_hashable(_prop(e, prop)) for e in touched if _prop(e, prop) is not None}))


def _op_median_property(spec, touched, parts) -> float | None:
    values = _numeric_values(touched, spec.get("property", ""), float(spec.get("scale", 1.0)))
    return float(statistics.median(values)) if values else None


def _op_mean_property(spec, touched, parts) -> float | None:
    values = _numeric_values(touched, spec.get("property", ""), float(spec.get("scale", 1.0)))
    return float(statistics.fmean(values)) if values else None


def _op_share_property_true(spec, touched, parts) -> float | None:
    if not touched:
        return None
    prop = spec.get("property", "")
    return sum(1 for e in touched if bool(_prop(e, prop))) / len(touched)


def _op_ratio_events(spec, touched, parts) -> float | None:
    num, den = parts if parts else ([], [])
    total = len(num) + len(den)
    return (len(num) / total) if total else None


def _op_count_items(spec, touched, parts) -> float:
    return float(len({e.item_id for e in touched if e.item_id}))


OPERATORS: dict[str, Callable[[dict, list[Event], Any], float | None]] = {
    "count_events": _op_count_events,
    "count_distinct_actors": _op_count_distinct_actors,
    "count_distinct_devices": _op_count_distinct_devices,
    "count_distinct_villages": _op_count_distinct_villages,
    "count_distinct_property": _op_count_distinct_property,
    "median_property": _op_median_property,
    "mean_property": _op_mean_property,
    "share_property_true": _op_share_property_true,
    "ratio_events": _op_ratio_events,
    "count_items": _op_count_items,
}


def evaluate(spec: dict, scope: Sequence[Event]) -> tuple[float | None, list[Event], str]:
    """Evaluate one spec over one dimension's events → (value, touched events, note)."""
    touched, parts = _select(spec, scope)
    op = OPERATORS.get(str(spec.get("type", "")))
    if op is None:
        return None, touched, UNSUPPORTED
    try:
        value = op(spec, touched, parts)
    except Exception as exc:  # a broken spec must not take the whole run down
        log.warning("KPI spec %r failed: %s", spec, exc)
        return None, touched, f"spec error: {type(exc).__name__}"
    note = NOTE_NO_EVENTS if not touched else ""
    return value, touched, note


# =================================================================================================
# cell construction
# =================================================================================================


def _persons_behind(kpi: dict, touched: Sequence[Event]) -> int | None:
    """Distinct individuals behind a cell: actors for person-level KPIs, otherwise devices.

    ``None`` means "not backed by individuals" (for example a count of validator decisions) — the
    k-rule does not apply to such a cell.
    """
    if not touched:
        return None
    if kpi.get("person_level"):
        return len({e.actor_pseudonym for e in touched if e.actor_pseudonym})
    devices = {e.device_pseudonym for e in touched if e.device_pseudonym}
    if devices:
        return len(devices)
    actors = {e.actor_pseudonym for e in touched if e.actor_pseudonym}
    return len(actors) if actors else None


def _cell(kpi: dict, dimension: str, kind: str, scope: Sequence[Event]) -> Cell:
    value, touched, note = evaluate(kpi["spec"], scope)
    return Cell(
        kpi_key=kpi["key"],
        kpi_label=kpi.get("label_en") or kpi["key"],
        dimension=dimension,
        dimension_kind=kind,
        value=value,
        unit=kpi.get("unit", "count"),
        n_persons=_persons_behind(kpi, touched),
        n_events=len(touched),
        provisional_definition=bool(kpi.get("provisional", True)),
        note=note,
    )


def _gender_scopes(events: Sequence[Event]) -> dict[str, list[Event]]:
    """Split events by *voluntarily self-reported* gender; everything else is ``not_reported``."""
    scopes: dict[str, list[Event]] = {g: [] for g in (*GENDER_CELLS, NOT_REPORTED)}
    for e in events:
        if e.gender_self_reported and e.actor_gender in GENDER_CELLS:
            scopes[e.actor_gender].append(e)
        else:
            scopes[NOT_REPORTED].append(e)
    return scopes


def build_cells(defs: Definitions, events: Sequence[Event], village_slugs: dict[uuid.UUID, str]) -> list[Cell]:
    """Every cell of a run, before disclosure control."""
    cells: list[Cell] = []
    by_gender = _gender_scopes(events)
    by_village: dict[uuid.UUID, list[Event]] = defaultdict(list)
    for e in events:
        if e.village_id is not None:
            by_village[e.village_id].append(e)

    for kpi in defs.kpis:
        cells.append(_cell(kpi, TOTAL, KIND_TOTAL, events))

        if kpi.get("gender_disaggregated"):
            for dim in (*GENDER_CELLS, NOT_REPORTED):
                cells.append(_cell(kpi, dim, KIND_GENDER, by_gender[dim]))

        for village_id, scope in by_village.items():
            slug = village_slugs.get(village_id)
            if slug is None:
                continue
            cell = _cell(kpi, slug, KIND_VILLAGE, scope)
            if cell.n_events:  # only villages the KPI actually saw
                cells.append(cell)

        if kpi.get("person_level"):
            cells.extend(_activity_cells(kpi, events))
    return cells


def _activity_cells(kpi: dict, events: Sequence[Event]) -> list[Cell]:
    """``date × activity × gender`` cells — the finest grain, governed by the small-cell rule."""
    touched, _ = _select(kpi["spec"], events)
    buckets: dict[tuple[str, str, str], list[Event]] = defaultdict(list)
    for e in touched:
        gender = e.actor_gender if (e.gender_self_reported and e.actor_gender in GENDER_CELLS) else NOT_REPORTED
        day = e.occurred_at.astimezone(timezone.utc).date().isoformat()
        buckets[(day, e.event_type, gender)].append(e)
    cells = []
    for (day, activity, gender), evs in sorted(buckets.items()):
        actors = {e.actor_pseudonym for e in evs if e.actor_pseudonym}
        cells.append(
            Cell(
                kpi_key=kpi["key"],
                kpi_label=kpi.get("label_en") or kpi["key"],
                dimension=f"{day}|{activity}|{gender}",
                dimension_kind=KIND_ACTIVITY,
                value=float(len(evs)),
                unit="count",
                n_persons=len(actors),
                n_events=len(evs),
                provisional_definition=bool(kpi.get("provisional", True)),
            )
        )
    return cells


# =================================================================================================
# heat map
# =================================================================================================


def build_heat_cells(events: Sequence[Event], k_min: int, cell_size: float = HEAT_CELL_SIZE_DEG) -> list[dict]:
    """Aggregate geotagged visitor events on a ~100 m grid; keep cells with ≥ k_min devices."""
    grid: dict[tuple[int, int], dict[str, Any]] = defaultdict(
        lambda: {"visits": 0, "devices": set(), "municipality": Counter()}
    )
    for e in events:
        if e.event_type not in HEAT_EVENT_TYPES or e.lat is None or e.lng is None:
            continue
        key = (math.floor(e.lat / cell_size), math.floor(e.lng / cell_size))
        bucket = grid[key]
        bucket["visits"] += 1
        if e.device_pseudonym:
            bucket["devices"].add(e.device_pseudonym)
        if e.municipality:
            bucket["municipality"][e.municipality] += 1

    out = []
    for (ilat, ilng), bucket in sorted(grid.items()):
        n_devices = len(bucket["devices"])
        if n_devices < k_min:
            continue  # a cell that could point at a handful of people is never stored
        municipality = bucket["municipality"].most_common(1)[0][0] if bucket["municipality"] else None
        out.append(
            {
                "cell_lat": round((ilat + 0.5) * cell_size, 6),
                "cell_lng": round((ilng + 0.5) * cell_size, 6),
                "cell_size_deg": cell_size,
                "n_visits": bucket["visits"],
                "n_devices": n_devices,
                "municipality": municipality,
            }
        )
    return out


def heat_feature(cell: HeatCell) -> dict[str, Any]:
    """One heat cell as a GeoJSON Polygon (the grid square), with its centre in the properties."""
    half = cell.cell_size_deg / 2
    lat, lng = cell.cell_lat, cell.cell_lng
    ring = [
        [round(lng - half, 6), round(lat - half, 6)],
        [round(lng + half, 6), round(lat - half, 6)],
        [round(lng + half, 6), round(lat + half, 6)],
        [round(lng - half, 6), round(lat + half, 6)],
        [round(lng - half, 6), round(lat - half, 6)],
    ]
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [ring]},
        "properties": {
            "n_visits": cell.n_visits,
            "n_devices": cell.n_devices,
            "municipality": cell.municipality,
            "cell_size_deg": cell.cell_size_deg,
            "center": {"lat": lat, "lng": lng},
        },
    }


# =================================================================================================
# runs
# =================================================================================================


def compute_kpis(
    db: Session,
    period_days: int = 365,
    now: datetime | None = None,
    publish: bool = False,
    definitions: Definitions | None = None,
) -> dict[str, Any]:
    """Compute one KPI run from the event stream and store the reviewed aggregates.

    ``publish=True`` marks the run published without a disclosure review — a convenience for the
    CLI demo (``python -m app.cli kpi-compute --publish``). The API always goes through
    :func:`review_run`.
    """
    defs = definitions or load_definitions()
    period_end = (now or utcnow()).astimezone(timezone.utc)
    period_start = period_end - timedelta(days=max(1, int(period_days)))
    k_min = settings.kpi_k_min

    events = list(
        db.scalars(
            select(Event)
            .where(Event.occurred_at >= period_start, Event.occurred_at <= period_end)
            .order_by(Event.occurred_at)
        )
    )
    village_slugs = {v.id: v.slug for v in db.scalars(select(Village))}

    run = KpiRun(
        period_start=period_start,
        period_end=period_end,
        k_min=k_min,
        definitions_version=defs.version,
        definitions_provisional=defs.provisional,
        status="computed",
    )
    db.add(run)
    db.flush()

    cells = build_cells(defs, events, village_slugs)
    summary = disclosure.apply_disclosure_control(cells, k_min)

    stored = [c for c in cells if not (c.dimension_kind == KIND_ACTIVITY and c.suppressed)]
    for c in stored:
        db.add(
            KpiAggregate(
                run_id=run.id,
                computed_at=run.computed_at,
                period_start=period_start,
                period_end=period_end,
                kpi_key=c.kpi_key,
                kpi_label=c.kpi_label,
                dimension=c.dimension,
                dimension_kind=c.dimension_kind,
                value=c.value,
                unit=c.unit,
                n_persons=c.n_persons,
                n_events=c.n_events,
                suppressed=c.suppressed,
                suppression_reason=c.suppression_reason,
                provisional_definition=c.provisional_definition,
                note=c.note,
            )
        )

    heat = build_heat_cells(events, k_min)
    for h in heat:
        db.add(HeatCell(run_id=run.id, computed_at=run.computed_at, **h))

    run.n_rows = len(stored)
    run.n_suppressed = sum(1 for c in stored if c.suppressed)
    if publish:
        run.status = "published"
        run.reviewed_at = utcnow()
        run.review_note = "published without a disclosure review (kpi-compute --publish, demo only)"
    db.commit()

    result = {
        "run_id": str(run.id),
        "status": run.status,
        "computed_at": run.computed_at,
        "period_start": period_start,
        "period_end": period_end,
        "period_days": period_days,
        "k_min": k_min,
        "definitions_version": defs.version,
        "definitions_provisional": defs.provisional,
        "definitions_path": defs.path,
        "n_kpis": len(defs.kpis),
        "n_events": len(events),
        "n_rows": run.n_rows,
        "n_suppressed": run.n_suppressed,
        "n_heat_cells": len(heat),
        "n_small_cells_dropped": len(cells) - len(stored),
        "disclosure": summary,
        "published_without_review": bool(publish),
    }
    log.info(
        "KPI run %s: %d events → %d rows (%d suppressed), %d heat cells, definitions %s%s",
        run.id, len(events), run.n_rows, run.n_suppressed, len(heat), defs.version,
        " (PROVISIONAL)" if defs.provisional else "",
    )
    return result


def latest_published_run(db: Session) -> KpiRun | None:
    return db.scalars(
        select(KpiRun).where(KpiRun.status == "published").order_by(KpiRun.computed_at.desc()).limit(1)
    ).first()


def get_run(db: Session, run_id: uuid.UUID | str) -> KpiRun | None:
    try:
        rid = run_id if isinstance(run_id, uuid.UUID) else uuid.UUID(str(run_id))
    except ValueError:
        return None
    return db.get(KpiRun, rid)


def recent_runs(db: Session, limit: int = 20) -> list[KpiRun]:
    return list(db.scalars(select(KpiRun).order_by(KpiRun.computed_at.desc()).limit(limit)))


def rows_for_run(db: Session, run: KpiRun) -> list[KpiAggregate]:
    return list(
        db.scalars(
            select(KpiAggregate)
            .where(KpiAggregate.run_id == run.id)
            .order_by(KpiAggregate.kpi_key, KpiAggregate.dimension_kind, KpiAggregate.dimension)
        )
    )


def heat_cells_for_run(db: Session, run: KpiRun) -> list[HeatCell]:
    return list(db.scalars(select(HeatCell).where(HeatCell.run_id == run.id)))


def review_run(
    db: Session,
    run_id: uuid.UUID | str,
    decision: str,
    note: str = "",
    reviewer: User | None = None,
) -> dict[str, Any]:
    """The disclosure review: publish or reject a computed run. Only a published run is readable."""
    if decision not in ("publish", "reject"):
        raise ValueError("decision must be 'publish' or 'reject'")
    run = get_run(db, run_id)
    if run is None:
        raise LookupError(f"KPI run {run_id} not found")
    if run.status in ("published", "rejected"):
        raise ValueError(f"KPI run {run.id} was already reviewed (status {run.status})")

    rows = rows_for_run(db, run)
    run.status = "published" if decision == "publish" else "rejected"
    run.review_note = note or ""
    run.reviewed_at = utcnow()
    run.reviewed_by = reviewer.id if reviewer is not None else None
    db.commit()
    return {
        "run_id": str(run.id),
        "status": run.status,
        "decision": decision,
        "reviewed_at": run.reviewed_at,
        "reviewed_by_role": reviewer.role if reviewer is not None else None,
        "review_note": run.review_note,
        "k_min": run.k_min,
        "definitions_version": run.definitions_version,
        "definitions_provisional": run.definitions_provisional,
        "disclosure": disclosure.review_summary(rows, k_min=run.k_min),
    }


def review_sheet(db: Session, run: KpiRun) -> dict[str, Any]:
    """What the human reviewer sees before signing off a run."""
    rows = rows_for_run(db, run)
    return {
        "run_id": str(run.id),
        "status": run.status,
        "computed_at": run.computed_at,
        "period_start": run.period_start,
        "period_end": run.period_end,
        "k_min": run.k_min,
        "definitions_version": run.definitions_version,
        "definitions_provisional": run.definitions_provisional,
        "n_rows": run.n_rows,
        "n_suppressed": run.n_suppressed,
        "n_heat_cells": len(heat_cells_for_run(db, run)),
        "disclosure": disclosure.review_summary(rows, k_min=run.k_min),
    }


# =================================================================================================
# internal quality metrics (/api/kpi/quality)
# =================================================================================================


def stt_wer_summary(db: Session) -> dict[str, Any]:
    """Latest speech-to-text evaluation run (word error rate on the elderly-speaker sample set)."""
    latest = db.scalars(
        select(SttEvaluation).order_by(SttEvaluation.evaluated_at.desc()).limit(1)
    ).first()
    if latest is None:
        return {"available": False, "note": "no speech-to-text evaluation has been run yet"}
    rows = list(db.scalars(select(SttEvaluation).where(SttEvaluation.run_id == latest.run_id)))
    wers = [r.wer for r in rows]
    words = sum(r.n_reference_words for r in rows)
    return {
        "available": True,
        "run_id": str(latest.run_id),
        "evaluated_at": latest.evaluated_at,
        "provider": latest.provider,
        "model": latest.model,
        "n_samples": len(rows),
        "n_reference_words": words,
        "mean_wer": round(statistics.fmean(wers), 4) if wers else None,
        "median_wer": round(statistics.median(wers), 4) if wers else None,
        "worst_wer": round(max(wers), 4) if wers else None,
        "synthetic_samples": all(r.is_synthetic_sample for r in rows) if rows else None,
    }


def cache_summary(db: Session) -> dict[str, Any]:
    """Response-cache effectiveness. Each entry cost one miss, so hit_rate = hits / (hits + entries)."""
    entries = list(db.scalars(select(ResponseCache)))
    hits = sum(e.hits for e in entries)
    invalidated = sum(1 for e in entries if e.invalidated_at is not None)
    requests = hits + len(entries)
    return {
        "entries": len(entries),
        "hits": hits,
        "hit_rate": round(hits / requests, 4) if requests else 0.0,
        "invalidated": invalidated,
        "enabled": settings.cache_enabled,
    }


def quality_metrics(db: Session) -> dict[str, Any]:
    from . import budget

    return {"stt_wer": stt_wer_summary(db), "cache": cache_summary(db), "budget": budget.status(db)}
