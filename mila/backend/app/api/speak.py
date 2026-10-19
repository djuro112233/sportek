"""``POST /api/speak`` (text -> WAV) and one-time audio URLs (``GET /api/audio/{token}``).

``/speak`` needs no session: the consent text is spoken before a session exists. It is
rate-limited through ``request.app.state.rate_limiter`` keyed by the optional
``session_id`` query parameter (anonymous callers share one bucket; IPs are never used).
The event it writes carries language, latency and the ``low_bandwidth`` flag, never the text.

One-time audio URLs let ``/api/ask`` answer with ``audio_url`` instead of inlining a WAV:
the pipeline calls :func:`register_audio` and the browser fetches the token once. The store
is an in-memory, insertion-ordered dict with monotonic expiry timestamps, at most
:data:`AUDIO_MAX_ENTRIES` entries (the oldest is evicted first). It is single-process only:
with several uvicorn workers a token registered by one worker is unknown to the others, so
run one worker or put a shared store (e.g. the optional Redis) behind the same interface.

The synthesiser is ``request.app.state.tts`` when the application set one, otherwise it is
created once through :func:`get_tts` and cached there.
"""

from __future__ import annotations

import logging
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DbSession

from app.api.deps import get_db, get_settings_dep
from app.config import Settings
from app.core.events import log_event
from app.core.i18n import render
from app.core.types import Lang, Script
from app.models import Session as SessionRow
from app.services.tts import TTS, clean_for_speech, get_tts

log = logging.getLogger("mila.api.speak")

router = APIRouter()

AUDIO_MAX_ENTRIES = 200
AUDIO_DEFAULT_TTL_S = 300.0
_WAV_HEADERS = {"Content-Disposition": 'inline; filename="mila.wav"', "Cache-Control": "no-store"}


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1500)
    lang: Lang
    script: Script = "latin"
    low_bandwidth: bool = False


# --- one-time audio store -------------------------------------------------------------------
@dataclass(slots=True)
class _Entry:
    wav: bytes
    expires_at: float


class AudioStore:
    """Thread-safe one-time store: ``put`` returns a token, ``pop`` serves it once or ``None``.

    ``clock`` is injectable (defaults to ``time.monotonic``) so expiry is testable.
    """

    def __init__(self, *, max_entries: int = AUDIO_MAX_ENTRIES, clock: Callable[[], float] = time.monotonic):
        if max_entries < 1:
            raise ValueError("max_entries must be at least 1")
        self.max_entries = max_entries
        self.clock = clock
        self._entries: dict[str, _Entry] = {}  # insertion-ordered: the first key is the oldest
        self._lock = threading.Lock()

    def put(self, wav: bytes, ttl_s: float = AUDIO_DEFAULT_TTL_S) -> str:
        if not wav:
            raise ValueError("audio must not be empty")
        if ttl_s <= 0:
            raise ValueError("ttl_s must be positive")
        token = secrets.token_urlsafe(24)
        now = self.clock()
        with self._lock:
            self._purge_expired(now)
            while len(self._entries) >= self.max_entries:
                del self._entries[next(iter(self._entries))]
            self._entries[token] = _Entry(wav=wav, expires_at=now + ttl_s)
        return token

    def pop(self, token: str) -> bytes | None:
        now = self.clock()
        with self._lock:
            self._purge_expired(now)
            entry = self._entries.pop(token, None)
        return entry.wav if entry is not None else None

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def _purge_expired(self, now: float) -> None:
        for token in [t for t, e in self._entries.items() if e.expires_at <= now]:
            del self._entries[token]


audio_store = AudioStore()


def register_audio(wav_bytes: bytes, ttl_s: float = AUDIO_DEFAULT_TTL_S) -> str:
    """Store WAV bytes for one fetch within ``ttl_s`` seconds and return the token."""
    return audio_store.put(wav_bytes, ttl_s)


def audio_url(token: str) -> str:
    """The path (under the API prefix) at which :func:`register_audio`'s token is served."""
    return f"/api/audio/{token}"


# --- helpers ----------------------------------------------------------------------------------
def prepare_speech_text(text: str, lang: str, script: str = "latin") -> str:
    """Markers and Markdown removed, then rendered in the requested script (as answers are)."""
    return render(clean_for_speech(text), lang, script)


def _tts_for(request: Request, settings: Settings) -> TTS:
    tts = getattr(request.app.state, "tts", None)
    if tts is None:
        tts = get_tts(settings)
        request.app.state.tts = tts
    return tts


def _wav_response(wav: bytes) -> Response:
    return Response(content=wav, media_type="audio/wav", headers=_WAV_HEADERS)


# --- routes -----------------------------------------------------------------------------------
@router.post(
    "/speak",
    response_class=Response,
    responses={
        200: {"content": {"audio/wav": {}}, "description": "PCM WAV, mono 16-bit"},
        422: {"description": "Text empty (also after removing markers) or longer than 1500 characters"},
        429: {"description": "Rate limit for this session exceeded"},
    },
)
def speak(
    body: SpeakRequest,
    request: Request,
    session_id: Annotated[str | None, Query(max_length=64)] = None,
    settings: Settings = Depends(get_settings_dep),
    db: DbSession = Depends(get_db),
) -> Response:
    if not request.app.state.rate_limiter.allow(session_id or "anonymous"):
        raise HTTPException(status_code=429, detail="rate limited", headers={"Retry-After": "60"})
    text = prepare_speech_text(body.text, body.lang, body.script)
    if not text:
        raise HTTPException(status_code=422, detail="nothing to speak")

    started = time.perf_counter()
    wav = _tts_for(request, settings).synthesize(text, body.lang, low_bandwidth=body.low_bandwidth)
    known_session = session_id if session_id and db.get(SessionRow, session_id) is not None else None
    log_event(
        db,
        type="speak",
        session_id=known_session,
        lang=body.lang,
        outcome="ok",
        latency_ms=int((time.perf_counter() - started) * 1000),
        payload={"low_bandwidth": body.low_bandwidth},
    )
    return _wav_response(wav)


@router.get(
    "/audio/{token}",
    response_class=Response,
    responses={
        200: {"content": {"audio/wav": {}}, "description": "Served once; the token is then gone"},
        404: {"description": "Unknown, expired or already fetched token"},
    },
)
def get_audio(token: str) -> Response:
    wav = audio_store.pop(token)
    if wav is None:
        raise HTTPException(status_code=404, detail="audio not found")
    return _wav_response(wav)
