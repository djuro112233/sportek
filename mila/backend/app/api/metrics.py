"""Aggregate metrics: ``/metrics/public`` (k-anonymised) and ``/metrics/internal`` (admin).

Both are computed on request from the ``events``, ``sessions`` and ``gate_records`` tables
for a time window ending at ``now``. The queries never select a session id, and nothing
in the output is finer than a count per day, per topic or per outcome.

Public suppression rules (``k`` = ``Settings.k_anonymity``):

- every count below ``k`` is ``null`` (:func:`app.core.privacy.suppress_small`);
- ratios, latency and support statistics are ``null`` when the population they are computed
  over has fewer than ``k`` members, and a ratio is also ``null`` when its numerator is
  below ``k`` (otherwise the ratio would reveal the suppressed count);
- per-day and per-topic rows below ``k`` are dropped (:func:`app.core.privacy.k_anonymize`).

Conventions the pipeline must follow for the figures to be meaningful (see ``log_event``):
a question is an event of type ``ask`` or ``redflag`` whose ``outcome`` is one of
``answered``, ``withheld``, ``redflag``; ``latency_ms`` and ``input_mode`` are set on those
events; ``support_ratio`` on answered ones; ``payload["translated"] = True`` marks an answer
composed from a source in another language.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from statistics import median

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.api.deps import get_db, get_settings_dep, require_admin
from app.config import Settings
from app.core.privacy import k_anonymize, suppress_small
from app.models import Event, GateRecord, Session

router = APIRouter(prefix="/metrics", tags=["metrics"])

DEFAULT_WINDOW_DAYS = 30
MAX_WINDOW_DAYS = 365
PUBLIC_WINDOWS: tuple[int, ...] = (7, 30, 90, 365)  # fixed windows: no differencing attacks
TOP_TOPICS = 10
QUESTION_EVENT_TYPES: tuple[str, ...] = ("ask", "redflag")
OUTCOMES: tuple[str, ...] = ("answered", "withheld", "redflag")
INPUT_MODES: tuple[str, ...] = ("text", "voice")


# --- output models --------------------------------------------------------------------------
class DayCount(BaseModel):
    date: str
    count: int


class TopicCount(BaseModel):
    topic: str
    count: int


class OutcomeCounts(BaseModel):
    answered: int | None = None
    withheld: int | None = None
    redflag: int | None = None


class OutcomeRatios(BaseModel):
    answered: float | None = None
    withheld: float | None = None
    redflag: float | None = None


class InputModeCounts(BaseModel):
    text: int | None = None
    voice: int | None = None


class PublicMetrics(BaseModel):
    """What ``GET /api/metrics/public`` returns. Every count may be ``null`` (suppressed)."""

    generated_at: str
    k: int
    window_days: int
    sessions_total: int | None
    sessions_per_day: list[DayCount] = Field(default_factory=list)
    outcomes: OutcomeCounts
    ratios: OutcomeRatios
    top_topics: list[TopicCount] = Field(default_factory=list)
    referral_rate: float | None
    redflag_rate: float | None
    input_modes: InputModeCounts
    median_latency_ms: float | None
    p90_latency_ms: float | None
    mean_support_ratio: float | None
    translated_rate: float | None


class UnsuppressedCounts(BaseModel):
    sessions_total: int
    questions: int
    answered: int
    withheld: int
    redflag: int
    text: int
    voice: int
    translated: int
    sessions_per_day: list[DayCount] = Field(default_factory=list)
    topics: list[TopicCount] = Field(default_factory=list)


class InternalMetrics(PublicMetrics):
    """Public figures plus the raw counts; still aggregate-only, admin token required."""

    unsuppressed: UnsuppressedCounts
    redflag_categories: dict[str, int] = Field(default_factory=dict)
    gate_reasons: dict[str, int] = Field(default_factory=dict)
    gate_decisions: dict[str, int] = Field(default_factory=dict)
    events_by_type: dict[str, int] = Field(default_factory=dict)


# --- collection -----------------------------------------------------------------------------
@dataclass
class _WindowStats:
    """Raw aggregates for one window; built by :func:`_collect`, never exposed directly."""

    now: datetime
    window_days: int
    sessions_total: int = 0
    sessions_per_day: Counter[str] = field(default_factory=Counter)
    questions: int = 0
    outcomes: Counter[str] = field(default_factory=Counter)
    topics: Counter[str] = field(default_factory=Counter)
    input_modes: Counter[str] = field(default_factory=Counter)
    latencies: list[int] = field(default_factory=list)
    support_ratios: list[float] = field(default_factory=list)
    translated: int = 0
    redflag_categories: Counter[str] = field(default_factory=Counter)
    events_by_type: Counter[str] = field(default_factory=Counter)
    gate_reasons: Counter[str] = field(default_factory=Counter)
    gate_decisions: Counter[str] = field(default_factory=Counter)


def _as_utc(value: datetime) -> datetime:
    """SQLite hands back naive datetimes; treat them (and naive inputs) as UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def clamp_window(window_days: int | None) -> int:
    """``None`` means the default; anything else is clamped to ``1..MAX_WINDOW_DAYS``."""
    if window_days is None:
        return DEFAULT_WINDOW_DAYS
    return max(1, min(MAX_WINDOW_DAYS, int(window_days)))


def _collect(db: DbSession, window_days: int | None, now: datetime | None) -> _WindowStats:
    now = _as_utc(now or datetime.now(UTC))
    days = clamp_window(window_days)
    cutoff = now - timedelta(days=days)
    stats = _WindowStats(now=now, window_days=days)

    for (created_at,) in db.execute(
        select(Session.created_at).where(Session.created_at >= cutoff, Session.created_at <= now)
    ):
        stats.sessions_total += 1
        stats.sessions_per_day[_as_utc(created_at).date().isoformat()] += 1

    rows = db.execute(
        select(
            Event.type,
            Event.outcome,
            Event.topic_class,
            Event.input_mode,
            Event.latency_ms,
            Event.support_ratio,
            Event.redflag_category,
            Event.payload,
        ).where(Event.created_at >= cutoff, Event.created_at <= now)
    )
    for ev_type, outcome, topic, input_mode, latency_ms, support_ratio, category, payload in rows:
        stats.events_by_type[ev_type] += 1
        if ev_type not in QUESTION_EVENT_TYPES or outcome not in OUTCOMES:
            continue
        stats.questions += 1
        stats.outcomes[outcome] += 1
        if topic:
            stats.topics[topic] += 1
        if input_mode in INPUT_MODES:
            stats.input_modes[input_mode] += 1
        if latency_ms is not None:
            stats.latencies.append(int(latency_ms))
        if support_ratio is not None:
            stats.support_ratios.append(float(support_ratio))
        if category:
            stats.redflag_categories[category] += 1
        if outcome == "answered" and bool((payload or {}).get("translated")):
            stats.translated += 1

    for status, reasons in db.execute(
        select(GateRecord.status, GateRecord.reasons).where(
            GateRecord.created_at >= cutoff, GateRecord.created_at <= now
        )
    ):
        stats.gate_decisions[status] += 1
        for reason in reasons or []:
            stats.gate_reasons[str(reason)] += 1
    return stats


# --- suppression helpers --------------------------------------------------------------------
def _ratio(numerator: int, denominator: int, k: int) -> float | None:
    """``numerator / denominator`` rounded to 3 decimals; ``None`` if either side is below k."""
    if denominator < k or numerator < k:
        return None
    return round(numerator / denominator, 3)


def _percentile(values: Sequence[int], fraction: float) -> float:
    """Nearest-rank percentile of a non-empty sequence (p90 of ten values is the ninth)."""
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1))
    return float(ordered[index])


def _day_rows(counter: Counter[str]) -> list[dict]:
    return [{"date": day, "count": count} for day, count in sorted(counter.items())]


def _topic_rows(counter: Counter[str]) -> list[dict]:
    return [
        {"topic": topic, "count": count}
        for topic, count in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


def _complement(rows: list[dict], total: int, k: int) -> tuple[list[dict], int]:
    """Drop the smallest published rows until the unpublished remainder is 0 or at least k.

    Without this, ``total - sum(shown rows)`` would reveal a suppressed cell.
    """
    rows = list(rows)
    rest = total - sum(int(r["count"]) for r in rows)
    while rows and 0 < rest < k:
        smallest = min(rows, key=lambda r: int(r["count"]))
        rows.remove(smallest)
        rest += int(smallest["count"])
    return rows, rest


def _public_fields(stats: _WindowStats, k: int) -> dict:
    """Assemble the public figures with complementary suppression.

    Every count below k is null. A total is published only when it cannot be combined with
    its published parts to recover a suppressed part; ratios only when every component is at
    least k (a ratio times a public total would reveal a suppressed count); input modes and
    topics only while the question total they complement is itself public.
    """
    n = stats.questions
    answered = stats.outcomes["answered"]
    withheld = stats.outcomes["withheld"]
    redflag = stats.outcomes["redflag"]
    enough_latency = len(stats.latencies) >= k
    enough_support = len(stats.support_ratios) >= k

    day_rows, day_rest = _complement(k_anonymize(_day_rows(stats.sessions_per_day), "count", k), stats.sessions_total, k)
    sessions_total = stats.sessions_total if (day_rest == 0 or day_rest >= k) and stats.sessions_total >= k else None

    outcomes_public = all(c >= k for c in (answered, withheld, redflag))
    # n is derivable only when all three outcome counts are public (or when ratios are shown).
    n_public = outcomes_public
    ratio = (lambda num, den: _ratio(num, den, k)) if outcomes_public else (lambda num, den: None)

    text, voice = stats.input_modes["text"], stats.input_modes["voice"]
    modes_public = n_public and text >= k and voice >= k
    topic_rows: list[dict] = k_anonymize(_topic_rows(stats.topics), "count", k)
    if n_public:
        topic_rows, _ = _complement(topic_rows, n, k)
    else:
        topic_rows, _ = _complement(topic_rows, sum(stats.topics.values()), k)
    translated_ok = outcomes_public and stats.translated >= k and (answered - stats.translated) >= k

    return {
        "generated_at": stats.now.isoformat(),
        "k": k,
        "window_days": stats.window_days,
        "sessions_total": sessions_total,
        "sessions_per_day": day_rows,
        "outcomes": OutcomeCounts(
            answered=suppress_small(answered, k),
            withheld=suppress_small(withheld, k),
            redflag=suppress_small(redflag, k),
        ),
        "ratios": OutcomeRatios(
            answered=ratio(answered, n),
            withheld=ratio(withheld, n),
            redflag=ratio(redflag, n),
        ),
        "top_topics": topic_rows[:TOP_TOPICS],
        "referral_rate": ratio(withheld + redflag, n),
        "redflag_rate": ratio(redflag, n),
        "input_modes": InputModeCounts(
            text=text if modes_public else None,
            voice=voice if modes_public else None,
        ),
        "median_latency_ms": float(median(stats.latencies)) if enough_latency else None,
        "p90_latency_ms": _percentile(stats.latencies, 0.9) if enough_latency else None,
        "mean_support_ratio": (
            round(sum(stats.support_ratios) / len(stats.support_ratios), 3) if enough_support else None
        ),
        "translated_rate": _ratio(stats.translated, answered, k) if translated_ok else None,
    }


# --- public API of this module ---------------------------------------------------------------
def compute_public_metrics(
    db: DbSession,
    k: int,
    window_days: int | None = DEFAULT_WINDOW_DAYS,
    now: datetime | None = None,
) -> PublicMetrics:
    """k-anonymised aggregates for the ``window_days`` ending at ``now`` (default: current UTC time).

    Pure with respect to the database contents and ``now``: calling it twice with the same
    arguments gives the same result, which is what the tests and ``scripts/export_metrics.py``
    rely on.
    """
    return PublicMetrics(**_public_fields(_collect(db, window_days, now), k))


def compute_internal_metrics(
    db: DbSession,
    k: int,
    window_days: int | None = DEFAULT_WINDOW_DAYS,
    now: datetime | None = None,
) -> InternalMetrics:
    """The public figures plus unsuppressed counts, red-flag categories and gate reasons."""
    stats = _collect(db, window_days, now)
    return InternalMetrics(
        **_public_fields(stats, k),
        unsuppressed=UnsuppressedCounts(
            sessions_total=stats.sessions_total,
            questions=stats.questions,
            answered=stats.outcomes["answered"],
            withheld=stats.outcomes["withheld"],
            redflag=stats.outcomes["redflag"],
            text=stats.input_modes["text"],
            voice=stats.input_modes["voice"],
            translated=stats.translated,
            sessions_per_day=[DayCount(**row) for row in _day_rows(stats.sessions_per_day)],
            topics=[TopicCount(**row) for row in _topic_rows(stats.topics)],
        ),
        redflag_categories=dict(sorted(stats.redflag_categories.items())),
        gate_reasons=dict(sorted(stats.gate_reasons.items())),
        gate_decisions=dict(sorted(stats.gate_decisions.items())),
        events_by_type=dict(sorted(stats.events_by_type.items())),
    )


@router.get("/public", response_model=PublicMetrics)
def public_metrics(
    window_days: int = Query(DEFAULT_WINDOW_DAYS, description=f"one of {PUBLIC_WINDOWS}"),
    db: DbSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> PublicMetrics:
    if window_days not in PUBLIC_WINDOWS:
        raise HTTPException(status_code=422, detail=f"window_days must be one of {list(PUBLIC_WINDOWS)}")
    return compute_public_metrics(db, settings.k_anonymity, window_days)


@router.get("/internal", response_model=InternalMetrics, dependencies=[Depends(require_admin)])
def internal_metrics(
    window_days: int = Query(DEFAULT_WINDOW_DAYS, description=f"1..{MAX_WINDOW_DAYS}, clamped"),
    db: DbSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> InternalMetrics:
    return compute_internal_metrics(db, settings.k_anonymity, window_days)
