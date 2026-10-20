"""FastAPI dependencies shared by all routers."""

from __future__ import annotations

import hmac
from collections.abc import Generator

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session as DbSession

from app.config import Settings
from app.db import get_db as _get_db
from app.models import Session


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_db() -> Generator[DbSession, None, None]:
    yield from _get_db()


def require_admin(
    settings: Settings = Depends(get_settings_dep),
    x_admin_token: str | None = Header(default=None),
) -> None:
    if not settings.admin_token:
        raise HTTPException(status_code=404, detail="admin disabled")
    if not x_admin_token or not hmac.compare_digest(x_admin_token.encode(), settings.admin_token.encode()):
        raise HTTPException(status_code=403, detail="forbidden")


def require_consented_session(session_id: str, db: DbSession, settings: Settings | None = None) -> Session:
    """A session must exist, carry consent, and (when ``settings`` is given) consent to the
    current consent text; an older consent version answers 403 ``consent_version_outdated``
    so the client asks again."""
    sess = db.get(Session, session_id)
    if sess is None:
        raise HTTPException(status_code=403, detail="unknown session; give consent first")
    if not sess.consent_given:
        raise HTTPException(status_code=403, detail="consent required")
    if settings is not None and sess.consent_version != settings.consent_version:
        raise HTTPException(status_code=403, detail="consent_version_outdated")
    return sess
