"""In-process end-to-end tests for ``app.core.pipeline.AskPipeline`` and ``app.core.container``.

The demo knowledge base is ingested once per module (hash embedder, demo mode). Tests call the
pipeline directly, the way ``scripts/measure.py`` does, so they can inspect the full gate
decision and the providers.
"""

from __future__ import annotations

import dataclasses
import io
import re
import wave
from pathlib import Path

import pytest
from conftest import make_test_settings
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.api.speak import audio_store
from app.config import Settings
from app.core.container import Providers, build_providers, get_providers, router_for
from app.core.events import classify_topic
from app.core.gate import GATE_VERSION, REASON_MEDICATION_OR_DOSE
from app.core.i18n import t
from app.core.pipeline import (
    REASON_PIPELINE_ERROR,
    AskPipeline,
    asks_for_dose,
    build_citations,
    citation_index,
    cited_chunks,
    elapsed_ms,
    public_gate,
)
from app.core.privacy import new_session_id
from app.core.redflags import RedFlagRouter, get_router
from app.core.retrieval import Retriever
from app.core.types import AnswerSentence, AskRequest, GateDecision, RedFlagResult, RetrievedChunk
from app.core.verifier import LexicalJudge, Verifier, split_sentences
from app.db import make_engine
from app.kb.embed import HashEmbedder
from app.kb.ingest import ingest_manifest, load_manifest
from app.main import create_app
from app.models import Base, Event, GateRecord, ReferralPoint, SavedQuestion
from app.models import Session as SessionRow
from app.services.llm import MockLLM, ScriptedLLM
from app.services.stt import MockSTT
from app.services.tts import MockTTS

SR_QUESTION = "Koje metode kontracepcije postoje i kako djeluju?"
OFF_KB_QUESTION = "kako da napravim kolac od jabuka"
CYRILLIC_RED_FLAG = "јако крварим, трудна сам"
_CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")
_LATIN_LETTER_RE = re.compile(r"[A-Za-z]")


# --- fixtures -----------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def demo_kb(tmp_path_factory):
    tmp_path: Path = tmp_path_factory.mktemp("pipeline_e2e")
    settings = make_test_settings(tmp_path)
    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    demo_ids = {d.id for d in load_manifest(settings.manifest_path) if d.id.startswith("demo-")}
    report = ingest_manifest(db, settings, HashEmbedder(dim=settings.embedding_dim), only=demo_ids)
    assert report.ok
    try:
        yield settings, db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture
def settings(demo_kb) -> Settings:
    return demo_kb[0]


@pytest.fixture
def db(demo_kb):
    return demo_kb[1]


@pytest.fixture
def providers(settings: Settings) -> Providers:
    return build_providers(settings)


@pytest.fixture
def pipeline(settings: Settings, db, providers: Providers) -> AskPipeline:
    return AskPipeline(settings, db, providers)


@pytest.fixture(autouse=True)
def _fresh_audio_store():
    audio_store.clear()
    yield
    audio_store.clear()


def _session(db, **overrides) -> SessionRow:
    fields = dict(
        id=new_session_id(),
        lang="sr",
        script="latin",
        region="BA",
        is_minor=False,
        consent_given=True,
        consent_version="2026-10-01",
        consent_save_questions=False,
    )
    fields.update(overrides)
    sess = SessionRow(**fields)
    db.add(sess)
    db.commit()
    return sess


def _events(db, sid: str) -> list[Event]:
    db.expire_all()
    return list(db.scalars(select(Event).where(Event.session_id == sid).order_by(Event.id)))


# --- helpers ------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("marker", "expected"), [("S1", 0), ("S12", 11), ("s3", 2), ("S0", None), ("X1", None), ("S", None)]
)
def test_citation_index(marker: str, expected: int | None) -> None:
    assert citation_index(marker) == expected


def test_cited_chunks_and_citations_follow_marker_order_without_duplicates() -> None:
    chunks = [
        RetrievedChunk(
            chunk_id=f"c{i}", source_id="src", source_title="T", source_version="v", text="x", page=i
        )
        for i in range(3)
    ]
    kept = [
        AnswerSentence(text="a", citations=["S3", "S1"], supported=True),
        AnswerSentence(text="b", citations=["S1", "S9"], supported=True),
    ]
    assert [(m, c.chunk_id) for m, c in cited_chunks(kept, chunks)] == [("S1", "c0"), ("S3", "c2")]
    citations = build_citations(kept, chunks)
    assert [(c.marker, c.chunk_id, c.page) for c in citations] == [("S1", "c0", 0), ("S3", "c2", 2)]


def test_public_gate_strips_removed_text_and_withheld_kept_text() -> None:
    kept = [AnswerSentence(text="shown", citations=["S1"], supported=True, support_score=1.0)]
    removed = [AnswerSentence(text="hidden", citations=["S1"], reason="unsupported")]
    approved = GateDecision(status="approved", gate_version=GATE_VERSION, kept=kept, removed=removed)
    withheld = GateDecision(
        status="withheld", gate_version=GATE_VERSION, reasons=["x"], kept=kept, removed=removed
    )
    assert public_gate(None) is None
    out = public_gate(approved)
    assert out is not None and out.kept[0].text == "shown" and out.removed[0].text == ""
    assert out.removed[0].reason == "unsupported" and out.kept[0].support_score == 1.0
    out = public_gate(withheld)
    assert out is not None and out.kept[0].text == "" and out.removed[0].text == "" and out.reasons == ["x"]
    assert approved.removed[0].text == "hidden"  # the original decision is untouched


def test_elapsed_ms_is_at_least_one() -> None:
    import time

    assert elapsed_ms(time.perf_counter()) >= 1


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("koliko mg ibuprofena smijem u trudnoci", True),
        ("колико мг ибупрофена смијем у трудноћи", True),
        ("smijem li uzeti 400 mg ibuprofena u trudnoci", True),
        ("koja doza folne kiseline se preporucuje", True),
        ("how many mg of paracetamol can I take while pregnant", True),
        ("what dose of iron is safe", True),
        (SR_QUESTION, False),
        ("koliko dugo djeluje spirala", False),
        ("koliko puta dnevno se uzima pilula", False),
        ("Koliko dugo nakon nezaštićenog odnosa mogu uzeti hitnu kontracepciju?", False),
        ("What is emergency contraception?", False),
    ],
)
def test_asks_for_dose(text: str, expected: bool) -> None:
    assert asks_for_dose(text) is expected


# --- container ----------------------------------------------------------------------------------
def test_build_providers_selects_the_mock_providers(settings: Settings, providers: Providers) -> None:
    assert isinstance(providers.llm, MockLLM)
    assert isinstance(providers.embedder, HashEmbedder) and providers.embedder.dim == settings.embedding_dim
    assert isinstance(providers.judge, LexicalJudge)
    assert isinstance(providers.redflags, RedFlagRouter) and providers.redflags is get_router()
    assert isinstance(providers.stt, MockSTT) and isinstance(providers.tts, MockTTS)
    assert providers.names()["llm"] == "mock" and providers.names()["judge"] == "LexicalJudge"


def test_router_for_honours_a_different_threshold(settings: Settings) -> None:
    custom = settings.model_copy(update={"redflag_classifier_threshold": 0.97})
    router = router_for(custom)
    assert router is not get_router() and router.classifier_threshold == 0.97


def test_get_providers_builds_lazily_once_and_adopts_injected_voice_providers(settings: Settings) -> None:
    app = create_app(settings)
    assert app.state.providers is None  # nothing is built at application start
    fake_stt = MockSTT()
    app.state.stt = fake_stt
    first = get_providers(app)
    assert first.stt is fake_stt and app.state.tts is first.tts
    assert get_providers(app) is first and app.state.providers is first


def test_pipeline_accepts_individual_providers_like_the_measure_script(settings: Settings, db) -> None:
    llm = MockLLM()
    pipeline = AskPipeline(
        settings,
        db,
        llm=llm,
        embedder=HashEmbedder(dim=settings.embedding_dim),
        judge=LexicalJudge(),
        redflags=get_router(),
        tts=None,
    )
    assert pipeline.providers.llm is llm and pipeline.providers.tts is None
    sess = _session(db)
    resp = pipeline.ask(AskRequest(session_id=sess.id, text=SR_QUESTION, lang="sr"), sess)
    assert resp.outcome == "answered"
    assert db.execute(select(ReferralPoint.id).limit(1)).first() is not None  # seeded on construction


# --- answered -----------------------------------------------------------------------------------
def test_answered_response_is_consistent_with_retrieval(
    pipeline: AskPipeline, settings: Settings, db
) -> None:
    sess = _session(db)
    resp = pipeline.ask(AskRequest(session_id=sess.id, text=SR_QUESTION, lang="sr", script="latin"), sess)
    assert resp.outcome == "answered" and resp.gate is not None and resp.gate.status == "approved"
    assert resp.sentences == resp.gate.kept
    chunks = Retriever(db, HashEmbedder(dim=settings.embedding_dim), settings).search(
        SR_QUESTION, lang="sr", top_k=settings.retrieval_top_k, topic=classify_topic(SR_QUESTION)
    )
    by_marker = {f"S{i + 1}": c for i, c in enumerate(chunks)}
    for citation in resp.citations:
        chunk = by_marker[citation.marker]
        assert citation.chunk_id == chunk.chunk_id and citation.source_title == chunk.source_title
        assert citation.section == chunk.heading_path and citation.version == chunk.source_version
        assert citation.date == chunk.published_on and citation.page == chunk.page
    for sentence in resp.sentences:
        for marker in sentence.citations:
            assert sentence.text in by_marker[marker].text  # the mock answers verbatim
    assert resp.support_ratio == resp.gate.support_ratio and resp.confidence == resp.gate.confidence
    assert resp.latency_ms >= 1


def test_script_comes_from_the_session_when_the_request_does_not_set_it(pipeline: AskPipeline, db) -> None:
    sess = _session(db, script="cyrillic")
    resp = pipeline.ask(AskRequest(session_id=sess.id, text=SR_QUESTION), sess)
    assert resp.script == "cyrillic" and resp.outcome == "answered"
    assert all(_CYRILLIC_RE.search(s.text) and not _LATIN_LETTER_RE.search(s.text) for s in resp.sentences)
    assert resp.disclaimer_short == t("disclaimer_short", "sr", "cyrillic")
    explicit = pipeline.ask(AskRequest(session_id=sess.id, text=SR_QUESTION, script="latin"), sess)
    assert explicit.script == "latin" and explicit.disclaimer_short == t("disclaimer_short", "sr")


def test_region_from_the_request_overrides_the_session(pipeline: AskPipeline, db) -> None:
    sess = _session(db, region="BA")
    resp = pipeline.ask(AskRequest(session_id=sess.id, text=SR_QUESTION, region="me"), sess)
    assert resp.referral is not None and resp.referral.points
    assert {p.region for p in resp.referral.points} == {"ME"}


def test_is_minor_reaches_the_router_and_the_referral(settings: Settings, db, providers: Providers) -> None:
    calls: list[tuple[str | None, bool | None]] = []

    class RecordingRouter:
        def check(self, text: str, *, lang: str | None = None, is_minor: bool | None = None) -> RedFlagResult:
            calls.append((lang, is_minor))
            return RedFlagResult(flagged=True, category="violence_coercion", source="rule", score=1.0)

    pipeline = AskPipeline(settings, db, dataclasses.replace(providers, redflags=RecordingRouter()))
    sess = _session(db, is_minor=True)
    resp = pipeline.ask(AskRequest(session_id=sess.id, text=SR_QUESTION, lang="bs"), sess)
    assert calls == [("bs", True)]
    assert resp.outcome == "redflag" and resp.redflag_category == "violence_coercion"
    assert resp.referral is not None and all(p.kind != "clinic" for p in resp.referral.points)
    assert any(p.kind == "child_protection" for p in resp.referral.points)


# --- withheld -----------------------------------------------------------------------------------
def test_off_kb_question_is_withheld_with_gate_reasons(pipeline: AskPipeline, db) -> None:
    sess = _session(db)
    resp = pipeline.ask(AskRequest(session_id=sess.id, text=OFF_KB_QUESTION), sess)
    assert resp.outcome == "withheld" and resp.sentences == [] and resp.citations == []
    assert resp.gate is not None and resp.gate.status == "withheld" and resp.gate.reasons == ["no_sentences"]
    assert resp.message == t("withheld", "sr") and resp.referral is not None and resp.referral.points
    assert resp.topic_class == "other"


def test_dose_question_is_withheld_before_generation(settings: Settings, db, providers: Providers) -> None:
    class NeverCalledLLM:
        name = "never"

        def complete(self, system: str, user: str, *, temperature: float = 0.0, max_tokens: int = 600) -> str:
            raise AssertionError("the model must not be called for a dose question")

    pipeline = AskPipeline(settings, db, dataclasses.replace(providers, llm=NeverCalledLLM()))
    sess = _session(db)
    resp = pipeline.ask(AskRequest(session_id=sess.id, text="koliko mg ibuprofena smijem u trudnoci"), sess)
    assert resp.outcome == "withheld" and resp.sentences == []
    assert resp.gate is not None and resp.gate.reasons == [REASON_MEDICATION_OR_DOSE]
    (event,) = [e for e in _events(db, sess.id) if e.type == "ask"]
    assert event.outcome == "withheld" and event.payload["n_chunks"] == 0
    record = db.scalar(select(GateRecord).where(GateRecord.event_id == event.id))
    assert record is not None and record.reasons == [REASON_MEDICATION_OR_DOSE]


def test_no_chunks_outside_demo_mode_gives_no_sentences(settings: Settings, db, providers: Providers) -> None:
    strict = settings.model_copy(update={"demo_mode": False})
    pipeline = AskPipeline(strict, db, providers)
    sess = _session(db)
    resp = pipeline.ask(AskRequest(session_id=sess.id, text=SR_QUESTION), sess)
    assert resp.outcome == "withheld" and resp.gate is not None and resp.gate.reasons == ["no_sentences"]
    (event,) = [e for e in _events(db, sess.id) if e.type == "ask"]
    assert event.payload["n_chunks"] == 0 and event.payload["n_sentences_in"] == 0


def test_want_audio_is_ignored_for_withheld_answers(pipeline: AskPipeline, db) -> None:
    sess = _session(db)
    resp = pipeline.ask(AskRequest(session_id=sess.id, text=OFF_KB_QUESTION, want_audio=True), sess)
    assert resp.outcome == "withheld" and resp.audio_url is None and len(audio_store) == 0


# --- red flags ----------------------------------------------------------------------------------
def test_red_flag_writes_a_redflag_event_and_no_gate_record(pipeline: AskPipeline, db) -> None:
    sess = _session(db, script="cyrillic")
    resp = pipeline.ask(AskRequest(session_id=sess.id, text=CYRILLIC_RED_FLAG, input_mode="voice"), sess)
    assert resp.outcome == "redflag" and resp.redflag_category == "bleeding_pregnancy"
    assert resp.gate is None and resp.sentences == [] and resp.citations == []
    assert resp.referral is not None and resp.referral.emergency
    assert any(p.phone == "124" for p in resp.referral.points)
    assert resp.message == t("redflag_emergency", "sr", "cyrillic")
    events = _events(db, sess.id)
    assert [e.type for e in events] == ["redflag"]
    event = events[0]
    assert event.outcome == "redflag" and event.redflag_category == "bleeding_pregnancy"
    assert event.input_mode == "voice" and event.lang == "sr" and event.latency_ms == resp.latency_ms > 0
    assert event.support_ratio is None
    assert set(event.payload) == {"source", "child_protection", "emergency", "want_audio"}
    assert db.scalar(select(GateRecord).where(GateRecord.event_id == event.id)) is None


def test_red_flag_audio_speaks_the_referral_message(pipeline: AskPipeline, db) -> None:
    sess = _session(db)
    resp = pipeline.ask(
        AskRequest(session_id=sess.id, text=CYRILLIC_RED_FLAG, want_audio=True, low_bandwidth=True), sess
    )
    assert resp.outcome == "redflag" and resp.audio_url
    wav = audio_store.pop(resp.audio_url.rsplit("/", 1)[-1])
    assert wav == MockTTS().synthesize(resp.message, "sr", low_bandwidth=True)
    with wave.open(io.BytesIO(wav), "rb") as wf:
        assert wf.getframerate() == 8000


# --- failing closed -------------------------------------------------------------------------------
def test_verifier_failure_fails_closed_with_an_error_event(
    pipeline: AskPipeline, db, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(self, answer_text, chunks):
        raise KeyError("judge")

    monkeypatch.setattr(Verifier, "verify", explode)
    sess = _session(db, consent_save_questions=True)
    resp = pipeline.ask(AskRequest(session_id=sess.id, text=SR_QUESTION), sess)
    assert resp.outcome == "withheld" and resp.sentences == [] and resp.citations == []
    assert resp.gate == GateDecision(
        status="withheld", gate_version=GATE_VERSION, reasons=[REASON_PIPELINE_ERROR]
    )
    assert resp.message == t("withheld", "sr") and resp.referral is not None and resp.referral.points
    assert resp.disclaimer_short == t("disclaimer_short", "sr")
    (event,) = _events(db, sess.id)
    assert event.type == "ask" and event.outcome == "error"
    assert event.payload == {"error": "KeyError", "stage": "verification"}
    assert event.latency_ms == resp.latency_ms >= 1
    record = db.scalar(select(GateRecord).where(GateRecord.event_id == event.id))
    assert record is not None and record.status == "withheld" and record.reasons == [REASON_PIPELINE_ERROR]
    saved = list(db.scalars(select(SavedQuestion).where(SavedQuestion.session_id == sess.id)))
    assert [(q.text, q.outcome) for q in saved] == [(SR_QUESTION, "withheld")]


def test_router_failure_does_not_answer(settings: Settings, db, providers: Providers) -> None:
    class BrokenRouter:
        def check(self, text: str, *, lang: str | None = None, is_minor: bool | None = None) -> RedFlagResult:
            raise RuntimeError("boom")

    pipeline = AskPipeline(settings, db, dataclasses.replace(providers, redflags=BrokenRouter()))
    sess = _session(db)
    resp = pipeline.ask(AskRequest(session_id=sess.id, text=SR_QUESTION), sess)
    assert resp.outcome == "withheld" and resp.sentences == []
    assert resp.gate is not None and resp.gate.reasons == [REASON_PIPELINE_ERROR]
    (event,) = _events(db, sess.id)
    assert event.outcome == "error" and event.payload == {"error": "RuntimeError", "stage": "redflag"}


def test_tts_failure_keeps_the_text_answer(settings: Settings, db, providers: Providers) -> None:
    class BrokenTTS:
        def synthesize(self, text: str, lang: str, *, low_bandwidth: bool = False) -> bytes:
            raise OSError("no voice")

    pipeline = AskPipeline(settings, db, dataclasses.replace(providers, tts=BrokenTTS()))
    sess = _session(db)
    resp = pipeline.ask(AskRequest(session_id=sess.id, text=SR_QUESTION, want_audio=True), sess)
    assert resp.outcome == "answered" and resp.sentences and resp.audio_url is None
    (event,) = _events(db, sess.id)
    assert event.outcome == "answered" and event.payload["want_audio"] is True


# --- translated ---------------------------------------------------------------------------------
def test_scripted_english_sentence_for_a_serbian_question_is_translated(
    settings: Settings, db, providers: Providers
) -> None:
    question = "What is emergency contraception?"
    chunks = Retriever(db, providers.embedder, settings).search(
        question, lang="sr", top_k=settings.retrieval_top_k, topic=classify_topic(question)
    )
    assert chunks[0].lang == "en"
    verbatim = split_sentences(chunks[0].text)[0]
    llm = ScriptedLLM([f"{verbatim} [S1]"])
    pipeline = AskPipeline(settings, db, dataclasses.replace(providers, llm=llm))
    sess = _session(db)
    resp = pipeline.ask(AskRequest(session_id=sess.id, text=question, lang="sr", script="cyrillic"), sess)
    assert resp.outcome == "answered" and resp.translated is True
    assert resp.message == t("translated_note", "sr", "cyrillic")
    assert len(resp.sentences) == 1 and resp.sentences[0].citations == ["S1"]
    assert resp.citations[0].marker == "S1" and resp.citations[0].lang == "en"
    assert resp.citations[0].source_title == chunks[0].source_title  # titles are never transliterated
    assert len(llm.calls) == 1 and question in llm.calls[0][1]
    (event,) = _events(db, sess.id)
    assert event.payload["translated"] is True


def test_saved_question_records_lang_and_outcome(pipeline: AskPipeline, db) -> None:
    sess = _session(db, consent_save_questions=True, lang="en")
    pipeline.ask(AskRequest(session_id=sess.id, text=OFF_KB_QUESTION), sess)
    pipeline.ask(AskRequest(session_id=sess.id, text=CYRILLIC_RED_FLAG, lang="sr"), sess)
    db.expire_all()
    saved = list(db.scalars(select(SavedQuestion).where(SavedQuestion.session_id == sess.id)))
    assert [(q.text, q.lang, q.outcome) for q in saved] == [
        (OFF_KB_QUESTION, "en", "withheld"),
        (CYRILLIC_RED_FLAG, "sr", "redflag"),
    ]
