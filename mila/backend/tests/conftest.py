"""Shared pytest fixtures. DO NOT add module-specific fixtures here; put them next to the tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import init_engine, session_factory
from app.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_KB_DIR = REPO_ROOT / "kb" / "demo"


def make_test_settings(tmp_path: Path, **overrides) -> Settings:
    base = dict(
        app_env="test",
        demo_mode=True,
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        llm_provider="mock",
        embedder="hash",
        judge_provider="lexical",
        stt_provider="mock",
        tts_provider="mock",
        audio_tmp_dir=str(tmp_path / "audio"),
        admin_token="test-admin-token",
        kb_dir=str(REPO_ROOT / "kb"),
        manifest_path=str(REPO_ROOT / "kb" / "manifest.yaml"),
    )
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    os.environ.pop("MILA_DATABASE_URL", None)
    return make_test_settings(tmp_path)


@pytest.fixture
def db(settings: Settings):
    init_engine(settings.database_url)
    session = session_factory()()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def app(settings: Settings):
    return create_app(settings)


@pytest.fixture
def client(app) -> TestClient:
    with TestClient(app) as c:
        yield c
