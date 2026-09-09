"""/api/trails — GPX trail segments and geotagged condition reports.

Reads are public and go through the visitor DB role (row-level security → approved rows only) *and*
``services.validation.approved_only``: a draft segment is a 404 and a draft report is invisible, so
the map never shows an unvalidated closure.

A visitor may submit a condition report without an account (a random ``session_id``/``device_id``
kept in the browser, pseudonymised in the event stream). The report is created as a **draft** through
the same validation gate as every other content item and is answered with ``202 Accepted`` and a
localised "visible after validation" message — it appears publicly only once a validator approves it.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import get_optional_user
from ..config import settings
from ..db import get_db, get_public_db
from ..events import emit_event
from ..models import CONDITION_VALUES, TrailSegment, User, Village
from ..ratelimit import limiter
from ..services import content, geo, validation

router = APIRouter(prefix="/api/trails", tags=["trails"])

ACCEPTED_MESSAGE = {
    "cnr": (
        "Hvala. Prijava je zabilježena i biće vidljiva na karti tek nakon provjere validatora."
    ),
    "en": (
        "Thank you. Your report has been recorded and becomes visible on the map only after a "
        "validator has checked it."
    ),
}


class TrailReportIn(BaseModel):
    """A geotagged condition report: which segment (path), which point (lat/lng), what state."""

    lat: float = Field(..., ge=-90.0, le=90.0)
    lng: float = Field(..., ge=-180.0, le=180.0)
    condition: str = Field(..., pattern="^(good|caution|blocked)$")
    note: str = Field(default="", max_length=1000)
    lang: str = Field(default="cnr", pattern="^(cnr|en)$")
    session_id: str | None = Field(default=None, max_length=64)
    device_id: str | None = Field(default=None, max_length=64)


@router.get("", summary="Approved trail segments with their latest condition report")
@limiter.limit(settings.rate_limit_public)
def list_trails(
    request: Request,
    village: str | None = Query(default=None, description="village slug or id (matches any village the trail connects)"),
    municipality: str | None = Query(default=None, description="Tivat or Kotor"),
    db: Session = Depends(get_public_db),
) -> list[dict]:
    """Every approved segment, its ``village_slugs`` and its latest **approved** condition report."""
    by_id = geo.villages_by_id(db)
    return [
        geo.trail_payload(db, seg, by_id)
        for seg in geo.approved_segments(db, village=village, municipality=municipality)
    ]


@router.get("/{slug_or_id}", summary="One approved trail segment with its approved reports")
@limiter.limit(settings.rate_limit_public)
def get_trail(request: Request, slug_or_id: str, db: Session = Depends(get_public_db)) -> dict:
    """404 unless the segment is approved. ``reports`` are approved reports, newest first."""
    seg = content.get_approved_by_slug_or_id(db, TrailSegment, slug_or_id)
    return geo.trail_payload(db, seg, geo.villages_by_id(db), with_reports=True)


@router.get("/{slug_or_id}/gpx", summary="GPX track of an approved trail segment")
@limiter.limit(settings.rate_limit_public)
def get_trail_gpx(request: Request, slug_or_id: str, db: Session = Depends(get_public_db)) -> Response:
    """The surveyed seed file when the segment references one, otherwise a track generated from the
    stored geometry. Both are GPX 1.1 and both are approximate in this prototype."""
    seg = content.get_approved_by_slug_or_id(db, TrailSegment, slug_or_id)
    document, origin = geo.gpx_for_segment(seg)
    return Response(
        content=document,
        media_type=geo.GPX_MEDIA_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="{seg.slug}.gpx"',
            "X-GPX-Origin": origin,
            "X-Coords-Approximate": "true" if seg.coords_approximate else "false",
        },
    )


@router.post(
    "/{slug_or_id}/reports",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit a geotagged condition report (goes to the validation queue)",
)
@limiter.limit(settings.rate_limit_public)
def submit_report(
    request: Request,
    slug_or_id: str,
    payload: TrailReportIn,
    public_db: Session = Depends(get_public_db),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
) -> dict:
    """Create the report as a **draft** and emit ``trail_report`` (pseudonymised, with coordinates).

    Anyone may report: an anonymous visitor identified only by a random client id, or a signed-in
    host/ambassador/validator. Nothing is published until the validation gate approves it.
    """
    segment = content.get_approved_by_slug_or_id(public_db, TrailSegment, slug_or_id)
    if not payload.session_id and user is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="a session_id is required for anonymous reports",
        )
    village = db.get(Village, segment.village_id)
    note = payload.note.strip()
    data = {
        "segment_id": segment.id,
        "village_id": segment.village_id,  # the report inherits the segment's village
        "lat": payload.lat,
        "lng": payload.lng,
        "condition": payload.condition,
        "note_local": note if payload.lang != "en" else "",
        "note_en": note if payload.lang == "en" else "",
        "reporter_user_id": user.id if user else None,
        "reporter_role": user.role if user else "visitor",
        "is_sample": False,
    }
    with content.constraint_violations_as_409(db):
        report = validation.create_item(
            db,
            "trail_report",
            data,
            actor=user,
            source=f"condition report submitted from the visitor app ({payload.condition})",
            note="awaiting validation",
        )
        emit_event(
            db,
            "trail_report",
            actor=user,
            session_id=payload.session_id,
            device_id=payload.device_id,
            item_type="trail_report",
            item_id=report.id,
            village=village,
            lat=payload.lat,
            lng=payload.lng,
            condition=payload.condition,
            report_id=str(report.id),
            segment_slug=segment.slug,
        )
    return {
        "id": str(report.id),
        "status": "draft",
        "segment_id": str(segment.id),
        "segment_slug": segment.slug,
        "condition": payload.condition,
        "village_slug": village.slug if village else None,
        "municipality": village.municipality if village else None,
        "visible_after_validation": True,
        "message": ACCEPTED_MESSAGE.get(payload.lang, ACCEPTED_MESSAGE["en"]),
        "conditions": list(CONDITION_VALUES),
    }
