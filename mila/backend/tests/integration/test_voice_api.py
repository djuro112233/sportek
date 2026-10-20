"""Integration tests for POST /api/transcribe, POST /api/speak and GET /api/audio/{token}."""

from __future__ import annotations

import io
import json
import stat
import wave
from pathlib import Path

import pytest
from conftest import make_test_settings
from fastapi.testclient import TestClient
from sqlalchemy import select

import app.api.speak as speak_module
import app.api.transcribe as transcribe_module
from app.api.speak import AudioStore, audio_store, audio_url, register_audio
from app.api.transcribe import MAX_UPLOAD_BYTES
from app.core.privacy import new_session_id
from app.core.types import Transcript
from app.main import create_app
from app.models import Event
from app.models import Session as SessionRow
from app.services.stt import MOCK_DEFAULT_TEXT
from app.services.tts import MockTTS

MOCK_TEXT = "Koliko traje trudnoća i kada je prvi pregled?"
MOCK_WORDS = ("trudno", "pregled")


@pytest.fixture(autouse=True)
def _fresh_audio_store():
    audio_store.clear()
    yield
    audio_store.clear()


def _session(db, *, consented: bool = True, lang: str = "sr") -> str:
    sid = new_session_id()
    db.add(
        SessionRow(
            id=sid, lang=lang, consent_given=consented, consent_version="2026-10-01" if consented else ""
        )
    )
    db.commit()
    return sid


def _wav_bytes(seconds: float = 0.5, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"\x00\x00" * int(seconds * rate))
    return buf.getvalue()


def _params(wav: bytes) -> tuple[int, int, int, int]:
    with wave.open(io.BytesIO(wav), "rb") as wf:
        return wf.getnchannels(), wf.getsampwidth(), wf.getframerate(), wf.getnframes()


def _post_audio(client: TestClient, sid: str, data: bytes, *, content_type: str = "audio/wav", **form):
    return client.post(
        "/api/transcribe",
        files={"file": ("q.wav", data, content_type)},
        data={"session_id": sid, **form},
    )


def _events(db, type_: str) -> list[Event]:
    db.expire_all()
    return list(db.scalars(select(Event).where(Event.type == type_).order_by(Event.id)))


def _assert_no_text(event: Event, words: tuple[str, ...]) -> None:
    dump = json.dumps(
        {c.name: str(getattr(event, c.name)) for c in Event.__table__.columns}, ensure_ascii=False
    )
    for word in words:
        assert word not in dump, f"event must not carry user text ({word!r})"


def _audio_dir(settings) -> Path:
    return Path(settings.audio_tmp_dir)


# --- /api/transcribe --------------------------------------------------------------------------
def test_transcribe_403_for_unknown_session(client: TestClient) -> None:
    resp = _post_audio(client, "no-such-session", b"MOCK:zdravo")
    assert resp.status_code == 403


def test_transcribe_403_without_consent(client: TestClient, db) -> None:
    sid = _session(db, consented=False)
    resp = _post_audio(client, sid, b"MOCK:zdravo")
    assert resp.status_code == 403
    assert "consent" in resp.json()["detail"]


def test_transcribe_415_for_unsupported_type(client: TestClient, db, settings) -> None:
    sid = _session(db)
    assert _post_audio(client, sid, b"MOCK:zdravo", content_type="text/plain").status_code == 415
    assert _post_audio(client, sid, b"MOCK:zdravo", content_type="video/mp4").status_code == 415
    assert not _audio_dir(settings).exists() or not any(_audio_dir(settings).iterdir())


def test_transcribe_413_for_oversized_upload(client: TestClient, db, settings) -> None:
    sid = _session(db)
    resp = _post_audio(client, sid, b"\x00" * (MAX_UPLOAD_BYTES + 1))
    assert resp.status_code == 413
    audio_dir = _audio_dir(settings)
    assert not audio_dir.exists() or list(audio_dir.iterdir()) == []


def test_transcribe_mock_payload_returns_transcript(client: TestClient, db, settings) -> None:
    sid = _session(db)
    resp = _post_audio(client, sid, f"MOCK:{MOCK_TEXT}|bs".encode(), content_type="audio/webm;codecs=opus")
    assert resp.status_code == 200
    assert resp.json() == {
        "text": MOCK_TEXT,
        "lang": "bs",
        "confidence": 1.0,
        "duration_s": 0.0,
        "confirm_required": True,
    }
    audio_dir = _audio_dir(settings)
    assert list(audio_dir.iterdir()) == [], "upload deleted right after transcription"
    assert stat.S_IMODE(audio_dir.stat().st_mode) & 0o077 == 0, "temp dir not readable by others"


def test_transcribe_wav_uses_session_language_and_header_duration(client: TestClient, db) -> None:
    sid = _session(db, lang="hr")
    resp = _post_audio(client, sid, _wav_bytes(0.5), content_type="audio/x-wav")
    assert resp.status_code == 200
    body = resp.json()
    assert body["text"] == MOCK_DEFAULT_TEXT
    assert body["lang"] == "hr"
    assert body["confidence"] == 0.5
    assert body["duration_s"] == pytest.approx(0.5)


def test_transcribe_lang_form_field(client: TestClient, db) -> None:
    sid = _session(db, lang="hr")
    assert _post_audio(client, sid, _wav_bytes(), lang="en").json()["lang"] == "en"
    assert _post_audio(client, sid, _wav_bytes(), lang="de").status_code == 422


def test_transcribe_rejects_empty_upload(client: TestClient, db, settings) -> None:
    sid = _session(db)
    assert _post_audio(client, sid, b"").status_code == 422
    assert list(_audio_dir(settings).iterdir()) == []


def test_transcribe_deletes_file_even_when_stt_raises(app, db, settings, monkeypatch) -> None:
    class ExplodingSTT:
        def __init__(self) -> None:
            self.seen: list[tuple[Path, bool, int]] = []

        def transcribe(self, path: Path, *, lang_hint: str | None = None) -> Transcript:
            self.seen.append((Path(path), Path(path).exists(), Path(path).stat().st_size))
            raise RuntimeError("model crashed")

    fake = ExplodingSTT()
    monkeypatch.setattr(transcribe_module, "get_stt", lambda _settings: fake)
    sid = _session(db)
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = _post_audio(client, sid, f"MOCK:{MOCK_TEXT}".encode())

    assert resp.status_code == 500
    assert resp.json() == {"detail": "internal error"}
    path, existed_during_call, size = fake.seen[0]
    assert existed_during_call and size == len(f"MOCK:{MOCK_TEXT}".encode())
    assert path.parent == _audio_dir(settings)
    assert not path.exists()
    assert list(_audio_dir(settings).iterdir()) == []
    errors = [e for e in _events(db, "transcribe") if e.outcome == "error"]
    assert len(errors) == 1 and errors[0].input_mode == "voice" and errors[0].payload == {}
    _assert_no_text(errors[0], MOCK_WORDS)


def test_transcribe_event_carries_no_text(client: TestClient, db) -> None:
    sid = _session(db)
    assert _post_audio(client, sid, f"MOCK:{MOCK_TEXT}|sr".encode()).status_code == 200
    events = _events(db, "transcribe")
    assert len(events) == 1
    ev = events[0]
    assert ev.session_id == sid
    assert ev.lang == "sr"
    assert ev.input_mode == "voice"
    assert ev.outcome == "ok"
    assert ev.latency_ms is not None and ev.latency_ms >= 0
    assert ev.payload == {"duration_s": 0.0}
    _assert_no_text(ev, MOCK_WORDS)


def test_transcribe_uses_stt_from_app_state(app, db) -> None:
    class FixedSTT:
        def transcribe(self, path: Path, *, lang_hint: str | None = None) -> Transcript:
            return Transcript(text="fiksno", lang=lang_hint or "sr", confidence=0.9, duration_s=3.0)

    app.state.stt = FixedSTT()
    sid = _session(db, lang="me")
    with TestClient(app) as client:
        body = _post_audio(client, sid, _wav_bytes()).json()
    assert body["text"] == "fiksno" and body["lang"] == "me" and body["duration_s"] == 3.0


# --- /api/speak -------------------------------------------------------------------------------
def test_speak_returns_wav_with_no_store_headers(client: TestClient) -> None:
    resp = client.post("/api/speak", json={"text": "Ovo su opšte informacije.", "lang": "sr"})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/wav"
    assert resp.headers["content-disposition"].startswith("inline")
    assert resp.headers["cache-control"] == "no-store"
    assert _params(resp.content)[:3] == (1, 2, 16000)
    assert resp.content == MockTTS().synthesize("Ovo su opšte informacije.", "sr")


def test_speak_strips_markers_and_markdown(client: TestClient) -> None:
    text = "**Pilula** se uzima svaki dan [S1]. Kondom štiti od infekcija [S2, S3]."
    resp = client.post("/api/speak", json={"text": text, "lang": "sr"})
    assert resp.status_code == 200
    clean = "Pilula se uzima svaki dan. Kondom štiti od infekcija."
    assert resp.content == MockTTS().synthesize(clean, "sr")
    assert _params(resp.content)[3] == 9 * 960


def test_speak_renders_cyrillic_when_requested(client: TestClient) -> None:
    payload = {"text": "Pozovi odmah.", "lang": "sr", "script": "cyrillic"}
    assert client.post("/api/speak", json=payload).status_code == 200
    assert speak_module.prepare_speech_text("Pozovi odmah [S1].", "sr", "cyrillic") == "Позови одмах."
    assert speak_module.prepare_speech_text("Call now [S1].", "en", "cyrillic") == "Call now."


@pytest.mark.parametrize(
    "payload",
    [
        {"text": "", "lang": "sr"},
        {"text": "x" * 1501, "lang": "sr"},
        {"text": "[S1] [S2]", "lang": "sr"},
        {"text": "zdravo", "lang": "de"},
        {"lang": "sr"},
    ],
)
def test_speak_422_for_invalid_input(client: TestClient, payload: dict) -> None:
    assert client.post("/api/speak", json=payload).status_code == 422


def test_speak_low_bandwidth_is_8k(client: TestClient) -> None:
    resp = client.post(
        "/api/speak", json={"text": "Režim za slabu vezu", "lang": "sr", "low_bandwidth": True}
    )
    assert resp.status_code == 200
    assert _params(resp.content)[:3] == (1, 2, 8000)


def test_speak_event_carries_no_text(client: TestClient, db) -> None:
    sid = _session(db)
    text = "Hvala što si mi rekla. Ovo nije tvoja krivica."
    resp = client.post(
        f"/api/speak?session_id={sid}", json={"text": text, "lang": "bs", "low_bandwidth": True}
    )
    assert resp.status_code == 200
    events = _events(db, "speak")
    assert len(events) == 1
    ev = events[0]
    assert ev.session_id == sid
    assert ev.lang == "bs"
    assert ev.outcome == "ok"
    assert ev.payload == {"low_bandwidth": True}
    assert ev.latency_ms is not None and ev.latency_ms >= 0
    _assert_no_text(ev, ("Hvala", "krivica"))


def test_speak_unknown_session_is_logged_anonymously(client: TestClient, db) -> None:
    resp = client.post("/api/speak?session_id=not-a-session", json={"text": "Pozovi odmah.", "lang": "sr"})
    assert resp.status_code == 200
    events = _events(db, "speak")
    assert len(events) == 1 and events[0].session_id is None and events[0].payload == {"low_bandwidth": False}


def test_speak_is_rate_limited_per_session(tmp_path: Path) -> None:
    settings = make_test_settings(tmp_path, rate_limit_per_minute=2)
    app = create_app(settings)
    with TestClient(app) as client:
        consent = {"lang": "sr", "is_minor": False, "accepted": True, "consent_version": settings.consent_version}
        abc = client.post("/api/consent", json=consent).json()["session_id"]
        xyz = client.post("/api/consent", json=consent).json()["session_id"]
        codes = [
            client.post(f"/api/speak?session_id={abc}", json={"text": "Pozovi odmah.", "lang": "sr"}).status_code
            for _ in range(3)
        ]
        other = client.post(f"/api/speak?session_id={xyz}", json={"text": "Pozovi odmah.", "lang": "sr"})
        limited = client.post(f"/api/speak?session_id={abc}", json={"text": "Pozovi odmah.", "lang": "sr"})
    assert codes == [200, 200, 429]
    assert other.status_code == 200
    assert limited.status_code == 429 and limited.headers["retry-after"] == "60"


# --- one-time audio URLs ---------------------------------------------------------------------
def test_audio_token_is_served_once(client: TestClient) -> None:
    wav = MockTTS().synthesize("Poslušaj", "sr")
    token = register_audio(wav)
    assert audio_url(token) == f"/api/audio/{token}"
    first = client.get(audio_url(token))
    assert first.status_code == 200
    assert first.content == wav
    assert first.headers["content-type"] == "audio/wav"
    assert first.headers["cache-control"] == "no-store"
    assert first.headers["content-disposition"].startswith("inline")
    assert client.get(audio_url(token)).status_code == 404


def test_audio_unknown_token_404(client: TestClient) -> None:
    assert client.get("/api/audio/does-not-exist").status_code == 404
    assert client.get("/api/audio/").status_code in (404, 405)


def test_audio_token_expires(client: TestClient, monkeypatch) -> None:
    now = 1000.0
    monkeypatch.setattr(audio_store, "clock", lambda: now)
    short = register_audio(b"RIFFshort", ttl_s=10)
    long = register_audio(b"RIFFlong", ttl_s=300)
    now = 1010.0  # the 10 s token expires at exactly 1010
    assert client.get(audio_url(short)).status_code == 404
    assert client.get(audio_url(long)).status_code == 200
    again = register_audio(b"RIFFagain")  # default ttl 300 s
    now = 1310.0
    assert client.get(audio_url(again)).status_code == 404
    assert len(audio_store) == 0


def test_audio_store_evicts_oldest_at_capacity() -> None:
    clock = [0.0]
    store = AudioStore(max_entries=2, clock=lambda: clock[0])
    t1 = store.put(b"one")
    t2 = store.put(b"two")
    t3 = store.put(b"three")
    assert len(store) == 2
    assert store.pop(t1) is None
    assert store.pop(t2) == b"two"
    assert store.pop(t3) == b"three"
    assert store.pop(t3) is None
    with pytest.raises(ValueError):
        store.put(b"")
    with pytest.raises(ValueError):
        store.put(b"x", ttl_s=0)
    with pytest.raises(ValueError):
        AudioStore(max_entries=0)


def test_audio_default_store_capacity_is_200() -> None:
    tokens = [register_audio(b"wav" + bytes([i % 256])) for i in range(201)]
    assert len(audio_store) == 200
    assert audio_store.pop(tokens[0]) is None
    assert audio_store.pop(tokens[1]) == b"wav\x01"
