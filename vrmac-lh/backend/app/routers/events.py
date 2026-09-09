"""/api/events — the one event a visitor's browser may write.

The public endpoint accepts **``visit_recorded`` only**: an anonymous "I am here" ping used for the
aggregated heat map. Anything else is rejected with 422 — application events (answers, itineraries,
requests, onboarding steps) are emitted server-side by the workflow that performs them, never by a
client, so nobody can inflate a KPI from outside.

Nothing is stored in the clear: the browser's random ``session_id`` and ``device_id`` are replaced
by keyed HMAC pseudonyms in ``app/events.py`` before the row is written, and the response echoes no
identifier back.
"""
from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..events import emit_event
from ..models import EVENT_TYPES, ITEM_TYPES, Village
from ..ratelimit import limiter
from ..services.geo import haversine_m

router = APIRouter(prefix="/api/events", tags=["events"])

#: the only event type a client may post
PUBLIC_EVENT_TYPES: tuple[str, ...] = ("visit_recorded",)
#: a visit farther than this from every known village is recorded without a village
VILLAGE_MATCH_RADIUS_M = 5000.0


class VisitEventIn(BaseModel):
    """A visitor's position ping. No free text, no identifier that survives in the clear."""

    event_type: Literal["visit_recorded"]
    session_id: str = Field(min_length=1, max_length=128)
    device_id: str | None = Field(default=None, max_length=128)
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    item_type: str | None = None
    item_id: uuid.UUID | None = None

    @field_validator("item_type")
    @classmethod
    def _known_item_type(cls, v: str | None) -> str | None:
        if v is not None and v not in ITEM_TYPES:
            raise ValueError(f"item_type must be one of {', '.join(ITEM_TYPES)}")
        return v


def nearest_village(db: Session, lat: float, lng: float) -> Village | None:
    """Closest village within ``VILLAGE_MATCH_RADIUS_M`` — used to give the event a territory."""
    best: tuple[float, Village] | None = None
    for v in db.scalars(select(Village)):
        if v.lat is None or v.lng is None:
            continue
        d = haversine_m((lat, lng), (v.lat, v.lng))
        if best is None or d < best[0]:
            best = (d, v)
    if best is None or best[0] > VILLAGE_MATCH_RADIUS_M:
        return None
    return best[1]


@router.post("", status_code=status.HTTP_201_CREATED, summary="Record an anonymous visit (public)")
@limiter.limit(settings.rate_limit_public)
def record_visit(request: Request, response: Response, body: VisitEventIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Write one pseudonymised ``visit_recorded`` event. Only aggregates of these are ever shown."""
    village = nearest_village(db, body.lat, body.lng)
    emit_event(
        db,
        "visit_recorded",
        session_id=body.session_id,
        device_id=body.device_id,
        item_type=body.item_type,
        item_id=body.item_id,
        village=village,
        lat=body.lat,
        lng=body.lng,
    )
    db.commit()
    return {
        "status": "recorded",
        "event_type": "visit_recorded",
        "village": village.slug if village else None,
        "municipality": village.municipality if village else None,
        "pseudonymised": True,
    }


@router.get("/types", summary="Event types emitted by the platform (public)")
@limiter.limit(settings.rate_limit_public)
def event_types(request: Request, response: Response) -> list[str]:
    """Every event type in the stream; only ``visit_recorded`` may be posted by a client."""
    return list(EVENT_TYPES)
