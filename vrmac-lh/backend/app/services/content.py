"""Shared helpers for the content routers (heritage, listings, validation).

Kept small on purpose:

* slug-or-UUID resolution — the visitor variant applies ``validation.approved_only`` on top of the visitor
  role's row-level security (belt *and* braces), the staff variant ignores status;
* unique slug generation for new items;
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
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import Provenance
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
