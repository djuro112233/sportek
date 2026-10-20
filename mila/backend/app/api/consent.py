"""Consent and session lifecycle: ``/consent``, ``/consent/text`` and ``/session/{id}``.

A session exists only after an explicit, versioned consent. Everything stored about it is
listed in docs/data-protection.md; the request model forbids any other field, so a client
cannot smuggle an age, a name or a device id into the session row.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete
from sqlalchemy.orm import Session as DbSession

from app.api.deps import get_db, get_settings_dep, require_consented_session
from app.config import Settings
from app.core.consent_texts import ConsentText, build_consent_text
from app.core.events import log_event
from app.core.privacy import delete_session_data, new_session_id
from app.core.referral import REGIONS
from app.core.types import Lang, Script
from app.models import SavedQuestion, Session, utcnow

router = APIRouter(tags=["consent"])

_REGION_RE = re.compile(r"^[A-Z]{2}$")
_SESSION_ID = Path(min_length=1, max_length=64, description="Pseudonymous session id")


def _normalise_region(value: str | None) -> str | None:
    """Upper-case ISO 3166-1 alpha-2 code, or ``None`` to fall back to the configured default."""
    if value is None:
        return None
    code = value.strip().upper()
    if not _REGION_RE.match(code):
        raise ValueError("region must be a 2-letter ISO country code")
    if code not in REGIONS:
        raise ValueError(f"region must be one of {sorted(REGIONS)}")
    return code


class ConsentRequest(BaseModel):
    """The act of consent. ``extra='forbid'`` rejects anything that is not in the data map."""

    model_config = ConfigDict(extra="forbid")

    lang: Lang
    script: Script = "latin"
    region: str | None = Field(default=None, description="ISO country code; default from settings")
    is_minor: bool
    accepted: bool
    save_questions: bool = False
    consent_version: str = Field(min_length=1, max_length=32)

    @field_validator("region")
    @classmethod
    def _validate_region(cls, value: str | None) -> str | None:
        return _normalise_region(value)


class ConsentResponse(BaseModel):
    session_id: str
    consent_version: str
    lang: str
    script: str
    region: str
    is_minor: bool
    save_questions: bool


class SessionInfo(BaseModel):
    """Everything the server knows about a session. All fields are ``None`` when it does not exist."""

    exists: bool
    consent_given: bool | None = None
    consent_version: str | None = None
    lang: str | None = None
    script: str | None = None
    region: str | None = None
    is_minor: bool | None = None
    save_questions: bool | None = None


class PreferencesRequest(BaseModel):
    """Changeable session settings. Unknown fields are dropped, never stored (the web client
    also sends UI-only preferences such as ``low_bandwidth``)."""

    model_config = ConfigDict(extra="ignore")

    save_questions: bool | None = None
    lang: Lang | None = None
    script: Script | None = None
    region: str | None = None
    is_minor: bool | None = None

    @field_validator("region")
    @classmethod
    def _validate_region(cls, value: str | None) -> str | None:
        return _normalise_region(value)


class DeleteResponse(BaseModel):
    deleted: dict[str, int]


def _session_info(sess: Session) -> SessionInfo:
    return SessionInfo(
        exists=True,
        consent_given=sess.consent_given,
        consent_version=sess.consent_version,
        lang=sess.lang,
        script=sess.script,
        region=sess.region,
        is_minor=sess.is_minor,
        save_questions=sess.consent_save_questions,
    )


@router.get("/consent/text", response_model=ConsentText)
def consent_text(
    lang: Lang = Query("sr"),
    script: Script = Query("latin"),
    is_minor: bool = Query(False),
    settings: Settings = Depends(get_settings_dep),
) -> ConsentText:
    """The consent copy to show and read aloud, with the version the client must echo back."""
    return build_consent_text(lang, script, is_minor, version=settings.consent_version)


@router.post("/consent", response_model=ConsentResponse, responses={403: {}, 409: {}, 422: {}})
def give_consent(
    body: ConsentRequest,
    request: Request,
    db: DbSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> ConsentResponse | JSONResponse:
    """Create a pseudonymous session. Nothing is stored unless the current text was accepted."""
    limiter = request.app.state.rate_limiter
    if not limiter.allow("consent", limit=limiter.per_minute * 10):
        raise HTTPException(status_code=429, detail="rate limited", headers={"Retry-After": "60"})
    if not body.accepted:
        return JSONResponse(status_code=403, content={"detail": "consent_required"})
    if body.consent_version != settings.consent_version:
        return JSONResponse(
            status_code=409,
            content={"detail": "consent_version_outdated", "current": settings.consent_version},
        )
    region = body.region or settings.default_region
    sess = Session(
        id=new_session_id(),
        lang=body.lang,
        script=body.script,
        region=region,
        is_minor=body.is_minor,
        consent_given=True,
        consent_version=body.consent_version,
        consent_save_questions=body.save_questions,
        consent_given_at=utcnow(),
    )
    db.add(sess)
    db.commit()
    log_event(
        db,
        type="consent",
        session_id=sess.id,
        lang=body.lang,
        payload={"is_minor": body.is_minor, "save_questions": body.save_questions},
    )
    return ConsentResponse(
        session_id=sess.id,
        consent_version=sess.consent_version,
        lang=sess.lang,
        script=sess.script,
        region=sess.region,
        is_minor=body.is_minor,
        save_questions=sess.consent_save_questions,
    )


@router.get("/session/{session_id}", response_model=SessionInfo)
def get_session(session_id: str = _SESSION_ID, db: DbSession = Depends(get_db)) -> SessionInfo:
    """Session settings for the UI; an unknown id answers ``exists: false`` rather than an error."""
    sess = db.get(Session, session_id)
    if sess is None:
        return SessionInfo(exists=False)
    return _session_info(sess)


@router.post("/session/{session_id}/preferences", response_model=SessionInfo, responses={403: {}})
def update_preferences(
    body: PreferencesRequest,
    session_id: str = _SESSION_ID,
    db: DbSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> SessionInfo:
    """Change language, script, region, minor flag or the save-questions opt-in.

    Turning ``save_questions`` off deletes the session's saved questions immediately, so the
    switch is a withdrawal of that consent and not just a flag.
    """
    sess = require_consented_session(session_id, db, settings)
    if body.lang is not None:
        sess.lang = body.lang
    if body.script is not None:
        sess.script = body.script
    if body.region is not None:
        sess.region = body.region
    if body.is_minor is not None:
        sess.is_minor = body.is_minor
    if body.save_questions is not None:
        if not body.save_questions:
            db.execute(delete(SavedQuestion).where(SavedQuestion.session_id == sess.id))
        sess.consent_save_questions = body.save_questions
    db.commit()
    db.refresh(sess)
    return _session_info(sess)


@router.delete("/session/{session_id}", response_model=DeleteResponse)
def delete_session(
    request: Request, session_id: str = _SESSION_ID, db: DbSession = Depends(get_db)
) -> DeleteResponse:
    """ "Delete my data": erase the session and everything linked to it. Idempotent."""
    counts = delete_session_data(db, session_id)
    from app.api.speak import audio_store  # local import: speak imports deps too

    counts["audio_tokens"] = audio_store.drop_session(session_id)
    limiter = getattr(request.app.state, "rate_limiter", None)
    if limiter is not None:
        limiter.forget(session_id)
    log_event(db, type="delete", session_id=None)
    return DeleteResponse(deleted=counts)
