"""FastAPI dependencies shared by all routers."""

from __future__ import annotations

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
    if x_admin_token != settings.admin_token:
        raise HTTPException(status_code=403, detail="forbidden")


def require_consented_session(session_id: str, db: DbSession) -> Session:
    """A session must exist and carry consent before any question is processed."""
    sess = db.get(Session, session_id)
    if sess is None:
        raise HTTPException(status_code=403, detail="unknown session; give consent first")
    if not sess.consent_given:
        raise HTTPException(status_code=403, detail="consent required")
    return sess
