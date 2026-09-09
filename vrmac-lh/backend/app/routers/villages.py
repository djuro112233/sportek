"""/api/villages — the territory: the villages of the Vrmac plateau on both sides of the ridge.

Villages are **reference data**: names, municipality (Tivat or Kotor), ridge side and *approximate*
coordinates, plus the source of those facts. They are the one table the visitor DB role may read in
full (db.py ``PUBLIC_REFERENCE_TABLES``), because a village row carries no claim of its own — every
claim about a village lives in a heritage entry that passes the validation gate.

Two flags travel with each village so the UI can mark what is not yet checked:

* ``facts_verified`` — false while the village's public sources could not be confirmed;
* ``verification_note`` — what exactly has to be verified.

``n_approved_items`` counts the *approved* heritage entries, listings and trail segments of the
village, so a client can tell an empty village from a village whose content is still in the queue.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_public_db
from ..models import Village
from ..ratelimit import limiter
from ..schemas import VillageOut
from ..services import content

router = APIRouter(prefix="/api/villages", tags=["villages"])


class VillageCounts(BaseModel):
    """Approved items of a village, by type (the validation gate applies to all three)."""

    heritage_entries: int = 0
    listings: int = 0
    trail_segments: int = 0


class VillageWithCounts(VillageOut):
    """``VillageOut`` plus the approved-content counters of the contract."""

    n_approved_items: int = 0
    counts: VillageCounts = VillageCounts()


def _with_counts(village: Village, counts: dict[str, int]) -> VillageWithCounts:
    per_type = VillageCounts(**counts)
    return VillageWithCounts(
        **VillageOut.model_validate(village).model_dump(),
        n_approved_items=per_type.heritage_entries + per_type.listings + per_type.trail_segments,
        counts=per_type,
    )


@router.get(
    "",
    response_model=list[VillageWithCounts],
    summary="Villages of the territory (public reference data) with their approved-item counts",
)
@limiter.limit(settings.rate_limit_public)
def list_villages(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_public_db)],
    municipality: Annotated[str | None, Query(description="Tivat | Kotor")] = None,
) -> list[VillageWithCounts]:
    """Every village, optionally restricted to one municipality.

    Unverified villages are **not** hidden: they are returned with ``facts_verified=false`` and a
    ``verification_note``, which is what the UI needs in order to mark them.
    """
    stmt = select(Village)
    wanted = content.canonical_municipality(municipality)
    if wanted is not None:
        stmt = stmt.where(Village.municipality == wanted)
    villages = list(db.scalars(stmt.order_by(Village.municipality, Village.name_local)))
    counts = content.approved_counts_by_village(db)
    return [_with_counts(v, counts.get(v.id, {})) for v in villages]


@router.get(
    "/{slug_or_id}",
    response_model=VillageWithCounts,
    summary="One village by slug or id, with its approved-item counts",
)
@limiter.limit(settings.rate_limit_public)
def get_village(
    request: Request,
    response: Response,
    slug_or_id: str,
    db: Annotated[Session, Depends(get_public_db)],
) -> VillageWithCounts:
    village = content.get_village(db, slug_or_id)
    counts = content.approved_counts_by_village(db)
    return _with_counts(village, counts.get(village.id, {}))
