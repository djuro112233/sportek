"""/api/kpi — the institutions' dashboard API.

Reads come from the **reviewed aggregates only**: ``GET /api/kpi`` serves the latest run whose
status is ``published``, which a human reached through ``POST /api/kpi/runs/{id}/review``. A freshly
computed run is invisible until then, and no endpoint here touches the ``events`` table.

``GET /api/kpi/definitions`` is public on purpose: anybody may check what the published numbers
claim to mean, including the warning that the definitions are provisional until SIP Draft §11 is
transcribed into ``backend/kpi_definitions/sip_section_11.json``.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..auth import require_role
from ..config import settings
from ..db import get_db
from ..models import KpiRun, User
from ..ratelimit import limiter
from ..services import kpi as kpi_service

router = APIRouter(prefix="/api/kpi", tags=["kpi"])

#: the dashboard roles; a host or ambassador never reads aggregate KPIs
READER_ROLES = ("institution", "validator")
ReaderUser = Annotated[User, Depends(require_role(*READER_ROLES))]
ReviewerUser = Annotated[User, Depends(require_role("validator", "institution"))]


# --- response models (the exact KpiRow of docs/api-contract.md) ----------------------------------


class KpiRow(BaseModel):
    """One published (or suppressed) cell. Carries no session, device or user identifier."""

    kpi_key: str
    kpi_label: str
    dimension: str
    dimension_kind: str
    value: float | None
    unit: str
    n_persons: int | None
    n_events: int
    suppressed: bool
    suppression_reason: str
    provisional_definition: bool
    note: str


class KpiTable(BaseModel):
    run_id: str | None
    computed_at: datetime | None
    period_start: datetime | None
    period_end: datetime | None
    k_min: int
    definitions_version: str
    definitions_provisional: bool
    rows: list[KpiRow]
    note: str = ""


class RunOut(BaseModel):
    run_id: str
    status: str
    computed_at: datetime
    period_start: datetime
    period_end: datetime
    k_min: int
    definitions_version: str
    definitions_provisional: bool
    n_rows: int
    n_suppressed: int
    reviewed_at: datetime | None
    review_note: str
    disclosure: dict[str, Any]


class ComputeIn(BaseModel):
    period_days: int = Field(default=365, ge=1, le=3650)


class ReviewIn(BaseModel):
    decision: Literal["publish", "reject"]
    note: str = Field(default="", max_length=2000)


def _run_out(db: Session, run: KpiRun) -> RunOut:
    return RunOut(
        run_id=str(run.id),
        status=run.status,
        computed_at=run.computed_at,
        period_start=run.period_start,
        period_end=run.period_end,
        k_min=run.k_min,
        definitions_version=run.definitions_version,
        definitions_provisional=run.definitions_provisional,
        n_rows=run.n_rows,
        n_suppressed=run.n_suppressed,
        reviewed_at=run.reviewed_at,
        review_note=run.review_note,
        disclosure=kpi_service.review_sheet(db, run)["disclosure"],
    )


# --- endpoints ------------------------------------------------------------------------------------


@router.get("", response_model=KpiTable, summary="Published KPI aggregates (latest reviewed run)")
def kpi_table(user: ReaderUser, db: Session = Depends(get_db)) -> KpiTable:
    """The dashboard's only data source. Empty until a disclosure review publishes a run."""
    run = kpi_service.latest_published_run(db)
    if run is None:
        defs = kpi_service.load_definitions()
        return KpiTable(
            run_id=None, computed_at=None, period_start=None, period_end=None,
            k_min=settings.kpi_k_min, definitions_version=defs.version,
            definitions_provisional=defs.provisional, rows=[],
            note="no published KPI run: compute a run and publish it through the disclosure review",
        )
    rows = [KpiRow.model_validate(r, from_attributes=True) for r in kpi_service.rows_for_run(db, run)]
    return KpiTable(
        run_id=str(run.id),
        computed_at=run.computed_at,
        period_start=run.period_start,
        period_end=run.period_end,
        k_min=run.k_min,
        definitions_version=run.definitions_version,
        definitions_provisional=run.definitions_provisional,
        rows=rows,
        note="provisional definitions — see GET /api/kpi/definitions" if run.definitions_provisional else "",
    )


@router.post("/compute", summary="Compute a new KPI run (status: computed, not yet published)")
def compute(
    user: ReaderUser,
    body: ComputeIn | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    body = body or ComputeIn()
    result = kpi_service.compute_kpis(db, period_days=body.period_days, publish=False)
    record_audit(
        db, user=user, action="kpi_compute", resource_type="kpi_run", resource_id=result["run_id"],
        detail={"period_days": body.period_days, "n_rows": result["n_rows"], "n_suppressed": result["n_suppressed"]},
    )
    db.commit()
    return result


@router.get("/runs", response_model=list[RunOut], summary="Recent KPI runs and their review status")
def runs(
    user: ReaderUser,
    limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[RunOut]:
    return [_run_out(db, r) for r in kpi_service.recent_runs(db, limit=limit)]


@router.post("/runs/{run_id}/review", summary="Disclosure review: publish or reject a computed run")
def review(
    run_id: uuid.UUID,
    body: ReviewIn,
    user: ReviewerUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """A human confirms the suppression result. Only a published run reaches ``GET /api/kpi``."""
    try:
        result = kpi_service.review_run(db, run_id, body.decision, body.note, reviewer=user)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    record_audit(
        db, user=user, action="kpi_review", resource_type="kpi_run", resource_id=str(run_id),
        detail={"decision": body.decision, "n_suppressed": result["disclosure"]["n_suppressed"]},
    )
    db.commit()
    return result


@router.get("/heatmap", summary="Heat map of the published run (GeoJSON, k≥k_min devices per cell)")
def heatmap(user: ReaderUser, db: Session = Depends(get_db)) -> dict[str, Any]:
    run = kpi_service.latest_published_run(db)
    features = [] if run is None else [kpi_service.heat_feature(c) for c in kpi_service.heat_cells_for_run(db, run)]
    return {
        "type": "FeatureCollection",
        "features": features,
        "properties": {
            "run_id": str(run.id) if run else None,
            "k_min": run.k_min if run else settings.kpi_k_min,
            "cell_size_deg": kpi_service.HEAT_CELL_SIZE_DEG,
            "note": "aggregated visit and trail-report cells; a cell is stored only when at least "
                    f"{run.k_min if run else settings.kpi_k_min} distinct pseudonymous devices are behind it",
        },
    }


@router.get("/definitions", summary="The K01–K23 definition file (public, provisional)")
@limiter.limit(settings.rate_limit_public)
def definitions(request: Request, response: Response) -> dict[str, Any]:
    """Public: the definitions behind every published number, with the provisional warning."""
    defs = kpi_service.load_definitions()
    doc = defs.public_dict()
    doc["k_min"] = settings.kpi_k_min
    doc["k11_dedup_days"] = settings.k11_dedup_days
    doc["pilot_start_date"] = settings.pilot_start_date
    return doc


@router.get("/quality", summary="Internal quality metrics: speech-to-text WER, cache, spend cap")
def quality(user: ReaderUser, db: Session = Depends(get_db)) -> dict[str, Any]:
    return kpi_service.quality_metrics(db)
