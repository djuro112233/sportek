"""Test configuration.

Runs against a real PostgreSQL 16 + pgvector database (TEST_DATABASE_URL, default
postgresql+psycopg://vrmac:vrmac@127.0.0.1:5432/vrmac_test). Providers are the offline ones:
hash embeddings, no LLM, fixture speech-to-text, synchronous queue.
"""
from __future__ import annotations

import os

os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://vrmac:vrmac@127.0.0.1:5432/vrmac_test"
)
os.environ["APP_ENV"] = "test"
os.environ["AUTO_INIT_DB"] = "false"
os.environ["QUEUE_MODE"] = "sync"
os.environ["EMBEDDINGS_PROVIDER"] = os.environ.get("TEST_EMBEDDINGS_PROVIDER", "hash")
os.environ["EMBEDDING_DIM"] = os.environ.get("TEST_EMBEDDING_DIM", "768")
os.environ["LLM_PROVIDER"] = os.environ.get("TEST_LLM_PROVIDER", "none")
os.environ["SUPPORT_CHECK_PROVIDER"] = os.environ.get("TEST_SUPPORT_CHECK_PROVIDER", "lexical")
os.environ["STT_PROVIDER"] = "fixture"
os.environ["EVENT_PSEUDONYM_KEY"] = os.environ.get("TEST_EVENT_PSEUDONYM_KEY", "test-pseudonym-key-0123456789")
os.environ["CACHE_ENABLED"] = os.environ.get("TEST_CACHE_ENABLED", "true")
os.environ["RATE_LIMIT_PUBLIC"] = "100000/minute"
os.environ["RATE_LIMIT_ASK"] = "100000/minute"
os.environ["UPLOAD_DIR"] = os.environ.get("TEST_UPLOAD_DIR", "./data/test-uploads")
os.environ["EXPORT_DIR"] = os.environ.get("TEST_EXPORT_DIR", "./data/test-exports")
os.environ.pop("PUBLIC_DB_USER", None)
os.environ.pop("PUBLIC_DB_PASSWORD", None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, make_url, text  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import PublicSessionLocal, SessionLocal, init_db  # noqa: E402


def _ensure_database_exists() -> None:
    url = make_url(settings.database_url)
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": url.database}).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    admin.dispose()


@pytest.fixture(scope="session", autouse=True)
def database():
    """Fresh schema + seed data once per test session."""
    _ensure_database_exists()
    init_db(drop=True)
    from app.seed.loader import load_seed

    with SessionLocal() as db:
        summary = load_seed(db, reset=True)
    yield summary


@pytest.fixture()
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def public_db():
    s = PublicSessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture(scope="session")
def client(database):
    from app.main import app

    with TestClient(app) as c:
        yield c


SAMPLE_ACCOUNTS = {
    "host": "host1@example.org",
    "host3": "host3@example.org",
    "host2": "host2@example.org",
    "ambassador": "ambassador1@example.org",
    "validator": "validator1@example.org",
    "institution": "institution1@example.org",
}


@pytest.fixture(scope="session")
def login(client):
    def _login(role: str) -> dict:
        email = SAMPLE_ACCOUNTS[role]
        r = client.post("/api/auth/login", json={"email": email, "password": settings.seed_password})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    return _login
