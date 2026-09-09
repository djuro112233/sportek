"""The validation gate.

State machine for every content item:  draft → reviewed → approved | rejected  (rejected → draft for rework;
approved → draft when a validator withdraws it or when the item is edited).

* Every transition writes a provenance record (who, when, version, source, note) and an audit-log row.
* Approval of a heritage entry (re)builds its RAG index; leaving ``approved`` removes it.
* Approval emits ``entry_approved``; rejection emits ``item_rejected``.
* The visitor side never sees anything but ``approved`` rows: services filter explicitly with
  ``approved_only`` AND the visitor DB role is limited by row-level security (db.py).
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..events import emit_event
from ..models import (
    STATUS_VALUES,
    HeritageEntry,
    Listing,
    Provenance,
    TrailReport,
    TrailSegment,
    User,
    utcnow,
)
from . import indexing

VILLAGE_MODELS = ("heritage_entry", "listing", "trail_segment", "trail_report")

MODEL_BY_TYPE: dict[str, type] = {
    "heritage_entry": HeritageEntry,
    "listing": Listing,
    "trail_segment": TrailSegment,
    "trail_report": TrailReport,
}

# (from, to) -> roles allowed to perform the transition
TRANSITIONS: dict[tuple[str, str], set[str]] = {
    ("draft", "reviewed"): {"ambassador", "validator"},
    ("reviewed", "approved"): {"validator"},
    ("draft", "approved"): {"validator"},
    ("draft", "rejected"): {"validator"},
    ("reviewed", "rejected"): {"validator"},
    ("reviewed", "draft"): {"ambassador", "validator"},
    ("rejected", "draft"): {"host", "ambassador", "validator"},
    ("approved", "draft"): {"validator"},
}


def approved_only(stmt, model):
    """Explicit visitor-side filter (belt) in addition to row-level security (braces)."""
    return stmt.where(model.status == "approved")


def get_item(db: Session, item_type: str, item_id: uuid.UUID | str):
    model = MODEL_BY_TYPE.get(item_type)
    if model is None:
        raise HTTPException(status_code=400, detail=f"unknown item type {item_type}")
    if isinstance(item_id, str):
        try:
            item_id = uuid.UUID(item_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="item not found") from exc
    item = db.get(model, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="item not found")
    return item


def add_provenance(
    db: Session,
    item_type: str,
    item,
    action: str,
    *,
    actor: User | None,
    source: str = "",
    note: str = "",
    from_status: str | None = None,
    to_status: str | None = None,
) -> Provenance:
    rec = Provenance(
        item_type=item_type,
        item_id=item.id,
        version=item.version,
        action=action,
        from_status=from_status,
        to_status=to_status,
        actor_user_id=actor.id if actor else None,
        actor_role=actor.role if actor else "system",
        source=source,
        note=note,
    )
    db.add(rec)
    db.flush()
    return rec


def provenance_for(db: Session, item_type: str, item_id: uuid.UUID) -> list[Provenance]:
    return list(
        db.scalars(
            select(Provenance)
            .where(Provenance.item_type == item_type, Provenance.item_id == item_id)
            .order_by(Provenance.created_at)
        )
    )


def create_item(db: Session, item_type: str, data: dict[str, Any], *, actor: User | None, source: str, note: str = ""):
    """Create a content item in ``draft`` with its first provenance record."""
    model = MODEL_BY_TYPE[item_type]
    data = dict(data)
    data["status"] = "draft"
    data["version"] = 1
    item = model(**data)
    db.add(item)
    db.flush()
    add_provenance(db, item_type, item, "created", actor=actor, source=source, note=note, to_status="draft")
    record_audit(db, user=actor, action=f"{item_type}.create", resource_type=item_type, resource_id=str(item.id))
    return item


def update_item(db: Session, item_type: str, item_id: uuid.UUID, data: dict[str, Any], *, actor: User, note: str = ""):
    """Edit a content item: bumps the version; an approved item drops back to draft (re-validation)."""
    item = get_item(db, item_type, item_id)
    from_status = item.status
    for k, v in data.items():
        if k in ("status", "version", "id"):
            continue
        setattr(item, k, v)
    item.version += 1
    if item.status == "approved":
        item.status = "draft"
        item.approved_at = None
        item.approved_by = None
        if item_type == "heritage_entry":
            indexing.remove_entry_index(db, item.id)
    add_provenance(
        db, item_type, item, "edited", actor=actor, note=note, from_status=from_status, to_status=item.status,
        source=f"edited by {actor.role}",
    )
    record_audit(db, user=actor, action=f"{item_type}.update", resource_type=item_type, resource_id=str(item.id),
                 detail={"version": item.version, "fields": sorted(data.keys())})
    db.flush()
    return item


def transition(
    db: Session, item_type: str, item_id: uuid.UUID | str, to_status: str, *, actor: User, note: str = ""
):
    """Move an item through the gate. Raises 403 when the actor's role may not perform the step."""
    if to_status not in STATUS_VALUES:
        raise HTTPException(status_code=400, detail=f"invalid status {to_status}")
    item = get_item(db, item_type, item_id)
    from_status = item.status
    allowed = TRANSITIONS.get((from_status, to_status))
    if allowed is None:
        raise HTTPException(status_code=409, detail=f"transition {from_status} → {to_status} is not allowed")
    if actor.role not in allowed:
        raise HTTPException(
            status_code=403, detail=f"role '{actor.role}' may not move an item from {from_status} to {to_status}"
        )
    if item_type == "listing" and to_status == "approved" and not item.consent_record_id:
        raise HTTPException(status_code=409, detail="listing cannot be approved without a consent record")
    # Content whose facts could not be verified against a public source is never published.
    if to_status == "approved" and getattr(item, "facts_verified", True) is False:
        raise HTTPException(
            status_code=409,
            detail=(
                "this item is marked as having unverified facts and cannot be approved — "
                "verify it against a public source and record the source first"
            ),
        )

    item.status = to_status
    now = utcnow()
    if to_status == "approved":
        item.approved_at = now
        item.approved_by = actor.id
        if item_type == "listing":
            item.published_at = now
    else:
        item.approved_at = None
        item.approved_by = None

    action = {"reviewed": "reviewed", "approved": "approved", "rejected": "rejected", "draft": "returned_to_draft"}[to_status]
    add_provenance(db, item_type, item, action, actor=actor, note=note, from_status=from_status, to_status=to_status,
                   source=f"validation by {actor.role}")
    record_audit(db, user=actor, action=f"{item_type}.{action}", resource_type=item_type, resource_id=str(item.id),
                 detail={"from": from_status, "to": to_status, "version": item.version})

    if item_type == "heritage_entry":
        if to_status == "approved":
            indexing.reindex_entry(db, item.id)
        else:
            indexing.remove_entry_index(db, item.id)

    published_seconds = None
    if item_type == "listing" and to_status == "approved":
        # Close the onboarding timing loop: elapsed time to publication (never compared with the
        # active-authoring target). The onboarding module owns the session bookkeeping.
        try:
            from .onboarding import mark_published

            published_seconds = mark_published(db, item)
        except ImportError:  # pragma: no cover - onboarding module not installed
            published_seconds = None

    if to_status == "approved":
        emit_event(db, "entry_approved", actor=actor, item_type=item_type, item_id=item.id,
                   version=item.version, from_status=from_status,
                   village_id=getattr(item, "village_id", None),
                   elapsed_to_publish_seconds=published_seconds)
    elif to_status == "rejected":
        emit_event(db, "item_rejected", actor=actor, item_type=item_type, item_id=item.id,
                   version=item.version, from_status=from_status,
                   village_id=getattr(item, "village_id", None))
    db.commit()
    db.refresh(item)
    return item


def queue(db: Session, item_type: str | None = None, statuses: tuple[str, ...] = ("draft", "reviewed")) -> list[dict]:
    """Items waiting for validation, oldest first."""
    out: list[dict] = []
    types = [item_type] if item_type else list(MODEL_BY_TYPE)
    for t in types:
        model = MODEL_BY_TYPE[t]
        for item in db.scalars(select(model).where(model.status.in_(statuses)).order_by(model.created_at)):
            out.append({"item_type": t, "item": item})
    out.sort(key=lambda d: d["item"].created_at)
    return out


def display_title(item_type: str, item) -> str:
    if item_type == "heritage_entry":
        return item.title_en or item.title_local
    if item_type == "listing":
        return item.title_en or item.title_local
    if item_type == "trail_segment":
        return item.name_en or item.name_local
    return f"Trail report ({item.condition})"
