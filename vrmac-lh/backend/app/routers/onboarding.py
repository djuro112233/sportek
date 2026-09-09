"""/api/onboarding — voice-first, offline-capable listing creation.

Flow (docs/api-contract.md, docs/onboarding.md)::

    POST /sessions              open a session          -> onboarding_started
    POST /sessions/{id}/heartbeat   ACTIVE authoring time (the ≤ 30 min target measures this)
    POST /sessions/{id}/audio       multipart upload -> speech-to-text -> transcript_ready
    POST /sessions/{id}/transcript  typed or corrected transcript
    POST /sessions/{id}/draft       title + description ONLY -> draft_generated
    POST /sessions/{id}/confirm     consent + host-confirmed fields -> listing (draft) -> listing_confirmed
    GET  /sessions/{id}             session state and both clocks
    GET  /timing-log                active vs elapsed time per session (validator, institution)

The model never produces a price, a date, a capacity or an accessibility fact: those are explicit
fields the host fills in and confirms (``confirmed_fields``), and ``/confirm`` returns 422 when any of
them was not confirmed.
"""
from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ..auth import CurrentUser, require_role
from ..config import settings
from ..db import get_db
from ..models import User, utcnow
from ..queue import enqueue
from ..schemas import ListingOut
from ..services import onboarding as svc
from ..services.content import constraint_violations_as_409

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])

HostOrAmbassador = Annotated[User, Depends(require_role("host", "ambassador"))]
StaffReader = Annotated[User, Depends(require_role("validator", "institution"))]
Db = Annotated[Session, Depends(get_db)]

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


# --------------------------------------------------------------------------------------------------
# request bodies
# --------------------------------------------------------------------------------------------------
class SessionIn(BaseModel):
    language: str | None = None
    village: str | None = None  # slug or id
    host_user_id: uuid.UUID | None = None  # only an ambassador may onboard on behalf of a host


class HeartbeatIn(BaseModel):
    """One heartbeat of ACTIVE authoring time. A single delta is capped so a stuck tab cannot inflate it."""

    active_seconds_delta: float = Field(ge=1, le=svc.MAX_HEARTBEAT_DELTA)


class TranscriptIn(BaseModel):
    text: str = Field(min_length=1, max_length=20000)


class ListingIn(BaseModel):
    """The host's own listing. Structured fields are entered here and listed in ``confirmed_fields``."""

    model_config = ConfigDict(extra="forbid")

    title_local: str = ""
    title_en: str = ""
    description_local: str = ""
    description_en: str = ""
    category: str = "other"
    village: str | None = None
    # --- host-entered, host-confirmed; never model-inferred ---
    price_min: float | None = Field(default=None, ge=0, le=100000)
    price_max: float | None = Field(default=None, ge=0, le=100000)
    currency: str = "EUR"
    price_note_local: str = ""
    price_note_en: str = ""
    season_from: int | None = Field(default=None, ge=1, le=12)
    season_to: int | None = Field(default=None, ge=1, le=12)
    season_all_year: bool = False
    capacity: int | None = Field(default=None, ge=1, le=500)
    accessibility_step_free: bool | None = None
    accessibility_note_local: str = ""
    accessibility_note_en: str = ""
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    coords_approximate: bool = True
    photo_url: str = ""
    confirmed_fields: list[str] = Field(default_factory=list)


class ConsentIn(BaseModel):
    given: bool = False
    method: str = "checkbox"
    text_version: str = "v1"


class ConfirmIn(BaseModel):
    listing: ListingIn
    consent: ConsentIn


# --------------------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------------------
def _writable_session(db: Session, session_id: str, user: User):
    session = svc.get_session(db, session_id)
    svc.require_write(session, user)
    return session


def safe_basename(filename: str | None, fallback_ext: str = ".webm") -> str:
    """``../../etc/passwd`` → ``etc-passwd``. Keeps the stem so the fixture provider can find it."""
    base = Path(filename or "").name
    base = _UNSAFE.sub("-", base).strip("-._") or "recording"
    if not Path(base).suffix:
        base = f"{base}{fallback_ext}"
    return base[:120]


def audio_extension(basename: str, content_type: str | None) -> str:
    """The accepted container extension, or 415 for anything that is not an audio upload."""
    ext = Path(basename).suffix.lower()
    if ext in svc.AUDIO_EXTENSIONS:
        return ext
    ctype = (content_type or "").split(";")[0].strip().lower()
    if ctype in svc.AUDIO_CONTENT_TYPES:
        return svc.AUDIO_CONTENT_TYPES[ctype]
    raise HTTPException(
        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        detail=(
            "unsupported audio type — upload one of: "
            + ", ".join(sorted(e.lstrip('.') for e in svc.AUDIO_EXTENSIONS))
        ),
    )


def save_upload(file: UploadFile, destination: Path) -> int:
    """Stream the upload to disk, refusing anything over :data:`MAX_AUDIO_BYTES`."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    try:
        with destination.open("wb") as out:
            while chunk := file.file.read(1024 * 1024):
                total += len(chunk)
                if total > svc.MAX_AUDIO_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        detail=f"the recording is larger than {svc.MAX_AUDIO_BYTES // (1024 * 1024)} MB",
                    )
                out.write(chunk)
    except HTTPException:
        destination.unlink(missing_ok=True)
        raise
    if total == 0:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="the recording is empty")
    return total


# --------------------------------------------------------------------------------------------------
# endpoints
# --------------------------------------------------------------------------------------------------
@router.post("/sessions", status_code=status.HTTP_201_CREATED)
def start_session(payload: SessionIn, user: HostOrAmbassador, db: Db) -> dict[str, Any]:
    """Open a voice onboarding session. An ambassador may onboard on behalf of a host."""
    session = svc.start_session(
        db,
        actor=user,
        language=payload.language,
        village=payload.village,
        host_user_id=payload.host_user_id,
    )
    db.commit()
    db.refresh(session)
    return svc.session_state(session)


@router.post("/sessions/{session_id}/heartbeat")
def heartbeat(session_id: str, payload: HeartbeatIn, user: HostOrAmbassador, db: Db) -> dict[str, float]:
    """Accumulate ACTIVE authoring time — this, not the wall clock, is what the 30-minute target measures."""
    session = _writable_session(db, session_id, user)
    active = svc.add_heartbeat(db, session, payload.active_seconds_delta)
    db.commit()
    return {"active_seconds": active}


@router.post("/sessions/{session_id}/audio")
def upload_audio(
    session_id: str,
    user: HostOrAmbassador,
    db: Db,
    file: Annotated[UploadFile, File(description="the recording (webm, ogg, wav, m4a, mp3, mp4; ≤ 25 MB)")],
    offline_captured: Annotated[bool, Form(description="recorded without connectivity, kept in IndexedDB")] = False,
    captured_at: Annotated[str | None, Form(description="ISO 8601 — when the recording was made")] = None,
) -> dict[str, Any]:
    """Upload a recording and transcribe it.

    The PWA may record offline (IndexedDB) and upload later: it then sends ``offline_captured=true``
    and ``captured_at``, and the API stores how long the recording waited (``upload_deferred_seconds``).
    The audio file is deleted as soon as it is transcribed unless ``KEEP_AUDIO=true``.
    """
    session = _writable_session(db, session_id, user)
    captured = svc.parse_captured_at(captured_at)

    basename = safe_basename(file.filename)
    ext = audio_extension(basename, file.content_type)
    if Path(basename).suffix.lower() != ext:
        basename = f"{Path(basename).stem}{ext}"
    destination = Path(settings.upload_dir) / str(session.id) / basename

    uploaded_at = utcnow()
    save_upload(file, destination)
    svc.record_upload(db, session, offline_captured=offline_captured, captured_at=captured, uploaded_at=uploaded_at)
    db.commit()

    # The job is module level and opens its own database session: identical code path in RQ and in
    # QUEUE_MODE=sync, where it runs inline and the transcript comes back with this response.
    result = enqueue(svc.transcribe_job, str(session.id), str(destination))
    if not isinstance(result, dict):  # RQ: the worker will fill the transcript in
        return {
            "status": session.status,
            "transcript": None,
            "stt": {"provider": settings.stt_provider, "model": settings.stt_model, "queued": True},
        }
    if result.get("status") == "failed":
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="speech-to-text failed — try again, or type the description instead",
        )
    db.expire(session)
    db.refresh(session)
    return {"status": result["status"], "transcript": result["transcript"], "stt": result["stt"]}


@router.post("/sessions/{session_id}/transcript")
def set_transcript(session_id: str, payload: TranscriptIn, user: HostOrAmbassador, db: Db) -> dict[str, Any]:
    """A typed transcript (no microphone), or the host's correction of the machine transcript."""
    session = _writable_session(db, session_id, user)
    svc.set_transcript(db, session, payload.text)
    db.commit()
    db.refresh(session)
    return svc.session_state(session)


@router.post("/sessions/{session_id}/draft")
def generate_draft(session_id: str, user: HostOrAmbassador, db: Db) -> dict[str, Any]:
    """Draft the **title and description only** from the host's own words.

    ``fields_required`` lists the structured fields the host must still fill in and confirm: price,
    season, capacity, accessibility, coordinates, category and village. The model never fills them.
    """
    session = _writable_session(db, session_id, user)
    result = svc.generate_draft(db, session)
    db.commit()
    return result


@router.post("/sessions/{session_id}/confirm")
def confirm(session_id: str, payload: ConfirmIn, user: HostOrAmbassador, db: Db) -> dict[str, Any]:
    """Consent + host-confirmed fields → a listing in ``draft`` (i.e. in the validation queue)."""
    session = _writable_session(db, session_id, user)
    with constraint_violations_as_409(db):  # commits on success, 409 on a constraint violation
        result = svc.confirm(
            db,
            session,
            actor=user,
            listing_in=payload.listing.model_dump(),
            consent_in=payload.consent.model_dump(),
        )
    listing = result.pop("listing")
    db.refresh(listing)
    return {"listing": ListingOut.model_validate(listing), **result}


@router.get("/sessions/{session_id}")
def read_session(session_id: str, user: CurrentUser, db: Db) -> dict[str, Any]:
    """The session's state and both clocks: the owner host, its ambassador, any ambassador or validator."""
    session = svc.get_session(db, session_id)
    svc.require_read(session, user)
    return svc.session_state(session)


@router.get("/timing-log")
def timing_log(user: StaffReader, db: Db) -> list[dict[str, Any]]:
    """Active authoring time vs elapsed time per session. Session ids and durations only — no user id."""
    return svc.timing_log(db)
