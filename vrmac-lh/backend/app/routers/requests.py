"""/api/requests — a visitor's message to a provider. No bookings, no payments.

Confirming a request is a *reply*, not a reservation. The visitor stays anonymous: they send the
random ``session_id`` their browser keeps, the host never sees it, and the event stream stores only
a keyed pseudonym of it.

* the visitor may list and cancel **their own** requests (matching ``session_id``);
* a host may only see and answer requests for **their own** listings (403 otherwise);
* every step emits the matching event from ``models.REQUEST_STATUS_EVENT``;
* overdue requests are closed as ``expired`` by ``services.requests_lifecycle.expire_stale_requests``
  (scheduler / ``python -m app.cli expire-requests``).
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import require_role
from ..config import settings
from ..db import get_db, get_public_db
from ..models import Listing, User, Village
from ..ratelimit import limiter
from ..services import content, requests_lifecycle as lifecycle

router = APIRouter(prefix="/api/requests", tags=["requests"])

SENT_MESSAGE = {
    "cnr": (
        "Poruka je poslata domaćinu. Ovo nije rezervacija: domaćin odgovara porukom, bez plaćanja."
    ),
    "en": (
        "Your message has been sent to the provider. This is not a booking: the provider answers "
        "with a message, and nothing is paid here."
    ),
}


class RequestIn(BaseModel):
    listing_id: str = Field(..., max_length=120, description="listing id or slug")
    message: str = Field(..., min_length=1, max_length=2000)
    requested_date: date | None = None
    party_size: int | None = Field(default=None, ge=1, le=50)
    session_id: str = Field(..., min_length=8, max_length=64)
    device_id: str | None = Field(default=None, max_length=64)
    lang: str = Field(default="cnr", pattern="^(cnr|en)$")


class RespondIn(BaseModel):
    status: str = Field(..., pattern="^(confirmed|refused)$")
    reply: str = Field(default="", max_length=2000)


class CloseIn(BaseModel):
    status: str = Field(..., pattern="^(completed|cancelled)$")
    note: str = Field(default="", max_length=2000)


class CancelIn(BaseModel):
    session_id: str = Field(..., min_length=8, max_length=64)


def _village(db: Session, listing: Listing) -> Village | None:
    return db.get(Village, listing.village_id) if listing.village_id else None


@router.post("", status_code=status.HTTP_201_CREATED, summary="Send a request to a provider")
@limiter.limit(settings.rate_limit_public)
def send_request(
    request: Request,
    payload: RequestIn,
    public_db: Session = Depends(get_public_db),
    db: Session = Depends(get_db),
) -> dict:
    """404 unless the listing is approved — a draft listing cannot receive requests."""
    approved = content.get_approved_by_slug_or_id(public_db, Listing, payload.listing_id)
    listing = db.get(Listing, approved.id)
    with content.constraint_violations_as_409(db):
        req = lifecycle.create_request(
            db,
            listing=listing,
            session_id=payload.session_id,
            device_id=payload.device_id,
            message=payload.message.strip(),
            requested_date=payload.requested_date,
            party_size=payload.party_size,
        )
    out = lifecycle.visitor_payload(req, listing, _village(db, listing))
    out["message_to_visitor"] = SENT_MESSAGE.get(payload.lang, SENT_MESSAGE["en"])
    out["no_booking"] = True
    return out


@router.get("/mine", summary="The visitor's own requests")
@limiter.limit(settings.rate_limit_public)
def my_requests(
    request: Request,
    session_id: str = Query(..., min_length=8, max_length=64),
    db: Session = Depends(get_db),
) -> list[dict]:
    """Only requests whose ``visitor_session_id`` matches exactly."""
    out = []
    for req in lifecycle.requests_for_session(db, session_id):
        listing = lifecycle.listing_of(db, req)
        out.append(lifecycle.visitor_payload(req, listing, _village(db, listing)))
    return out


@router.get("/host", summary="Requests for the signed-in host's own listings")
def host_requests(
    status_filter: str | None = Query(default=None, alias="status", max_length=16),
    host: User = Depends(require_role("host")),
    db: Session = Depends(get_db),
) -> list[dict]:
    """The host-facing view: message, date and party size — never the visitor's session id."""
    out = []
    for req in lifecycle.requests_for_host(db, host, status_filter=status_filter):
        listing = lifecycle.listing_of(db, req)
        out.append(lifecycle.host_payload(req, listing, _village(db, listing)))
    return out


@router.post("/{request_id}/respond", summary="Host confirms or refuses a request")
def respond(
    request_id: str,
    payload: RespondIn,
    host: User = Depends(require_role("host")),
    db: Session = Depends(get_db),
) -> dict:
    """A confirmation is a message, not a reservation. 403 for another provider's listing."""
    req = lifecycle.get_request(db, request_id)
    listing = lifecycle.listing_of(db, req)
    lifecycle.require_owner(listing, host)
    with content.constraint_violations_as_409(db):
        lifecycle.set_status(
            db, req, payload.status, actor=host, actor_kind="host", reply=payload.reply.strip()
        )
    return lifecycle.host_payload(req, listing, _village(db, listing))


@router.post("/{request_id}/close", summary="Host closes a confirmed request (completed / cancelled)")
def close(
    request_id: str,
    payload: CloseIn,
    host: User = Depends(require_role("host")),
    db: Session = Depends(get_db),
) -> dict:
    req = lifecycle.get_request(db, request_id)
    listing = lifecycle.listing_of(db, req)
    lifecycle.require_owner(listing, host)
    with content.constraint_violations_as_409(db):
        lifecycle.set_status(
            db, req, payload.status, actor=host, actor_kind="host", reply=payload.note.strip()
        )
    return lifecycle.host_payload(req, listing, _village(db, listing))


@router.post("/{request_id}/cancel", summary="Visitor cancels their own request")
@limiter.limit(settings.rate_limit_public)
def cancel(
    request: Request,
    request_id: str,
    payload: CancelIn,
    db: Session = Depends(get_db),
) -> dict:
    """403 unless the request carries exactly this ``session_id``."""
    req = lifecycle.get_request(db, request_id)
    lifecycle.require_visitor(req, payload.session_id)
    listing = lifecycle.listing_of(db, req)
    with content.constraint_violations_as_409(db):
        lifecycle.set_status(
            db, req, "cancelled", actor=None, actor_kind="visitor", session_id=payload.session_id
        )
    return lifecycle.visitor_payload(req, listing, _village(db, listing))
