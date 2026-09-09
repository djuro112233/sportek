"""``POST /api/ask`` — grounded answers or refusal (innovation claim #2).

The endpoint is a thin shell around :func:`app.services.rag.ask`: the same function serves the API
and the automated grounding test, so what the pitch demo shows is what the test measures.

Two sessions are injected on purpose:

* ``db_public`` — the **visitor** role (read-only + row-level security → approved rows only). All
  retrieval happens here, which is the data-layer half of the human-approval control.
* ``db_app`` — the application role, which writes the pseudonymised event, the spend-accounting row
  and the unlinked answer record. A visitor session may never write.

The visitor's ``session_id`` / ``device_id`` are accepted only to be **pseudonymised** by
``app/events.py``; they are never stored in the clear and never reach the answer record.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db, get_public_db
from ..ratelimit import limiter
from ..config import settings
from ..schemas import Citation, SupportResult
from ..services import rag

router = APIRouter(prefix="/api/ask", tags=["ask"])


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    lang: str | None = Field(default=None, description="cnr | en; detected from the question when omitted")
    session_id: str | None = Field(default=None, max_length=128)
    device_id: str | None = Field(default=None, max_length=128)


class ProviderInfo(BaseModel):
    llm: str
    embeddings: str
    support_check: str


class AskResponse(BaseModel):
    """The exact shape agreed in docs/api-contract.md (section `ask`)."""

    answered: bool
    answer: str | None = None
    citations: list[Citation] = []
    confidence: float = 0.0
    #: one verdict per candidate sentence of the answer (claim 2b)
    support: list[SupportResult] = []
    #: unsupported sentences removed before answering
    dropped_sentences: int = 0
    #: low_confidence | no_approved_source | llm_declined | unsupported_answer | assistant_paused
    refusal_reason: str | None = None
    refusal_message: str | None = None
    served_from_cache: bool = False
    provider: ProviderInfo
    event: str


@router.post("", response_model=AskResponse, summary="Ask the visitor assistant")
@router.post("/", response_model=AskResponse, include_in_schema=False)
@limiter.limit(settings.rate_limit_ask)
def ask_endpoint(
    request: Request,
    response: Response,
    payload: AskIn,
    db_public: Session = Depends(get_public_db),
    db_app: Session = Depends(get_db),
) -> AskResponse:
    result = rag.ask(
        db_public,
        db_app,
        payload.question,
        lang=payload.lang,
        session_id=payload.session_id,
        device_id=payload.device_id,
    )
    return AskResponse(
        answered=result.answered,
        answer=result.answer,
        citations=result.citations,
        confidence=result.confidence,
        support=result.support,
        dropped_sentences=result.dropped_sentences,
        refusal_reason=result.refusal_reason,
        refusal_message=result.refusal_message,
        served_from_cache=result.served_from_cache,
        provider=ProviderInfo(**result.provider),
        event=result.event,
    )
