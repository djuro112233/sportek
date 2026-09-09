"""/api/auth — login, the current user and the **voluntary** gender self-report.

Three endpoints, all of them audited:

* ``POST /api/auth/login`` — rate-limited; a failed attempt writes an audit row that deliberately
  carries **no e-mail address** (only the outcome), so the log cannot be turned into a list of who
  tried to sign in.
* ``GET  /api/auth/me`` — the caller's own record.
* ``POST /api/auth/me/gender`` — the *only* way ``gender_self_reported`` becomes true. Gender is
  disaggregated in the KPIs exclusively from this voluntary self-report; ``undisclosed`` (never
  answered) and ``prefer_not_to_say`` are excluded from every gender cell. A person can only ever
  report their own gender: the endpoint takes no user parameter and always writes to the token's
  subject. The audit row records **that** a self-report happened, never the value — the value next
  to a user id in an audit trail would be exactly the disclosure the voluntary regime avoids.
"""
from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..auth import CurrentUser, authenticate, create_access_token
from ..config import settings
from ..db import get_db
from ..models import GENDER_REPORTED, User
from ..ratelimit import limiter
from ..schemas import LoginIn, TokenOut, UserOut
from ..services import content

router = APIRouter(prefix="/api/auth", tags=["auth"])

#: The four answers a person may give. ``undisclosed`` is not offered: it is the default state of
#: someone who has never been asked, and no API call can put a person back into it by accident.
GenderChoice = Literal["female", "male", "other", "prefer_not_to_say"]


class GenderSelfReportIn(BaseModel):
    """Voluntary self-report. Extra fields (a user id, an e-mail…) are rejected on purpose:
    nobody may report a gender *for* somebody else."""

    model_config = {"extra": "forbid"}

    gender: GenderChoice = Field(description="female | male | other | prefer_not_to_say")


@router.post("/login", response_model=TokenOut, summary="Sign in with e-mail and password")
@limiter.limit(settings.rate_limit_public)
def login(
    request: Request,
    body: LoginIn,
    db: Annotated[Session, Depends(get_db)],
) -> TokenOut:
    """Exchange sample credentials for a short-lived JWT.

    The audit row for a *failed* attempt holds no e-mail address and no client address — only the
    fact that a login failed, with the request id for correlation.
    """
    user = authenticate(db, body.email, body.password)
    if user is None:
        record_audit(
            db,
            user=None,
            action="auth.login_failed",
            resource_type="user",
            detail={"outcome": "invalid_credentials"},  # never the e-mail that was tried
            request_id=content.request_id(request),
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid e-mail address or password"
        )
    record_audit(
        db,
        user=user,
        action="auth.login",
        resource_type="user",
        resource_id=str(user.id),
        detail={"outcome": "ok"},
        request_id=content.request_id(request),
    )
    db.commit()
    return TokenOut(access_token=create_access_token(user), user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut, summary="The signed-in user")
def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@router.post(
    "/me/gender",
    response_model=UserOut,
    summary="Voluntary gender self-report (the only way gender_self_reported becomes true)",
)
def set_gender(
    request: Request,
    body: GenderSelfReportIn,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> UserOut:
    """Record the caller's own voluntary self-report.

    ``gender_self_reported`` becomes true for every one of the four answers — including
    ``prefer_not_to_say``, which is an answer, not silence. Only the values in
    ``models.GENDER_REPORTED`` are ever disaggregated; the KPI engine excludes the rest.
    """
    subject = db.get(User, user.id)  # write through this request's session
    assert subject is not None  # the token was resolved from this database a moment ago
    subject.gender = body.gender
    subject.gender_self_reported = True
    record_audit(
        db,
        user=subject,
        action="user.gender_self_report",
        resource_type="user",
        resource_id=str(subject.id),
        # The value is deliberately absent: an audit row already identifies the person.
        detail={"self_reported": True, "disaggregated": body.gender in GENDER_REPORTED},
        request_id=content.request_id(request),
    )
    db.commit()
    db.refresh(subject)
    return UserOut.model_validate(subject)
