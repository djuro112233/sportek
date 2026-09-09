"""Shared helpers for the content routers (heritage, listings, validation).

Kept small on purpose:

* slug-or-UUID resolution — the visitor variant applies ``validation.approved_only`` on top of the visitor
  role's row-level security (belt *and* braces), the staff variant ignores status;
* unique slug generation for new items;
* territory helpers — resolving the mandatory ``village`` (slug or id) of a content item, the
  ``?village=``/``?municipality=`` filters and the per-village count of *approved* items;
* a batched "first provenance record's source" lookup for the validation queue;
* a context manager turning database constraint violations into HTTP 409 instead of a 500.

Nothing here logs or returns personal data.
"""
from __future__ import annotations

import re
import unicodedata
import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager

from fastapi import HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import MUNICIPALITIES, HeritageEntry, Listing, Provenance, TrailSegment, Village
from . import validation

_SLUG_MAX = 100  # leaves room for a "-N" uniqueness suffix inside the 120-char slug column


def parse_uuid(value: str | uuid.UUID | None) -> uuid.UUID | None:
    """``UUID`` for a UUID-looking string, else ``None`` (the caller then treats the value as a slug)."""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


def request_id(request: Request | None) -> str:
    """Correlation id set by the request middleware (empty string outside a request)."""
    if request is None:
        return ""
    return str(getattr(request.state, "request_id", "") or "")


def _by_slug_or_id(model, slug_or_id: str):
    uid = parse_uuid(slug_or_id)
    stmt = select(model)
    return stmt.where(model.id == uid) if uid is not None else stmt.where(model.slug == slug_or_id)


def get_approved_by_slug_or_id(db: Session, model, slug_or_id: str):
    """Visitor-side lookup: approved rows only, 404 otherwise.

    The explicit filter is applied even though the visitor role cannot see other rows, so the gate does
    not depend on which session a caller happened to pass in.
    """
    item = db.scalars(validation.approved_only(_by_slug_or_id(model, slug_or_id), model)).first()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    return item


def get_any_by_slug_or_id(db: Session, model, slug_or_id: str):
    """Staff-side lookup regardless of status (application role), 404 when missing."""
    item = db.scalars(_by_slug_or_id(model, slug_or_id)).first()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    return item


def slugify(text: str) -> str:
    """ASCII slug: diacritics folded (č→c, đ→d …), lower-case, hyphen separated."""
    folded = unicodedata.normalize("NFKD", text).replace("đ", "d").replace("Đ", "D")
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    slug = re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")
    return slug[:_SLUG_MAX].rstrip("-") or "item"


def slug_taken(db: Session, model, slug: str, exclude_id: uuid.UUID | None = None) -> bool:
    stmt = select(model.id).where(model.slug == slug)
    if exclude_id is not None:
        stmt = stmt.where(model.id != exclude_id)
    return db.scalar(stmt) is not None


def unique_slug(db: Session, model, base: str) -> str:
    """``base``, or ``base-2``, ``base-3`` … until the slug is free."""
    base = base[:_SLUG_MAX].rstrip("-") or "item"
    candidate, n = base, 2
    while slug_taken(db, model, candidate):
        candidate = f"{base}-{n}"
        n += 1
    return candidate


# --- territory (every content item belongs to a village with its municipality) ----------------
#: The content models that carry a mandatory ``village_id`` and a validation status. The visitor
#: role may read all of them (row-level security limits it to ``status='approved'``).
VILLAGE_SCOPED_MODELS: tuple[type, ...] = (HeritageEntry, Listing, TrailSegment)


def canonical_municipality(value: str | None) -> str | None:
    """``"kotor"`` → ``"Kotor"``; ``None``/empty → ``None``; anything else → 422.

    Keeping the comparison out of the SQL means a typo in a query string is reported to the caller
    instead of silently returning an empty list.
    """
    if value is None or not value.strip():
        return None
    wanted = value.strip().casefold()
    for name in MUNICIPALITIES:
        if name.casefold() == wanted:
            return name
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=f"unknown municipality '{value}' (expected one of: {', '.join(MUNICIPALITIES)})",
    )


def get_village(db: Session, slug_or_id: str) -> Village:
    """Village by slug or id; 404 when it does not exist. Villages are public reference data."""
    village = db.scalars(_by_slug_or_id(Village, slug_or_id)).first()
    if village is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="village not found")
    return village


def resolve_village_id(db: Session, slug_or_id: str | uuid.UUID | None) -> uuid.UUID:
    """Village id for a slug or id supplied in a request body (422 when unknown or missing).

    Every heritage entry, listing and trail segment belongs to a village — a write that cannot name
    one is rejected rather than stored without a territory.
    """
    value = str(slug_or_id or "").strip()
    if not value:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="village is required (slug or id): every item belongs to a village",
        )
    village = db.scalars(_by_slug_or_id(Village, value)).first()
    if village is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"unknown village '{value}' (use a village slug or id from GET /api/villages)",
        )
    return village.id


def filter_by_territory(stmt, model, *, village: str | None = None, municipality: str | None = None):
    """Apply the ``?village=<slug|id>`` and ``?municipality=`` filters to a content query."""
    municipality = canonical_municipality(municipality)
    if village is None and municipality is None:
        return stmt
    stmt = stmt.join(Village, Village.id == model.village_id)
    if village is not None and village.strip():
        uid = parse_uuid(village)
        stmt = stmt.where(Village.id == uid) if uid is not None else stmt.where(Village.slug == village.strip())
    if municipality is not None:
        stmt = stmt.where(Village.municipality == municipality)
    return stmt


def approved_counts_by_village(db: Session) -> dict[uuid.UUID, dict[str, int]]:
    """Number of **approved** heritage entries, listings and trail segments per village id.

    Used for ``n_approved_items`` on ``GET /api/villages``. The query runs with whatever session is
    passed in; on the visitor session row-level security already hides everything else, and
    ``approved_only`` repeats the restriction explicitly.
    """
    counts: dict[uuid.UUID, dict[str, int]] = {}
    for model in VILLAGE_SCOPED_MODELS:
        key = model.__tablename__
        stmt = validation.approved_only(
            select(model.village_id, func.count()).group_by(model.village_id), model
        )
        for village_id, n in db.execute(stmt).all():
            counts.setdefault(village_id, {})[key] = int(n)
    return counts


def village_labels(db: Session, village_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, Village]:
    """``{village_id: Village}`` for the ids given (one query; unknown ids are simply absent)."""
    ids = {v for v in village_ids if v is not None}
    if not ids:
        return {}
    return {v.id: v for v in db.scalars(select(Village).where(Village.id.in_(ids)))}


def matches_village(village: Village | None, wanted: str | None) -> bool:
    """Does ``village`` match a ``?village=`` query value (slug or id)? Empty value matches all."""
    if wanted is None or not wanted.strip():
        return True
    if village is None:
        return False
    wanted = wanted.strip()
    uid = parse_uuid(wanted)
    return village.id == uid if uid is not None else village.slug == wanted


def first_provenance_source(
    db: Session, keys: Iterable[tuple[str, uuid.UUID]]
) -> dict[tuple[str, uuid.UUID], str]:
    """Source string of the *first* provenance record for every ``(item_type, item_id)`` in ``keys``."""
    keys = list(keys)
    if not keys:
        return {}
    rows = db.execute(
        select(Provenance.item_type, Provenance.item_id, Provenance.source)
        .where(Provenance.item_id.in_({k[1] for k in keys}))
        .order_by(Provenance.created_at, Provenance.version)
    ).all()
    out: dict[tuple[str, uuid.UUID], str] = {}
    for item_type, item_id, source in rows:
        out.setdefault((item_type, item_id), source)
    return out


@contextmanager
def constraint_violations_as_409(db: Session) -> Iterator[None]:
    """Run a write block and commit; a CHECK/UNIQUE/FK violation becomes a 409 (no stack trace, no data)."""
    try:
        yield
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="the change violates a data constraint"
        ) from exc
