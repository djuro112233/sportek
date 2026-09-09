"""Word error rate of the speech-to-text provider on a Montenegrin elderly-speaker test set.

Why it exists
-------------
The brief asks for the WER of the recogniser on **five samples of elderly Montenegrin speakers**,
logged and exposed on the dashboard as an *internal* metric (``GET /api/kpi/quality``). Elderly rural
speakers are exactly the group the voice-first onboarding is built for and exactly the group a Whisper
model trained on broadcast speech gets wrong, so publishing the figure keeps the claim honest.

What the five samples currently are
-----------------------------------
**Synthetic stand-ins.** ``seed_data/stt_eval_set.json`` pairs a reference sentence with a 2-second
synthetic WAV; with ``STT_PROVIDER=fixture`` the "recognised" text is read from a sidecar file that
deliberately differs from the reference by a word or two. The number is therefore a real measurement
of a fake recogniser: every row is flagged ``is_synthetic_sample`` and the summary carries
``is_synthetic`` so the dashboard can label it. Real consented recordings must replace them before the
pitch — ``docs/samples/README.md`` says how. Running with ``STT_PROVIDER=faster-whisper`` (or the EU
API) against real recordings needs no code change: only the audio files and the flag change.

Usage: ``python -m app.cli stt-eval`` → :func:`run_evaluation`.
"""
from __future__ import annotations

import json
import logging
import statistics
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from ..config import settings
from ..models import SttEvaluation, utcnow
from ..providers.stt import get_stt, word_error_rate
from . import budget

log = logging.getLogger(__name__)

EVAL_SET_FILENAME = "stt_eval_set.json"


def eval_set_path() -> Path:
    return Path(settings.seed_dir) / EVAL_SET_FILENAME


def load_eval_set(path: Path | None = None) -> dict[str, Any]:
    path = path or eval_set_path()
    if not path.exists():
        raise FileNotFoundError(f"speech-to-text evaluation set not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _audio_path(doc: dict[str, Any], sample: dict[str, Any], base: Path) -> Path:
    return base / doc.get("audio_dir", "stt_fixtures") / sample["audio_file"]


def run_evaluation(db: Session, *, path: Path | None = None) -> dict[str, Any]:
    """Transcribe every sample, compute the WER per sample and the mean, store one row per sample.

    All rows of one run share ``run_id``. Returns the summary the dashboard reads::

        {run_id, provider, model, n_samples, mean_wer, median_wer,
         samples: [{sample_id, wer, n_reference_words, speaker_note}], is_synthetic}
    """
    path = path or eval_set_path()
    doc = load_eval_set(path)
    samples = doc.get("samples", [])
    if not samples:
        raise ValueError(f"{path} contains no samples")

    stt = get_stt()
    run_id = uuid.uuid4()
    evaluated_at = utcnow()
    language = doc.get("language", settings.local_language)
    stt_language = "en" if language == "en" else settings.stt_language

    rows: list[dict[str, Any]] = []
    for sample in samples:
        audio = _audio_path(doc, sample, path.parent)
        reference = sample["reference_text"]
        result = stt.transcribe(audio, language=stt_language)
        wer, n_reference_words = word_error_rate(reference, result.text)
        is_synthetic = bool(sample.get("is_synthetic", doc.get("is_synthetic", True)))
        db.add(
            SttEvaluation(
                evaluated_at=evaluated_at,
                run_id=run_id,
                sample_id=sample["sample_id"],
                speaker_note=sample.get("speaker_note", "")[:255],
                provider=result.provider or settings.stt_provider,
                model=result.model or settings.stt_model,
                reference_text=reference,
                hypothesis_text=result.text,
                wer=round(wer, 6),
                n_reference_words=n_reference_words,
                is_synthetic_sample=is_synthetic,
            )
        )
        if getattr(result, "billable", False):
            budget.record_stt(
                db, result.provider, result.model, float(result.duration_s or 0.0), billable=True
            )
        rows.append(
            {
                "sample_id": sample["sample_id"],
                "wer": round(wer, 6),
                "n_reference_words": n_reference_words,
                "speaker_note": sample.get("speaker_note", ""),
                "is_synthetic": is_synthetic,
            }
        )

    wers = [r["wer"] for r in rows]
    summary = {
        "run_id": str(run_id),
        "evaluated_at": evaluated_at,
        "provider": stt.name,
        "model": stt.model,
        "language": language,
        "n_samples": len(rows),
        "mean_wer": round(statistics.fmean(wers), 6),
        "median_wer": round(statistics.median(wers), 6),
        "samples": rows,
        "is_synthetic": all(r["is_synthetic"] for r in rows),
    }
    db.commit()
    log.info(
        "stt evaluation %s: %s/%s mean WER %.3f over %d samples (synthetic=%s)",
        run_id, summary["provider"], summary["model"], summary["mean_wer"], summary["n_samples"],
        summary["is_synthetic"],
    )
    return summary


def latest_summary(db: Session) -> dict[str, Any] | None:
    """The most recent stored run, in the same shape — what ``/api/kpi/quality`` serves."""
    from sqlalchemy import select

    latest = db.scalars(
        select(SttEvaluation).order_by(SttEvaluation.evaluated_at.desc()).limit(1)
    ).first()
    if latest is None:
        return None
    rows = db.scalars(
        select(SttEvaluation).where(SttEvaluation.run_id == latest.run_id).order_by(SttEvaluation.sample_id)
    ).all()
    wers = [r.wer for r in rows]
    return {
        "run_id": str(latest.run_id),
        "evaluated_at": latest.evaluated_at,
        "provider": latest.provider,
        "model": latest.model,
        "n_samples": len(rows),
        "mean_wer": round(statistics.fmean(wers), 6),
        "median_wer": round(statistics.median(wers), 6),
        "samples": [
            {
                "sample_id": r.sample_id,
                "wer": r.wer,
                "n_reference_words": r.n_reference_words,
                "speaker_note": r.speaker_note,
                "is_synthetic": r.is_synthetic_sample,
            }
            for r in rows
        ],
        "is_synthetic": all(r.is_synthetic_sample for r in rows),
    }
