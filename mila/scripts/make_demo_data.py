#!/usr/bin/env python3
"""Seed a development database with referral points, the demo knowledge base and synthetic sessions.

The synthetic sessions and events exist so that ``GET /api/metrics/public`` has something to
show on a fresh checkout. They are generated with ``random.Random(seed)`` (deterministic for a
given seed), carry ``payload == {"synthetic": True}`` on every event, and never contain user
text, audio, IPs or device identifiers (the ``Event`` model has no such columns, and the
payload is constant).

The script refuses to run when ``MILA_APP_ENV=prod``: synthetic data must never reach a pilot
database.

The generator (:func:`generate_sessions`) imports nothing from the backend; the backend is
imported lazily in :func:`seed_database` / :func:`main`.
"""

from __future__ import annotations

import argparse
import os
import random
import sys
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"

SYNTHETIC_PAYLOAD: dict[str, bool] = {"synthetic": True}

# Mirrors app.core.types (duplicated on purpose so the generator stays import-free; the unit
# test checks the two stay in sync).
OUTCOMES: tuple[str, ...] = ("answered", "withheld", "redflag")
TOPIC_CLASSES: tuple[str, ...] = (
    "contraception",
    "pregnancy",
    "antenatal_care",
    "postnatal",
    "menstruation",
    "sti",
    "mental_health",
    "adolescent",
    "other",
)
RED_FLAG_CATEGORIES: tuple[str, ...] = (
    "bleeding_pregnancy",
    "severe_abdominal_pain",
    "fever_pregnancy",
    "preeclampsia",
    "reduced_fetal_movement",
    "suicidal_ideation",
    "violence_coercion",
    "minor_sexual_adult",
)
LANGS: tuple[str, ...] = ("sr", "bs", "me", "hr", "en")
INPUT_MODES: tuple[str, ...] = ("text", "voice")

# Weights chosen to look like a small pilot: most questions are answered, one in five is
# withheld (off-KB, dosing, unsupported) and a few per hundred trip a red flag.
_OUTCOME_WEIGHTS: tuple[float, ...] = (0.72, 0.21, 0.07)
_TOPIC_WEIGHTS: tuple[float, ...] = (0.22, 0.16, 0.12, 0.10, 0.12, 0.08, 0.06, 0.06, 0.08)
_LANG_WEIGHTS: tuple[float, ...] = (0.46, 0.22, 0.14, 0.06, 0.12)
_INPUT_MODE_WEIGHTS: tuple[float, ...] = (0.55, 0.45)
_REGION_WEIGHTS: dict[str, float] = {"BA": 0.65, "ME": 0.35}
_MINOR_SHARE = 0.15
_WITHHELD_REASONS: tuple[tuple[str, ...], ...] = (
    ("low_support_ratio",),
    ("no_citations",),
    ("medication_or_dose",),
    ("low_confidence",),
    ("no_sentences",),
    ("low_support_ratio", "low_confidence"),
)
_GATE_VERSION = "1.0.0"


@dataclass
class SyntheticEvent:
    type: str
    offset_s: float  # seconds before "now" (so the event's created_at = now - offset)
    lang: str
    topic_class: str = ""
    outcome: str = ""
    latency_ms: int | None = None
    support_ratio: float | None = None
    redflag_category: str = ""
    input_mode: str = "text"
    gate: dict[str, Any] | None = None  # for ask events: a GateRecord to attach
    payload: dict[str, Any] = field(default_factory=lambda: dict(SYNTHETIC_PAYLOAD))


@dataclass
class SyntheticSession:
    index: int
    created_offset_s: float
    lang: str
    script: str
    region: str
    is_minor: bool
    events: list[SyntheticEvent] = field(default_factory=list)


def _latency(rng: random.Random, input_mode: str, outcome: str) -> int:
    """Log-normal latencies: text answers around 0.9 s median, voice around 2.6 s; red flags are quick."""
    if outcome == "redflag":
        mu, sigma = 5.3, 0.25  # ~200 ms: rules fire before retrieval
    elif input_mode == "voice":
        mu, sigma = 7.85, 0.35  # ~2.6 s: STT + retrieval + generation + TTS
    else:
        mu, sigma = 6.8, 0.4  # ~0.9 s
    return int(min(max(rng.lognormvariate(mu, sigma), 60.0), 20000.0))


def _support_ratio(rng: random.Random, outcome: str) -> float | None:
    if outcome == "answered":
        return round(min(1.0, rng.betavariate(8, 1.6)), 3)
    if outcome == "withheld":
        return round(rng.betavariate(1.5, 4), 3)
    return None


def generate_sessions(n_sessions: int, days: int, seed: int) -> list[SyntheticSession]:
    """Deterministic synthetic sessions with 1 to 5 ask events each, spread over the last ``days`` days."""
    if n_sessions < 0 or days <= 0:
        raise ValueError("n_sessions must be >= 0 and days > 0")
    rng = random.Random(seed)
    horizon_s = days * 86400
    sessions: list[SyntheticSession] = []
    for idx in range(n_sessions):
        created_offset = rng.uniform(60.0, horizon_s)
        lang = rng.choices(LANGS, weights=_LANG_WEIGHTS, k=1)[0]
        script = "cyrillic" if lang == "sr" and rng.random() < 0.3 else "latin"
        region = rng.choices(list(_REGION_WEIGHTS), weights=list(_REGION_WEIGHTS.values()), k=1)[0]
        is_minor = rng.random() < _MINOR_SHARE
        sess = SyntheticSession(idx, created_offset, lang, script, region, is_minor)
        sess.events.append(SyntheticEvent(type="consent", offset_s=created_offset, lang=lang, outcome="ok"))
        n_asks = rng.choices((1, 2, 3, 4, 5), weights=(0.3, 0.3, 0.2, 0.12, 0.08), k=1)[0]
        t = created_offset
        for _ in range(n_asks):
            t -= rng.uniform(20.0, 240.0)  # later events are closer to "now"
            if t < 1.0:
                break
            outcome = rng.choices(OUTCOMES, weights=_OUTCOME_WEIGHTS, k=1)[0]
            topic = rng.choices(TOPIC_CLASSES, weights=_TOPIC_WEIGHTS, k=1)[0]
            input_mode = rng.choices(INPUT_MODES, weights=_INPUT_MODE_WEIGHTS, k=1)[0]
            if input_mode == "voice":
                sess.events.append(
                    SyntheticEvent(
                        type="transcribe",
                        offset_s=t + rng.uniform(1.0, 4.0),
                        lang=lang,
                        outcome="ok",
                        latency_ms=int(rng.lognormvariate(6.9, 0.3)),
                        input_mode="voice",
                    )
                )
            if outcome == "redflag":
                category = rng.choice(RED_FLAG_CATEGORIES[:-1] if not is_minor else RED_FLAG_CATEGORIES)
                sess.events.append(
                    SyntheticEvent(
                        type="redflag",
                        offset_s=t,
                        lang=lang,
                        topic_class=topic,
                        outcome="redflag",
                        latency_ms=_latency(rng, input_mode, outcome),
                        redflag_category=category,
                        input_mode=input_mode,
                    )
                )
                continue
            ratio = _support_ratio(rng, outcome)
            n_in = rng.randint(2, 7)
            n_kept = n_in if outcome == "answered" and ratio is not None and ratio >= 0.99 else int(round(n_in * (ratio or 0.0)))
            gate = {
                "gate_version": _GATE_VERSION,
                "status": "approved" if outcome == "answered" else "withheld",
                "reasons": [] if outcome == "answered" else list(rng.choice(_WITHHELD_REASONS)),
                "support_ratio": ratio or 0.0,
                "confidence": round(rng.uniform(0.4, 0.95) if outcome == "answered" else rng.uniform(0.05, 0.5), 3),
                "n_sentences_in": n_in,
                "n_sentences_kept": n_kept,
            }
            sess.events.append(
                SyntheticEvent(
                    type="ask",
                    offset_s=t,
                    lang=lang,
                    topic_class=topic,
                    outcome=outcome,
                    latency_ms=_latency(rng, input_mode, outcome),
                    support_ratio=ratio,
                    input_mode=input_mode,
                    gate=gate,
                )
            )
        sessions.append(sess)
    return sessions


def summarize(sessions: Sequence[SyntheticSession]) -> dict[str, Any]:
    events = [e for s in sessions for e in s.events]
    asks = [e for e in events if e.type in ("ask", "redflag")]
    return {
        "sessions": len(sessions),
        "events": len(events),
        "asks": len(asks),
        "by_outcome": dict(sorted(Counter(e.outcome for e in asks).items())),
        "by_topic": dict(sorted(Counter(e.topic_class for e in asks).items())),
        "by_input_mode": dict(sorted(Counter(e.input_mode for e in asks).items())),
        "by_lang": dict(sorted(Counter(s.lang for s in sessions).items())),
        "by_region": dict(sorted(Counter(s.region for s in sessions).items())),
        "minors": sum(1 for s in sessions if s.is_minor),
        "max_age_days": round(max((s.created_offset_s for s in sessions), default=0.0) / 86400, 1),
    }


def refuse_in_prod(env: Mapping[str, str] | None = None) -> None:
    """Raise ``SystemExit(2)`` when ``MILA_APP_ENV`` is ``prod``. Called before any backend import."""
    env = os.environ if env is None else env
    if str(env.get("MILA_APP_ENV", "")).strip().lower() == "prod":
        print("refusing to create synthetic data: MILA_APP_ENV=prod", file=sys.stderr)
        raise SystemExit(2)


def _bootstrap_backend() -> None:
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))


def seed_database(
    db: Any,
    settings: Any,
    sessions: Sequence[SyntheticSession],
    *,
    now: datetime | None = None,
    referral_seeder: Callable[[Any], int] | None = None,
    kb_ingester: Callable[[Any, Any], Any] | None = None,
) -> dict[str, Any]:
    """Write referral points, the knowledge base and the synthetic sessions/events into ``db``.

    ``referral_seeder`` defaults to ``app.core.referral.seed_referral_points`` and
    ``kb_ingester`` to ``app.kb.ingest.ingest_manifest``; tests pass fakes.
    """
    _bootstrap_backend()
    from app.core.privacy import new_session_id
    from app.models import Event, GateRecord, Session

    now = now or datetime.now(UTC)
    result: dict[str, Any] = {}
    if referral_seeder is None:
        from app.core.referral import seed_referral_points as referral_seeder  # type: ignore[no-redef]
    result["referral_points"] = referral_seeder(db)
    if kb_ingester is None:
        from app.kb.ingest import ingest_manifest as kb_ingester  # type: ignore[no-redef]
    report = kb_ingester(db, settings)
    result["kb"] = report.model_dump() if hasattr(report, "model_dump") else report

    n_events = n_gates = 0
    for sess in sessions:
        created = now - timedelta(seconds=sess.created_offset_s)
        row = Session(
            id=new_session_id(),
            created_at=created,
            lang=sess.lang,
            script=sess.script,
            region=sess.region,
            is_minor=sess.is_minor,
            consent_given=True,
            consent_version=settings.consent_version,
            consent_save_questions=False,
            consent_given_at=created,
        )
        db.add(row)
        db.flush()
        for ev in sess.events:
            event = Event(
                session_id=row.id,
                type=ev.type,
                created_at=now - timedelta(seconds=ev.offset_s),
                lang=ev.lang,
                topic_class=ev.topic_class,
                outcome=ev.outcome,
                latency_ms=ev.latency_ms,
                support_ratio=ev.support_ratio,
                redflag_category=ev.redflag_category,
                input_mode=ev.input_mode,
                payload=dict(ev.payload),
            )
            db.add(event)
            n_events += 1
            if ev.gate:
                db.flush()
                db.add(GateRecord(event_id=event.id, created_at=event.created_at, **ev.gate))
                n_gates += 1
    db.commit()
    result["sessions"] = len(sessions)
    result["events"] = n_events
    result["gate_records"] = n_gates
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="make_demo_data.py",
        description="Seed referral points, the demo knowledge base and synthetic consented sessions (dev/test only).",
    )
    parser.add_argument("--sessions", type=int, default=40, help="number of synthetic sessions (default 40)")
    parser.add_argument("--days", type=int, default=14, help="spread events over the last N days (default 14)")
    parser.add_argument("--seed", type=int, default=42, help="random seed (default 42)")
    parser.add_argument("--database-url", default=None, help="SQLAlchemy URL (default: MILA_DATABASE_URL or settings default)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    refuse_in_prod()
    if args.sessions < 0 or args.days <= 0:
        build_parser().error("--sessions must be >= 0 and --days > 0")
    sessions = generate_sessions(args.sessions, args.days, args.seed)

    _bootstrap_backend()
    from app.config import Settings
    from app.db import init_engine, session_factory

    overrides: dict[str, Any] = {}
    if args.database_url:
        overrides["database_url"] = args.database_url
    settings = Settings(**overrides)
    if settings.app_env == "prod":
        print("refusing to create synthetic data: app_env is prod", file=sys.stderr)
        return 2
    init_engine(settings.database_url)
    db = session_factory()()
    try:
        result = seed_database(db, settings, sessions)
    finally:
        db.close()

    summary = summarize(sessions)
    print(f"database: {settings.database_url.split('://', 1)[0]}://...")
    print(f"referral points seeded: {result['referral_points']}")
    kb = result.get("kb")
    if isinstance(kb, dict):
        print(
            f"knowledge base: ingested={len(kb.get('ingested', []))} unchanged={len(kb.get('skipped_unchanged', []))} "
            f"missing={len(kb.get('missing_files', []))} errors={len(kb.get('errors', {}))} chunks_current={kb.get('chunks_current', 0)}"
        )
    print(f"synthetic sessions: {summary['sessions']} (minors: {summary['minors']}), events: {result['events']}, gate records: {result['gate_records']}")
    print(f"asks by outcome: {summary['by_outcome']}")
    print(f"asks by topic: {summary['by_topic']}")
    print(f"asks by input mode: {summary['by_input_mode']}")
    print(f"sessions by lang: {summary['by_lang']}, by region: {summary['by_region']}")
    print(f"oldest event: {summary['max_age_days']} days ago; seed={args.seed}; every event payload is {SYNTHETIC_PAYLOAD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
