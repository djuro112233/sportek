"""End-to-end tests for ``POST /api/ask`` and ``GET /api/ask/topics`` over the real demo KB.

The demo knowledge base (manifest ids ``demo-*``) is ingested once per module into one SQLite
file; every test builds its own application on that database, so events and sessions
accumulate and assertions are scoped by session id.
"""

from __future__ import annotations

import dataclasses
import io
import json
import re
import wave
from pathlib import Path

import pytest
from conftest import make_test_settings
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.speak import audio_store
from app.config import Settings
from app.core.container import Providers, build_providers
from app.core.events import classify_topic
from app.core.gate import GATE_VERSION
from app.core.generation import Generator
from app.core.i18n import t
from app.core.pipeline import REASON_PIPELINE_ERROR
from app.core.redflags import RedFlagRouter
from app.core.retrieval import Retriever
from app.core.types import RED_FLAG_CATEGORIES, TOPIC_CLASSES
from app.core.verifier import split_sentences
from app.db import init_engine, session_factory
from app.kb.embed import HashEmbedder
from app.kb.ingest import ingest_manifest, load_manifest
from app.main import create_app
from app.models import Event, GateRecord, SavedQuestion
from app.models import Session as SessionRow
from app.services.llm import ScriptedLLM

SR_QUESTION = "Koje metode kontracepcije postoje i kako djeluju?"
EN_QUESTION = "Which contraception methods are available and how do they work?"
OFF_KB_QUESTION = "kako da napravim kolac od jabuka"
DOSING_QUESTION = "koliko mg ibuprofena smijem u trudnoci"
CYRILLIC_RED_FLAG = "јако крварим, трудна сам"
MINOR_RED_FLAG = "nastavnik me dira, imam 14 godina"
SUICIDAL_INPUT = "ne zelim vise da zivim, razmisljam da se ubijem"
# Distinctive words of the questions above; none of them may ever reach the events table.
QUESTION_WORDS = ("kontracepcije", "jabuka", "ibuprofena", "крварим", "krvarim", "nastavnik", "ubijem")

_CYRILLIC_RE = re.compile(r"[Ѐ-ӿ]")
_LATIN_LETTER_RE = re.compile(r"[A-Za-z]")


# --- fixtures -----------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def kb_settings(tmp_path_factory) -> Settings:
    """Settings whose SQLite file holds the ingested demo KB (hash embedder, demo mode)."""
    tmp_path: Path = tmp_path_factory.mktemp("ask_api")
    settings = make_test_settings(tmp_path)
    init_engine(settings.database_url)
    db = session_factory()()
    try:
        demo_ids = {d.id for d in load_manifest(settings.manifest_path) if d.id.startswith("demo-")}
        report = ingest_manifest(db, settings, HashEmbedder(dim=settings.embedding_dim), only=demo_ids)
        assert report.ok and len(report.ingested) == len(demo_ids)
    finally:
        db.close()
    return settings


@pytest.fixture
def app(kb_settings: Settings):
    audio_store.clear()
    yield create_app(kb_settings)
    audio_store.clear()


@pytest.fixture
def client(app) -> TestClient:
    with TestClient(app) as c:
        yield c


@pytest.fixture
def db(app):
    session = session_factory()()
    try:
        yield session
    finally:
        session.close()


def _consent(client: TestClient, settings: Settings, **overrides) -> str:
    body = {"lang": "sr", "is_minor": False, "accepted": True, "consent_version": settings.consent_version}
    body.update(overrides)
    r = client.post("/api/consent", json=body)
    assert r.status_code == 200, r.text
    return r.json()["session_id"]


def _ask(client: TestClient, sid: str, text: str, **extra) -> dict:
    r = client.post("/api/ask", json={"session_id": sid, "text": text, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def _events(db, sid: str) -> list[Event]:
    db.expire_all()
    return list(db.scalars(select(Event).where(Event.session_id == sid).order_by(Event.id)))


def _wav_params(data: bytes) -> tuple[int, int, int, int]:
    with wave.open(io.BytesIO(data), "rb") as wf:
        return wf.getnchannels(), wf.getsampwidth(), wf.getframerate(), wf.getnframes()


# --- topics -------------------------------------------------------------------------------------
def test_topics_endpoint_lists_topic_classes_and_red_flag_categories(client: TestClient) -> None:
    r = client.get("/api/ask/topics")
    assert r.status_code == 200
    assert r.json() == {"topics": list(TOPIC_CLASSES), "red_flag_categories": list(RED_FLAG_CATEGORIES)}


# --- consent gate -------------------------------------------------------------------------------
def test_unknown_session_is_403(client: TestClient, db) -> None:
    r = client.post("/api/ask", json={"session_id": "no-such-session-000000000000000", "text": SR_QUESTION})
    assert r.status_code == 403
    assert _events(db, "no-such-session-000000000000000") == []


def test_session_without_consent_is_403(client: TestClient, db) -> None:
    db.add(SessionRow(id="unconsented-session-00000000000", lang="sr", consent_given=False))
    db.commit()
    r = client.post("/api/ask", json={"session_id": "unconsented-session-00000000000", "text": SR_QUESTION})
    assert r.status_code == 403
    assert r.json()["detail"] == "consent required"


def test_empty_text_is_422(client: TestClient, kb_settings: Settings) -> None:
    sid = _consent(client, kb_settings)
    assert client.post("/api/ask", json={"session_id": sid, "text": ""}).status_code == 422


# --- answered -----------------------------------------------------------------------------------
def test_sr_contraception_question_is_answered_with_citations(
    client: TestClient, kb_settings: Settings
) -> None:
    sid = _consent(client, kb_settings)
    body = _ask(client, sid, SR_QUESTION)
    assert body["outcome"] == "answered"
    assert body["session_id"] == sid and body["lang"] == "sr" and body["script"] == "latin"
    assert body["topic_class"] == "contraception"
    assert len(body["sentences"]) >= 1
    assert all(s["supported"] and s["text"] for s in body["sentences"])
    assert all("[S" not in s["text"] for s in body["sentences"])
    markers = {c["marker"] for c in body["citations"]}
    assert markers
    for sentence in body["sentences"]:
        assert sentence["citations"]
        assert set(sentence["citations"]) <= markers
    for citation in body["citations"]:
        assert citation["source_title"].endswith("(demo)")
        assert citation["section"] and citation["version"] and citation["date"] == "2026-10-19"
        assert citation["chunk_id"].startswith(f"{citation['source_id']}:{citation['version']}:")
        assert citation["review_status"] == "public_unreviewed"
    assert body["demo_unreviewed_sources"] is True
    assert body["translated"] is False and body["message"] == ""
    assert body["disclaimer_short"] == t("disclaimer_short", "sr")
    assert body["referral"]["emergency"] is False and len(body["referral"]["points"]) >= 1
    assert body["referral"]["message"] == t("referral_general", "sr")
    assert body["confidence"] > 0 and body["support_ratio"] > 0
    assert body["gate"]["status"] == "approved" and body["gate"]["reasons"] == []
    assert body["latency_ms"] > 0
    assert body["audio_url"] is None and body["redflag_category"] is None


def test_cyrillic_script_renders_every_visible_string(client: TestClient, kb_settings: Settings) -> None:
    sid = _consent(client, kb_settings, script="cyrillic")
    body = _ask(client, sid, SR_QUESTION, script="cyrillic")
    assert body["outcome"] == "answered" and body["script"] == "cyrillic"
    for sentence in body["sentences"]:
        assert _CYRILLIC_RE.search(sentence["text"]), sentence["text"]
        assert not _LATIN_LETTER_RE.search(sentence["text"]), sentence["text"]
    assert body["disclaimer_short"] == t("disclaimer_short", "sr", "cyrillic")
    assert body["referral"]["message"] == t("referral_general", "sr", "cyrillic")
    # Citation titles are bibliographic data and keep their original script.
    assert all(c["source_title"].endswith("(demo)") for c in body["citations"])


def test_english_question_is_answered_from_english_sources(client: TestClient, kb_settings: Settings) -> None:
    sid = _consent(client, kb_settings, lang="en")
    body = _ask(client, sid, EN_QUESTION, lang="en")
    assert body["outcome"] == "answered" and body["lang"] == "en"
    assert body["sentences"] and all(not _CYRILLIC_RE.search(s["text"]) for s in body["sentences"])
    assert all(c["lang"] == "en" for c in body["citations"])
    assert body["translated"] is False
    assert body["disclaimer_short"] == t("disclaimer_short", "en")


def test_session_language_is_used_when_the_request_has_none(
    client: TestClient, kb_settings: Settings
) -> None:
    sid = _consent(client, kb_settings, lang="en")
    body = _ask(client, sid, EN_QUESTION)
    assert body["lang"] == "en" and body["outcome"] == "answered"
    assert all(c["lang"] == "en" for c in body["citations"])


# --- withheld -----------------------------------------------------------------------------------
def test_off_kb_question_is_withheld_with_referral(client: TestClient, kb_settings: Settings, db) -> None:
    sid = _consent(client, kb_settings)
    body = _ask(client, sid, OFF_KB_QUESTION)
    assert body["outcome"] == "withheld"
    assert body["sentences"] == [] and body["citations"] == []
    assert body["message"] == t("withheld", "sr")
    assert body["referral"]["points"] and body["referral"]["emergency"] is False
    assert body["gate"]["status"] == "withheld" and body["gate"]["reasons"]
    assert body["demo_unreviewed_sources"] is False and body["translated"] is False
    assert body["audio_url"] is None
    (event,) = [e for e in _events(db, sid) if e.type == "ask"]
    assert event.outcome == "withheld" and event.support_ratio is None
    assert event.payload["gate_status"] == "withheld" and event.payload["n_kept"] == 0


def test_dosing_question_is_withheld_and_returns_no_dose_text(
    client: TestClient, kb_settings: Settings
) -> None:
    sid = _consent(client, kb_settings)
    body = _ask(client, sid, DOSING_QUESTION)
    assert body["outcome"] == "withheld"
    assert body["sentences"] == []
    assert "medication_or_dose" in body["gate"]["reasons"]
    returned = [s["text"] for s in body["sentences"]]
    returned += [s["text"] for s in body["gate"]["kept"]] + [s["text"] for s in body["gate"]["removed"]]
    assert not any(re.search(r"\bmg\b", text) for text in returned)
    assert body["message"] == t("withheld", "sr") and body["referral"]["points"]


def test_demo_mode_off_withholds_when_only_unreviewed_sources_exist(kb_settings: Settings) -> None:
    app = create_app(kb_settings.model_copy(update={"demo_mode": False}))
    with TestClient(app) as client:
        sid = _consent(client, kb_settings)
        body = _ask(client, sid, SR_QUESTION)
    assert body["outcome"] == "withheld"
    assert body["sentences"] == [] and body["citations"] == []
    assert body["gate"]["reasons"] == ["no_sentences"]
    assert body["message"] == t("withheld", "sr") and body["referral"]["points"]


# --- red flags ----------------------------------------------------------------------------------
def test_cyrillic_red_flag_returns_emergency_referral(client: TestClient, kb_settings: Settings, db) -> None:
    sid = _consent(client, kb_settings, script="cyrillic")
    body = _ask(client, sid, CYRILLIC_RED_FLAG, script="cyrillic")
    assert body["outcome"] == "redflag"
    assert body["redflag_category"] == "bleeding_pregnancy"
    assert body["sentences"] == [] and body["citations"] == [] and body["gate"] is None
    assert body["referral"]["emergency"] is True
    assert any(p["phone"] == "124" for p in body["referral"]["points"])
    assert body["message"] == body["referral"]["message"] == t("redflag_emergency", "sr", "cyrillic")
    assert _CYRILLIC_RE.search(body["message"]) and not _LATIN_LETTER_RE.search(body["message"])
    assert body["disclaimer_short"] == t("disclaimer_short", "sr", "cyrillic")
    assert body["latency_ms"] > 0
    events = _events(db, sid)
    assert [e.type for e in events] == ["consent", "redflag"]
    event = events[-1]
    assert event.outcome == "redflag" and event.redflag_category == "bleeding_pregnancy"
    assert event.topic_class == "pregnancy" and event.input_mode == "text"
    assert event.latency_ms is not None and event.latency_ms > 0
    assert event.payload["source"] == "rule"
    assert db.scalar(select(GateRecord).where(GateRecord.event_id == event.id)) is None


def test_minor_child_protection_input_routes_to_child_protection(
    client: TestClient, kb_settings: Settings, db
) -> None:
    sid = _consent(client, kb_settings, is_minor=True)
    body = _ask(client, sid, MINOR_RED_FLAG)
    assert body["outcome"] == "redflag" and body["redflag_category"] == "minor_sexual_adult"
    assert body["message"] == t("redflag_child_protection", "sr")
    kinds = [p["kind"] for p in body["referral"]["points"]]
    assert kinds and kinds[0] == "child_protection"
    (event,) = [e for e in _events(db, sid) if e.type == "redflag"]
    assert event.redflag_category == "minor_sexual_adult" and event.payload["child_protection"] is True


def test_suicidal_input_takes_the_support_path(client: TestClient, kb_settings: Settings) -> None:
    sid = _consent(client, kb_settings)
    body = _ask(client, sid, SUICIDAL_INPUT)
    assert body["outcome"] == "redflag" and body["redflag_category"] == "suicidal_ideation"
    assert body["message"] == t("redflag_support", "sr")
    assert body["referral"]["emergency"] is True
    kinds = [p["kind"] for p in body["referral"]["points"]]
    assert "mental_health" in kinds and "er" in kinds


# --- privacy ------------------------------------------------------------------------------------
def test_saved_question_rows_only_with_the_separate_consent(
    client: TestClient, kb_settings: Settings, db
) -> None:
    saving = _consent(client, kb_settings, save_questions=True)
    silent = _consent(client, kb_settings, save_questions=False)
    _ask(client, saving, SR_QUESTION)
    _ask(client, silent, SR_QUESTION)
    db.expire_all()
    saved = list(db.scalars(select(SavedQuestion).where(SavedQuestion.session_id == saving)))
    assert [(q.text, q.lang, q.outcome) for q in saved] == [(SR_QUESTION, "sr", "answered")]
    assert list(db.scalars(select(SavedQuestion).where(SavedQuestion.session_id == silent))) == []


def test_question_text_never_reaches_the_events_table(client: TestClient, kb_settings: Settings, db) -> None:
    sid = _consent(client, kb_settings, save_questions=True)
    for text in (SR_QUESTION, OFF_KB_QUESTION, DOSING_QUESTION, CYRILLIC_RED_FLAG, SUICIDAL_INPUT):
        _ask(client, sid, text)
    db.expire_all()
    rows = list(db.scalars(select(Event)))
    assert len(rows) >= 6
    for event in rows:
        dump = json.dumps(
            {c.name: getattr(event, c.name) for c in Event.__table__.columns}, default=str, ensure_ascii=False
        ).lower()
        for word in QUESTION_WORDS:
            assert word not in dump, (event.id, word)


def test_gate_record_is_linked_to_the_ask_event(client: TestClient, kb_settings: Settings, db) -> None:
    sid = _consent(client, kb_settings)
    body = _ask(client, sid, SR_QUESTION)
    (event,) = [e for e in _events(db, sid) if e.type == "ask"]
    record = db.scalar(select(GateRecord).where(GateRecord.event_id == event.id))
    assert record is not None
    assert record.status == "approved" and record.gate_version == GATE_VERSION
    assert record.n_sentences_kept == len(body["sentences"]) == record.n_sentences_in
    assert record.support_ratio == body["support_ratio"] and record.confidence == body["confidence"]
    assert event.lang == "sr" and event.topic_class == "contraception" and event.outcome == "answered"
    assert event.support_ratio == body["support_ratio"] and event.input_mode == "text"
    assert event.payload == {
        "n_chunks": kb_settings.retrieval_top_k,
        "n_sentences_in": record.n_sentences_in,
        "n_kept": record.n_sentences_kept,
        "translated": False,
        "want_audio": False,
        "gate_status": "approved",
        "gate_reasons": [],
    }


# --- audio ----------------------------------------------------------------------------------------
def test_want_audio_returns_a_one_time_wav_url(client: TestClient, kb_settings: Settings, db) -> None:
    sid = _consent(client, kb_settings)
    body = _ask(client, sid, SR_QUESTION, want_audio=True)
    assert body["outcome"] == "answered"
    assert body["audio_url"] and body["audio_url"].startswith("/api/audio/")
    first = client.get(body["audio_url"])
    assert first.status_code == 200 and first.headers["content-type"] == "audio/wav"
    channels, width, rate, frames = _wav_params(first.content)
    assert (channels, width, rate) == (1, 2, 16000) and frames > 0
    assert client.get(body["audio_url"]).status_code == 404
    (event,) = [e for e in _events(db, sid) if e.type == "ask"]
    assert event.payload["want_audio"] is True


def test_low_bandwidth_audio_is_8khz(client: TestClient, kb_settings: Settings) -> None:
    sid = _consent(client, kb_settings)
    body = _ask(client, sid, SR_QUESTION, want_audio=True, low_bandwidth=True)
    wav = client.get(body["audio_url"]).content
    assert _wav_params(wav)[2] == 8000


def test_red_flag_message_can_be_spoken_but_withheld_answers_are_silent(
    client: TestClient, kb_settings: Settings
) -> None:
    sid = _consent(client, kb_settings)
    flagged = _ask(client, sid, CYRILLIC_RED_FLAG, want_audio=True)
    assert flagged["outcome"] == "redflag" and flagged["audio_url"]
    assert client.get(flagged["audio_url"]).status_code == 200
    withheld = _ask(client, sid, OFF_KB_QUESTION, want_audio=True)
    assert withheld["outcome"] == "withheld" and withheld["audio_url"] is None


# --- rate limit -----------------------------------------------------------------------------------
def test_third_call_within_a_minute_is_rate_limited(kb_settings: Settings) -> None:
    app = create_app(kb_settings.model_copy(update={"rate_limit_per_minute": 2}))
    with TestClient(app) as client:
        sid = _consent(client, kb_settings)
        assert _ask(client, sid, SR_QUESTION)["outcome"] == "answered"
        assert _ask(client, sid, SR_QUESTION)["outcome"] == "answered"
        third = client.post("/api/ask", json={"session_id": sid, "text": SR_QUESTION})
        assert third.status_code == 429 and third.headers["retry-after"] == "60"
        # Another session has its own budget.
        other = _consent(client, kb_settings)
        assert _ask(client, other, SR_QUESTION)["outcome"] == "answered"


# --- failing closed -------------------------------------------------------------------------------
def test_generator_failure_fails_closed(client: TestClient, kb_settings: Settings, db, monkeypatch) -> None:
    def explode(self, question, chunks, lang, *, is_minor=False):
        raise RuntimeError("model endpoint down")

    monkeypatch.setattr(Generator, "generate", explode)
    sid = _consent(client, kb_settings)
    r = client.post("/api/ask", json={"session_id": sid, "text": SR_QUESTION})
    assert r.status_code == 200
    body = r.json()
    assert body["outcome"] == "withheld" and body["sentences"] == [] and body["citations"] == []
    assert body["gate"] == {
        "status": "withheld",
        "gate_version": GATE_VERSION,
        "reasons": [REASON_PIPELINE_ERROR],
        "support_ratio": 0.0,
        "confidence": 0.0,
        "kept": [],
        "removed": [],
    }
    assert body["message"] == t("withheld", "sr") and body["referral"]["points"]
    assert "model endpoint down" not in r.text and "Traceback" not in r.text
    (event,) = [e for e in _events(db, sid) if e.type == "ask"]
    assert event.outcome == "error"
    assert event.payload == {"error": "RuntimeError", "stage": "generation"}
    record = db.scalar(select(GateRecord).where(GateRecord.event_id == event.id))
    assert record is not None and record.reasons == [REASON_PIPELINE_ERROR]


def test_red_flag_router_failure_withholds_instead_of_answering(
    client: TestClient, kb_settings: Settings, db, monkeypatch
) -> None:
    def explode(self, text, *, lang=None, is_minor=None):
        raise ValueError("classifier broke")

    monkeypatch.setattr(RedFlagRouter, "check", explode)
    sid = _consent(client, kb_settings)
    body = _ask(client, sid, SR_QUESTION)
    assert body["outcome"] == "withheld" and body["sentences"] == []
    assert body["gate"]["reasons"] == [REASON_PIPELINE_ERROR]
    assert body["referral"]["points"]
    (event,) = [e for e in _events(db, sid) if e.type == "ask"]
    assert event.outcome == "error" and event.payload == {"error": "ValueError", "stage": "redflag"}


# --- voice flow -----------------------------------------------------------------------------------
def test_transcribe_then_ask_marks_the_event_as_voice(client: TestClient, kb_settings: Settings, db) -> None:
    sid = _consent(client, kb_settings)
    upload = client.post(
        "/api/transcribe",
        files={"file": ("q.wav", f"MOCK:{SR_QUESTION}|sr".encode(), "audio/wav")},
        data={"session_id": sid},
    )
    assert upload.status_code == 200, upload.text
    transcript = upload.json()
    assert transcript["text"] == SR_QUESTION and transcript["confirm_required"] is True
    body = _ask(client, sid, transcript["text"], lang=transcript["lang"], input_mode="voice")
    assert body["outcome"] == "answered"
    events = _events(db, sid)
    assert [e.type for e in events] == ["consent", "transcribe", "ask"]
    assert events[-1].input_mode == "voice" and events[-2].input_mode == "voice"


# --- translated answers ---------------------------------------------------------------------------
def test_translated_answer_carries_the_note(app, kb_settings: Settings, db) -> None:
    question = "What is emergency contraception?"
    chunks = Retriever(db, HashEmbedder(dim=kb_settings.embedding_dim), kb_settings).search(
        question, lang="sr", top_k=kb_settings.retrieval_top_k, topic=classify_topic(question)
    )
    assert chunks and chunks[0].lang == "en"
    verbatim = split_sentences(chunks[0].text)[0]
    providers = dataclasses.replace(build_providers(kb_settings), llm=ScriptedLLM([f"{verbatim} [S1]"]))
    app.state.providers = providers
    with TestClient(app) as client:
        sid = _consent(client, kb_settings)
        body = _ask(client, sid, question, lang="sr")
    assert body["outcome"] == "answered" and body["translated"] is True
    assert [s["text"] for s in body["sentences"]] == [verbatim]
    assert [c["marker"] for c in body["citations"]] == ["S1"]
    assert body["citations"][0]["chunk_id"] == chunks[0].chunk_id and body["citations"][0]["lang"] == "en"
    assert body["message"] == t("translated_note", "sr")
    (event,) = [e for e in _events(db, sid) if e.type == "ask"]
    assert event.payload["translated"] is True


def test_injected_providers_are_used_and_published_for_the_voice_routers(app, kb_settings: Settings) -> None:
    providers: Providers = build_providers(kb_settings)
    app.state.providers = providers
    with TestClient(app) as client:
        sid = _consent(client, kb_settings)
        _ask(client, sid, SR_QUESTION)
    assert app.state.providers is providers
    assert app.state.stt is providers.stt and app.state.tts is providers.tts
