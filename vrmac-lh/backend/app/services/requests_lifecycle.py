"""Visitor-request lifecycle — **no bookings, no payments**.

A request is a message from a visitor to a provider. Confirming one is a *reply*, not a reservation:
nothing is held, nothing is charged, and the prototype never asks the visitor for a name, an e-mail
or a phone number. The visitor is identified only by the random ``session_id`` their browser keeps,
which is why that value is never shown to the host and never written to the event stream in the
clear (events carry a keyed pseudonym instead — app/pseudonym.py).

State machine::

    sent ──> confirmed ──> completed
      │  └──> refused       └──> cancelled
      └──> cancelled (visitor or host)
      │
    sent | confirmed ──> expired   (scheduler / `python -m app.cli expire-requests`)

Every transition emits the matching event from :data:`app.models.REQUEST_STATUS_EVENT`.
``expires_at`` is set when the request is created: the day after the requested date, or 30 days
after it was sent when no date was given — an unanswered request closes itself rather than sitting
in a provider's list forever.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..events import emit_event
from ..models import (
    REQUEST_STATUS_EVENT,
    REQUEST_STATUS_VALUES,
    Listing,
    User,
    Village,
    VisitorRequest,
    utcnow,
)

#: Statuses a request may still move away from.
OPEN_STATUSES: tuple[str, ...] = ("sent", "confirmed")
#: Statuses that close a request for good.
TERMINAL_STATUSES: tuple[str, ...] = ("completed", "cancelled", "refused", "expired")

#: target status -> statuses it may be reached from.
REQUEST_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "confirmed": ("sent",),
    "refused": ("sent",),
    "completed": ("confirmed",),
    "cancelled": ("sent", "confirmed"),
    "expired": ("sent", "confirmed"),
}

#: Statuses a host may set through /respond and /close, and the ones a visitor may set themselves.
HOST_RESPONSE_STATUSES: tuple[str, ...] = ("confirmed", "refused")
HOST_CLOSE_STATUSES: tuple[str, ...] = ("completed", "cancelled")
VISITOR_STATUSES: tuple[str, ...] = ("cancelled",)

DEFAULT_TTL_DAYS = 30  # an undated request expires 30 days after it was sent
REQUESTED_DATE_GRACE_DAYS = 1  # a dated request expires the day after the requested date


def default_expiry(created_at: datetime, requested_date: date | None) -> datetime:
    """``requested_date + 1 day`` (midnight UTC) when a date was given, else ``created_at + 30 days``."""
    if requested_date is not None:
        return datetime.combine(
            requested_date + timedelta(days=REQUESTED_DATE_GRACE_DAYS), time.min, tzinfo=timezone.utc
        )
    return created_at + timedelta(days=DEFAULT_TTL_DAYS)


def _village(db: Session, listing: Listing) -> Village | None:
    return db.get(Village, listing.village_id) if listing.village_id else None


def get_request(db: Session, request_id: uuid.UUID | str) -> VisitorRequest:
    if isinstance(request_id, str):
        try:
            request_id = uuid.UUID(request_id)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="request not found") from exc
    req = db.get(VisitorRequest, request_id)
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="request not found")
    return req


def listing_of(db: Session, req: VisitorRequest) -> Listing:
    listing = db.get(Listing, req.listing_id)
    if listing is None:  # pragma: no cover - the FK cascades, so this cannot normally happen
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="listing not found")
    return listing


def require_owner(listing: Listing, host: User) -> None:
    """A host may only act on requests for their **own** listings."""
    if listing.host_user_id != host.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="this request belongs to another provider's listing",
        )


def require_visitor(req: VisitorRequest, session_id: str) -> None:
    """A visitor may only cancel their own request (matching ``session_id``)."""
    if not session_id or req.visitor_session_id != session_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="this request belongs to another visitor session"
        )


def create_request(
    db: Session,
    *,
    listing: Listing,
    session_id: str,
    message: str,
    device_id: str | None = None,
    requested_date: date | None = None,
    party_size: int | None = None,
) -> VisitorRequest:
    """Store a request in ``sent``, set ``expires_at`` and emit ``request_sent``."""
    now = utcnow()
    req = VisitorRequest(
        listing_id=listing.id,
        visitor_session_id=session_id,
        message=message,
        requested_date=requested_date,
        party_size=party_size,
        status="sent",
        created_at=now,
        expires_at=default_expiry(now, requested_date),
    )
    db.add(req)
    db.flush()
    emit_event(
        db,
        "request_sent",
        session_id=session_id,
        device_id=device_id,
        item_type="listing",
        item_id=listing.id,
        village=_village(db, listing),
        category=listing.category,
        party_size=party_size,
        has_requested_date=requested_date is not None,
    )
    record_audit(
        db, user=None, action="request.create", resource_type="visitor_request", resource_id=str(req.id),
        detail={"listing": str(listing.id), "status": "sent"},
    )
    return req


def set_status(
    db: Session,
    req: VisitorRequest,
    to_status: str,
    *,
    actor: User | None = None,
    actor_kind: str = "system",
    reply: str = "",
    session_id: str | None = None,
    device_id: str | None = None,
) -> VisitorRequest:
    """Move a request to ``to_status`` and emit the matching event. 409 on an impossible step.

    ``actor_kind`` is ``host``, ``visitor`` or ``system`` and only ever reaches the event stream as
    a coarse label — the visitor's session id is passed as ``session_id`` for *visitor* actions, so
    it is pseudonymised, and it is never attached to a host's action.
    """
    if to_status not in REQUEST_STATUS_VALUES or to_status == "sent":
        raise HTTPException(status_code=400, detail=f"invalid request status '{to_status}'")
    allowed_from = REQUEST_TRANSITIONS[to_status]
    if req.status not in allowed_from:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"a request in status '{req.status}' cannot become '{to_status}'",
        )
    from_status = req.status
    now = utcnow()
    req.status = to_status
    if reply:
        req.host_reply = reply
    if to_status in HOST_RESPONSE_STATUSES:
        req.responded_at = now
    if to_status in TERMINAL_STATUSES:
        req.closed_at = now

    listing = listing_of(db, req)
    emit_event(
        db,
        REQUEST_STATUS_EVENT[to_status],
        actor=actor,
        actor_role=None if actor else ("visitor" if actor_kind == "visitor" else "system"),
        session_id=session_id,
        device_id=device_id,
        item_type="listing",
        item_id=listing.id,
        village=_village(db, listing),
        from_status=from_status,
        closed_by=actor_kind,
        category=listing.category,
    )
    record_audit(
        db, user=actor, action=f"request.{to_status}", resource_type="visitor_request",
        resource_id=str(req.id), detail={"from": from_status, "to": to_status, "by": actor_kind},
    )
    db.flush()
    return req


def expire_stale_requests(db: Session, *, now: datetime | None = None) -> dict[str, Any]:
    """Close every open request whose ``expires_at`` has passed, emitting ``request_expired``.

    Called by the scheduler and by ``python -m app.cli expire-requests``. Idempotent: a request that
    is already closed is never touched again.
    """
    now = now or utcnow()
    stale = list(
        db.scalars(
            select(VisitorRequest)
            .where(
                VisitorRequest.status.in_(OPEN_STATUSES),
                VisitorRequest.expires_at.is_not(None),
                VisitorRequest.expires_at < now,
            )
            .order_by(VisitorRequest.created_at)
        )
    )
    for req in stale:
        set_status(db, req, "expired", actor=None, actor_kind="system")
    open_left = db.scalar(
        select(VisitorRequest.id).where(VisitorRequest.status.in_(OPEN_STATUSES)).limit(1)
    )
    db.commit()
    return {
        "expired": len(stale),
        "ids": [str(r.id) for r in stale],
        "at": now.isoformat(),
        "open_requests_remaining": bool(open_left),
    }


# --- payloads ---------------------------------------------------------------------------------


#: Everything a visitor may learn about a listing they wrote to, once it is no longer published.
WITHDRAWN_SUMMARY_LOCAL = "Ovaj oglas trenutno nije objavljen."
WITHDRAWN_SUMMARY_EN = "This listing is not currently published."


def _listing_summary(
    listing: Listing, village: Village | None, *, for_visitor: bool = False
) -> dict[str, Any]:
    """Describe the listing behind a request.

    The visitor side runs on the owner database session (it is keyed by a session id, not by a
    login, so it cannot use the row-level-security role), which means the validation gate has to be
    applied here by hand: a listing that is not ``approved`` — a draft, one withdrawn for re-review,
    or one a validator rejected — must never reach an anonymous caller through this path. The
    visitor keeps their own request and is told plainly that the listing is not published.
    """
    published = listing.status == "approved"
    if for_visitor and not published:
        return {
            "id": str(listing.id),
            "slug": None,
            "title_local": WITHDRAWN_SUMMARY_LOCAL,
            "title_en": WITHDRAWN_SUMMARY_EN,
            "category": None,
            "status": "not_published",
            "village_slug": None,
            "village_name_local": None,
            "village_name_en": None,
            "municipality": None,
            "is_sample": None,
            "published": False,
        }
    return {
        "id": str(listing.id),
        "slug": listing.slug,
        "title_local": listing.title_local,
        "title_en": listing.title_en,
        "category": listing.category,
        "status": listing.status,
        "village_slug": village.slug if village else None,
        "village_name_local": village.name_local if village else None,
        "village_name_en": village.name_en if village else None,
        "municipality": village.municipality if village else None,
        "is_sample": bool(listing.is_sample),
        "published": published,
    }


def _base_payload(
    req: VisitorRequest, listing: Listing, village: Village | None, *, for_visitor: bool = False
) -> dict[str, Any]:
    summary = _listing_summary(listing, village, for_visitor=for_visitor)
    hide = for_visitor and not summary.get("published", True)
    return {
        "id": str(req.id),
        "listing_id": str(req.listing_id),
        "listing": summary,
        "village_slug": None if hide else (village.slug if village else None),
        "municipality": None if hide else (village.municipality if village else None),
        "status": req.status,
        "message": req.message,
        "requested_date": req.requested_date.isoformat() if req.requested_date else None,
        "party_size": req.party_size,
        "host_reply": req.host_reply,
        "created_at": req.created_at.isoformat() if req.created_at else None,
        "responded_at": req.responded_at.isoformat() if req.responded_at else None,
        "closed_at": req.closed_at.isoformat() if req.closed_at else None,
        "expires_at": req.expires_at.isoformat() if req.expires_at else None,
        "is_open": req.status in OPEN_STATUSES,
    }


def visitor_payload(req: VisitorRequest, listing: Listing, village: Village | None) -> dict[str, Any]:
    """What the visitor sees about their own request (they already hold their session id)."""
    payload = _base_payload(req, listing, village, for_visitor=True)
    payload["can_cancel"] = req.status in REQUEST_TRANSITIONS["cancelled"]
    return payload


def host_payload(req: VisitorRequest, listing: Listing, village: Village | None) -> dict[str, Any]:
    """What the provider sees. **Never** the visitor's session id — only the message and the dates."""
    payload = _base_payload(req, listing, village)
    payload["can_respond"] = req.status == "sent"
    payload["can_close"] = req.status == "confirmed"
    payload["no_booking_note"] = (
        "A confirmation is a message to the visitor, not a reservation: no booking and no payment."
    )
    return payload


def requests_for_session(db: Session, session_id: str) -> list[VisitorRequest]:
    return list(
        db.scalars(
            select(VisitorRequest)
            .where(VisitorRequest.visitor_session_id == session_id)
            .order_by(VisitorRequest.created_at.desc())
        )
    )


def requests_for_host(db: Session, host: User, *, status_filter: str | None = None) -> list[VisitorRequest]:
    stmt = (
        select(VisitorRequest)
        .join(Listing, Listing.id == VisitorRequest.listing_id)
        .where(Listing.host_user_id == host.id)
        .order_by(VisitorRequest.created_at.desc())
    )
    if status_filter:
        stmt = stmt.where(VisitorRequest.status == status_filter)
    return list(db.scalars(stmt))
