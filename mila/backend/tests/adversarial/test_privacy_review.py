"""Privacy findings from the 2026-10-20 adversarial review (PRIV-1 .. PRIV-10)."""

from __future__ import annotations

import logging
import wave
from datetime import UTC, datetime
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.metrics import compute_public_metrics
from app.api.speak import AudioStore, audio_store
from app.config import Settings
from app.core.events import log_event
from app.core.privacy import RedactionFilter, redact
from app.main import _RateLimiter, create_app
from app.models import Event
from app.models import Session as SessionRow
from tests.conftest import make_test_settings

QUESTION = "Imam 16 godina, trudna sam i krvarim, moj momak ima 30 godina MOCKMARKER"


def _consent(client: TestClient, settings: Settings, **overrides) -> str:
    body = {"lang": "sr", "is_minor": False, "accepted": True, "consent_version": settings.consent_version}
    body.update(overrides)
    r = client.post("/api/consent", json=body)
    assert r.status_code == 200, r.text
    return r.json()["session_id"]


# --- PRIV-1: tracebacks and SQL parameters never carry user text ---------------------------------
def test_redaction_filter_covers_exception_text() -> None:
    flt = RedactionFilter()
    try:
        raise RuntimeError(f"INSERT INTO saved_questions VALUES ('{QUESTION}', 'a@b.com', '+387 65 123 456')")
    except RuntimeError:
        import sys

        record = logging.LogRecord("t", logging.ERROR, __file__, 1, "boom", (), sys.exc_info())
    assert flt.filter(record)
    assert record.exc_info is None and record.exc_text
    assert "a@b.com" not in record.exc_text and "[EMAIL]" in record.exc_text
    assert "+387 65 123 456" not in record.exc_text


def test_sql_errors_hide_bound_parameters(tmp_path) -> None:
    from sqlalchemy import text

    from app.db import make_engine

    engine = make_engine(f"sqlite:///{tmp_path / 'p.db'}")
    with pytest.raises(Exception) as excinfo:
        with engine.connect() as conn:
            conn.execute(text("INSERT INTO missing_table (t) VALUES (:t)"), {"t": QUESTION})
    assert "MOCKMARKER" not in str(excinfo.value) and "hidden" in str(excinfo.value)


def test_saved_question_storage_failure_never_leaks_or_breaks(tmp_path, monkeypatch, caplog) -> None:
    settings = make_test_settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        sid = _consent(client, settings, save_questions=True, is_minor=True)
        from app.models import SavedQuestion

        def boom(self, *a, **k):  # the INSERT fails at commit time
            raise RuntimeError(f"disk full while writing {QUESTION}")

        monkeypatch.setattr(SavedQuestion, "__init__", boom)
        with caplog.at_level(logging.DEBUG):
            r = client.post("/api/ask", json={"session_id": sid, "text": QUESTION})
        assert r.status_code == 200 and r.json()["outcome"] == "redflag"
        assert "MOCKMARKER" not in caplog.text and "MOCKMARKER" not in r.text


# --- PRIV-2: complementary suppression -----------------------------------------------------------
def _seed(
    db, *, days: dict[str, int], outcomes: dict[str, int], modes: dict[str, int] | None = None, now: datetime
):
    for day, count in days.items():
        for _ in range(count):
            db.add(
                SessionRow(
                    id=f"s{day}{_}",
                    created_at=datetime.fromisoformat(day).replace(tzinfo=UTC),
                    consent_given=True,
                )
            )
    db.commit()
    i = 0
    for outcome, count in outcomes.items():
        for _ in range(count):
            mode = "text"
            if modes:
                mode = "voice" if i < modes.get("voice", 0) else "text"
            db.add(
                Event(
                    session_id=None,
                    type="ask",
                    outcome=outcome,
                    created_at=now,
                    input_mode=mode,
                    topic_class="other",
                )
            )
            i += 1
    db.commit()


def test_total_is_hidden_when_it_would_reveal_a_suppressed_day(db) -> None:
    now = datetime(2026, 10, 20, 12, tzinfo=UTC)
    _seed(db, days={"2026-10-17": 5, "2026-10-18": 1}, outcomes={}, now=now)
    m = compute_public_metrics(db, 5, 30, now)
    assert m.sessions_per_day == [] or m.sessions_total is None
    assert not (m.sessions_total == 6 and any(r.count == 5 for r in m.sessions_per_day))


def test_ratios_only_when_every_outcome_count_is_public(db) -> None:
    now = datetime(2026, 10, 20, 12, tzinfo=UTC)
    _seed(db, days={}, outcomes={"answered": 10, "withheld": 5, "redflag": 1}, modes={"voice": 1}, now=now)
    m = compute_public_metrics(db, 5, 30, now)
    assert m.outcomes.redflag is None
    assert m.ratios.answered is None and m.referral_rate is None and m.redflag_rate is None
    assert m.input_modes.text is None and m.input_modes.voice is None


def test_public_window_must_be_a_fixed_choice(client) -> None:
    assert client.get("/api/metrics/public", params={"window_days": 29}).status_code == 422
    assert client.get("/api/metrics/public", params={"window_days": 30}).status_code == 200


# --- PRIV-3: consent version ---------------------------------------------------------------------
def test_old_consent_version_is_refused_until_re_consent(tmp_path) -> None:
    settings = make_test_settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        sid = _consent(client, settings)
        assert client.get(f"/api/session/{sid}").json()["consent_version"] == settings.consent_version
        app.state.settings = settings.model_copy(update={"consent_version": "2027-01-01"})
        r = client.post("/api/ask", json={"session_id": sid, "text": "Koje metode kontracepcije postoje?"})
        assert r.status_code == 403 and r.json()["detail"] == "consent_version_outdated"
        r = client.post(f"/api/session/{sid}/preferences", json={"save_questions": True})
        assert r.status_code == 403
        r = client.post(
            "/api/transcribe",
            data={"session_id": sid},
            files={"file": ("a.wav", b"MOCK:zdravo", "audio/wav")},
        )
        assert r.status_code == 403


# --- PRIV-4: tokens in paths are redacted ---------------------------------------------------------
def test_session_ids_and_audio_tokens_are_redacted_from_paths() -> None:
    assert "[TOKEN]" in redact("GET /api/session/smRiz9DpAbCdEfGhIjKlMnOpQrStUv/preferences")
    assert "[TOKEN]" in redact("POST /api/speak?session_id=smRiz9DpAbCdEfGh")
    assert "[TOKEN]" in redact("GET /api/audio/0A1vugevAbCdEfGhIjKlMnOpQrStUv")


# --- PRIV-5: rate limiter bounds and budgets ------------------------------------------------------
def test_rate_limiter_is_bounded_and_forgettable() -> None:
    limiter = _RateLimiter(3, max_keys=100)
    for i in range(1000):
        assert limiter.allow(f"k{i}")
    assert len(limiter) <= 100
    assert limiter.allow("x", limit=1) and not limiter.allow("x", limit=1)
    limiter.forget("x")
    assert limiter.allow("x", limit=1)


def test_speak_anonymous_bucket_and_forged_ids(tmp_path) -> None:
    settings = make_test_settings(tmp_path, rate_limit_per_minute=2)
    app = create_app(settings)
    with TestClient(app) as client:
        body = {"text": "Zdravo", "lang": "sr"}
        # forged ids do not open their own buckets: they share the anonymous one (10x budget)
        statuses = [
            client.post("/api/speak", params={"session_id": f"forged{i}"}, json=body).status_code
            for i in range(25)
        ]
        assert statuses[:20] == [200] * 20 and statuses[20] == 429
        assert len(app.state.rate_limiter) <= 1


def test_transcribe_and_consent_are_rate_limited(tmp_path) -> None:
    settings = make_test_settings(tmp_path, rate_limit_per_minute=1)
    app = create_app(settings)
    with TestClient(app) as client:
        sid = _consent(client, settings)
        files = {"file": ("a.wav", b"MOCK:zdravo", "audio/wav")}
        assert client.post("/api/transcribe", data={"session_id": sid}, files=files).status_code == 200
        assert client.post("/api/transcribe", data={"session_id": sid}, files=files).status_code == 429
        statuses = [
            client.post(
                "/api/consent",
                json={
                    "lang": "sr",
                    "is_minor": False,
                    "accepted": True,
                    "consent_version": settings.consent_version,
                },
            ).status_code
            for _ in range(12)
        ]
        assert 429 in statuses


def test_oversized_bodies_are_refused_before_reading(client) -> None:
    r = client.post(
        "/api/ask",
        content=b"{}",
        headers={"content-type": "application/json", "content-length": str(5_000_000)},
    )
    assert r.status_code == 413 and r.headers["x-content-type-options"] == "nosniff"


# --- PRIV-7: audio tokens die with the session ---------------------------------------------------
def test_audio_tokens_are_dropped_on_delete_and_capped_per_session(tmp_path) -> None:
    settings = make_test_settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        sid = _consent(client, settings)
        r = client.post(
            "/api/ask",
            json={
                "session_id": sid,
                "text": "Koje metode kontracepcije postoje i kako djeluju?",
                "want_audio": True,
            },
        )
        url = r.json().get("audio_url")
        if url:  # the demo KB is not ingested in this app; audio is produced for red flags too
            pass
        r = client.post(
            "/api/ask", json={"session_id": sid, "text": "јако крварим, трудна сам", "want_audio": True}
        )
        url = r.json()["audio_url"]
        assert url
        assert client.delete(f"/api/session/{sid}").json()["deleted"]["audio_tokens"] >= 1
        assert client.get(url).status_code == 404
    store = AudioStore()
    tokens = [store.put(b"x", session_id="a") for _ in range(5)]
    assert sum(1 for t in tokens if store.pop(t)) == 3


# --- PRIV-8: payload codes only ------------------------------------------------------------------
@pytest.mark.parametrize(
    "payload",
    [
        {"q": "Trudna sam i krvarim"},
        {"meta": {"text": "x"}},
        {"items": [{"transcript": "x"}]},
        {"tеxt": "x"},  # Cyrillic homoglyph key
        {"stage": "Trudna sam i krvarim"},
        {"note": "hello world"},
    ],
)
def test_log_event_rejects_free_text_anywhere(db, payload) -> None:
    with pytest.raises(ValueError):
        log_event(db, type="ask", session_id=None, payload=payload)


def test_log_event_accepts_codes_and_numbers(db) -> None:
    ev = log_event(
        db,
        type="ask",
        session_id=None,
        payload={
            "gate_reasons": ["low_relevance"],
            "relevance": 0.4,
            "error": "RuntimeError",
            "nested": {"ok": True},
        },
    )
    assert db.scalar(select(Event).where(Event.id == ev.id)) is not None


def test_referral_region_is_validated(client) -> None:
    assert client.get("/api/referral", params={"region": "zz0abcd"}).status_code == 422
    assert client.get("/api/referral", params={"region": "XX"}).status_code == 422


# --- PRIV-9: headers on 500 ----------------------------------------------------------------------
def test_internal_errors_carry_security_headers(tmp_path, monkeypatch) -> None:
    settings = make_test_settings(tmp_path)
    app = create_app(settings)
    with TestClient(app, raise_server_exceptions=False) as client:
        from app.api import consent as consent_module

        monkeypatch.setattr(consent_module, "delete_session_data", lambda *a, **k: 1 / 0)
        r = client.delete("/api/session/abcdefghijklmnopqrstuvwx")
        assert r.status_code == 500 and r.headers["x-frame-options"] == "DENY"
        assert r.headers["cache-control"] == "no-store"


# --- PRIV-10: admin token ------------------------------------------------------------------------
def test_wrong_admin_token_is_refused_with_compare_digest(client) -> None:
    assert client.get("/api/admin/sources", headers={"X-Admin-Token": "test-admin-tokeN"}).status_code == 403
    assert client.get("/api/admin/sources", headers={"X-Admin-Token": "test-admin-token"}).status_code == 200


def _wav() -> bytes:
    buf = BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * 800)
    return buf.getvalue()


def test_audio_store_global_cap_does_not_evict_other_sessions_first() -> None:
    store = AudioStore(max_entries=4)
    mine = store.put(_wav(), session_id="me")
    for _i in range(10):
        store.put(_wav(), session_id="other")
    # the other session is capped at 3 of its own tokens, so mine survives
    assert store.pop(mine) is not None
    audio_store.clear()
