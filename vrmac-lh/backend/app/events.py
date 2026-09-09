"""Event emission.

Every workflow step calls :func:`emit_event`; KPIs are derived from this stream only.

**Pseudonymisation.** No direct identifier is written: the actor's user id, the visitor's session id
and the device id are replaced by keyed HMAC pseudonyms (app/pseudonym.py). ``actor_gender`` is
copied only when the person *voluntarily self-reported* it — otherwise it stays null and the row is
excluded from gender-disaggregated KPIs.

**No personal data in properties.** A small deny-list rejects obvious personal-data keys, and free
text (questions, messages, notes) is never stored in an event.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from .models import EVENT_TYPES, GENDER_REPORTED, Event, User, Village
from .pseudonym import ACTOR, DEVICE, SESSION, pseudonymise

_FORBIDDEN_PROPERTY_KEYS = {
    "email", "e-mail", "mail", "name", "first_name", "last_name", "surname", "phone", "ip",
    "ip_address", "address", "user_id", "session_id", "device_id", "question", "message",
    "transcript", "answer",
}


def emit_event(
    db: Session,
    event_type: str,
    *,
    actor: User | None = None,
    actor_role: str | None = None,
    session_id: str | None = None,
    device_id: str | None = None,
    item_type: str | None = None,
    item_id: uuid.UUID | str | None = None,
    village: Village | None = None,
    village_id: uuid.UUID | None = None,
    municipality: str | None = None,
    lat: float | None = None,
    lng: float | None = None,
    occurred_at: datetime | None = None,
    **properties,
) -> Event:
    """Append one pseudonymised event. ``actor`` is used for its pseudonym and gender snapshot only."""
    if event_type not in EVENT_TYPES:
        raise ValueError(f"unknown event type: {event_type}")
    bad = _FORBIDDEN_PROPERTY_KEYS.intersection(k.lower() for k in properties)
    if bad:
        raise ValueError(f"event properties must not contain personal data keys: {sorted(bad)}")
    if isinstance(item_id, str):
        item_id = uuid.UUID(item_id)

    gender = None
    self_reported = False
    if actor is not None and actor.gender_self_reported and actor.gender in GENDER_REPORTED:
        gender = actor.gender
        self_reported = True

    if village is not None:
        village_id = village.id
        municipality = municipality or village.municipality

    ev = Event(
        event_type=event_type,
        actor_pseudonym=pseudonymise(ACTOR, actor.id) if actor else None,
        actor_role=actor_role or (actor.role if actor else ("visitor" if session_id else "system")),
        actor_gender=gender,
        gender_self_reported=self_reported,
        session_pseudonym=pseudonymise(SESSION, session_id),
        device_pseudonym=pseudonymise(DEVICE, device_id or session_id),
        item_type=item_type,
        item_id=item_id,
        village_id=village_id,
        municipality=municipality,
        lat=lat,
        lng=lng,
        properties=properties,
    )
    if occurred_at is not None:
        ev.occurred_at = occurred_at
    db.add(ev)
    db.flush()
    return ev
