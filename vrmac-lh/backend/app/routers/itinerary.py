"""/api/itinerary — the multi-village day plan.

Public and rate-limited. Candidate stops are **approved** heritage entries and listings with
coordinates, read through the visitor DB role plus ``approved_only``; the walk is a deterministic
greedy nearest-neighbour from the start point, and it deliberately ignores village boundaries, so a
plan naturally spans villages and, where content exists, municipalities. Every stop carries its
village, its municipality and its own Google Maps navigation link.

The response feeds the KPI stream through one ``itinerary_generated`` event whose ``multi_village``
property is read by K15 (share of itineraries covering more than one village).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db, get_public_db
from ..events import emit_event
from ..ratelimit import limiter
from ..services import content, geo

router = APIRouter(prefix="/api/itinerary", tags=["itinerary"])


class StartPoint(BaseModel):
    lat: float = Field(..., ge=-90.0, le=90.0)
    lng: float = Field(..., ge=-180.0, le=180.0)


class ItineraryIn(BaseModel):
    """What the visitor asks for: interests, available hours, where they start, which villages."""

    interests: list[str] = Field(default_factory=list, max_length=24)
    hours: float = Field(default=3.0, ge=1.0, le=float(geo.MAX_ITINERARY_HOURS))
    start: StartPoint | None = None
    villages: list[str] = Field(default_factory=list, max_length=24)
    municipality: str | None = Field(default=None, max_length=32)
    lang: str = Field(default="cnr", pattern="^(cnr|en)$")
    session_id: str | None = Field(default=None, max_length=64)
    device_id: str | None = Field(default=None, max_length=64)


@router.get("/interests", summary="Interest values accepted by POST /api/itinerary")
@limiter.limit(settings.rate_limit_public)
def interests(request: Request) -> JSONResponse:
    """Heritage kinds and listing categories, with the localised label used for ``why``."""
    return JSONResponse({
        "interests": [
            {
                "value": value,
                "group": "heritage" if value in geo.HERITAGE_KINDS else "listing",
                "label_local": geo.WHY_BY_KIND.get(value, geo.WHY_BY_KIND["other"])["cnr"],
                "label_en": geo.WHY_BY_KIND.get(value, geo.WHY_BY_KIND["other"])["en"],
            }
            for value in geo.INTEREST_VALUES
        ],
        "aliases": {k: list(v) for k, v in geo.INTEREST_ALIASES.items()},
        "max_hours": geo.MAX_ITINERARY_HOURS,
        "default_start": {"lat": geo.DEFAULT_START[0], "lng": geo.DEFAULT_START[1], "village_slug": "donja-lastva"},
    })


@router.post("", summary="Plan a walking itinerary across the villages of Vrmac")
@limiter.limit(settings.rate_limit_public)
def create_itinerary(
    request: Request,
    payload: ItineraryIn,
    db: Session = Depends(get_public_db),
    write_db: Session = Depends(get_db),
) -> JSONResponse:
    """Greedy nearest-neighbour plan within ``hours``; emits ``itinerary_generated``."""
    _, unknown = geo.normalise_interests(payload.interests)
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"unknown interests: {', '.join(unknown)} "
                f"(expected values from GET /api/itinerary/interests: {', '.join(geo.INTEREST_VALUES)})"
            ),
        )
    municipality = content.canonical_municipality(payload.municipality)  # 422 on a typo
    for village in payload.villages:
        content.get_village(db, village)  # 404 when a requested village does not exist

    candidates = geo.itinerary_candidates(
        db, payload.interests, villages=payload.villages, municipality=municipality
    )
    start = (payload.start.lat, payload.start.lng) if payload.start else geo.DEFAULT_START
    result = geo.plan_itinerary(candidates, start, payload.hours, payload.lang)
    result["interests"] = list(payload.interests)
    result["n_candidates"] = len(candidates)
    result["prototype_note"] = geo.COORDS_NOTE["en" if payload.lang == "en" else "cnr"]

    by_slug = geo.villages_by_slug(db)
    anchor = next((by_slug.get(s) for s in result["villages"] if by_slug.get(s)), None)
    emit_event(
        write_db,
        "itinerary_generated",
        session_id=payload.session_id,
        device_id=payload.device_id,
        village=anchor,
        n_stops=len(result["stops"]),
        hours=float(payload.hours),
        total_km=result["total_km"],
        est_hours=result["est_hours"],
        interests=sorted({i.strip().lower() for i in payload.interests if i and i.strip()}),
        multi_village=result["multi_village"],
        multi_municipality=result["multi_municipality"],
        n_villages=len(result["villages"]),
        lang=payload.lang,
    )
    write_db.commit()
    return JSONResponse(result)
