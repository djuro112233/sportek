#!/usr/bin/env python3
"""Export the public, k-anonymised metrics to ``reports/metrics_<date>.json`` and ``.csv``.

The JSON file is the output of ``app.api.metrics.compute_public_metrics`` (the same aggregate
the ``GET /api/metrics/public`` endpoint serves). The CSV file holds one row per day with
event counts; every count below ``MILA_K_ANONYMITY`` is suppressed (left empty) and days whose
total is below k are dropped, so the export is never finer-grained than the public endpoint.

Nothing here reads question text, audio, IPs or device identifiers: the ``Event`` table has no
such columns.
"""

from __future__ import annotations

import argparse
import csv
import inspect
import json
import sys
from collections.abc import Callable, Sequence
from datetime import date as date_type
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
REPORTS_DIR = REPO_ROOT / "reports"

CSV_COLUMNS: tuple[str, ...] = (
    "day",
    "events",
    "sessions",
    "asks",
    "answered",
    "withheld",
    "redflag",
    "voice",
    "text",
)


def _bootstrap_backend() -> None:
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))


def find_compute_function(module: Any) -> Callable[..., Any] | None:
    """``compute_public_metrics`` if present, else the first public callable whose name starts with ``compute_``."""
    fn = getattr(module, "compute_public_metrics", None)
    if callable(fn):
        return fn
    for name in sorted(dir(module)):
        if name.startswith("compute_") and callable(getattr(module, name)):
            return getattr(module, name)
    return None


def call_with_known_args(fn: Callable[..., Any], **available: Any) -> Any:
    """Call ``fn`` passing only the keyword arguments its signature declares (by name)."""
    sig = inspect.signature(fn)
    kwargs: dict[str, Any] = {}
    positional: list[Any] = []
    for name, param in sig.parameters.items():
        if param.kind is inspect.Parameter.VAR_POSITIONAL or param.kind is inspect.Parameter.VAR_KEYWORD:
            continue
        if name in available:
            if param.kind is inspect.Parameter.POSITIONAL_ONLY:
                positional.append(available[name])
            else:
                kwargs[name] = available[name]
        elif param.default is inspect.Parameter.empty:
            raise TypeError(f"{fn.__name__} requires parameter {name!r} which the exporter cannot supply")
    return fn(*positional, **kwargs)


def suppress(value: int, k: int) -> int | None:
    return value if value >= k else None


def per_day_rows(db: Any, k: int, days: int | None = None) -> list[dict[str, Any]]:
    """Per-day counts from the ``events`` table, k-suppressed per cell and per row."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from app.core.privacy import k_anonymize
    from app.models import Event

    stmt = select(Event.created_at, Event.session_id, Event.type, Event.outcome, Event.input_mode)
    if days:
        stmt = stmt.where(Event.created_at >= datetime.now(UTC) - timedelta(days=days))
    buckets: dict[str, dict[str, Any]] = {}
    for created_at, session_id, ev_type, outcome, input_mode in db.execute(stmt):
        day = created_at.date().isoformat() if created_at else "unknown"
        b = buckets.setdefault(
            day,
            {"events": 0, "sessions": set(), "asks": 0, "answered": 0, "withheld": 0, "redflag": 0, "voice": 0, "text": 0},
        )
        b["events"] += 1
        if session_id:
            b["sessions"].add(session_id)
        if ev_type in ("ask", "redflag"):
            b["asks"] += 1
            if outcome in ("answered", "withheld", "redflag"):
                b[outcome] += 1
            if input_mode in ("voice", "text"):
                b[input_mode] += 1
    rows = [
        {"day": day, "events": b["events"], "sessions": len(b["sessions"]), **{c: b[c] for c in CSV_COLUMNS[3:]}}
        for day, b in sorted(buckets.items())
    ]
    rows = k_anonymize(rows, "events", k)
    for row in rows:
        for col in CSV_COLUMNS[1:]:
            row[col] = suppress(int(row[col]), k)
    return rows


def write_csv(path: Path, rows: Sequence[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(CSV_COLUMNS))
        writer.writeheader()
        for row in rows:
            writer.writerow({c: ("" if row.get(c) is None else row.get(c)) for c in CSV_COLUMNS})
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="export_metrics.py", description="Dump the public metrics to reports/metrics_<date>.{json,csv}.")
    parser.add_argument("--date", default=date_type.today().isoformat(), help="date used in the file names (default today)")
    parser.add_argument("--out-dir", type=Path, default=REPORTS_DIR, help="output directory (default reports/)")
    parser.add_argument("--days", type=int, default=None, help="limit the per-day CSV to the last N days")
    parser.add_argument("--database-url", default=None, help="SQLAlchemy URL (default: MILA_DATABASE_URL or settings default)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _bootstrap_backend()
    from app.config import Settings
    from app.db import init_engine, session_factory

    overrides: dict[str, Any] = {}
    if args.database_url:
        overrides["database_url"] = args.database_url
    settings = Settings(**overrides)
    k = int(settings.k_anonymity)
    init_engine(settings.database_url)
    db = session_factory()()
    payload: dict[str, Any] = {"date": args.date, "k_anonymity": k, "public_metrics": None, "note": ""}
    try:
        try:
            import importlib

            metrics_module = importlib.import_module("app.api.metrics")
            fn = find_compute_function(metrics_module)
        except Exception as exc:
            fn = None
            payload["note"] = f"app.api.metrics unavailable ({type(exc).__name__})"
        if fn is None:
            payload["note"] = payload["note"] or "no compute_* function found in app.api.metrics"
        else:
            result = call_with_known_args(
                fn, db=db, session=db, settings=settings, k=k, k_anonymity=k, days=args.days, window_days=args.days
            )
            payload["public_metrics"] = result.model_dump() if hasattr(result, "model_dump") else result
            payload["source"] = f"app.api.metrics.{fn.__name__}"
        rows = per_day_rows(db, k, args.days)
    finally:
        db.close()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"metrics_{args.date}.json"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    csv_path = write_csv(out_dir / f"metrics_{args.date}.csv", rows)
    print(f"wrote {json_path}")
    print(f"wrote {csv_path} ({len(rows)} day rows at k={k})")
    if payload["note"]:
        print(f"note: {payload['note']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
