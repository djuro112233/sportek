"""Event emission. Every workflow step calls ``emit_event``; KPIs are derived from this stream only.

Events carry no PII: no e-mail, no names, no IP addresses. Person-level events snapshot the
actor's ``sex`` so KPIs can be disaggregated without joining back to accounts.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from .models import EVENT_TYPES, Event, User

_FORBIDDEN_PROPERTY_KEYS = {"email", "e-mail", "name", "first_name", "last_name", "phone", "ip", "address"}


def emit_event(
    db: Session,
    event_type: str,
    *,
    actor: User | None = None,
    actor_role: str | None = None,
    session_id: str | None = None,
    item_type: str | None = None,
    item_id: uuid.UUID | str | None = None,
    lat: float | None = None,
    lng: float | None = None,
    occurred_at: datetime | None = None,
    **properties,
) -> Event:
    if event_type not in EVENT_TYPES:
        raise ValueError(f"unknown event type: {event_type}")
    bad = _FORBIDDEN_PROPERTY_KEYS.intersection(k.lower() for k in properties)
    if bad:
        raise ValueError(f"event properties must not contain personal data keys: {sorted(bad)}")
    if isinstance(item_id, str):
        item_id = uuid.UUID(item_id)
    ev = Event(
        event_type=event_type,
        actor_user_id=actor.id if actor else None,
        actor_role=actor_role or (actor.role if actor else ("visitor" if session_id else "system")),
        actor_sex=actor.sex if actor else None,
        session_id=session_id,
        item_type=item_type,
        item_id=item_id,
        lat=lat,
        lng=lng,
        properties=properties,
    )
    if occurred_at is not None:
        ev.occurred_at = occurred_at
    db.add(ev)
    db.flush()
    return ev
