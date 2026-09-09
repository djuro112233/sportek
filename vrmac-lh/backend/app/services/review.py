"""Monthly human sampling of assistant answers.

The automatic support check (providers/support.py) is the *machine* control of innovation claim #2.
This module is the *human* one: once a month a person draws a random sample of the answers the
assistant actually gave and judges them against the cited sources.

**The sheet contains no visitor identifier.** It is built from ``answer_records``, a table that
deliberately has no session, device or actor pseudonym and no foreign key to anything about the
person who asked (see app/models.py: ``AnswerRecord``). A reviewer can therefore judge the answer
and its citations, but cannot tie a question back to a visitor — not even by joining tables.

Output (``python -m app.cli review-sample --n 30 --days 31``):

* ``answer_review_<period>.csv`` — one row per sampled answer with two blank columns the reviewer
  fills in (``reviewer verdict``, ``reviewer note``);
* ``answer_review_<period>.md`` — the short instruction header that travels with the sheet.

Sampling is ``random.sample`` over the period's rows; the caller may seed ``random`` to make a run
reproducible (the rows are ordered deterministically before sampling).
"""
from __future__ import annotations

import csv
import logging
import random
from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import PROTOTYPE_LABEL, settings
from ..models import AnswerRecord, utcnow

log = logging.getLogger(__name__)

CSV_COLUMNS = [
    "id",
    "date",
    "language",
    "question",
    "answer",
    "citations",
    "supported sentences",
    "dropped sentences",
    "reviewer verdict",
    "reviewer note",
]

VERDICT_OPTIONS = ("grounded", "not grounded", "should have refused", "wrong refusal", "unclear")

INSTRUCTIONS = """# Monthly answer review — {period}

*{prototype}*

{n_sampled} answers were drawn at random from the {n_total} the assistant produced between
{start} and {end} ({days} days). Open `{csv_name}` in a spreadsheet and fill in the last two
columns for every row.

## What to check

1. **Is every sentence of the answer supported by the cited source?** Open the entry named in
   *citations* and read it. The assistant already removed the sentences its automatic support check
   could not attribute (column *dropped sentences*); you are checking whether the check was right.
2. **Was a refusal correct?** A row whose *answer* reads `— withheld (<reason>)` is a refusal. It is
   correct when the approved entries really do not contain the answer, and wrong when they do.
3. **Is the answer in the language of the question?**

## Verdicts

`{verdicts}`

Anything other than `grounded` (for an answer) or a correct refusal is a finding: note the entry
slug and what was wrong in *reviewer note*, and hand the sheet to the validator group.

## Privacy

The sheet carries **no visitor identifier**: no session id, no device id, no pseudonym, no IP, no
account. The underlying table stores the question and the answer only, unlinked from the person who
asked, so a sampled row cannot be traced back to a visitor.
"""


def _period_bounds(days: int):
    end = utcnow()
    return end - timedelta(days=days), end


def _row(record: AnswerRecord) -> dict[str, Any]:
    citations = "; ".join(
        f"{c.get('slug', '?')} v{c.get('entry_version', '?')} ({c.get('source', '')})"
        for c in (record.citations or [])
    )
    supported = [s for s in (record.support_results or []) if s.get("supported")]
    answer = record.answer or ""
    if not record.answered:
        answer = f"— withheld ({record.refusal_reason or 'unknown'})"
    return {
        "id": str(record.id),
        "date": record.occurred_at.isoformat(timespec="seconds"),
        "language": record.lang,
        "question": record.question,
        "answer": answer,
        "citations": citations,
        "supported sentences": len(supported),
        "dropped sentences": record.dropped_sentences,
        "reviewer verdict": "",
        "reviewer note": "",
    }


def export_review_sheet(
    db: Session,
    n: int = 30,
    out_dir: str | Path | None = None,
    days: int = 31,
) -> dict[str, Any]:
    """Draw ``n`` random answers of the last ``days`` days and write the review sheet.

    Returns ``{"csv": ..., "markdown": ..., "sampled": int, "available": int, ...}``. Fewer rows are
    written when fewer answers exist. Ordering is deterministic for a seeded ``random``.
    """
    start, end = _period_bounds(days)
    records = list(
        db.scalars(
            select(AnswerRecord)
            .where(AnswerRecord.occurred_at >= start, AnswerRecord.occurred_at <= end)
            .order_by(AnswerRecord.occurred_at, AnswerRecord.id)
        )
    )
    sample = records if len(records) <= n else random.sample(records, n)
    sample.sort(key=lambda r: (r.occurred_at, str(r.id)))

    directory = Path(out_dir or settings.export_dir)
    directory.mkdir(parents=True, exist_ok=True)
    period = end.strftime("%Y-%m")
    csv_path = directory / f"answer_review_{period}.csv"
    md_path = directory / f"answer_review_{period}.md"

    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for record in sample:
            writer.writerow(_row(record))

    md_path.write_text(
        INSTRUCTIONS.format(
            period=period,
            prototype=PROTOTYPE_LABEL,
            n_sampled=len(sample),
            n_total=len(records),
            start=start.date().isoformat(),
            end=end.date().isoformat(),
            days=days,
            csv_name=csv_path.name,
            verdicts="` / `".join(VERDICT_OPTIONS),
        ),
        encoding="utf-8",
    )
    result = {
        "csv": str(csv_path),
        "markdown": str(md_path),
        "sampled": len(sample),
        "available": len(records),
        "requested": n,
        "period_start": start.isoformat(timespec="seconds"),
        "period_end": end.isoformat(timespec="seconds"),
        "columns": CSV_COLUMNS,
        "contains_visitor_identifier": False,
    }
    log.info("review sheet: %s of %s answers → %s", len(sample), len(records), csv_path)
    return result
