"""``POST /api/transcribe``: speech to text for a consented session; the audio dies here.

The upload is written under a random name into ``MILA_AUDIO_TMP_DIR`` (created ``0700``,
file ``0600``), transcribed, and overwritten + unlinked by :func:`secure_delete` in a
``finally`` block, so it is gone on success, on a size error and on an STT failure. The
event written afterwards carries language, latency and the recording's duration only; the
transcript is returned to the client and never stored or logged.

The recogniser is ``request.app.state.stt`` when the application set one, otherwise it is
created once through :func:`get_stt` and cached there.
"""

from __future__ import annotations

import logging
import os
import secrets
import time
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session as DbSession

from app.api.deps import get_db, get_settings_dep, require_consented_session
from app.config import Settings
from app.core.events import log_event
from app.core.i18n import coerce_lang
from app.core.privacy import secure_delete
from app.core.types import Lang, Transcript
from app.services.stt import STT, get_stt

log = logging.getLogger("mila.api.transcribe")

router = APIRouter()

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
_CHUNK_BYTES = 64 * 1024
# Browser recorders produce WebM/Ogg (Opus) or MP4/M4A (AAC); WAV comes from tests and tools;
# octet-stream covers clients that do not label the blob.
_SUFFIX_BY_CONTENT_TYPE: dict[str, str] = {
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "audio/m4a": ".m4a",
    "application/octet-stream": ".bin",
}
ALLOWED_CONTENT_TYPES: frozenset[str] = frozenset(_SUFFIX_BY_CONTENT_TYPE)


class TranscribeResponse(Transcript):
    """A transcript plus the instruction to show it and ask the user to confirm before asking."""

    confirm_required: Literal[True] = True


def _stt_for(request: Request, settings: Settings) -> STT:
    stt = getattr(request.app.state, "stt", None)
    if stt is None:
        stt = get_stt(settings)
        request.app.state.stt = stt
    return stt


def _normalised_content_type(upload: UploadFile) -> str:
    return (upload.content_type or "").split(";", 1)[0].strip().lower()


def _spool_upload(upload: UploadFile, path: Path) -> int:
    """Copy the upload into ``path`` (created ``0600``) in chunks; 413 past the size limit."""
    total = 0
    upload.file.seek(0)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as out:
        while True:
            chunk = upload.file.read(_CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail="audio larger than 10 MB")
            out.write(chunk)
    if total == 0:
        raise HTTPException(status_code=422, detail="empty audio")
    return total


@router.post(
    "/transcribe",
    response_model=TranscribeResponse,
    responses={
        403: {"description": "Unknown session or consent not given"},
        413: {"description": "Recording larger than 10 MB"},
        415: {"description": "Unsupported audio content type"},
    },
)
def transcribe(
    request: Request,
    file: Annotated[UploadFile, File(description="Recording: WAV, WebM, Ogg, MP3 or MP4/M4A, at most 10 MB")],
    session_id: Annotated[str, Form(min_length=1, max_length=64)],
    lang: Annotated[
        Lang | None, Form(description="Expected language; defaults to the session language")
    ] = None,
    settings: Settings = Depends(get_settings_dep),
    db: DbSession = Depends(get_db),
) -> TranscribeResponse:
    sess = require_consented_session(session_id, db, settings)
    if not request.app.state.rate_limiter.allow(sess.id):
        raise HTTPException(status_code=429, detail="rate limited", headers={"Retry-After": "60"})
    content_type = _normalised_content_type(file)
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail="unsupported audio type")
    lang_hint = lang or coerce_lang(sess.lang)

    tmp_dir = Path(settings.audio_tmp_dir)
    tmp_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp_path = tmp_dir / f"{secrets.token_hex(16)}{_SUFFIX_BY_CONTENT_TYPE[content_type]}"
    started = time.perf_counter()
    try:
        _spool_upload(file, tmp_path)
        transcript = _stt_for(request, settings).transcribe(tmp_path, lang_hint=lang_hint)
    except HTTPException:
        raise
    except Exception:
        log_event(
            db,
            type="transcribe",
            session_id=session_id,
            lang=lang_hint,
            outcome="error",
            latency_ms=int((time.perf_counter() - started) * 1000),
            input_mode="voice",
        )
        raise
    finally:
        secure_delete(tmp_path)

    log_event(
        db,
        type="transcribe",
        session_id=session_id,
        lang=transcript.lang,
        outcome="ok",
        latency_ms=int((time.perf_counter() - started) * 1000),
        input_mode="voice",
        payload={"duration_s": round(transcript.duration_s, 2)},
    )
    return TranscribeResponse(**transcript.model_dump())
