"""Monthly spend cap for paid model calls (``LLM_MONTHLY_CAP_EUR``, default 50 €).

Every billable call is priced from the configured per-million-token rates and written to
``llm_usage``. Before a paid call the caller asks :func:`guard`; once the month's spend reaches the
cap it raises :class:`SpendCapReached` and the assistant:

1. serves an answer from the response cache when one is valid, otherwise
2. replies with a polite "assistant paused" message.

It never falls back to unsourced text: generation is the only thing that stops, and the cached
answers still carry their citations.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import LlmUsage
from ..providers.llm import LLMResult

log = logging.getLogger(__name__)


class SpendCapReached(RuntimeError):
    """The monthly euro cap for paid model calls is exhausted."""

    def __init__(self, spent: float, cap: float):
        super().__init__(f"monthly LLM spend cap reached: {spent:.2f} € of {cap:.2f} €")
        self.spent = spent
        self.cap = cap


def month_key(when: datetime | None = None) -> str:
    when = when or datetime.now(timezone.utc)
    return when.astimezone(timezone.utc).strftime("%Y-%m")


def price_eur(input_tokens: int, output_tokens: int, audio_seconds: float = 0.0) -> float:
    return (
        input_tokens / 1_000_000 * settings.llm_price_input_eur_per_mtok
        + output_tokens / 1_000_000 * settings.llm_price_output_eur_per_mtok
        + audio_seconds / 60 * settings.stt_price_eur_per_minute
    )


def spent_this_month(db: Session, when: datetime | None = None) -> float:
    total = db.scalar(
        select(func.coalesce(func.sum(LlmUsage.cost_eur), 0.0)).where(
            LlmUsage.month_key == month_key(when), LlmUsage.billable.is_(True)
        )
    )
    return float(total or 0.0)


def remaining_eur(db: Session, when: datetime | None = None) -> float:
    return max(0.0, settings.llm_monthly_cap_eur - spent_this_month(db, when))


def cap_reached(db: Session, when: datetime | None = None) -> bool:
    if settings.llm_monthly_cap_eur <= 0:
        return False
    return spent_this_month(db, when) >= settings.llm_monthly_cap_eur


def guard(db: Session, purpose: str, *, billable: bool | None = None) -> None:
    """Raise :class:`SpendCapReached` when the month's budget for paid calls is exhausted.

    ``billable`` says whether *this particular* call costs money. It defaults to whether the text
    model is paid, which is the wrong test for an embedding or a transcription bought from a hosted
    service while the text model is self-hosted, so those callers pass the flag explicitly.
    """
    from ..providers.llm import get_llm

    if billable is None:
        billable = bool(getattr(get_llm(), "billable", False))
    if not billable:
        return  # self-hosted: no euro cost, no cap
    spent = spent_this_month(db)
    if settings.llm_monthly_cap_eur > 0 and spent >= settings.llm_monthly_cap_eur:
        log.warning("spend cap reached (%.2f €), refusing paid call for %s", spent, purpose)
        raise SpendCapReached(spent, settings.llm_monthly_cap_eur)


def record(db: Session, result: LLMResult, purpose: str, *, audio_seconds: float = 0.0) -> LlmUsage:
    """Write one usage row (priced only when the provider is billable)."""
    cost = price_eur(result.input_tokens, result.output_tokens, audio_seconds) if result.billable else 0.0
    usage = LlmUsage(
        month_key=month_key(),
        provider=result.provider or settings.llm_provider,
        model=result.model or settings.llm_model,
        purpose=purpose,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        audio_seconds=audio_seconds,
        cost_eur=round(cost, 6),
        billable=result.billable,
    )
    db.add(usage)
    db.flush()
    return usage


def record_stt(db: Session, provider: str, model: str, audio_seconds: float, *, billable: bool) -> LlmUsage:
    cost = audio_seconds / 60 * settings.stt_price_eur_per_minute if billable else 0.0
    usage = LlmUsage(
        month_key=month_key(), provider=provider, model=model, purpose="stt",
        input_tokens=0, output_tokens=0, audio_seconds=audio_seconds,
        cost_eur=round(cost, 6), billable=billable,
    )
    db.add(usage)
    db.flush()
    return usage


def status(db: Session) -> dict:
    spent = spent_this_month(db)
    cap = settings.llm_monthly_cap_eur
    return {
        "month": month_key(),
        "cap_eur": cap,
        "spent_eur": round(spent, 4),
        "remaining_eur": round(max(0.0, cap - spent), 4),
        "cap_reached": cap > 0 and spent >= cap,
        "provider": settings.llm_provider,
        "provider_name": settings.llm_provider_name,
        "billable": bool(getattr(__import__("app.providers.llm", fromlist=["get_llm"]).get_llm(), "billable", False)),
    }
