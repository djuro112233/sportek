"""Statistical disclosure control — the review step every KPI run passes before publication.

The KPI engine (``services/kpi.py``) produces one :class:`Cell` per KPI and dimension. Nothing is
written to the dashboard tables before this module has been over it, and no run becomes visible
through the API before a human confirms the result (``POST /api/kpi/runs/{id}/review``).

Three rules, applied in this order:

1. **Small-cell rule** (``small_cell``) — every ``date × activity × gender`` cell backed by fewer
   than ``k_min`` distinct persons is suppressed *outright*: the KPI engine does not even store it,
   so the finest-grained table the dashboard can reach never contains a small cell.
2. **Primary suppression** (``k<{k}``) — any remaining cell backed by fewer than ``k_min`` distinct
   persons or devices loses its value (``value = None``). Cells that are not backed by persons or
   devices at all (for example "heritage entries approved", a count of editorial decisions) carry
   ``n_persons = None`` and are not subject to the rule; they contain no personal data.
3. **Secondary suppression** (``secondary``) — if exactly one gender cell of a KPI is suppressed
   while the KPI total is published, the smallest remaining gender cell is suppressed as well.
   Otherwise the hidden value could be recovered by subtracting the published cells from the total.

``k_min`` defaults to ``settings.kpi_k_min`` (5). It is a *minimum*: raising KPI_K_MIN raises the
threshold everywhere, in the engine, in the review summary and on the dashboard.

The module is deliberately free of database access so it can be tested on constructed cells.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol, Sequence

from ..config import settings

# --- dimension vocabulary ------------------------------------------------------------------------

TOTAL = "total"
KIND_TOTAL = "total"
KIND_GENDER = "gender"
KIND_VILLAGE = "village"
KIND_ACTIVITY = "activity_date_gender"

#: gender dimensions; only a voluntary self-report reaches the first three
GENDER_CELLS: tuple[str, ...] = ("female", "male", "other")
NOT_REPORTED = "not_reported"
GENDER_DIMENSIONS: tuple[str, ...] = (*GENDER_CELLS, NOT_REPORTED)

# --- suppression reasons -------------------------------------------------------------------------

SECONDARY = "secondary"
SMALL_CELL = "small_cell"
UNSUPPORTED = "unsupported spec"


def primary_reason(k_min: int) -> str:
    """Reason string of the primary rule, e.g. ``k<5``."""
    return f"k<{k_min}"


@dataclass
class Cell:
    """One computed KPI value for one dimension, before and after disclosure control."""

    kpi_key: str
    kpi_label: str = ""
    dimension: str = TOTAL
    dimension_kind: str = KIND_TOTAL
    value: float | None = None
    unit: str = "count"
    #: distinct persons (actor pseudonyms) or devices behind the cell; ``None`` when the cell is not
    #: backed by individuals at all and the k-rule therefore does not apply.
    n_persons: int | None = None
    n_events: int = 0
    provisional_definition: bool = True
    note: str = ""
    suppressed: bool = False
    suppression_reason: str = ""

    def suppress(self, reason: str) -> None:
        self.value = None
        self.suppressed = True
        self.suppression_reason = reason


class HasSuppression(Protocol):
    """Anything the review summary can count: a :class:`Cell` or a ``KpiAggregate`` row."""

    kpi_key: str
    dimension: str
    dimension_kind: str
    suppressed: bool
    suppression_reason: str


# --- the three rules -----------------------------------------------------------------------------


def apply_small_cell(cells: Iterable[Cell], k_min: int) -> list[Cell]:
    """Rule 1. Mark every ``date × activity × gender`` cell below ``k_min`` as ``small_cell``.

    Returns the marked cells; the caller (the KPI engine) drops them instead of storing them.
    """
    hit = []
    for cell in cells:
        if cell.dimension_kind != KIND_ACTIVITY or cell.suppressed:
            continue
        if (cell.n_persons or 0) < k_min:
            cell.suppress(SMALL_CELL)
            hit.append(cell)
    return hit


def apply_primary(cells: Iterable[Cell], k_min: int) -> list[Cell]:
    """Rule 2. Suppress any cell backed by fewer than ``k_min`` distinct persons/devices."""
    hit = []
    for cell in cells:
        if cell.suppressed or cell.n_persons is None:
            continue
        if cell.n_persons < k_min:
            cell.suppress(primary_reason(k_min))
            hit.append(cell)
    return hit


def apply_secondary(cells: Sequence[Cell], k_min: int) -> list[Cell]:
    """Rule 3. Protect a single suppressed gender cell against recovery by subtraction."""
    hit = []
    totals: dict[str, Cell] = {
        c.kpi_key: c for c in cells if c.dimension_kind == KIND_TOTAL and c.dimension == TOTAL
    }
    by_kpi: dict[str, list[Cell]] = defaultdict(list)
    for cell in cells:
        if cell.dimension_kind == KIND_GENDER:
            by_kpi[cell.kpi_key].append(cell)

    for kpi_key, gender_cells in by_kpi.items():
        total = totals.get(kpi_key)
        if total is None or total.suppressed or total.value is None:
            continue  # nothing to subtract from
        suppressed = [c for c in gender_cells if c.suppressed]
        if len(suppressed) != 1:
            continue  # zero → nothing hidden; two or more → not recoverable by subtraction
        remaining = [c for c in gender_cells if not c.suppressed and c.value is not None]
        if not remaining:
            continue
        smallest = min(remaining, key=lambda c: (c.value, c.dimension))
        smallest.suppress(SECONDARY)
        hit.append(smallest)
    return hit


def apply_disclosure_control(cells: list[Cell], k_min: int | None = None) -> dict[str, Any]:
    """Run all three rules in order and return the review summary.

    The cells are mutated in place. ``date × activity × gender`` cells marked ``small_cell`` stay in
    the list so the reviewer can be told how many were dropped; the KPI engine filters them out
    before writing the aggregates.
    """
    k = settings.kpi_k_min if k_min is None else k_min
    apply_small_cell(cells, k)
    apply_primary(cells, k)
    apply_secondary(cells, k)
    return review_summary(cells, k_min=k)


# --- review summary ------------------------------------------------------------------------------


def review_summary(cells: Iterable[Any], k_min: int | None = None) -> dict[str, Any]:
    """What a human signs off: how many cells were suppressed, by which rule and where.

    Accepts :class:`Cell` objects or persisted ``KpiAggregate`` rows (same attribute names).
    """
    k = settings.kpi_k_min if k_min is None else k_min
    cells = list(cells)
    by_rule: Counter[str] = Counter()
    by_kind: Counter[str] = Counter()
    suppressed_keys: set[str] = set()
    unsupported: list[str] = []
    n_suppressed = 0
    for cell in cells:
        if getattr(cell, "suppressed", False):
            n_suppressed += 1
            by_rule[cell.suppression_reason or "unspecified"] += 1
            by_kind[cell.dimension_kind] += 1
            suppressed_keys.add(cell.kpi_key)
        if (getattr(cell, "note", "") or "") == UNSUPPORTED:
            unsupported.append(cell.kpi_key)
    published_keys = {
        c.kpi_key for c in cells if not getattr(c, "suppressed", False)
    }
    return {
        "k_min": k,
        "n_cells": len(cells),
        "n_published": len(cells) - n_suppressed,
        "n_suppressed": n_suppressed,
        "by_rule": {
            primary_reason(k): by_rule.get(primary_reason(k), 0),
            SECONDARY: by_rule.get(SECONDARY, 0),
            SMALL_CELL: by_rule.get(SMALL_CELL, 0),
            **{r: n for r, n in by_rule.items() if r not in (primary_reason(k), SECONDARY, SMALL_CELL)},
        },
        "by_dimension_kind": dict(sorted(by_kind.items())),
        "kpis_with_suppressed_cells": sorted(suppressed_keys),
        "kpis_fully_suppressed": sorted(suppressed_keys - published_keys),
        "kpis_unsupported_spec": sorted(set(unsupported)),
    }


__all__ = [
    "Cell",
    "GENDER_CELLS",
    "GENDER_DIMENSIONS",
    "KIND_ACTIVITY",
    "KIND_GENDER",
    "KIND_TOTAL",
    "KIND_VILLAGE",
    "NOT_REPORTED",
    "SECONDARY",
    "SMALL_CELL",
    "TOTAL",
    "UNSUPPORTED",
    "apply_disclosure_control",
    "apply_primary",
    "apply_secondary",
    "apply_small_cell",
    "primary_reason",
    "review_summary",
]
