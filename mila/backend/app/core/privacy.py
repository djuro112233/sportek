"""Privacy primitives: pseudonymous ids, log redaction, k-anonymity, secure deletion.

See docs/data-protection.md for the data map these functions enforce.
"""

from __future__ import annotations

import logging
import os
import re
import secrets
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DbSession

from app.models import Event, GateRecord, SavedQuestion, Session


def new_session_id() -> str:
    """Random, URL-safe, 192-bit id. Never derived from device, IP or time."""
    return secrets.token_urlsafe(24)


# --- redaction ------------------------------------------------------------------------------
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)(bearer\s+)[a-z0-9\-._~+/]{8,}=*"), r"\1[REDACTED]"),
    (re.compile(r"(?i)\b(sk|key|token|secret|api[_-]?key)[=:\s\"']+[a-z0-9\-._]{8,}"), r"\1=[REDACTED]"),
    (re.compile(r"\bsk-[A-Za-z0-9]{8,}\b"), "[REDACTED]"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[EMAIL]"),
    (re.compile(r"\b\d{13}\b"), "[ID13]"),  # JMBG-shaped identifiers
    (re.compile(r"(?<!\d)(?:\+?\d[\d\s\-/]{7,}\d)(?!\d)"), "[PHONE]"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "[IP]"),
]


def redact(text: str) -> str:
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


class RedactionFilter(logging.Filter):
    """Masks secrets and direct identifiers in every log record (message and args)."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # pragma: no cover
            return True
        record.msg = redact(msg)
        record.args = ()
        return True


# --- k-anonymity ----------------------------------------------------------------------------
def k_anonymize(rows: list[dict], count_key: str, k: int) -> list[dict]:
    """Drop any aggregate row whose count is below k (suppression, not noise)."""
    return [r for r in rows if int(r.get(count_key, 0)) >= k]


def suppress_small(value: int, k: int) -> int | None:
    return value if value >= k else None


# --- deletion -------------------------------------------------------------------------------
def secure_delete(path: Path) -> None:
    """Overwrite then unlink. Best effort on COW filesystems; the unlink always happens."""
    path = Path(path)
    if not path.exists():
        return
    try:
        size = path.stat().st_size
        with open(path, "r+b", buffering=0) as fh:
            fh.write(b"\0" * size)
            fh.flush()
            os.fsync(fh.fileno())
    except OSError:
        pass
    finally:
        try:
            path.unlink()
        except FileNotFoundError:  # pragma: no cover
            pass


def delete_session_data(db: DbSession, session_id: str) -> dict[str, int]:
    """Erase everything tied to a session: saved questions, events, gate records, the session row."""
    counts: dict[str, int] = {}
    counts["saved_questions"] = db.execute(
        delete(SavedQuestion).where(SavedQuestion.session_id == session_id)
    ).rowcount
    event_ids = list(db.scalars(select(Event.id).where(Event.session_id == session_id)))
    if event_ids:
        counts["gate_records"] = db.execute(
            delete(GateRecord).where(GateRecord.event_id.in_(event_ids))
        ).rowcount
    else:
        counts["gate_records"] = 0
    counts["events"] = db.execute(delete(Event).where(Event.session_id == session_id)).rowcount
    counts["sessions"] = db.execute(delete(Session).where(Session.id == session_id)).rowcount
    db.commit()
    return counts
