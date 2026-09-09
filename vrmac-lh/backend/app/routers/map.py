"""/api/map — the interactive map of the territory and the "how to get there" deep links.

Both endpoints are public and rate-limited. ``/features`` reads through the visitor DB role
(row-level security → approved rows only) *and* the explicit ``approved_only`` filter inside
``services.geo``; ``/directions`` is a pure URL builder — the server never calls Google, so no
visitor coordinate and no API key ever leaves this process.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_public_db
from ..ratelimit import limiter
from ..services import geo

router = APIRouter(prefix="/api/map", tags=["map"])


def _check_item_type(item_type: str | None) -> str | None:
    """``?item_type=`` must name a mappable item type; a typo is reported, not silently ignored."""
    if item_type is None or not item_type.strip():
        return None
    value = item_type.strip()
    if value not in geo.MAP_ITEM_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"unknown item_type '{item_type}' (expected one of: {', '.join(geo.MAP_ITEM_TYPES)})",
        )
    return value


@router.get("/features", summary="Approved map features (GeoJSON FeatureCollection)")
@limiter.limit(settings.rate_limit_public)
def map_features(
    request: Request,
    village: str | None = Query(default=None, description="village slug or id"),
    municipality: str | None = Query(default=None, description="Tivat or Kotor"),
    item_type: str | None = Query(default=None, description="heritage_entry | listing | trail_segment"),
    db: Session = Depends(get_public_db),
) -> JSONResponse:
    """Points for approved heritage entries and listings, LineStrings for approved trail segments.

    Every feature carries its village and municipality, the ``coords_approximate`` flag and both
    Google Maps navigation links. Trail features additionally carry the GPX URL, the villages they
    connect and the latest **approved** condition report.
    """
    collection = geo.features(
        db, village=village, municipality=municipality, item_type=_check_item_type(item_type)
    )
    return JSONResponse(collection, media_type="application/geo+json")


@router.get("/directions", summary="Google Maps navigation deep link for a destination")
@limiter.limit(settings.rate_limit_public)
def directions(
    request: Request,
    lat: float = Query(..., ge=-90.0, le=90.0, description="destination latitude (WGS84)"),
    lng: float = Query(..., ge=-180.0, le=180.0, description="destination longitude (WGS84)"),
    mode: str = Query("walking", pattern="^(walking|driving)$", description="walking | driving"),
) -> JSONResponse:
    """The deep link the "how to get there" button opens — real Google routing, no API key."""
    return JSONResponse({
        "url": geo.directions_url(lat, lng, mode),
        "mode": mode,
        "destination": {"lat": lat, "lng": lng},
        "provider": "google-maps-deeplink",
        "maps_provider": settings.maps_provider,
    })
