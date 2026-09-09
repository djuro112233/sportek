"""/api/validation — the validator's queue, the item view, the state machine and the audit trail.

The gate itself lives in ``services/validation.py``: ``TRANSITIONS`` says which role may move an
item from which status to which, every transition writes a provenance record and an audit row, and
approving a heritage entry (re)builds its RAG index while leaving ``approved`` removes it.

This router adds the staff-side views (queue, item with provenance, audit) and repeats one gate rule
as a pre-condition, so that it holds even if the service is called differently in future:

    a content item whose ``facts_verified`` is false may never reach ``approved`` (409).

The authoritative copy of that rule lives in ``services.validation.transition`` (next to the consent
check), which is where every caller — API, CLI, seed loader, jobs — meets it; see
``_refuse_unverified_facts`` below.
"""
from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_user, require_role
from ..db import get_db
from ..models import STATUS_VALUES, AuditLog, User
from ..schemas import (
    HeritageEntryOut,
    ListingOut,
    ProvenanceOut,
    StatusTransitionIn,
    TrailReportOut,
    TrailSegmentOut,
)
from ..services import content, validation

router = APIRouter(prefix="/api/validation", tags=["validation"])

#: Read model per item type — the queue and the item view return the same shapes as the public API.
SCHEMA_BY_TYPE: dict[str, type] = {
    "heritage_entry": HeritageEntryOut,
    "listing": ListingOut,
    "trail_segment": TrailSegmentOut,
    "trail_report": TrailReportOut,
}

QUEUE_STATUSES: tuple[str, ...] = ("draft", "reviewed")


class QueueItem(BaseModel):
    """One row of the validator's queue (docs/api-contract.md § validation)."""

    item_type: str
    id: uuid.UUID
    title: str
    village: str | None = None
    municipality: str | None = None
    status: str
    version: int
    created_at: Any
    source: str = ""
    #: False marks an item whose facts could not be checked — it can never be approved.
    facts_verified: bool = True


class AuditRow(BaseModel):
    """An audit row. ``detail`` never contains personal data (see app/audit.py)."""

    id: uuid.UUID
    occurred_at: Any
    user_id: uuid.UUID | None
    role: str
    action: str
    resource_type: str
    resource_id: str
    detail: dict
    request_id: str


class ItemView(BaseModel):
    """One item in any status, with its full provenance trail."""

    item_type: str
    item: dict
    provenance: list[ProvenanceOut]


def _serialise(item_type: str, item) -> dict:
    """ORM item → the read model of its type (plain dict, so the union stays simple for clients)."""
    schema = SCHEMA_BY_TYPE.get(item_type)
    if schema is None:  # pragma: no cover - guarded by validation.MODEL_BY_TYPE beforehand
        raise HTTPException(status_code=400, detail=f"unknown item type {item_type}")
    return schema.model_validate(item).model_dump(mode="json")


def _refuse_unverified_facts(item_type: str, item, to_status: str) -> None:
    """Refuse to approve an item whose facts are not verified (409).

    This is a *gate* rule, not a routing rule: its authoritative copy sits beside the consent check
    inside ``services.validation.transition``, so every caller (API, CLI, seed loader, future jobs)
    is bound by it. Repeating it here — in the same position in the sequence of checks — costs one
    comparison and keeps the API's behaviour explicit at the edge.
    """
    if to_status == "approved" and getattr(item, "facts_verified", True) is False:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "facts are not verified: this item cannot be approved until its sources have been "
                "checked (facts_verified=false)"
            ),
        )


@router.get("/queue", response_model=list[QueueItem], summary="Items waiting for validation")
def queue(
    actor: Annotated[User, Depends(require_role("validator", "ambassador"))],
    db: Annotated[Session, Depends(get_db)],
    item_type: Annotated[str | None, Query(description="heritage_entry | listing | trail_segment | trail_report")] = None,
    village: Annotated[str | None, Query(description="village slug or id")] = None,
) -> list[QueueItem]:
    """Drafts and reviewed items, oldest first, with their village, municipality and source.

    ``facts_verified=false`` tells the validator up front that approving is refused until the
    sources have been checked.
    """
    if item_type is not None and item_type not in validation.MODEL_BY_TYPE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"unknown item type {item_type}"
        )
    rows = validation.queue(db, item_type, statuses=QUEUE_STATUSES)
    villages = content.village_labels(db, (getattr(r["item"], "village_id", None) for r in rows))
    sources = content.first_provenance_source(db, ((r["item_type"], r["item"].id) for r in rows))

    out: list[QueueItem] = []
    for row in rows:
        item, t = row["item"], row["item_type"]
        vill = villages.get(getattr(item, "village_id", None))
        if not content.matches_village(vill, village):
            continue
        out.append(
            QueueItem(
                item_type=t,
                id=item.id,
                title=validation.display_title(t, item),
                village=vill.slug if vill else None,
                municipality=vill.municipality if vill else None,
                status=item.status,
                version=item.version,
                created_at=item.created_at,
                source=getattr(item, "source", "") or sources.get((t, item.id), ""),
                facts_verified=bool(getattr(item, "facts_verified", True)),
            )
        )
    return out


@router.get(
    "/items/{item_type}/{item_id}",
    response_model=ItemView,
    summary="One item in any status, with its provenance trail",
)
def get_item(
    item_type: str,
    item_id: str,
    actor: Annotated[User, Depends(require_role("validator", "ambassador"))],
    db: Annotated[Session, Depends(get_db)],
) -> ItemView:
    item = validation.get_item(db, item_type, item_id)
    return ItemView(
        item_type=item_type,
        item=_serialise(item_type, item),
        provenance=[ProvenanceOut.model_validate(p) for p in validation.provenance_for(db, item_type, item.id)],
    )


@router.post(
    "/items/{item_type}/{item_id}/transition",
    summary="Move an item through the gate (draft → reviewed → approved | rejected)",
)
def transition(
    item_type: str,
    item_id: str,
    body: StatusTransitionIn,
    actor: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Perform one transition.

    Roles come from ``services.validation.TRANSITIONS`` (403 when the actor's role may not do it),
    the step itself must exist (409), a listing needs a consent record before approval (409) and an
    item whose facts are unverified is refused approval (409). The transition writes provenance and
    audit rows, updates the RAG index and emits ``entry_approved`` / ``item_rejected``.
    """
    if body.to_status not in STATUS_VALUES:  # pragma: no cover - the schema already constrains it
        raise HTTPException(status_code=400, detail=f"invalid status {body.to_status}")
    item = validation.get_item(db, item_type, item_id)
    # Only once the step itself and the actor's role are acceptable does the facts rule apply, so an
    # impossible step still reads as "not allowed" (409) and a wrong role as 403 — the same order the
    # rule will have when it moves into services.validation.transition.
    allowed = validation.TRANSITIONS.get((item.status, body.to_status))
    if allowed is not None and actor.role in allowed:
        _refuse_unverified_facts(item_type, item, body.to_status)
    item = validation.transition(db, item_type, item.id, body.to_status, actor=actor, note=body.note)
    return _serialise(item_type, item)


@router.get("/audit", response_model=list[AuditRow], summary="The last 200 audit rows")
def audit(
    actor: Annotated[User, Depends(require_role("validator", "institution"))],
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 200,
) -> list[AuditLog]:
    """Newest first. Audit details are free of personal data by construction (app/audit.py)."""
    return list(db.scalars(select(AuditLog).order_by(AuditLog.occurred_at.desc(), AuditLog.id).limit(limit)))
