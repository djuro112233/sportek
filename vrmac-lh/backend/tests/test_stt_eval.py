"""Word error rate of the speech-to-text provider on the Montenegrin elderly-speaker test set.

The five samples are **synthetic stand-ins** (see docs/samples/README.md): the audio is a tone and the
"recognised" text comes from a fixture that deliberately differs from the reference by a word or two.
That is exactly what these tests check — the metric is computed for real, the samples are flagged as
synthetic, and the WER is visibly non-zero so nobody mistakes a passing test for a working recogniser.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.config import settings
from app.models import SttEvaluation
from app.providers.stt import word_error_rate
from app.services.stt_eval import EVAL_SET_FILENAME, latest_summary, load_eval_set, run_evaluation

SUMMARY_KEYS = {"run_id", "provider", "model", "n_samples", "mean_wer", "median_wer", "samples", "is_synthetic"}
SAMPLE_KEYS = {"sample_id", "wer", "n_reference_words", "speaker_note"}
EXPECTED_SAMPLES = 5


@pytest.fixture(scope="module")
def eval_doc() -> dict:
    return load_eval_set()


@pytest.fixture()
def summary(db) -> dict:
    return run_evaluation(db)


# (1) the test set itself ---------------------------------------------------------------------------
def test_eval_set_has_five_samples_with_audio_and_a_speaker_note(eval_doc):
    samples = eval_doc["samples"]
    assert len(samples) == EXPECTED_SAMPLES
    assert len({s["sample_id"] for s in samples}) == EXPECTED_SAMPLES
    base = Path(settings.seed_dir) / eval_doc.get("audio_dir", "stt_fixtures")
    for s in samples:
        assert (base / s["audio_file"]).exists(), f"missing audio for {s['sample_id']}"
        assert (base / f"{s['sample_id']}.txt").exists(), "the fixture provider needs a sidecar transcript"
        assert s["reference_text"].strip()
        assert "replace with a consented recording" in s["speaker_note"]
        assert s["is_synthetic"] is True


def test_every_fixture_transcript_differs_from_its_reference(eval_doc):
    """A zero WER would mean the metric is not measuring anything."""
    base = Path(settings.seed_dir) / eval_doc.get("audio_dir", "stt_fixtures")
    for s in eval_doc["samples"]:
        hypothesis = (base / f"{s['sample_id']}.txt").read_text(encoding="utf-8")
        wer, n_words = word_error_rate(s["reference_text"], hypothesis)
        assert n_words >= 10
        assert 0 < wer < 0.5, f"{s['sample_id']}: WER {wer} is not a plausible recogniser error"


def test_the_eval_set_ships_with_the_seed_data():
    assert (Path(settings.seed_dir) / EVAL_SET_FILENAME).exists()


# (2) run_evaluation --------------------------------------------------------------------------------
def test_run_evaluation_writes_one_row_per_sample_with_a_shared_run_id(db, summary):
    run_id = uuid.UUID(summary["run_id"])
    rows = db.scalars(select(SttEvaluation).where(SttEvaluation.run_id == run_id)).all()
    assert len(rows) == EXPECTED_SAMPLES
    assert {r.sample_id for r in rows} == {s["sample_id"] for s in summary["samples"]}
    for r in rows:
        assert r.provider == summary["provider"]
        assert r.model == summary["model"]
        assert r.reference_text and r.hypothesis_text
        assert r.reference_text != r.hypothesis_text
        assert r.n_reference_words > 0
        assert 0 < r.wer < 1


def test_summary_shape_is_what_the_dashboard_reads(summary):
    assert SUMMARY_KEYS <= set(summary)
    assert summary["n_samples"] == EXPECTED_SAMPLES
    assert len(summary["samples"]) == EXPECTED_SAMPLES
    for s in summary["samples"]:
        assert SAMPLE_KEYS <= set(s)
        assert isinstance(s["wer"], float)
        assert isinstance(s["n_reference_words"], int)
    # the summary must survive the trip to the dashboard as JSON
    json.dumps(summary, default=str)


def test_mean_wer_is_between_zero_and_one_and_not_zero(summary):
    assert 0 < summary["mean_wer"] < 1
    assert 0 < summary["median_wer"] < 1
    assert summary["mean_wer"] == pytest.approx(
        sum(s["wer"] for s in summary["samples"]) / EXPECTED_SAMPLES, abs=1e-6
    )


def test_samples_are_flagged_synthetic_so_the_dashboard_can_say_so(db, summary):
    assert summary["is_synthetic"] is True
    assert all(s["is_synthetic"] for s in summary["samples"])
    rows = db.scalars(
        select(SttEvaluation).where(SttEvaluation.run_id == uuid.UUID(summary["run_id"]))
    ).all()
    assert all(r.is_synthetic_sample for r in rows)
    assert all("synthetic stand-in" in r.speaker_note for r in rows)


def test_latest_summary_returns_the_run_that_was_just_written(db, summary):
    latest = latest_summary(db)
    assert latest is not None
    assert latest["run_id"] == summary["run_id"]
    assert latest["n_samples"] == summary["n_samples"]
    assert latest["mean_wer"] == pytest.approx(summary["mean_wer"], abs=1e-6)
