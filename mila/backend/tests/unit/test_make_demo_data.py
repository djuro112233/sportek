"""Unit tests for scripts/make_demo_data.py: deterministic synthetic data, privacy invariants, prod refusal."""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import asdict
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.config import Settings
from app.core.types import RED_FLAG_CATEGORIES, SUPPORTED_LANGS, TOPIC_CLASSES
from app.db import init_engine, session_factory
from app.models import Event, GateRecord, ReferralPoint, Session

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / "scripts"


def make_test_settings(tmp_path: Path) -> Settings:
    return Settings(
        app_env="test",
        demo_mode=True,
        database_url=f"sqlite:///{tmp_path / 'demo.db'}",
        llm_provider="mock",
        embedder="hash",
        judge_provider="lexical",
        stt_provider="mock",
        tts_provider="mock",
        audio_tmp_dir=str(tmp_path / "audio"),
        kb_dir=str(REPO_ROOT / "kb"),
        manifest_path=str(REPO_ROOT / "kb" / "manifest.yaml"),
    )


@pytest.fixture(scope="module")
def demo():
    path = SCRIPTS_DIR / "make_demo_data.py"
    spec = importlib.util.spec_from_file_location("mila_scripts_make_demo_data", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_constants_match_backend_types(demo):
    assert demo.TOPIC_CLASSES == TOPIC_CLASSES
    assert demo.RED_FLAG_CATEGORIES == RED_FLAG_CATEGORIES
    assert set(demo.LANGS) == set(SUPPORTED_LANGS)
    assert demo.OUTCOMES == ("answered", "withheld", "redflag")


def test_generation_is_deterministic_for_a_seed(demo):
    a = demo.generate_sessions(25, 14, seed=7)
    b = demo.generate_sessions(25, 14, seed=7)
    c = demo.generate_sessions(25, 14, seed=8)
    assert [asdict(s) for s in a] == [asdict(s) for s in b]
    assert [asdict(s) for s in a] != [asdict(s) for s in c]
    assert len(a) == 25


def test_generated_events_respect_schema_and_privacy(demo):
    sessions = demo.generate_sessions(60, 10, seed=1)
    events = [e for s in sessions for e in s.events]
    assert events
    for s in sessions:
        assert s.lang in demo.LANGS and s.region in ("BA", "ME") and s.script in ("latin", "cyrillic")
        assert 0 < s.created_offset_s <= 10 * 86400
        assert s.events[0].type == "consent"
    for e in events:
        assert e.payload == {"synthetic": True}
        assert not {"text", "question", "transcript", "audio", "ip", "email", "phone", "name"} & set(e.payload)
        assert e.type in ("consent", "ask", "redflag", "transcribe")
        assert 0 < e.offset_s <= 10 * 86400
        if e.type in ("ask", "redflag"):
            assert e.outcome in demo.OUTCOMES
            assert e.topic_class in demo.TOPIC_CLASSES
            assert e.input_mode in demo.INPUT_MODES
            assert e.latency_ms is not None and 60 <= e.latency_ms <= 20000
        if e.type == "redflag":
            assert e.redflag_category in demo.RED_FLAG_CATEGORIES
            assert e.support_ratio is None and e.gate is None
        if e.type == "ask":
            assert e.gate is not None and e.gate["gate_version"] == "1.0.0"
            assert 0.0 <= e.support_ratio <= 1.0
            assert e.gate["status"] == ("approved" if e.outcome == "answered" else "withheld")
            assert (e.outcome == "answered") == (e.gate["reasons"] == [])
    asks = [e for e in events if e.type in ("ask", "redflag")]
    summary = demo.summarize(sessions)
    assert summary["asks"] == len(asks) and summary["sessions"] == 60
    # realistic ratios: answered is the majority, both other outcomes occur, both input modes occur
    assert summary["by_outcome"]["answered"] > summary["by_outcome"].get("withheld", 0) > summary["by_outcome"].get("redflag", 0) > 0
    assert set(summary["by_input_mode"]) == {"text", "voice"}
    minor_only = {e.redflag_category for s in sessions if not s.is_minor for e in s.events if e.type == "redflag"}
    assert "minor_sexual_adult" not in minor_only


def test_generate_rejects_bad_arguments(demo):
    with pytest.raises(ValueError):
        demo.generate_sessions(-1, 7, 0)
    with pytest.raises(ValueError):
        demo.generate_sessions(1, 0, 0)
    assert demo.generate_sessions(0, 7, 0) == []


def test_refuses_in_prod_before_touching_the_database(demo, monkeypatch, tmp_path):
    monkeypatch.setenv("MILA_APP_ENV", "prod")
    db_path = tmp_path / "never.db"
    with pytest.raises(SystemExit) as exc:
        demo.main(["--sessions", "1", "--database-url", f"sqlite:///{db_path}"])
    assert exc.value.code == 2
    assert not db_path.exists()
    with pytest.raises(SystemExit):
        demo.refuse_in_prod({"MILA_APP_ENV": "PROD"})
    demo.refuse_in_prod({"MILA_APP_ENV": "dev"})  # no exception


def test_seed_database_writes_sessions_events_and_gate_records(demo, tmp_path):
    settings = make_test_settings(tmp_path)
    init_engine(settings.database_url)
    db = session_factory()()
    seen: dict[str, object] = {}

    def fake_referrals(session) -> int:
        session.add(ReferralPoint(name="Test clinic", kind="clinic", region="BA", phone="000"))
        session.flush()
        seen["referrals"] = True
        return 1

    def fake_ingest(session, s):
        seen["ingest_settings"] = s
        return {"ingested": [], "chunks_current": 0}

    sessions = demo.generate_sessions(12, 5, seed=3)
    try:
        result = demo.seed_database(db, settings, sessions, referral_seeder=fake_referrals, kb_ingester=fake_ingest)
        assert result["referral_points"] == 1 and seen["ingest_settings"] is settings
        assert result["sessions"] == 12
        n_sessions = db.scalar(select(func.count()).select_from(Session))
        n_events = db.scalar(select(func.count()).select_from(Event))
        n_gates = db.scalar(select(func.count()).select_from(GateRecord))
        assert n_sessions == 12
        assert n_events == result["events"] == sum(len(s.events) for s in sessions)
        assert n_gates == result["gate_records"] == sum(1 for s in sessions for e in s.events if e.gate)
        for row in db.scalars(select(Session)):
            assert row.consent_given is True and row.consent_version == settings.consent_version
            assert row.consent_save_questions is False
            assert len(row.id) >= 32
        for ev in db.scalars(select(Event)):
            assert ev.payload == {"synthetic": True}
            assert ev.created_at is not None
        # ask events carry a gate record linked by event id
        ask_ids = set(db.scalars(select(Event.id).where(Event.type == "ask")))
        gate_event_ids = set(db.scalars(select(GateRecord.event_id)))
        assert gate_event_ids == ask_ids
    finally:
        db.close()
