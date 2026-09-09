"""/api/heritage — heritage fact sheets (places, churches, buildings, events, traditions…).

**Validation gate.** The three public endpoints read through the visitor DB role
(``get_public_db``, row-level security → approved rows only) *and* filter ``status == 'approved'``
explicitly (``services.validation.approved_only``). A draft, reviewed or rejected entry is not
merely hidden by the UI: it is invisible to the query and to the database role behind it.

**Territory.** Every entry belongs to a village (mandatory ``village_id``), so the list can be
filtered by ``?village=<slug|id>`` and ``?municipality=Tivat|Kotor``.

**Provenance.** Creating an entry requires a non-empty ``source`` citation; the citation is stored
on the entry *and* in its first provenance record, which is what the validator sees in the queue.
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import require_role
from ..config import settings
from ..db import get_db, get_public_db
from ..models import HeritageEntry, User
from ..ratelimit import limiter
from ..schemas import HeritageEntryOut, ProvenanceOut, SourceRef
from ..services import content, validation

router = APIRouter(prefix="/api/heritage", tags=["heritage"])

#: The kinds the prototype knows (mirrored in the admin app's ``HERITAGE_KINDS``).
HeritageKind = Literal["place", "church", "building", "event", "tradition", "institution", "landscape"]

ITEM_TYPE = "heritage_entry"


class HeritageCreateIn(BaseModel):
    """New entry. It is always created in ``draft``: nothing enters the site without validation."""

    village: str = Field(description="village slug or id — every entry belongs to a village")
    kind: HeritageKind = "place"
    title_local: str = Field(min_length=1, max_length=255, description="Montenegrin (Latin script)")
    title_en: str = Field(min_length=1, max_length=255)
    summary_local: str = ""
    summary_en: str = ""
    body_local: str = ""
    body_en: str = ""
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    coords_approximate: bool = True
    coords_source: str = ""
    elevation_m: int | None = None
    event_date: date | None = None
    recurrence_rule: str | None = None
    established_year: int | None = None
    source: str = Field(min_length=1, description="required citation for the facts of this entry")
    sources: list[SourceRef] = Field(default_factory=list)
    facts_verified: bool = Field(
        default=True,
        description="false marks facts that could not be checked; such an entry can never be approved",
    )
    verification_note: str = ""
    tags: list[str] = Field(default_factory=list)

    @field_validator("source")
    @classmethod
    def _source_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("a heritage entry must cite a source")
        return v.strip()


class HeritageUpdateIn(BaseModel):
    """Partial edit. Any edit bumps the version; an approved entry drops back to draft."""

    village: str | None = None
    kind: HeritageKind | None = None
    title_local: str | None = Field(default=None, min_length=1, max_length=255)
    title_en: str | None = Field(default=None, min_length=1, max_length=255)
    summary_local: str | None = None
    summary_en: str | None = None
    body_local: str | None = None
    body_en: str | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    coords_approximate: bool | None = None
    coords_source: str | None = None
    elevation_m: int | None = None
    event_date: date | None = None
    recurrence_rule: str | None = None
    established_year: int | None = None
    source: str | None = None
    sources: list[SourceRef] | None = None
    facts_verified: bool | None = None
    verification_note: str | None = None
    tags: list[str] | None = None
    note: str = Field(default="", max_length=2000, description="why the entry was edited")

    @field_validator("source")
    @classmethod
    def _source_not_blank(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("a heritage entry must cite a source")
        return v.strip() if v is not None else None


# --- public (approved only) -------------------------------------------------------------------
@router.get("", response_model=list[HeritageEntryOut], summary="Approved heritage entries")
@limiter.limit(settings.rate_limit_public)
def list_entries(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_public_db)],
    kind: Annotated[str | None, Query(description="place | church | building | event | …")] = None,
    village: Annotated[str | None, Query(description="village slug or id")] = None,
    municipality: Annotated[str | None, Query(description="Tivat | Kotor")] = None,
) -> list[HeritageEntry]:
    """Approved entries only — visitor DB role (RLS) plus the explicit status filter."""
    stmt = validation.approved_only(select(HeritageEntry), HeritageEntry)
    if kind:
        stmt = stmt.where(HeritageEntry.kind == kind)
    stmt = content.filter_by_territory(stmt, HeritageEntry, village=village, municipality=municipality)
    return list(db.scalars(stmt.order_by(HeritageEntry.slug)))


@router.get("/calendar", response_model=list[HeritageEntryOut], summary="Approved events by date")
@limiter.limit(settings.rate_limit_public)
def calendar(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_public_db)],
    village: Annotated[str | None, Query(description="village slug or id")] = None,
    municipality: Annotated[str | None, Query(description="Tivat | Kotor")] = None,
) -> list[HeritageEntry]:
    """Approved ``kind='event'`` entries, earliest date first; recurring events without a date last."""
    stmt = validation.approved_only(select(HeritageEntry), HeritageEntry).where(
        HeritageEntry.kind == "event"
    )
    stmt = content.filter_by_territory(stmt, HeritageEntry, village=village, municipality=municipality)
    return list(db.scalars(stmt.order_by(HeritageEntry.event_date.asc().nulls_last(), HeritageEntry.slug)))


@router.get("/{slug_or_id}", response_model=HeritageEntryOut, summary="One approved entry")
@limiter.limit(settings.rate_limit_public)
def get_entry(
    request: Request,
    response: Response,
    slug_or_id: str,
    db: Annotated[Session, Depends(get_public_db)],
) -> HeritageEntry:
    """404 unless the entry is approved — the gate does not leak existence of unvalidated content."""
    return content.get_approved_by_slug_or_id(db, HeritageEntry, slug_or_id)


# --- authoring (ambassador / validator) --------------------------------------------------------
@router.post(
    "",
    response_model=HeritageEntryOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a heritage entry (always draft)",
)
def create_entry(
    body: HeritageCreateIn,
    actor: Annotated[User, Depends(require_role("ambassador", "validator"))],
    db: Annotated[Session, Depends(get_db)],
) -> HeritageEntry:
    """Store a new entry in ``draft`` with its citation and first provenance record."""
    village_id = content.resolve_village_id(db, body.village)
    data = body.model_dump(exclude={"village"})
    data["sources"] = [s.model_dump() for s in body.sources]
    data["village_id"] = village_id
    data["created_by"] = actor.id
    data["slug"] = content.unique_slug(db, HeritageEntry, content.slugify(body.title_en or body.title_local))
    with content.constraint_violations_as_409(db):
        entry = validation.create_item(
            db, ITEM_TYPE, data, actor=actor, source=body.source, note="created via API"
        )
    db.refresh(entry)
    return entry


@router.put("/{item_id}", response_model=HeritageEntryOut, summary="Edit an entry (new version, back to draft)")
def update_entry(
    item_id: uuid.UUID,
    body: HeritageUpdateIn,
    actor: Annotated[User, Depends(require_role("ambassador", "validator"))],
    db: Annotated[Session, Depends(get_db)],
) -> HeritageEntry:
    """Any edit bumps the version; an approved entry returns to ``draft`` and leaves the index."""
    validation.get_item(db, ITEM_TYPE, item_id)  # 404 before anything is written
    data = body.model_dump(exclude_unset=True, exclude={"note"})
    if "village" in data:
        data["village_id"] = content.resolve_village_id(db, data.pop("village"))
    if body.sources is not None:
        data["sources"] = [s.model_dump() for s in body.sources]
    if not data:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="nothing to update")
    with content.constraint_violations_as_409(db):
        entry = validation.update_item(db, ITEM_TYPE, item_id, data, actor=actor, note=body.note)
    db.refresh(entry)
    return entry


@router.get(
    "/{item_id}/provenance",
    response_model=list[ProvenanceOut],
    summary="Provenance trail of an entry (who did what, when, to which version)",
)
def entry_provenance(
    item_id: uuid.UUID,
    actor: Annotated[User, Depends(require_role("ambassador", "validator", "institution"))],
    db: Annotated[Session, Depends(get_db)],
) -> list:
    validation.get_item(db, ITEM_TYPE, item_id)
    return validation.provenance_for(db, ITEM_TYPE, item_id)
