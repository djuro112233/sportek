"""Voice-first onboarding: record → speech-to-text → draft → confirm → validation queue → publish.

What the model does and does not do
-----------------------------------
The model only ever rephrases the host's own words into a **title and a description**
(``services/extraction.draft_title_and_description``). **Price, dates/season, capacity and
accessibility are never inferred**: they are asked as explicit form fields, filled in by the host and
actively confirmed (``confirmed_fields``) before :func:`confirm` will create the listing. A confirm
call whose ``confirmed_fields`` does not cover price, season, capacity, accessibility and coordinates
is rejected with 422.

Two clocks, logged separately
-----------------------------
* **active authoring time** (``active_seconds``) — accumulated from client heartbeats sent while the
  wizard is open and the tab is focused. A single heartbeat delta is capped at
  :data:`MAX_HEARTBEAT_DELTA` seconds so a tab left open cannot inflate it. The ≤ 30 min target
  (``ONBOARDING_TARGET_MINUTES``, KPI K06/K07) refers to the *median* of this value only.
* **elapsed time** (``elapsed_to_confirm_seconds`` / ``elapsed_to_publish_seconds``) — wall clock from
  the start of the session. Publication time includes waiting for a validator, which the platform does
  not control, so it is reported (K08) but never compared with the authoring target.

Offline capture
---------------
The PWA records into IndexedDB when there is no connectivity and uploads later. The upload then carries
``offline_captured=true`` and ``captured_at`` (when the recording was actually made);
``upload_deferred_seconds`` is how long the recording waited in the browser. See docs/onboarding.md.

Privacy
-------
Events are pseudonymised (app/pseudonym.py) and carry no transcript, no free text and no user id. The
audio file is deleted as soon as it has been transcribed unless ``KEEP_AUDIO=true``. The timing log
exposed to institutions carries session ids and durations only — never a user id.
"""
from __future__ import annotations

import logging
import uuid
import wave
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException, status as http_status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import REPO_DIR, settings
from ..events import emit_event
from ..models import ConsentRecord, Listing, OnboardingSession, User, Village, utcnow
from ..providers.stt import audio_duration_seconds, get_stt
from . import budget, content, extraction, validation

log = logging.getLogger(__name__)

#: A single heartbeat may not add more than two minutes of "active" time.
MAX_HEARTBEAT_DELTA = 120
#: Upload limit for one recording.
MAX_AUDIO_BYTES = 25 * 1024 * 1024
#: Container formats the PWA may upload (MediaRecorder produces webm/ogg; iOS produces m4a/mp4).
AUDIO_EXTENSIONS: frozenset[str] = frozenset({".webm", ".ogg", ".oga", ".wav", ".m4a", ".mp3", ".mp4"})
AUDIO_CONTENT_TYPES: dict[str, str] = {
    "audio/webm": ".webm", "video/webm": ".webm",
    "audio/ogg": ".ogg", "application/ogg": ".ogg", "audio/vorbis": ".ogg",
    "audio/wav": ".wav", "audio/x-wav": ".wav", "audio/wave": ".wav", "audio/vnd.wave": ".wav",
    "audio/mp4": ".m4a", "audio/x-m4a": ".m4a", "audio/m4a": ".m4a",
    "audio/mpeg": ".mp3", "audio/mp3": ".mp3", "video/mp4": ".mp4",
}

#: Host-chosen listing categories. The model never picks one — the host does, on the form.
LISTING_CATEGORIES: tuple[str, ...] = (
    "accommodation", "food", "guiding", "craft", "experience", "transport", "other",
)

#: Statuses in which the session has produced its listing and accepts no further capture. A late
#: deferred upload, or a typed transcript sent after the fact, would otherwise reopen it.
CLOSED_STATUSES: frozenset[str] = frozenset({"confirmed", "published"})

#: The host must actively confirm each of these groups. Any alias in ``confirmed_fields`` counts, so
#: both the compact form (``["price", "season", …]``) and the per-column form
#: (``["price_min", "price_max", "season_from", …]``) are accepted.
CONFIRMATION_GROUPS: dict[str, tuple[str, ...]] = {
    "price": ("price", "price_range", "price_min", "price_max"),
    "season": ("season", "season_from", "season_to", "season_all_year", "dates"),
    "capacity": ("capacity",),
    "accessibility": (
        "accessibility", "accessibility_step_free", "accessibility_note",
        "accessibility_note_local", "accessibility_note_en",
    ),
    "coordinates": ("coordinates", "lat", "lng", "location"),
}

TIMING_LOG_PATH = REPO_DIR / "docs" / "test-results" / "onboarding_timing.log"
TIMING_LOG_HEADER = (
    "# Active authoring time vs elapsed time, one line per confirmed/published onboarding session.\n"
    "# Appended by app/services/onboarding.py. Session ids and durations only — no user id, no name,\n"
    "# no transcript. active_s is the KPI K06/K07 input; elapsed_* include waiting for a validator.\n"
)


# --------------------------------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------------------------------
def target_seconds() -> int:
    return int(settings.onboarding_target_minutes) * 60


def within_active_target(active_seconds: float) -> bool:
    """K07: was the *active* authoring time within the target? Waiting for review never counts."""
    return float(active_seconds) <= target_seconds()


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _since_start(session: OnboardingSession, when: datetime | None = None) -> float:
    started = _aware(session.started_at) or utcnow()
    return round(max(0.0, ((when or utcnow()) - started).total_seconds()), 3)


def parse_captured_at(value: str | None) -> datetime | None:
    """ISO 8601 from the PWA ('2026-09-09T10:00:00Z' or with an offset). Naive input is read as UTC."""
    if value is None or not str(value).strip():
        return None
    try:
        dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="captured_at must be an ISO 8601 timestamp",
        ) from exc
    return _aware(dt)


def resolve_village(db: Session, value: str | uuid.UUID | None) -> Village | None:
    """A village by slug or id; 404 when it does not exist. ``None`` passes through."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    uid = content.parse_uuid(value)
    stmt = select(Village).where(Village.id == uid) if uid else select(Village).where(Village.slug == str(value).strip())
    village = db.scalars(stmt).first()
    if village is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="village not found")
    return village


def get_session(db: Session, session_id: uuid.UUID | str) -> OnboardingSession:
    uid = content.parse_uuid(session_id)
    session = db.get(OnboardingSession, uid) if uid else None
    if session is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="onboarding session not found")
    return session


def may_write(session: OnboardingSession, user: User) -> bool:
    """Only the host of the session, or the ambassador who started it on their behalf, may write."""
    return user.id in (session.host_user_id, session.ambassador_user_id)


def may_read(session: OnboardingSession, user: User) -> bool:
    """Writers plus any ambassador or validator (they staff the queue and the timing log)."""
    return may_write(session, user) or user.role in ("ambassador", "validator")


def require_write(session: OnboardingSession, user: User) -> None:
    if not may_write(session, user):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN, detail="this onboarding session belongs to another host"
        )


def require_read(session: OnboardingSession, user: User) -> None:
    if not may_read(session, user):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN, detail="this onboarding session belongs to another host"
        )


def is_closed(session: OnboardingSession) -> bool:
    """True once the host has confirmed the listing: the session's own work is finished."""
    return session.status in CLOSED_STATUSES or session.listing_id is not None


def require_open_for_capture(session: OnboardingSession, *, what: str = "recording") -> None:
    """Refuse new capture on a session that already produced a listing.

    A deferred upload can arrive minutes or hours after the host confirmed the listing (the PWA
    keeps recordings in IndexedDB). Accepting it would run :func:`transcribe` over a finished
    session, set ``transcript_ready_at`` again and push ``status`` back to ``transcribed`` — while
    ``confirmed_at``, ``elapsed_to_confirm_seconds`` and the listing stay in place. The timing log
    that validators and institutions read would then carry a *confirmed* session's durations under
    the status of an unfinished one. There is nothing to repair afterwards, so the API refuses the
    late upload with 409 and the browser drops the recording from its queue.
    """
    if is_closed(session):
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=(
                f"this onboarding session is already {session.status} and its listing exists — "
                f"a late {what} is not accepted, because it would reopen a finished session"
            ),
        )


def _host_of(db: Session, session: OnboardingSession) -> User | None:
    """The event actor is always the HOST: the pseudonym and any voluntary gender self-report are the
    host's, even when an ambassador operates the wizard for them."""
    return db.get(User, session.host_user_id)


def _village_of(db: Session, session: OnboardingSession) -> Village | None:
    return db.get(Village, session.village_id) if session.village_id else None


# --------------------------------------------------------------------------------------------------
# 1. start
# --------------------------------------------------------------------------------------------------
def start_session(
    db: Session,
    *,
    actor: User,
    language: str | None = None,
    village: str | uuid.UUID | None = None,
    host_user_id: str | uuid.UUID | None = None,
) -> OnboardingSession:
    """Open a session. An ambassador may onboard **on behalf of** a host; a host only themselves."""
    lang = (language or settings.local_language).strip().lower()
    if lang not in (settings.local_language, "en"):
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"language must be '{settings.local_language}' or 'en'",
        )

    ambassador: User | None = None
    if actor.role == "host":
        wanted = content.parse_uuid(host_user_id) if host_user_id else None
        if wanted is not None and wanted != actor.id:
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="only an ambassador may open an onboarding session on behalf of another host",
            )
        host = actor
    elif actor.role == "ambassador":
        wanted = content.parse_uuid(host_user_id) if host_user_id else None
        if wanted is None:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="host_user_id is required when an ambassador onboards on behalf of a host",
            )
        host = db.get(User, wanted)
        if host is None or host.role != "host":
            raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="host not found")
        ambassador = actor
    else:  # pragma: no cover - the router already restricts the roles
        raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail="role may not start an onboarding session")

    village_row = resolve_village(db, village) or (db.get(Village, host.village_id) if host.village_id else None)

    session = OnboardingSession(
        host_user_id=host.id,
        ambassador_user_id=ambassador.id if ambassador else None,
        village_id=village_row.id if village_row else None,
        language=lang,
        status="started",
        started_at=utcnow(),
        llm_provider=settings.llm_provider,
    )
    db.add(session)
    db.flush()
    emit_event(
        db,
        "onboarding_started",
        actor=host,  # the pseudonym and the voluntary gender self-report belong to the HOST
        item_type="onboarding_session",
        item_id=session.id,
        village=village_row,
        language=lang,
        via_ambassador=ambassador is not None,
    )
    log.info("onboarding session %s started (via_ambassador=%s)", session.id, ambassador is not None)
    return session


# --------------------------------------------------------------------------------------------------
# 2. heartbeat — the measurement of ACTIVE authoring time
# --------------------------------------------------------------------------------------------------
def add_heartbeat(db: Session, session: OnboardingSession, active_seconds_delta: float) -> float:
    """Accumulate active authoring time. One delta is capped at :data:`MAX_HEARTBEAT_DELTA`."""
    delta = max(0.0, min(float(active_seconds_delta), float(MAX_HEARTBEAT_DELTA)))
    session.active_seconds = round(float(session.active_seconds or 0.0) + delta, 3)
    db.flush()
    return session.active_seconds


# --------------------------------------------------------------------------------------------------
# 3. audio upload → speech-to-text (background job)
# --------------------------------------------------------------------------------------------------
def record_upload(
    db: Session,
    session: OnboardingSession,
    *,
    offline_captured: bool,
    captured_at: datetime | None,
    uploaded_at: datetime | None = None,
) -> None:
    """Store the offline-capture contract of one upload before the transcription job starts."""
    uploaded_at = uploaded_at or utcnow()
    session.offline_captured = bool(offline_captured)
    if captured_at is not None:
        session.captured_at = captured_at
        session.upload_deferred_seconds = round(max(0.0, (uploaded_at - captured_at).total_seconds()), 3)
    elif offline_captured:
        session.upload_deferred_seconds = None
    if offline_captured:
        session.status = "captured_offline"
    db.flush()


def _wav_duration(path: Path) -> float | None:
    try:
        with wave.open(str(path), "rb") as w:
            rate = w.getframerate()
            return round(w.getnframes() / rate, 2) if rate else None
    except Exception:  # not a WAV, or unreadable
        return None


def audio_duration(path: Path) -> float | None:
    """Duration in seconds: the container's own metadata, with a stdlib WAV fallback."""
    return audio_duration_seconds(path) or _wav_duration(path)


def _stt_language(session_language: str) -> str:
    """Whisper has no 'cnr' code; ``STT_LANGUAGE`` (default 'hr') yields Latin-script output."""
    return "en" if session_language == "en" else settings.stt_language


def _delete_audio(path: Path) -> None:
    """Delete the recording (and its now-empty session folder) unless KEEP_AUDIO is set."""
    if settings.keep_audio:
        log.warning("KEEP_AUDIO=true — the recording %s is kept on disk", path.name)
        return
    try:
        path.unlink(missing_ok=True)
        parent = path.parent
        if parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
    except OSError as exc:  # pragma: no cover - filesystem edge case
        log.warning("could not delete the recording (%s)", exc.__class__.__name__)


def transcribe_job(session_id: str, audio_path: str) -> dict:
    """RQ job (module level, opens its own session). In ``QUEUE_MODE=sync`` it runs inline."""
    from ..db import SessionLocal

    with SessionLocal() as db:
        return transcribe(db, session_id, Path(audio_path))


def transcribe(db: Session, session_id: str | uuid.UUID, path: Path) -> dict:
    """Transcribe one recording, store the result, emit ``transcript_ready``, delete the audio."""
    session = db.get(OnboardingSession, content.parse_uuid(session_id))
    if session is None:  # pragma: no cover - the row is committed before the job is enqueued
        log.error("transcription job for unknown onboarding session")
        return {"status": "failed", "error": "unknown_session"}
    try:
        stt = get_stt()
        result = stt.transcribe(path, language=_stt_language(session.language))
        duration = result.duration_s if result.duration_s else audio_duration(path)
    except Exception as exc:
        log.error("speech-to-text failed (%s)", exc.__class__.__name__)
        _delete_audio(path)
        db.commit()
        return {"status": "failed", "error": exc.__class__.__name__}

    now = utcnow()
    session.transcript = result.text
    session.stt_provider = result.provider
    session.stt_model = result.model
    session.audio_duration_s = duration
    session.transcript_ready_at = now
    session.status = "transcribed"

    if getattr(result, "billable", False):
        budget.record_stt(db, result.provider, result.model, float(duration or 0.0), billable=True)

    emit_event(
        db,
        "transcript_ready",
        actor=_host_of(db, session),
        item_type="onboarding_session",
        item_id=session.id,
        village=_village_of(db, session),
        stt_provider=result.provider,
        stt_model=result.model,
        audio_duration_s=duration,
        transcript_chars=len(result.text or ""),
        offline_captured=bool(session.offline_captured),
        upload_deferred_seconds=session.upload_deferred_seconds,
        seconds_since_start=_since_start(session, now),
    )
    _delete_audio(path)
    db.commit()
    log.info("onboarding session %s transcribed with %s", session.id, result.provider)
    return {
        "status": session.status,
        "transcript": session.transcript,
        "stt": {
            "provider": session.stt_provider,
            "model": session.stt_model,
            "audio_duration_s": session.audio_duration_s,
            "language": result.language,
        },
    }


# --------------------------------------------------------------------------------------------------
# 4. typed / corrected transcript
# --------------------------------------------------------------------------------------------------
def set_transcript(db: Session, session: OnboardingSession, text: str) -> OnboardingSession:
    """A typed transcript, or the host's correction of the machine transcript."""
    text = (text or "").strip()
    if not text:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT, detail="text must not be empty"
        )
    now = utcnow()
    session.transcript = text
    session.stt_provider = "typed"
    session.stt_model = ""
    session.transcript_ready_at = now
    session.status = "transcribed"
    db.flush()
    emit_event(
        db,
        "transcript_ready",
        actor=_host_of(db, session),
        item_type="onboarding_session",
        item_id=session.id,
        village=_village_of(db, session),
        stt_provider="typed",
        stt_model="",
        audio_duration_s=None,
        transcript_chars=len(text),
        offline_captured=bool(session.offline_captured),
        upload_deferred_seconds=session.upload_deferred_seconds,
        seconds_since_start=_since_start(session, now),
    )
    return session


# --------------------------------------------------------------------------------------------------
# 5. draft — title and description ONLY
# --------------------------------------------------------------------------------------------------
def generate_draft(db: Session, session: OnboardingSession) -> dict:
    """Title + description in both languages. Never a price, a date, a capacity or an accessibility fact."""
    if not (session.transcript or "").strip():
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="record or type the description first — there is no transcript to draft from",
        )
    village = _village_of(db, session)
    village_name = (village.name_en if session.language == "en" else village.name_local) if village else ""
    result = extraction.draft_title_and_description(
        session.transcript, session.language, village_name=village_name, db=db
    )
    fields = {k: result["fields"].get(k, "") for k in extraction.FIELD_NAMES}
    now = utcnow()
    session.draft = {
        "fields": fields,
        "extraction_method": result["extraction_method"],
        "translation_pending": bool(result["translation_pending"]),
        "fields_required": list(result["fields_required"]),
    }
    session.llm_provider = result.get("llm_provider", settings.llm_provider)
    session.draft_generated_at = now
    session.status = "drafted"
    db.flush()
    emit_event(
        db,
        "draft_generated",
        actor=_host_of(db, session),
        item_type="onboarding_session",
        item_id=session.id,
        village=village,
        llm_provider=session.llm_provider,
        extraction_method=result["extraction_method"],
        translation_pending=bool(result["translation_pending"]),
        seconds_since_start=_since_start(session, now),
        active_seconds=float(session.active_seconds or 0.0),
    )
    return {
        "draft": fields,
        "extraction_method": result["extraction_method"],
        "translation_pending": bool(result["translation_pending"]),
        "fields_required": list(result["fields_required"]),
    }


# --------------------------------------------------------------------------------------------------
# 6. confirm — the host's explicit, confirmed structured fields
# --------------------------------------------------------------------------------------------------
def unconfirmed_groups(confirmed_fields: list[str]) -> list[str]:
    """Which of price / season / capacity / accessibility / coordinates the host did NOT confirm."""
    given = {str(f).strip().lower() for f in confirmed_fields or []}
    return [group for group, aliases in CONFIRMATION_GROUPS.items() if not given.intersection(aliases)]


def missing_structured_fields(data: dict) -> list[str]:
    """Confirmed but still empty — the validator sees this on the queue card."""
    missing: list[str] = []
    if data.get("price_min") is None and data.get("price_max") is None:
        missing.append("price")
    if not data.get("season_all_year") and data.get("season_from") is None and data.get("season_to") is None:
        missing.append("season")
    if data.get("capacity") is None:
        missing.append("capacity")
    if data.get("accessibility_step_free") is None and not (
        data.get("accessibility_note_local") or data.get("accessibility_note_en")
    ):
        missing.append("accessibility")
    if data.get("lat") is None or data.get("lng") is None:
        missing.append("coordinates")
    return missing


def confirm(
    db: Session,
    session: OnboardingSession,
    *,
    actor: User,
    listing_in: dict,
    consent_in: dict,
) -> dict:
    """Consent record → listing in ``draft`` (validation queue) → timings, event and timing-log line."""
    if session.listing_id is not None:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT, detail="this onboarding session already produced a listing"
        )
    if not bool(consent_in.get("given")):
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="the host must give consent before the listing is created",
        )

    confirmed_fields = [str(f) for f in (listing_in.get("confirmed_fields") or [])]
    unconfirmed = unconfirmed_groups(confirmed_fields)
    if unconfirmed:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "the host must confirm every structured field the model never fills; "
                f"not confirmed: {', '.join(unconfirmed)}"
            ),
        )

    category = str(listing_in.get("category") or "other").strip().lower()
    if category not in LISTING_CATEGORIES:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"category must be one of: {', '.join(LISTING_CATEGORIES)}",
        )

    village = resolve_village(db, listing_in.get("village")) or _village_of(db, session)
    if village is None:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="village is required (slug or id) — every listing belongs to a village of the territory",
        )

    title_local = " ".join(str(listing_in.get("title_local") or "").split())
    title_en = " ".join(str(listing_in.get("title_en") or "").split())
    if not title_local and not title_en:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT, detail="title_local is required"
        )

    draft = session.draft or {}
    consent = ConsentRecord(
        host_user_id=session.host_user_id,
        ambassador_user_id=session.ambassador_user_id,
        onboarding_session_id=session.id,
        consent_text_version=str(consent_in.get("text_version") or "v1")[:32],
        consent_given=True,
        method=str(consent_in.get("method") or "checkbox")[:32],
        given_at=utcnow(),
    )
    db.add(consent)
    db.flush()

    data = {
        "slug": content.unique_slug(db, Listing, content.slugify(title_local or title_en)),
        "host_user_id": session.host_user_id,
        "village_id": village.id,
        "category": category,
        "title_local": title_local or title_en,
        "title_en": title_en,
        "description_local": str(listing_in.get("description_local") or ""),
        "description_en": str(listing_in.get("description_en") or ""),
        # --- host-entered, host-confirmed. No model ever writes these. ---
        "price_min": listing_in.get("price_min"),
        "price_max": listing_in.get("price_max"),
        "currency": str(listing_in.get("currency") or "EUR").upper()[:3],
        "price_note_local": str(listing_in.get("price_note_local") or ""),
        "price_note_en": str(listing_in.get("price_note_en") or ""),
        "season_from": listing_in.get("season_from"),
        "season_to": listing_in.get("season_to"),
        "season_all_year": bool(listing_in.get("season_all_year", False)),
        "capacity": listing_in.get("capacity"),
        "accessibility_step_free": listing_in.get("accessibility_step_free"),
        "accessibility_note_local": str(listing_in.get("accessibility_note_local") or ""),
        "accessibility_note_en": str(listing_in.get("accessibility_note_en") or ""),
        "confirmed_fields": confirmed_fields,
        "lat": listing_in.get("lat"),
        "lng": listing_in.get("lng"),
        "coords_approximate": bool(listing_in.get("coords_approximate", True)),
        "photo_url": str(listing_in.get("photo_url") or ""),
        "is_sample": True,
        "extraction_method": str(draft.get("extraction_method") or "manual"),
        "translation_pending": bool(draft.get("translation_pending", False)),
        "onboarding_session_id": session.id,
        "consent_record_id": consent.id,
    }
    data["missing_fields"] = missing_structured_fields(data)

    listing = validation.create_item(
        db,
        "listing",
        data,
        actor=actor,
        source=f"voice onboarding session {session.id}",
        note="host-confirmed structured fields; title and description drafted from the host's own words",
    )
    consent.listing_id = listing.id

    now = utcnow()
    session.confirmed_at = now
    session.elapsed_to_confirm_seconds = _since_start(session, now)
    session.listing_id = listing.id
    session.status = "confirmed"
    active = float(session.active_seconds or 0.0)
    in_target = within_active_target(active)
    db.flush()

    emit_event(
        db,
        "listing_confirmed",
        actor=_host_of(db, session),  # the HOST, even when an ambassador operated the wizard
        item_type="listing",
        item_id=listing.id,
        village=village,
        onboarding_session_id=str(session.id),
        active_seconds=active,
        elapsed_to_confirm_seconds=session.elapsed_to_confirm_seconds,
        within_active_target=in_target,
        category=listing.category,
        extraction_method=listing.extraction_method,
        offline_captured=bool(session.offline_captured),
    )
    append_timing_log(session, event="confirmed")
    return {
        "listing": listing,
        "consent_record_id": consent.id,
        "active_seconds": active,
        "elapsed_to_confirm_seconds": session.elapsed_to_confirm_seconds,
        "target_minutes": settings.onboarding_target_minutes,
        "within_active_target": in_target,
    }


# --------------------------------------------------------------------------------------------------
# 7. publication timing
# --------------------------------------------------------------------------------------------------
def session_of_listing(db: Session, listing: Listing) -> OnboardingSession | None:
    """The onboarding session a listing came from, or ``None`` for a manually created listing."""
    if getattr(listing, "onboarding_session_id", None):
        session = db.get(OnboardingSession, listing.onboarding_session_id)
        if session is not None:
            return session
    return db.scalars(select(OnboardingSession).where(OnboardingSession.listing_id == listing.id)).first()


def mark_published(db: Session, listing: Listing) -> float | None:
    """Close the *elapsed* clock when a listing born of an onboarding session is approved.

    ``services/validation.transition`` calls this after it has set ``published_at`` on an approved
    listing, and puts the returned value into the ``entry_approved`` event as
    ``elapsed_to_publish_seconds`` (KPI K08). This function flushes and leaves the commit to that
    transition.

    Returns the elapsed wall-clock seconds from the start of the session to publication — which
    includes waiting for the validator and is therefore **never** compared with the active-authoring
    target — or ``None`` for a listing that did not come from the voice wizard. Calling it twice for
    the same listing is a no-op.
    """
    session = session_of_listing(db, listing)
    if session is None:
        return None
    already_published = session.published_at is not None and session.status == "published"
    published = _aware(listing.published_at) or utcnow()
    session.published_at = session.published_at if already_published else published
    session.elapsed_to_publish_seconds = _since_start(session, session.published_at)
    session.status = "published"
    db.flush()
    if not already_published:
        append_timing_log(session, event="published")
        log.info(
            "onboarding session %s published after %.0f s elapsed (active %.0f s)",
            session.id, session.elapsed_to_publish_seconds, session.active_seconds or 0.0,
        )
    return session.elapsed_to_publish_seconds


# --------------------------------------------------------------------------------------------------
# 8. timing log (file) and timing log (API)
# --------------------------------------------------------------------------------------------------
def _fmt(value: float | None) -> str:
    return "-" if value is None else f"{float(value):.0f}"


def append_timing_log(session: OnboardingSession, *, event: str) -> None:
    """One line per milestone in ``docs/test-results/onboarding_timing.log``. No user id, no name."""
    line = (
        f"{utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')}  event={event}  session={session.id}  "
        f"active_s={_fmt(session.active_seconds)}  "
        f"elapsed_to_confirm_s={_fmt(session.elapsed_to_confirm_seconds)}  "
        f"elapsed_to_publish_s={_fmt(session.elapsed_to_publish_seconds)}  "
        f"within_active_target={str(within_active_target(session.active_seconds or 0.0)).lower()}  "
        f"target_min={settings.onboarding_target_minutes}  "
        f"offline_captured={str(bool(session.offline_captured)).lower()}  "
        f"upload_deferred_s={_fmt(session.upload_deferred_seconds)}  "
        f"stt={session.stt_provider or '-'}  llm={session.llm_provider or '-'}  status={session.status}\n"
    )
    try:
        TIMING_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        new_file = not TIMING_LOG_PATH.exists()
        with TIMING_LOG_PATH.open("a", encoding="utf-8") as fh:
            if new_file:
                fh.write(TIMING_LOG_HEADER)
            fh.write(line)
    except OSError as exc:  # pragma: no cover - a read-only checkout must never break onboarding
        log.warning("could not append to the onboarding timing log (%s)", exc.__class__.__name__)


def timing_log(db: Session, limit: int = 200) -> list[dict]:
    """Timings for the validator/institution dashboard. Session ids and durations only."""
    rows = db.scalars(
        select(OnboardingSession).order_by(OnboardingSession.started_at.desc()).limit(limit)
    ).all()
    return [
        {
            "session_id": str(s.id),
            "started_at": s.started_at,
            "active_seconds": float(s.active_seconds or 0.0),
            "elapsed_to_confirm_seconds": s.elapsed_to_confirm_seconds,
            "elapsed_to_publish_seconds": s.elapsed_to_publish_seconds,
            "within_active_target": within_active_target(s.active_seconds or 0.0) if s.confirmed_at else None,
            "offline_captured": bool(s.offline_captured),
            "stt_provider": s.stt_provider,
            "llm_provider": s.llm_provider,
            "status": s.status,
        }
        for s in rows
    ]


def session_state(session: OnboardingSession) -> dict:
    """The session as the wizard sees it: state, both clocks and the offline-capture contract."""
    return {
        "id": session.id,
        "host_user_id": session.host_user_id,
        "ambassador_user_id": session.ambassador_user_id,
        "village_id": session.village_id,
        "language": session.language,
        "status": session.status,
        "started_at": session.started_at,
        "captured_at": session.captured_at,
        "transcript_ready_at": session.transcript_ready_at,
        "draft_generated_at": session.draft_generated_at,
        "confirmed_at": session.confirmed_at,
        "published_at": session.published_at,
        "active_seconds": float(session.active_seconds or 0.0),
        "elapsed_to_confirm_seconds": session.elapsed_to_confirm_seconds,
        "elapsed_to_publish_seconds": session.elapsed_to_publish_seconds,
        "target_minutes": settings.onboarding_target_minutes,
        "within_active_target": within_active_target(session.active_seconds or 0.0),
        "offline_captured": bool(session.offline_captured),
        "upload_deferred_seconds": session.upload_deferred_seconds,
        "audio_duration_s": session.audio_duration_s,
        "stt_provider": session.stt_provider,
        "stt_model": session.stt_model,
        "llm_provider": session.llm_provider,
        "transcript": session.transcript,
        "draft": session.draft or {},
        "listing_id": session.listing_id,
    }
