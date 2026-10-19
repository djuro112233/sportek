"""``POST /api/ask`` (the question endpoint) and ``GET /api/ask/topics``.

The request text is handed to :class:`app.core.pipeline.AskPipeline` and nowhere else: it is
never logged and never stored unless the session opted in to "save my questions". A session
must exist and carry consent (403 otherwise), and each session is rate limited through
``request.app.state.rate_limiter`` (429 with ``Retry-After``). The gate decision leaves the
server through :func:`app.core.pipeline.public_gate`, so removed or withheld sentences never
reach a client.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from app.api.deps import get_db, get_settings_dep, require_consented_session
from app.config import Settings
from app.core.container import get_providers
from app.core.pipeline import AskPipeline, public_gate
from app.core.types import RED_FLAG_CATEGORIES, TOPIC_CLASSES, AskRequest, AskResponse

router = APIRouter(tags=["ask"])


class TopicsResponse(BaseModel):
    topics: list[str]
    red_flag_categories: list[str]


@router.get("/ask/topics", response_model=TopicsResponse)
def topics() -> TopicsResponse:
    """The topic classes events are bucketed into and the red-flag categories the router knows."""
    return TopicsResponse(topics=list(TOPIC_CLASSES), red_flag_categories=list(RED_FLAG_CATEGORIES))


@router.post(
    "/ask",
    response_model=AskResponse,
    responses={
        403: {"description": "Unknown session or consent not given"},
        429: {"description": "Rate limit for this session exceeded"},
    },
)
def ask(
    body: AskRequest,
    request: Request,
    db: DbSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> AskResponse:
    session = require_consented_session(body.session_id, db)
    if not request.app.state.rate_limiter.allow(session.id):
        raise HTTPException(status_code=429, detail="rate limited", headers={"Retry-After": "60"})
    response = AskPipeline(settings, db, get_providers(request.app)).ask(body, session)
    response.gate = public_gate(response.gate)
    return response
