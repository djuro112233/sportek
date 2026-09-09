"""/api/listings — provider offers (accommodation, food, guiding, craft…). No bookings, no payments.

**Validation gate.** The public list and detail read through the visitor DB role (row-level
security → approved rows only) *and* filter ``status == 'approved'`` explicitly. ``GET /mine`` is
the host's own view: it returns every status, but only the caller's own listings.

**Territory.** Every listing belongs to a village; ``?village=`` and ``?municipality=`` filter on it.

**Host-confirmed fields.** ``price_*``, ``season_*``, ``capacity`` and ``accessibility_*`` are
entered and confirmed by the host — a model never fills them. ``confirmed_fields`` records what the
host actually confirmed; an edit through this router keeps that list under the host's control.

A listing may not be approved without a consent record — the rule lives in
``services.validation.transition`` and is exercised by ``tests/test_validation_gate.py``.
"""
from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import require_role
from ..config import settings
from ..db import get_db, get_public_db
from ..models import Listing, User
from ..ratelimit import limiter
from ..schemas import ListingOut, ProvenanceOut
from ..services import content, validation

router = APIRouter(prefix="/api/listings", tags=["listings"])

ListingCategory = Literal[
    "accommodation", "food", "guiding", "craft", "experience", "transport", "other"
]

ITEM_TYPE = "listing"


class ListingUpdateIn(BaseModel):
    """Partial edit by the owning host (or an ambassador helping them).

    Every structured field is optional and **host-entered**; sending one is the host confirming it.
    Any edit bumps the version and returns the listing to ``draft`` for re-validation.
    """

    village: str | None = None
    category: ListingCategory | None = None
    title_local: str | None = Field(default=None, min_length=1, max_length=255)
    title_en: str | None = Field(default=None, max_length=255)
    description_local: str | None = None
    description_en: str | None = None
    price_min: float | None = Field(default=None, ge=0)
    price_max: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    price_note_local: str | None = None
    price_note_en: str | None = None
    season_from: int | None = Field(default=None, ge=1, le=12)
    season_to: int | None = Field(default=None, ge=1, le=12)
    season_all_year: bool | None = None
    capacity: int | None = Field(default=None, ge=0)
    accessibility_step_free: bool | None = None
    accessibility_note_local: str | None = None
    accessibility_note_en: str | None = None
    confirmed_fields: list[str] | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    coords_approximate: bool | None = None
    photo_url: str | None = None
    note: str = Field(default="", max_length=2000, description="why the listing was edited")


# --- public (approved only) -------------------------------------------------------------------
@router.get("", response_model=list[ListingOut], summary="Approved listings")
@limiter.limit(settings.rate_limit_public)
def list_listings(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_public_db)],
    category: Annotated[str | None, Query(description="accommodation | food | guiding | …")] = None,
    village: Annotated[str | None, Query(description="village slug or id")] = None,
    municipality: Annotated[str | None, Query(description="Tivat | Kotor")] = None,
) -> list[Listing]:
    """Approved listings only — visitor DB role (RLS) plus the explicit status filter."""
    stmt = validation.approved_only(select(Listing), Listing)
    if category:
        stmt = stmt.where(Listing.category == category)
    stmt = content.filter_by_territory(stmt, Listing, village=village, municipality=municipality)
    return list(db.scalars(stmt.order_by(Listing.slug)))


# NOTE: /mine must be declared before /{slug_or_id}, otherwise "mine" is read as a slug.
@router.get("/mine", response_model=list[ListingOut], summary="The host's own listings (every status)")
def my_listings(
    actor: Annotated[User, Depends(require_role("host"))],
    db: Annotated[Session, Depends(get_db)],
) -> list[Listing]:
    """A host sees their own drafts and rejected listings — nobody else's, whatever the status."""
    stmt = select(Listing).where(Listing.host_user_id == actor.id).order_by(Listing.created_at)
    return list(db.scalars(stmt))


@router.get("/{slug_or_id}", response_model=ListingOut, summary="One approved listing")
@limiter.limit(settings.rate_limit_public)
def get_listing(
    request: Request,
    response: Response,
    slug_or_id: str,
    db: Annotated[Session, Depends(get_public_db)],
) -> Listing:
    """404 unless the listing is approved."""
    return content.get_approved_by_slug_or_id(db, Listing, slug_or_id)


# --- host / ambassador ---------------------------------------------------------------------------
def _owned_listing(db: Session, item_id: uuid.UUID, actor: User) -> Listing:
    """The listing, with the ownership rule: a host may only touch their own."""
    listing = validation.get_item(db, ITEM_TYPE, item_id)
    if actor.role == "host" and listing.host_user_id != actor.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="a host may only act on their own listings"
        )
    return listing


@router.put("/{item_id}", response_model=ListingOut, summary="Edit a listing (new version, back to draft)")
def update_listing(
    item_id: uuid.UUID,
    body: ListingUpdateIn,
    actor: Annotated[User, Depends(require_role("host", "ambassador"))],
    db: Annotated[Session, Depends(get_db)],
) -> Listing:
    """Edit and re-submit: the listing leaves the public site until a validator approves it again."""
    _owned_listing(db, item_id, actor)
    data = body.model_dump(exclude_unset=True, exclude={"note"})
    if "village" in data:
        data["village_id"] = content.resolve_village_id(db, data.pop("village"))
    if not data:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="nothing to update")
    with content.constraint_violations_as_409(db):
        listing = validation.update_item(db, ITEM_TYPE, item_id, data, actor=actor, note=body.note)
    db.refresh(listing)
    return listing


@router.get(
    "/{item_id}/provenance",
    response_model=list[ProvenanceOut],
    summary="Provenance trail of a listing",
)
def listing_provenance(
    item_id: uuid.UUID,
    actor: Annotated[User, Depends(require_role("host", "ambassador", "validator", "institution"))],
    db: Annotated[Session, Depends(get_db)],
) -> list:
    _owned_listing(db, item_id, actor)
    return validation.provenance_for(db, ITEM_TYPE, item_id)
