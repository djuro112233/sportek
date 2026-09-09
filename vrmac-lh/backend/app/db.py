"""Database engines, sessions and schema initialisation.

Two engines:
  * ``engine``        — application role (owner of the tables, full access; used by authenticated
                        endpoints, jobs and the seed loader).
  * ``public_engine`` — the *visitor* role. It can only SELECT from the content tables, and
                        PostgreSQL row-level security restricts every SELECT to ``status='approved'``.
                        Every visitor-facing endpoint must use ``get_public_db``; this is the
                        data-layer half of the validation gate (the other half is the explicit
                        ``status == approved`` filter in the services).
"""
from __future__ import annotations

import re
from collections.abc import Generator

from sqlalchemy import create_engine, make_url, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)

_public_url = make_url(settings.database_url).set(
    username=settings.public_db_user, password=settings.public_db_password
)
public_engine = create_engine(_public_url, pool_pre_ping=True, future=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
PublicSessionLocal = sessionmaker(bind=public_engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_public_db() -> Generator[Session, None, None]:
    """Session bound to the row-level-security-limited visitor role."""
    db = PublicSessionLocal()
    try:
        yield db
    finally:
        db.close()


# Reference tables the visitor role may read in full. Villages carry no free-text claim: only names,
# municipality, approximate coordinates and the source/verification flag of those facts. Every claim
# about a village lives in a heritage entry, which goes through the validation gate.
PUBLIC_REFERENCE_TABLES: tuple[str, ...] = ("villages",)

# Tables the visitor role may read (RLS restricts rows to approved content).
PUBLIC_TABLES: dict[str, str] = {
    "heritage_entries": "status = 'approved'",
    "listings": "status = 'approved'",
    "trail_segments": "status = 'approved'",
    "trail_reports": (
        "status = 'approved' AND EXISTS (SELECT 1 FROM trail_segments s "
        "WHERE s.id = trail_reports.segment_id AND s.status = 'approved')"
    ),
    "entry_chunks": (
        "EXISTS (SELECT 1 FROM heritage_entries e "
        "WHERE e.id = entry_chunks.entry_id AND e.status = 'approved')"
    ),
}

_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")


def apply_public_role_and_rls(conn) -> None:
    """Create/refresh the visitor role and the row-level-security policies."""
    role = settings.public_db_user
    if not _IDENT.match(role):
        raise ValueError("PUBLIC_DB_USER must be a simple lowercase identifier")
    dbname = make_url(settings.database_url).database
    pw = settings.public_db_password.replace("'", "''")
    conn.execute(
        text(
            f"""
            DO $$ BEGIN
              IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                CREATE ROLE {role} LOGIN PASSWORD '{pw}';
              END IF;
            END $$;
            """
        )
    )
    conn.execute(text(f"ALTER ROLE {role} WITH LOGIN PASSWORD '{pw}' NOSUPERUSER NOCREATEDB NOCREATEROLE"))
    conn.execute(text(f'GRANT CONNECT ON DATABASE "{dbname}" TO {role}'))
    conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {role}"))
    # Revoke anything broader that may have been granted earlier, then grant SELECT only.
    conn.execute(text(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {role}"))
    for table in PUBLIC_REFERENCE_TABLES:
        conn.execute(text(f"GRANT SELECT ON {table} TO {role}"))
    for table, predicate in PUBLIC_TABLES.items():
        conn.execute(text(f"GRANT SELECT ON {table} TO {role}"))
        conn.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
        conn.execute(text(f"DROP POLICY IF EXISTS approved_only ON {table}"))
        conn.execute(
            text(f"CREATE POLICY approved_only ON {table} FOR SELECT TO {role} USING ({predicate})")
        )


def init_db(drop: bool = False) -> None:
    """Create extension, tables, visitor role and RLS policies. Idempotent.

    ``drop=True`` recreates the whole ``public`` schema, which is the only reliable way to reset a
    database whose schema predates the current models (the prototype ships no migrations).
    """
    from . import models  # noqa: F401  (register tables)

    with engine.begin() as conn:
        if drop:
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        Base.metadata.create_all(conn)
        apply_public_role_and_rls(conn)
