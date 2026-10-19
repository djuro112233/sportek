"""Unit tests for scripts/measure.py (pure metric functions, loaders, rendering) and the eval datasets."""

from __future__ import annotations

import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / "scripts"
EVAL_DIR = REPO_ROOT / "eval"


def _load_script(name: str):
    path = SCRIPTS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"mila_scripts_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def measure():
    before = {m for m in sys.modules if m == "app" or m.startswith("app.")}
    module = _load_script("measure")
    after = {m for m in sys.modules if m == "app" or m.startswith("app.")}
    # Importing the script must not import the backend.
    assert after == before
    return module


# --- support rate -----------------------------------------------------------------------------
def test_support_rate_counts_supported_sentences(measure):
    records = [
        {"sentences": [{"supported": True}, {"supported": False}, {"supported": True}]},
        {"sentences": [{"supported": True}]},
        {"sentences": []},
    ]
    assert measure.support_counts(records) == (3, 4)
    assert measure.support_rate(records) == pytest.approx(0.75)


def test_support_rate_is_none_for_no_sentences(measure):
    assert measure.support_rate([]) is None
    assert measure.support_rate([{"sentences": []}, {"outcome": "redflag"}]) is None


# --- refusal correctness ----------------------------------------------------------------------
def test_refusal_correctness_ratio_and_incorrect_ids(measure):
    results = [
        {"id": "off-001", "expected": "withheld", "outcome": "withheld"},
        {"id": "off-002", "expected": "withheld", "outcome": "answered", "reasons": []},
        {"id": "off-003", "expected": "withheld", "outcome": "redflag", "redflag_category": "fever_pregnancy"},
        {"id": "off-004", "expected": "withheld", "outcome": "withheld"},
    ]
    assert measure.refusal_correctness(results) == pytest.approx(0.5)
    wrong = measure.incorrect_refusals(results)
    assert [w["id"] for w in wrong] == ["off-002", "off-003"]
    assert wrong[1]["redflag_category"] == "fever_pregnancy"
    assert all("text" not in w for w in wrong)


def test_refusal_correctness_none_for_empty(measure):
    assert measure.refusal_correctness([]) is None
    assert measure.incorrect_refusals([]) == []


# --- red flags --------------------------------------------------------------------------------
def test_redflag_recall_requires_flag_and_matching_category(measure):
    results = [
        {"expected": "bleeding_pregnancy", "flagged": True, "category": "bleeding_pregnancy"},
        {"expected": "preeclampsia", "flagged": True, "category": "fever_pregnancy"},  # wrong category
        {"expected": "suicidal_ideation", "flagged": False, "category": None},
        {"expected": "violence_coercion", "flagged": True, "category": "violence_coercion"},
    ]
    assert measure.redflag_recall(results) == pytest.approx(0.5)
    assert measure.redflag_recall([]) is None


def test_redflag_false_positive_rate(measure):
    negatives = [{"flagged": False}, {"flagged": True}, {"flagged": False}, {"flagged": False}]
    assert measure.redflag_false_positive_rate(negatives) == pytest.approx(0.25)
    assert measure.redflag_false_positive_rate([]) is None


def test_grouped_rate_per_variant(measure):
    results = [
        {"variant": "plain", "expected": "a", "flagged": True, "category": "a"},
        {"variant": "plain", "expected": "a", "flagged": True, "category": "a"},
        {"variant": "typo", "expected": "a", "flagged": False, "category": None},
        {"variant": "typo", "expected": "a", "flagged": True, "category": "a"},
    ]
    grouped = measure.grouped_rate(results, "variant", measure.redflag_recall)
    assert grouped == {"plain": {"rate": 1.0, "n": 2}, "typo": {"rate": 0.5, "n": 2}}


# --- latency ----------------------------------------------------------------------------------
def test_latency_stats_nearest_rank_p90(measure):
    samples = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    stats = measure.latency_stats(samples)
    assert stats == {"n": 10, "median": 55.0, "p90": 90.0}  # rank ceil(0.9*10)=9 -> 90
    assert measure.latency_stats([7])["p90"] == 7.0
    assert measure.latency_stats([5, 1, 3])["p90"] == 5.0  # rank ceil(2.7)=3 -> largest
    assert measure.percentile_nearest_rank([1, 2, 3, 4], 50) == 2.0


def test_latency_stats_empty(measure):
    assert measure.latency_stats([]) == {"n": 0, "median": None, "p90": None}
    with pytest.raises(ValueError):
        measure.percentile_nearest_rank([1.0], 0)


# --- WER --------------------------------------------------------------------------------------
def test_wer_known_values(measure):
    assert measure.wer(["the cat sat"], ["the cat sat"]) == pytest.approx(0.0)
    assert measure.wer(["a b c"], ["a b d"]) == pytest.approx(1 / 3)  # one substitution
    assert measure.wer(["a b c"], ["a b"]) == pytest.approx(1 / 3)  # one deletion
    assert measure.wer(["a b c"], ["a b c d"]) == pytest.approx(1 / 3)  # one insertion
    # corpus-level aggregation: (1 + 0) edits / (3 + 2) words
    assert measure.wer(["a b c", "x y"], ["a b d", "x y"]) == pytest.approx(0.2)
    # default normalisation ignores case and punctuation
    assert measure.wer(["Kada, treba?"], ["kada treba"]) == pytest.approx(0.0)
    # the pure fallback agrees with jiwer on the same inputs
    refs = ["ovo je test", "kada treba da idem"]
    hyps = ["ovo test", "kad treba da idem sutra"]
    assert measure._wer_pure(refs, hyps) == pytest.approx(measure.wer(refs, hyps))


def test_wer_edge_cases(measure):
    assert measure.wer([], []) is None
    with pytest.raises(ValueError):
        measure.wer(["a"], ["a", "b"])
    with pytest.raises(ValueError):
        measure.wer(["..."], ["a"])  # empty reference after normalisation


# --- usability --------------------------------------------------------------------------------
def test_usability_summary_ignores_example_and_unconsented_rows(measure):
    rows = [
        {"participant_id": "EXAMPLE-P00", "group": "adult", "task_completed": "true", "time_s": "999", "comment1": "x", "comment2": "", "comment3": "", "consent_recorded": "true"},
        {"participant_id": "P01", "group": "adult", "task_completed": "true", "time_s": "200", "comment1": "lako", "comment2": "", "comment3": "", "consent_recorded": "true"},
        {"participant_id": "P02", "group": "adult", "task_completed": "false", "time_s": "300", "comment1": "", "comment2": "sporo", "comment3": "", "consent_recorded": "true"},
        {"participant_id": "P03", "group": "minor_with_guardian", "task_completed": "true", "time_s": "250", "comment1": "", "comment2": "", "comment3": "ok", "consent_recorded": "true"},
        {"participant_id": "P04", "group": "adult", "task_completed": "true", "time_s": "100", "comment1": "no", "comment2": "", "comment3": "", "consent_recorded": "false"},
    ]
    s = measure.usability_summary(rows, k=5)
    assert s["n"] == 3
    assert s["completed"] == 2
    assert s["completion_rate"] == pytest.approx(2 / 3)
    assert s["median_time_s"] == 250
    assert s["time_range_s"] == [200, 300]
    assert s["comments"] == ["lako", "sporo", "ok"]
    assert s["groups"] == {"adult": 2, "minor_with_guardian": 1}
    assert set(s["groups_below_k"]) == {"adult", "minor_with_guardian"}
    assert s["excluded_rows"] == 2


def test_usability_summary_empty(measure):
    s = measure.usability_summary([])
    assert s["n"] == 0 and s["completion_rate"] is None and s["median_time_s"] is None and s["comments"] == []


# --- report rendering -------------------------------------------------------------------------
def test_render_report_contains_tables_providers_and_dry_run_banner(measure):
    sec = measure.Section("Support rate", providers={"llm": "mock", "judge": "lexical"})
    sec.add("Support rate (sentence level)", 0.8125, 16, "13 / 16")
    sec.notes.append("Lexical judge: upper bound.")
    lat = measure.Section("Latency (ms)", providers={"stt": "mock"})
    lat.add("Text median", 42.0, 10)
    md = measure.render_report(
        [sec, lat],
        "2026-10-19",
        config={"git commit": "abc123", "MILA_LLM_PROVIDER": "mock"},
        dry_run=True,
        providers={"llm": "mock", "judge": "lexical", "stt": "mock"},
    )
    assert md.startswith("# MILA measurement report, 2026-10-19")
    assert "DRY RUN (mock providers)" in md
    assert "| Metric | Value | n | Notes |" in md
    assert "|---|---|---|---|" in md
    assert "| Support rate (sentence level) | 0.812 | 16 | 13 / 16 |" in md
    assert "| Setting | Value |" in md and "| git commit | abc123 |" in md
    assert "Providers: llm=mock, judge=lexical" in md
    assert "Providers: stt=mock" in md
    assert "- Lexical judge: upper bound." in md
    real = measure.render_report([sec], "2026-10-19", dry_run=False, providers={"llm": "openai_compatible:x"})
    assert "DRY RUN" not in real
    assert measure.fmt_value(None) == "not measured"


def test_is_dry_run(measure):
    assert measure.is_dry_run({"llm": "mock", "judge": "lexical"})
    assert measure.is_dry_run({"llm": "openai_compatible:m", "embedder": "hash"})
    assert not measure.is_dry_run({"llm": "openai_compatible:m", "judge": "llm", "stt": "faster_whisper:large-v3", "tts": "piper", "embedder": "bge_m3"})


def test_write_report_writes_markdown_and_json(measure, tmp_path):
    out = tmp_path / "reports" / "2026-10-19_measurement.md"
    written = measure.write_report(out, "# hello\n", {"date": "2026-10-19", "value": 0.5})
    assert [p.name for p in written] == ["2026-10-19_measurement.md", "2026-10-19_measurement.json"]
    assert out.read_text(encoding="utf-8") == "# hello\n"
    assert json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))["value"] == 0.5


def test_sample_spot_check_is_stratified_and_deterministic(measure, tmp_path):
    sentences = [
        {"sentence_id": f"q-{i:03d}-s01", "question_id": f"q-{i:03d}", "sentence": f"s{i}", "citation_chunk_id": "c", "judge_score": 0.9 if i % 3 else 0.1, "supported": bool(i % 3)}
        for i in range(90)
    ]
    chosen = measure.sample_spot_check(sentences, n=50, seed=1)
    assert len(chosen) == 50
    assert sum(1 for s in chosen if s["supported"]) == 25
    assert chosen == measure.sample_spot_check(sentences, n=50, seed=1)
    # a short stratum is topped up from the other one
    few_unsupported = [s for s in sentences if s["supported"]][:40] + [s for s in sentences if not s["supported"]][:5]
    topped = measure.sample_spot_check(few_unsupported, n=50, seed=1)
    assert len(topped) == 45 and sum(1 for s in topped if not s["supported"]) == 5
    path = measure.write_spot_check_csv(tmp_path / "spot.csv", chosen)
    header = path.read_text(encoding="utf-8").splitlines()[0]
    assert header == ",".join(measure.SPOT_CHECK_COLUMNS)


# --- loaders ----------------------------------------------------------------------------------
def test_load_jsonl_validates_schema_and_unique_ids(measure, tmp_path):
    good = tmp_path / "good.jsonl"
    good.write_text('{"id": "a", "text": "x"}\n\n{"id": "b", "text": "y"}\n', encoding="utf-8")
    assert [r["id"] for r in measure.load_jsonl(good, required=("id", "text"))] == ["a", "b"]

    dup = tmp_path / "dup.jsonl"
    dup.write_text('{"id": "a", "text": "x"}\n{"id": "a", "text": "y"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate id"):
        measure.load_jsonl(dup, required=("id", "text"))

    missing = tmp_path / "missing.jsonl"
    missing.write_text('{"id": "a"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="missing keys"):
        measure.load_jsonl(missing, required=("id", "text"))

    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"id": "a", "text": "x"}\nnot json\n', encoding="utf-8")
    with pytest.raises(ValueError, match="bad.jsonl:2"):
        measure.load_jsonl(bad)


# --- the committed eval datasets ------------------------------------------------------------
_JSONL_REQUIRED = {
    "offkb_questions.jsonl": ("id", "lang", "text", "category", "expected"),
    "inkb_questions.jsonl": ("id", "lang", "text", "topic"),
    "onkb_questions.jsonl": ("id", "lang", "text", "topic"),
    "redflag_inputs.jsonl": ("id", "lang", "text", "category", "expected"),
    "redflag_negatives.jsonl": ("id", "lang", "text"),
    "manifest.jsonl": ("id", "audio", "lang", "reference", "consent_recorded"),
}
_LANGS = {"sr", "bs", "hr", "me", "en"}


def _eval_jsonl_files() -> list[Path]:
    return sorted(EVAL_DIR.rglob("*.jsonl"))


@pytest.mark.parametrize("path", _eval_jsonl_files(), ids=lambda p: str(p.relative_to(EVAL_DIR)))
def test_every_eval_jsonl_parses_with_unique_ids(measure, path: Path):
    required = _JSONL_REQUIRED.get(path.name, ("id",))
    rows = measure.load_jsonl(path, required=required)
    assert rows, f"{path} is empty"
    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids))
    assert all(isinstance(r["id"], str) and r["id"] for r in rows)
    for r in rows:
        if "lang" in r:
            assert r["lang"] in _LANGS, f"{path}:{r['id']} has lang {r['lang']!r}"
        if "text" in r:
            assert isinstance(r["text"], str) and r["text"].strip()


def test_offkb_dataset_shape(measure):
    rows = measure.load_jsonl(EVAL_DIR / "offkb_questions.jsonl", required=_JSONL_REQUIRED["offkb_questions.jsonl"])
    assert len(rows) == 100
    assert all(r["expected"] == "withheld" for r in rows)
    categories = Counter(r["category"] for r in rows)
    assert set(categories) == {"off_domain", "dosing_request", "diagnosis_request", "test_interpretation", "unsupported_in_kb", "manipulation"}
    assert min(categories.values()) >= 15
    langs = Counter(r["lang"] for r in rows)
    assert langs["en"] == 40
    assert langs["sr"] + langs["bs"] + langs["me"] == 60
    assert sum(1 for r in rows if r.get("script") == "cyrillic") >= 10
    assert [r["id"] for r in rows] == [f"off-{i:03d}" for i in range(1, 101)]


def test_inkb_dataset_shape(measure):
    rows = measure.load_jsonl(EVAL_DIR / "inkb_questions.jsonl", required=_JSONL_REQUIRED["inkb_questions.jsonl"])
    assert len(rows) == 30
    langs = Counter(r["lang"] for r in rows)
    assert langs == {"sr": 20, "en": 10}
    topics = {
        "contraception",
        "pregnancy",
        "antenatal_care",
        "postnatal",
        "menstruation",
        "sti",
        "mental_health",
        "adolescent",
        "other",
    }
    assert all(r["topic"] in topics for r in rows)
    assert {r["topic"] for r in rows} >= {"contraception", "antenatal_care", "pregnancy", "postnatal", "menstruation", "sti", "mental_health"}
    assert all(isinstance(r.get("source_ids"), list) and r["source_ids"] for r in rows)


def test_wer_manifest_shape(measure):
    rows = measure.load_jsonl(EVAL_DIR / "wer_set" / "manifest.jsonl", required=_JSONL_REQUIRED["manifest.jsonl"])
    assert len(rows) == 50
    assert [r["id"] for r in rows] == [f"wer-{i:03d}" for i in range(1, 51)]
    assert [r["audio"] for r in rows] == [f"audio/u{i:03d}.wav" for i in range(1, 51)]
    assert {r["lang"] for r in rows} == {"sr", "bs", "me"}
    assert {r["dialect"] for r in rows} == {"ekavian", "ijekavian"}
    assert all(r["consent_recorded"] is False for r in rows), "no recordings are committed yet"
    assert not (EVAL_DIR / "wer_set" / "audio").exists() or not any((EVAL_DIR / "wer_set" / "audio").glob("*.wav"))
    assert len({r["reference"] for r in rows}) == 50


def test_usability_csv_and_spot_check_template(measure):
    rows = measure.load_csv_rows(EVAL_DIR / "usability_sessions.csv")
    assert rows and set(rows[0]) == {"participant_id", "group", "task_completed", "time_s", "comment1", "comment2", "comment3", "consent_recorded"}
    assert all(measure.is_example_row(r) for r in rows), "only EXAMPLE rows are committed until sessions happen"
    assert measure.usability_summary(rows)["n"] == 0
    template = measure.load_csv_rows(EVAL_DIR / "support_spot_check_template.csv")
    assert len(template) == 50
    assert list(template[0]) == list(measure.SPOT_CHECK_COLUMNS)
    assert [r["sentence_id"] for r in template] == [f"s{i:03d}" for i in range(1, 51)]
    assert all(not any(r[c] for c in measure.SPOT_CHECK_COLUMNS[1:]) for r in template)


# --- CLI argument parsing (no backend needed) ------------------------------------------------
def test_parse_args_defaults_and_skip_validation(measure):
    args = measure.parse_args(["--date", "2026-10-19", "--skip", "wer, usability", "--limit", "3"])
    assert args.skip == ["wer", "usability"]
    assert args.limit == 3
    assert args.out == measure.REPORTS_DIR / "2026-10-19_measurement.md"
    with pytest.raises(SystemExit):
        measure.parse_args(["--skip", "latency"])
    with pytest.raises(SystemExit):
        measure.parse_args(["--limit", "0"])
