"""Database engine and session management (SQLAlchemy 2.x).

SQLite is the default for dev/tests; Postgres (with pgvector) is used in docker-compose.
"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.models.base import Base

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def make_engine(database_url: str) -> Engine:
    # hide_parameters: SQL errors never carry bound values (a saved question, a session id) into logs
    kwargs: dict = {"future": True, "hide_parameters": True}
    if database_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in database_url:
            from sqlalchemy.pool import StaticPool

            kwargs["poolclass"] = StaticPool
    engine = create_engine(database_url, **kwargs)
    if database_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _record):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    return engine


def init_engine(database_url: str) -> Engine:
    """Create (or replace) the process-wide engine and create all tables."""
    global _engine, _SessionLocal
    _engine = make_engine(database_url)
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(_engine)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        from app.config import get_settings

        init_engine(get_settings().database_url)
    assert _engine is not None
    return _engine


def session_factory() -> sessionmaker[Session]:
    if _SessionLocal is None:
        get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency."""
    db = session_factory()()
    try:
        yield db
    finally:
        db.close()
