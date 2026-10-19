#!/usr/bin/env python3
"""MILA measurement: metric library + CLI that writes ``reports/<date>_measurement.{md,json}``.

The file has two halves.

1. A library of pure functions (``support_rate``, ``refusal_correctness``, ``redflag_recall``,
   ``redflag_false_positive_rate``, ``latency_stats``, ``wer``, ``usability_summary``,
   ``render_report``, ``write_report``, the JSONL/CSV loaders). They import nothing from the
   backend and are unit-tested with fakes in ``backend/tests/unit/test_measure.py``.
2. A CLI (``main``) that imports the backend lazily, runs the evaluation datasets under
   ``eval/`` through the real pipeline and writes the report.

Every section of the report names the providers it was computed with (LLM, judge, STT, TTS,
embedder) and the header says ``DRY RUN (mock providers)`` whenever any provider is a mock,
so a mock run can never be mistaken for a real measurement. Only committed reports under
``reports/`` feed the UNICEF form (see ``reports/README.md`` and ``docs/evaluation.md``).

Privacy: the script never writes user text anywhere. The evaluation questions are team-written
datasets, the spot-check sheet contains generator sentences and knowledge-base chunk ids, and
the evaluation session created for the run is deleted at the end unless ``--keep-session``.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import platform
import random
import re
import statistics
import subprocess
import sys
import time
import wave
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from datetime import date as date_type
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
EVAL_DIR = REPO_ROOT / "eval"
REPORTS_DIR = REPO_ROOT / "reports"

# Dataset files (owned by the eval/ folder; see eval/README.md).
INKB_FILE = EVAL_DIR / "inkb_questions.jsonl"
ONKB_FILE_LEGACY = EVAL_DIR / "onkb_questions.jsonl"  # name used in docs/evaluation.md
OFFKB_FILE = EVAL_DIR / "offkb_questions.jsonl"
REDFLAG_INPUTS_FILE = EVAL_DIR / "redflag_inputs.jsonl"
REDFLAG_NEGATIVES_FILE = EVAL_DIR / "redflag_negatives.jsonl"
WER_MANIFEST_FILE = EVAL_DIR / "wer_set" / "manifest.jsonl"
USABILITY_FILE = EVAL_DIR / "usability_sessions.csv"

SKIPPABLE: tuple[str, ...] = ("wer", "usability", "latency_voice")
# Provider values that mean "no real model behind it".
MOCK_PROVIDER_VALUES: frozenset[str] = frozenset({"mock", "hash"})
SPOT_CHECK_COLUMNS: tuple[str, ...] = (
    "sentence_id",
    "question_id",
    "sentence",
    "citation_chunk_id",
    "judge_score",
    "rater1_supported",
    "rater2_supported",
    "notes",
)
REPORT_COLUMNS: tuple[str, ...] = ("Metric", "Value", "n", "Notes")
NOT_MEASURED = "not measured"

_TRUE_VALUES = frozenset({"1", "true", "yes", "y", "t"})
_WORD_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+")


# =============================================================================================
# Pure metric functions (no backend imports)
# =============================================================================================
def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in _TRUE_VALUES


def support_counts(records: Iterable[dict]) -> tuple[int, int]:
    """Return ``(supported, total)`` over every sentence of every record.

    ``records`` are dicts shaped ``{"sentences": [{"supported": bool, ...}, ...], ...}``.
    """
    supported = total = 0
    for rec in records:
        for sentence in rec.get("sentences") or []:
            total += 1
            if _as_bool(sentence.get("supported")):
                supported += 1
    return supported, total


def support_rate(records: Iterable[dict]) -> float | None:
    """Share of sentences the verifier marked supported; ``None`` when there are no sentences."""
    supported, total = support_counts(records)
    return supported / total if total else None


def refusal_correctness(results: Iterable[dict]) -> float | None:
    """Share of results whose ``outcome`` equals ``expected`` (default ``withheld``); ``None`` for n=0."""
    n = correct = 0
    for res in results:
        n += 1
        if res.get("outcome") == res.get("expected", "withheld"):
            correct += 1
    return correct / n if n else None


def incorrect_refusals(results: Iterable[dict]) -> list[dict]:
    """Ids (never text) of off-KB questions that were not withheld, with the gate reasons or category."""
    out: list[dict] = []
    for res in results:
        if res.get("outcome") != res.get("expected", "withheld"):
            out.append(
                {
                    "id": res.get("id", ""),
                    "outcome": res.get("outcome", ""),
                    "reasons": list(res.get("reasons") or []),
                    "redflag_category": res.get("redflag_category") or "",
                }
            )
    return out


def redflag_recall(results: Iterable[dict]) -> float | None:
    """Share of inputs where the router flagged *and* returned the expected category."""
    n = hits = 0
    for res in results:
        n += 1
        if _as_bool(res.get("flagged")) and res.get("category") == res.get("expected"):
            hits += 1
    return hits / n if n else None


def redflag_false_positive_rate(results: Iterable[dict]) -> float | None:
    """Share of negatives the router flagged; ``None`` for n=0."""
    n = flagged = 0
    for res in results:
        n += 1
        if _as_bool(res.get("flagged")):
            flagged += 1
    return flagged / n if n else None


def grouped_rate(
    results: Iterable[dict], key: str, rate_fn: Callable[[list[dict]], float | None]
) -> dict[str, dict[str, Any]]:
    """Apply ``rate_fn`` per value of ``results[i][key]``; returns ``{group: {"rate": r, "n": n}}``."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for res in results:
        groups[str(res.get(key, "") or "")].append(res)
    return {g: {"rate": rate_fn(items), "n": len(items)} for g, items in sorted(groups.items())}


def percentile_nearest_rank(samples: Sequence[float], percentile: float) -> float | None:
    """Nearest-rank percentile: the value at rank ``ceil(p/100 * n)`` of the sorted sample."""
    if not samples:
        return None
    if not 0 < percentile <= 100:
        raise ValueError("percentile must be in (0, 100]")
    ordered = sorted(float(s) for s in samples)
    rank = max(1, math.ceil(percentile / 100.0 * len(ordered)))
    return ordered[rank - 1]


def latency_stats(samples_ms: Sequence[float]) -> dict[str, Any]:
    """``{"n", "median", "p90"}`` in milliseconds; p90 is nearest-rank, median is the usual median."""
    samples = [float(s) for s in samples_ms]
    if not samples:
        return {"n": 0, "median": None, "p90": None}
    return {
        "n": len(samples),
        "median": round(statistics.median(samples), 1),
        "p90": round(percentile_nearest_rank(samples, 90) or 0.0, 1),
    }


def basic_normalize(text: str) -> str:
    """Lower-case, drop punctuation, collapse whitespace. The CLI swaps in ``app.core.i18n.normalize_text``."""
    text = _WORD_RE.sub(" ", str(text).lower())
    return _WS_RE.sub(" ", text).strip()


def _word_edit_distance(ref: list[str], hyp: list[str]) -> int:
    """Levenshtein distance on word lists (substitutions + deletions + insertions)."""
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, start=1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, start=1):
            cost = 0 if r == h else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[-1]


def _wer_pure(refs: Sequence[str], hyps: Sequence[str]) -> float:
    edits = words = 0
    for ref, hyp in zip(refs, hyps, strict=True):
        r, h = ref.split(), hyp.split()
        edits += _word_edit_distance(r, h)
        words += len(r)
    return edits / words


def wer(
    refs: Sequence[str],
    hyps: Sequence[str],
    normalizer: Callable[[str], str] | None = None,
) -> float | None:
    """Corpus-level word error rate: (S + D + I) over all utterances / reference words.

    Uses ``jiwer`` when it is installed (the dev extra) and an equivalent pure-Python edit
    distance otherwise, so the number does not depend on the environment. Both texts are
    normalised first (``normalizer`` defaults to :func:`basic_normalize`). Returns ``None``
    for an empty set and raises ``ValueError`` on length mismatch or an empty reference.
    """
    if len(refs) != len(hyps):
        raise ValueError(f"refs and hyps differ in length ({len(refs)} vs {len(hyps)})")
    if not refs:
        return None
    norm = normalizer or basic_normalize
    n_refs = [norm(r) for r in refs]
    n_hyps = [norm(h) for h in hyps]
    for idx, r in enumerate(n_refs):
        if not r:
            raise ValueError(f"reference {idx} is empty after normalisation")
    try:
        import jiwer  # type: ignore[import-not-found]
    except ImportError:
        return _wer_pure(n_refs, n_hyps)
    return float(jiwer.wer(n_refs, n_hyps))


def is_example_row(row: dict) -> bool:
    """Rows whose ``participant_id`` starts with ``EXAMPLE`` are documentation, not data."""
    return str(row.get("participant_id", "")).strip().upper().startswith("EXAMPLE")


def usability_summary(rows: Iterable[dict], k: int = 5) -> dict[str, Any]:
    """Completion rate, median/range of ``time_s``, group counts and verbatim comments.

    EXAMPLE rows and rows with ``consent_recorded`` false are excluded. Groups with fewer
    than ``k`` participants are reported as a count only (they are never broken down further).
    """
    all_rows = list(rows)
    kept = [
        r
        for r in all_rows
        if not is_example_row(r) and _as_bool(r.get("consent_recorded", "true"))
    ]
    n = len(kept)
    completed = sum(1 for r in kept if _as_bool(r.get("task_completed")))
    times: list[float] = []
    for r in kept:
        raw = str(r.get("time_s", "")).strip()
        if raw:
            try:
                times.append(float(raw))
            except ValueError:
                continue
    comments = [
        str(r[key]).strip()
        for r in kept
        for key in ("comment1", "comment2", "comment3")
        if str(r.get(key) or "").strip()
    ]
    groups = Counter(str(r.get("group", "") or "unspecified") for r in kept)
    return {
        "n": n,
        "completed": completed,
        "completion_rate": completed / n if n else None,
        "median_time_s": statistics.median(times) if times else None,
        "time_range_s": [min(times), max(times)] if times else None,
        "groups": dict(sorted(groups.items())),
        "groups_below_k": sorted(g for g, c in groups.items() if c < k),
        "comments": comments,
        "excluded_rows": len(all_rows) - n,
    }


def is_dry_run(providers: dict[str, str]) -> bool:
    """True when any provider value is a mock (``mock`` LLM/STT/TTS or the ``hash`` embedder)."""
    return any(str(v).split(":", 1)[0].strip().lower() in MOCK_PROVIDER_VALUES for v in providers.values())


# =============================================================================================
# Loaders
# =============================================================================================
def load_jsonl(path: str | Path, *, required: Sequence[str] = ("id",), id_key: str = "id") -> list[dict]:
    """Parse a JSONL file, check that every row has ``required`` keys and that ids are unique."""
    path = Path(path)
    rows: list[dict] = []
    seen: set[str] = set()
    with open(path, encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{lineno}: invalid JSON ({exc.msg})") from exc
            if not isinstance(obj, dict):
                raise ValueError(f"{path}:{lineno}: expected an object")
            missing = [k for k in required if k not in obj]
            if missing:
                raise ValueError(f"{path}:{lineno}: missing keys {missing}")
            if id_key in obj:
                ident = str(obj[id_key])
                if ident in seen:
                    raise ValueError(f"{path}:{lineno}: duplicate id {ident!r}")
                seen.add(ident)
            rows.append(obj)
    return rows


def load_csv_rows(path: str | Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as fh:
        return [dict(row) for row in csv.DictReader(fh)]


def sample_spot_check(sentences: Sequence[dict], n: int = 50, seed: int = 0) -> list[dict]:
    """Stratified sample for the human spot-check: half judged supported, half unsupported.

    Each input dict carries ``supported`` plus the template columns; when one stratum is short
    the other fills the remaining slots. Deterministic for a given ``seed``.
    """
    rng = random.Random(seed)
    supported = [s for s in sentences if _as_bool(s.get("supported"))]
    unsupported = [s for s in sentences if not _as_bool(s.get("supported"))]
    rng.shuffle(supported)
    rng.shuffle(unsupported)
    half = n // 2
    take_sup = min(len(supported), half + max(0, half - len(unsupported)))
    take_unsup = min(len(unsupported), n - take_sup)
    chosen = supported[:take_sup] + unsupported[:take_unsup]
    chosen.sort(key=lambda s: (str(s.get("question_id", "")), str(s.get("sentence_id", ""))))
    return chosen


def write_spot_check_csv(path: str | Path, sentences: Sequence[dict]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(SPOT_CHECK_COLUMNS), extrasaction="ignore")
        writer.writeheader()
        for s in sentences:
            row = {col: s.get(col, "") for col in SPOT_CHECK_COLUMNS}
            score = row.get("judge_score")
            if isinstance(score, float):
                row["judge_score"] = f"{score:.3f}"
            writer.writerow(row)
    return path


# =============================================================================================
# Report rendering
# =============================================================================================
@dataclass
class Section:
    title: str
    rows: list[list[Any]] = field(default_factory=list)  # [metric, value, n, notes]
    notes: list[str] = field(default_factory=list)
    providers: dict[str, str] = field(default_factory=dict)
    columns: tuple[str, ...] = REPORT_COLUMNS

    def add(self, metric: str, value: Any, n: Any = "", notes: str = "") -> None:
        self.rows.append([metric, value, n, notes])

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "columns": list(self.columns),
            "rows": [list(r) for r in self.rows],
            "notes": list(self.notes),
            "providers": dict(self.providers),
        }


def fmt_value(value: Any) -> str:
    if value is None:
        return NOT_MEASURED
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.3f}"
    if isinstance(value, (list, tuple)):
        return ", ".join(fmt_value(v) for v in value)
    return str(value)


def _md_cell(value: Any) -> str:
    return fmt_value(value).replace("|", "\\|").replace("\n", " ")


def md_table(columns: Sequence[str], rows: Iterable[Sequence[Any]]) -> str:
    lines = ["| " + " | ".join(columns) + " |", "|" + "|".join("---" for _ in columns) + "|"]
    for row in rows:
        cells = list(row) + [""] * (len(columns) - len(row))
        lines.append("| " + " | ".join(_md_cell(c) for c in cells[: len(columns)]) + " |")
    return "\n".join(lines)


def providers_line(providers: dict[str, str]) -> str:
    if not providers:
        return ""
    return "Providers: " + ", ".join(f"{k}={v}" for k, v in providers.items())


def render_report(
    sections: Sequence[Section],
    date: str,
    *,
    config: dict[str, Any] | None = None,
    dry_run: bool = False,
    providers: dict[str, str] | None = None,
    title: str = "MILA measurement report",
) -> str:
    """Render the Markdown report (header, configuration table, one table per section)."""
    out: list[str] = [f"# {title}, {date}", ""]
    if dry_run:
        out += [
            "**DRY RUN (mock providers)**: at least one provider in this run is a deterministic mock.",
            "The numbers below measure the pipeline mechanics, not model quality, and must not be",
            "quoted as results.",
            "",
        ]
    if providers:
        out += [providers_line(providers), ""]
    out += ["## Configuration", ""]
    if config:
        out += [md_table(("Setting", "Value"), [[k, v] for k, v in config.items()]), ""]
    else:
        out += ["Configuration was not recorded.", ""]
    for section in sections:
        out += [f"## {section.title}", ""]
        line = providers_line(section.providers)
        if line:
            out += [line, ""]
        if section.rows:
            out += [md_table(section.columns, section.rows), ""]
        for note in section.notes:
            out += [f"- {note}"]
        if section.notes:
            out.append("")
    return "\n".join(out).rstrip() + "\n"


def write_report(path: str | Path, markdown: str, data: dict[str, Any] | None = None) -> list[Path]:
    """Write ``path`` (Markdown) and, when ``data`` is given, the sibling ``.json``. Returns written paths."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")
    written = [path]
    if data is not None:
        json_path = path.with_suffix(".json")
        json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
        written.append(json_path)
    return written


# =============================================================================================
# CLI (lazy backend imports from here on)
# =============================================================================================
def _bootstrap_backend() -> None:
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))


def _git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _error_note(what: str, exc: BaseException) -> str:
    msg = str(exc).replace("\n", " ")
    return f"{what}: {NOT_MEASURED} ({type(exc).__name__}: {msg[:200]})"


def _write_silent_wav(path: Path, seconds: float = 0.5, rate: int = 16000) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"\x00\x00" * int(seconds * rate))
    return path


def _resolve_audio(entry: dict) -> Path:
    raw = str(entry.get("audio", ""))
    p = Path(raw)
    if p.is_absolute():
        return p
    if raw.startswith("eval/"):
        return REPO_ROOT / raw
    return WER_MANIFEST_FILE.parent / raw


def _limit(items: list[dict], limit: int | None) -> list[dict]:
    return items[:limit] if limit else items


class MeasurementRun:
    """Runs every section against the backend and collects :class:`Section` objects plus raw data."""

    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.date: str = args.date
        self.skip: set[str] = set(args.skip)
        self.limit: int | None = args.limit
        self.sections: list[Section] = []
        self.data: dict[str, Any] = {}
        self.text_latencies: list[float] = []
        self.voice_latencies: list[float] = []
        self.settings: Any = None
        self.db: Any = None
        self.session: Any = None
        self.pipeline: Any = None
        self.pipeline_error: str = "pipeline not built"
        self.tts: Any = None
        self.providers: dict[str, str] = {}
        self.normalize: Callable[[str], str] = basic_normalize

    # --- setup --------------------------------------------------------------------------------
    def setup(self) -> None:
        _bootstrap_backend()
        from app.config import Settings
        from app.db import init_engine, session_factory

        overrides: dict[str, Any] = {"demo_mode": True}
        if self.args.database_url:
            overrides["database_url"] = self.args.database_url
        elif not os.environ.get("MILA_DATABASE_URL"):
            overrides["database_url"] = f"sqlite:///{REPO_ROOT / '.measure.db'}"
        self.settings = Settings(**overrides)
        init_engine(self.settings.database_url)
        self.db = session_factory()()
        s = self.settings
        self.providers = {
            "llm": s.llm_provider if s.llm_provider == "mock" else f"{s.llm_provider}:{s.llm_model}",
            "judge": s.judge_provider,
            "stt": s.stt_provider if s.stt_provider == "mock" else f"{s.stt_provider}:{s.stt_model}",
            "tts": s.tts_provider,
            "embedder": s.embedder,
        }
        try:
            from app.core.i18n import normalize_text

            self.normalize = normalize_text
        except Exception:  # pragma: no cover - i18n is part of the core contract
            pass
        self._ensure_kb()
        self._seed_referrals()
        self._create_session()
        try:
            self._build_pipeline()
        except Exception as exc:  # sections that need the pipeline report it; the others still run
            self.pipeline = None
            self.pipeline_error = f"pipeline unavailable ({type(exc).__name__}: {str(exc)[:200]})"
            self.data["pipeline_error"] = self.pipeline_error

    def _ensure_kb(self) -> None:
        from sqlalchemy import func, select

        from app.models import Chunk

        n_chunks = self.db.scalar(select(func.count()).select_from(Chunk)) or 0
        if n_chunks:
            self.data["kb_ingested_now"] = False
            return
        from app.kb.ingest import ingest_manifest

        report = ingest_manifest(self.db, self.settings)
        self.data["kb_ingested_now"] = True
        self.data["kb_ingest_report"] = report.model_dump() if hasattr(report, "model_dump") else str(report)

    def _seed_referrals(self) -> None:
        try:
            from app.core.referral import seed_referral_points

            seed_referral_points(self.db)
        except Exception as exc:  # referral module may be absent in a partial checkout
            self.data["referral_seed_error"] = f"{type(exc).__name__}: {str(exc)[:200]}"

    def _create_session(self) -> None:
        from app.core.privacy import new_session_id
        from app.models import Session

        self.session = Session(
            id=new_session_id(),
            lang="sr",
            script="latin",
            region=self.settings.default_region,
            is_minor=False,
            consent_given=True,
            consent_version=self.settings.consent_version,
            consent_save_questions=False,
            consent_given_at=datetime.now(UTC),
        )
        self.db.add(self.session)
        self.db.commit()

    def _build_pipeline(self) -> None:
        # noqa on the block: ruff sorts app.* modules by whether their files exist yet, and these
        # modules are built in parallel; the order below is the final alphabetical one.
        from app.core.pipeline import AskPipeline  # noqa: I001
        from app.core.redflags import get_router
        from app.core.verifier import get_judge
        from app.kb.embed import get_embedder
        from app.services.llm import get_llm

        llm = get_llm(self.settings)
        embedder = get_embedder(self.settings)
        judge = get_judge(self.settings, llm)
        tts = None
        try:
            from app.services.tts import get_tts

            tts = get_tts(self.settings)
        except Exception:
            tts = None
        self.tts = tts
        self.pipeline = AskPipeline(
            self.settings, self.db, llm=llm, embedder=embedder, judge=judge, redflags=get_router(), tts=tts
        )

    def teardown(self) -> None:
        if self.db is None:
            return
        try:
            if self.session is not None and not self.args.keep_session:
                from app.core.privacy import delete_session_data

                self.data["evaluation_session_deleted"] = delete_session_data(self.db, self.session.id)
        except Exception as exc:
            self.data["evaluation_session_deleted"] = f"failed: {type(exc).__name__}"
        finally:
            self.db.close()

    # --- helpers ------------------------------------------------------------------------------
    def ask(self, text: str, lang: str, *, input_mode: str = "text") -> tuple[Any, float]:
        from app.core.types import AskRequest

        req = AskRequest(
            session_id=self.session.id,
            text=text,
            lang=lang if lang in ("sr", "bs", "hr", "me", "en") else None,
            script="latin",
            region=self.settings.default_region,
            input_mode=input_mode,  # type: ignore[arg-type]
        )
        t0 = time.perf_counter()
        resp = self.pipeline.ask(req, self.session)
        ms = (time.perf_counter() - t0) * 1000.0
        return resp, ms

    def _sentences_of(self, resp: Any) -> list[Any]:
        gate = getattr(resp, "gate", None)
        if gate is not None:
            return list(gate.kept) + list(gate.removed)
        return list(getattr(resp, "sentences", []) or [])

    def _providers_for(self, *keys: str) -> dict[str, str]:
        return {k: self.providers[k] for k in keys if k in self.providers}

    # --- sections -----------------------------------------------------------------------------
    def section_support(self) -> None:
        sec = Section("Support rate (in-KB questions)", providers=self._providers_for("llm", "judge", "embedder"))
        self.sections.append(sec)
        if self.pipeline is None:
            sec.add("Support rate (sentence level)", None, 0, self.pipeline_error)
            return
        path = INKB_FILE if INKB_FILE.exists() else ONKB_FILE_LEGACY
        try:
            questions = _limit(load_jsonl(path, required=("id", "lang", "text")), self.limit)
        except (OSError, ValueError) as exc:
            sec.notes.append(_error_note("dataset", exc))
            return
        records: list[dict] = []
        spot: list[dict] = []
        answered = reached_verifier = 0
        answer_ratios: list[float] = []
        errors: list[str] = []
        for q in questions:
            try:
                resp, ms = self.ask(q["text"], q["lang"])
            except Exception as exc:
                errors.append(f"{q['id']}: {type(exc).__name__}")
                continue
            self.text_latencies.append(ms)
            if resp.outcome == "redflag":
                records.append({"id": q["id"], "lang": q["lang"], "outcome": resp.outcome, "sentences": []})
                continue
            reached_verifier += 1
            if resp.outcome == "answered":
                answered += 1
            gate = getattr(resp, "gate", None)
            if gate is not None:
                answer_ratios.append(float(gate.support_ratio))
            marker_to_chunk = {c.marker: c.chunk_id for c in (getattr(resp, "citations", None) or [])}
            sentences = self._sentences_of(resp)
            records.append(
                {
                    "id": q["id"],
                    "lang": q["lang"],
                    "outcome": resp.outcome,
                    "sentences": [{"supported": bool(s.supported)} for s in sentences],
                }
            )
            for idx, s in enumerate(sentences, start=1):
                spot.append(
                    {
                        "sentence_id": f"{q['id']}-s{idx:02d}",
                        "question_id": q["id"],
                        "sentence": s.text,
                        "citation_chunk_id": ";".join(marker_to_chunk.get(m, m) for m in s.citations),
                        "judge_score": float(s.support_score),
                        "supported": bool(s.supported),
                        "rater1_supported": "",
                        "rater2_supported": "",
                        "notes": "",
                    }
                )
        supported, total = support_counts(records)
        rate = support_rate(records)
        per_lang = grouped_rate(records, "lang", support_rate)
        sec.add("Support rate (sentence level)", rate, total, f"{supported} supported sentences / {total}")
        for lang, g in per_lang.items():
            n_sent = support_counts([r for r in records if r.get("lang") == lang])[1]
            sec.add(f"Support rate, {lang}", g["rate"], n_sent, f"{g['n']} questions")
        sec.add(
            "Answer-level mean support ratio",
            statistics.mean(answer_ratios) if answer_ratios else None,
            len(answer_ratios),
            "mean of GateDecision.support_ratio",
        )
        sec.add("Answered share", answered / len(questions) if questions else None, len(questions), f"{answered} answered")
        sec.add("Reached verifier", reached_verifier, len(questions), "questions not red-flagged")
        judge = self.providers.get("judge", "")
        if judge == "lexical":
            sec.notes.append("Lexical judge: this support rate is an upper bound until the human spot-check is done.")
        sec.notes.append(
            f"Verifier threshold {self.settings.verifier_support_threshold}, gate min support ratio "
            f"{self.settings.gate_min_support_ratio}, gate min confidence {self.settings.gate_min_confidence}."
        )
        if errors:
            sec.notes.append(f"Errors (id: type) on {len(errors)} questions: " + ", ".join(errors[:20]))
        spot_path = self.args.out.with_name(f"{self.date}_spotcheck.csv")
        chosen = sample_spot_check(spot, n=50, seed=0)
        write_spot_check_csv(spot_path, chosen)
        sec.notes.append(
            f"Spot-check sheet with {len(chosen)} sentences written to {spot_path.relative_to(REPO_ROOT) if spot_path.is_relative_to(REPO_ROOT) else spot_path}; "
            "rater columns are empty until two raters fill them (docs/evaluation.md, section 3)."
        )
        self.data["support"] = {
            "rate": rate,
            "supported": supported,
            "total_sentences": total,
            "per_lang": per_lang,
            "answer_level_mean_support_ratio": statistics.mean(answer_ratios) if answer_ratios else None,
            "answered": answered,
            "n_questions": len(questions),
            "reached_verifier": reached_verifier,
            "errors": errors,
            "outcomes": dict(Counter(r["outcome"] for r in records)),
            "spot_check_sheet": str(spot_path),
            "spot_check_sentences": len(chosen),
        }

    def section_refusal(self) -> None:
        sec = Section("Refusal correctness (off-KB questions)", providers=self._providers_for("llm", "judge", "embedder"))
        self.sections.append(sec)
        if self.pipeline is None:
            sec.add("Refusal correctness", None, 0, self.pipeline_error)
            return
        try:
            questions = _limit(load_jsonl(OFFKB_FILE, required=("id", "lang", "text", "category", "expected")), self.limit)
        except (OSError, ValueError) as exc:
            sec.notes.append(_error_note("dataset", exc))
            return
        results: list[dict] = []
        errors: list[str] = []
        for q in questions:
            try:
                resp, ms = self.ask(q["text"], q["lang"])
            except Exception as exc:
                errors.append(f"{q['id']}: {type(exc).__name__}")
                continue
            self.text_latencies.append(ms)
            gate = getattr(resp, "gate", None)
            results.append(
                {
                    "id": q["id"],
                    "lang": q["lang"],
                    "category": q["category"],
                    "expected": q["expected"],
                    "outcome": resp.outcome,
                    "reasons": list(gate.reasons) if gate is not None else [],
                    "redflag_category": getattr(resp, "redflag_category", None) or "",
                }
            )
        rate = refusal_correctness(results)
        wrong = incorrect_refusals(results)
        sec.add("Refusal correctness", rate, len(results), f"{len(results) - len(wrong)} withheld / {len(results)}")
        for cat, g in grouped_rate(results, "category", refusal_correctness).items():
            sec.add(f"Refusal correctness, {cat}", g["rate"], g["n"])
        for lang, g in grouped_rate(results, "lang", refusal_correctness).items():
            sec.add(f"Refusal correctness, {lang}", g["rate"], g["n"])
        if wrong:
            listing = "; ".join(
                f"{w['id']} -> {w['outcome']}" + (f" [{', '.join(w['reasons'])}]" if w["reasons"] else "")
                + (f" ({w['redflag_category']})" if w["redflag_category"] else "")
                for w in wrong[:40]
            )
            sec.notes.append(f"Incorrect cases ({len(wrong)}), by id only: {listing}")
        if errors:
            sec.notes.append(f"Errors (id: type) on {len(errors)} questions: " + ", ".join(errors[:20]))
        sec.notes.append("A red-flag or answered outcome on an off-KB question counts as incorrect.")
        self.data["refusal"] = {
            "rate": rate,
            "n": len(results),
            "incorrect": wrong,
            "per_category": grouped_rate(results, "category", refusal_correctness),
            "per_lang": grouped_rate(results, "lang", refusal_correctness),
            "errors": errors,
        }

    def section_redflags(self) -> None:
        sec = Section("Red-flag router (recall and false positives)", providers={"router": "rules+classifier"})
        self.sections.append(sec)
        try:
            from app.core.redflags import get_router

            router = get_router()
        except Exception as exc:
            sec.notes.append(_error_note("router", exc))
            return

        def run(path: Path, required: tuple[str, ...]) -> list[dict] | None:
            if not path.exists():
                sec.notes.append(f"{path.relative_to(REPO_ROOT)}: {NOT_MEASURED} (dataset missing)")
                return None
            try:
                rows = _limit(load_jsonl(path, required=required), self.limit)
            except ValueError as exc:
                sec.notes.append(_error_note(path.name, exc))
                return None
            out: list[dict] = []
            for r in rows:
                res = router.check(r["text"], lang=r.get("lang"))
                out.append(
                    {
                        "id": r["id"],
                        "lang": r.get("lang", ""),
                        "variant": r.get("variant", ""),
                        "expected": r.get("expected"),
                        "flagged": bool(res.flagged),
                        "category": res.category,
                        "source": res.source,
                    }
                )
            return out

        positives = run(REDFLAG_INPUTS_FILE, ("id", "lang", "text", "category", "expected"))
        negatives = run(REDFLAG_NEGATIVES_FILE, ("id", "lang", "text"))
        payload: dict[str, Any] = {}
        if positives is not None:
            recall = redflag_recall(positives)
            misses = [p["id"] for p in positives if not (p["flagged"] and p["category"] == p["expected"])]
            sec.add("Red-flag recall", recall, len(positives), f"{len(positives) - len(misses)} correct")
            per_cat = grouped_rate(positives, "expected", redflag_recall)
            per_var = grouped_rate(positives, "variant", redflag_recall)
            for cat, g in per_cat.items():
                sec.add(f"Recall, {cat}", g["rate"], g["n"])
            for var, g in per_var.items():
                if var:
                    sec.add(f"Recall, variant {var}", g["rate"], g["n"])
            if misses:
                sec.notes.append(f"Missed ids ({len(misses)}): " + ", ".join(misses[:40]))
            payload["recall"] = recall
            payload["n_inputs"] = len(positives)
            payload["missed_ids"] = misses
            payload["per_category"] = per_cat
            payload["per_variant"] = per_var
        if negatives is not None:
            fpr = redflag_false_positive_rate(negatives)
            fps = [n["id"] for n in negatives if n["flagged"]]
            sec.add("False-positive rate", fpr, len(negatives), f"{len(fps)} flagged")
            if fps:
                sec.notes.append(f"False-positive ids ({len(fps)}): " + ", ".join(fps[:40]))
            payload["false_positive_rate"] = fpr
            payload["n_negatives"] = len(negatives)
            payload["false_positive_ids"] = fps
        sec.notes.append("Measured by calling RedFlagRouter.check(text, lang=lang) directly; the pipeline path is covered by the test suite.")
        self.data["redflags"] = payload

    def section_latency(self) -> None:
        sec = Section("Latency (ms)", providers=self._providers_for("llm", "judge", "stt", "tts", "embedder"))
        self.sections.append(sec)
        text_stats = latency_stats(self.text_latencies)
        sec.add("Text median", text_stats["median"], text_stats["n"], "POST /api/ask equivalent, in-KB + off-KB questions")
        sec.add("Text p90", text_stats["p90"], text_stats["n"], "nearest-rank")
        payload: dict[str, Any] = {"text": text_stats}
        if "latency_voice" in self.skip:
            sec.add("Voice median", None, 0, "skipped (--skip latency_voice)")
            sec.add("Voice p90", None, 0, "skipped (--skip latency_voice)")
        else:
            note = self._run_voice_latency()
            voice_stats = latency_stats(self.voice_latencies)
            sec.add("Voice median", voice_stats["median"], voice_stats["n"], note)
            sec.add("Voice p90", voice_stats["p90"], voice_stats["n"], "nearest-rank")
            payload["voice"] = voice_stats
            payload["voice_note"] = note
        if is_dry_run(self.providers):
            sec.notes.append("Mock providers: these latencies are pipeline overhead only.")
        sec.notes.append(
            f"Hardware: {platform.machine()}, {os.cpu_count() or '?'} CPUs, {platform.system()} {platform.release()}; "
            "sequential requests on an idle process; models not warmed separately."
        )
        self.data["latency"] = payload

    def _run_voice_latency(self) -> str:
        if self.pipeline is None:
            return self.pipeline_error
        try:
            from app.services.stt import get_stt

            stt = get_stt(self.settings)
        except Exception as exc:
            return _error_note("STT", exc)
        if not WER_MANIFEST_FILE.exists():
            return f"{NOT_MEASURED} (eval/wer_set/manifest.jsonl missing)"
        try:
            utterances = _limit(load_jsonl(WER_MANIFEST_FILE, required=("id", "audio", "lang", "reference")), self.limit)
        except ValueError as exc:
            return _error_note("manifest", exc)
        tmp_dir = Path(self.settings.audio_tmp_dir)
        synthetic_used = False
        for utt in utterances:
            audio = _resolve_audio(utt)
            if not audio.exists():
                audio = _write_silent_wav(tmp_dir / f"measure-{utt['id']}.wav")
                synthetic_used = True
            t0 = time.perf_counter()
            try:
                transcript = stt.transcribe(audio, lang_hint=utt.get("lang"))
                text = (getattr(transcript, "text", "") or "").strip() or utt["reference"]
                resp, _ = self.ask(text, utt.get("lang", "sr"), input_mode="voice")
                if self.tts is not None:
                    spoken = " ".join(s.text for s in getattr(resp, "sentences", []) or []) or resp.message or "."
                    self.tts.synthesize(spoken, resp.lang)
            except Exception as exc:
                return _error_note("voice run", exc)
            finally:
                if audio.parent == tmp_dir and audio.exists():
                    audio.unlink()
            self.voice_latencies.append((time.perf_counter() - t0) * 1000.0)
        parts = ["transcribe + ask + speak"]
        if self.providers.get("stt") == "mock":
            parts.append("mock STT")
        if self.providers.get("tts") == "mock":
            parts.append("mock TTS")
        if synthetic_used:
            parts.append("synthetic silent audio (no consented recordings yet); transcript replaced by the reference text when empty")
        return "; ".join(parts)

    def section_wer(self) -> None:
        sec = Section("Word error rate (consented utterances)", providers=self._providers_for("stt"))
        self.sections.append(sec)
        if "wer" in self.skip:
            sec.add("WER", None, 0, "skipped (--skip wer)")
            self.data["wer"] = {"skipped": True}
            return
        if not WER_MANIFEST_FILE.exists():
            sec.add("WER", None, 0, f"{NOT_MEASURED} (manifest missing)")
            return
        try:
            utterances = load_jsonl(WER_MANIFEST_FILE, required=("id", "audio", "lang", "reference"))
        except ValueError as exc:
            sec.notes.append(_error_note("manifest", exc))
            return
        usable = [u for u in utterances if _as_bool(u.get("consent_recorded")) and _resolve_audio(u).exists()]
        usable = _limit(usable, self.limit)
        if not usable:
            sec.add("WER", None, 0, f"{NOT_MEASURED} (no consented recordings yet)")
            sec.notes.append(f"{len(utterances)} reference utterances are listed; recordings are collected per eval/wer_set/README.md.")
            self.data["wer"] = {"n": 0, "listed": len(utterances)}
            return
        try:
            from app.services.stt import get_stt

            stt = get_stt(self.settings)
        except Exception as exc:
            sec.notes.append(_error_note("STT", exc))
            return
        refs: list[str] = []
        hyps: list[str] = []
        langs: list[str] = []
        for u in usable:
            try:
                tr = stt.transcribe(_resolve_audio(u), lang_hint=u.get("lang"))
            except Exception as exc:
                sec.notes.append(_error_note(u["id"], exc))
                continue
            refs.append(u["reference"])
            hyps.append(getattr(tr, "text", "") or "")
            langs.append(u.get("lang", ""))
        overall = wer(refs, hyps, self.normalize) if refs else None
        sec.add("WER overall", overall, len(refs), "normalised with app.core.i18n.normalize_text")
        per_lang: dict[str, Any] = {}
        for lang in sorted(set(langs)):
            idx = [i for i, l_ in enumerate(langs) if l_ == lang]
            value = wer([refs[i] for i in idx], [hyps[i] for i in idx], self.normalize)
            per_lang[lang] = {"wer": value, "n": len(idx)}
            sec.add(f"WER, {lang}", value, len(idx))
        if self.providers.get("stt") == "mock":
            sec.notes.append("Mock STT: this is not a speech-recognition measurement.")
        self.data["wer"] = {"overall": overall, "n": len(refs), "per_lang": per_lang}

    def section_usability(self) -> None:
        sec = Section("Usability (facilitated sessions)", providers={})
        self.sections.append(sec)
        if "usability" in self.skip:
            sec.add("Task completion rate", None, 0, "skipped (--skip usability)")
            self.data["usability"] = {"skipped": True}
            return
        if not USABILITY_FILE.exists():
            sec.add("Task completion rate", None, 0, f"{NOT_MEASURED} (eval/usability_sessions.csv missing)")
            return
        rows = load_csv_rows(USABILITY_FILE)
        summary = usability_summary(rows, k=int(self.settings.k_anonymity))
        if summary["n"] == 0:
            sec.add("Task completion rate", None, 0, f"{NOT_MEASURED} (no usability sessions recorded yet)")
            self.data["usability"] = summary
            return
        sec.add("Task completion rate", summary["completion_rate"], summary["n"], f"{summary['completed']} completed")
        sec.add("Median time (s)", summary["median_time_s"], summary["n"], f"range {fmt_value(summary['time_range_s'])}")
        for group, count in summary["groups"].items():
            sec.add(f"Participants, {group}", count, "", "count only" if group in summary["groups_below_k"] else "")
        for comment in summary["comments"]:
            sec.notes.append(f"Comment: {comment}")
        self.data["usability"] = summary

    def section_spot_check_and_incidents(self) -> None:
        spot = Section("Spot-check")
        if self.data.get("support", {}).get("spot_check_sheet"):
            spot.notes.append(
                "Not run in this report: the spot-check sheet written next to this file has empty rater columns. "
                "Agreement, kappa and judge accuracy are added in a later report once two raters have labelled it."
            )
        else:
            spot.notes.append("Not run: no spot-check sheet could be written because the support section did not run.")
        self.sections.append(spot)
        inc = Section("Incidents since the last report")
        inc.notes.append(
            "Not computed by this script. Maintainers add the count by severity and the fix commits from the "
            "incident log (docs/safety.md) before committing the report."
        )
        self.sections.append(inc)

    def section_caveats(self) -> None:
        sec = Section("Caveats")
        if is_dry_run(self.providers):
            sec.notes.append("DRY RUN: at least one provider is a mock; nothing here describes model quality.")
        if self.providers.get("judge") == "lexical":
            sec.notes.append("The lexical judge over-estimates support; treat the support rate as an upper bound.")
        if self.settings.demo_mode:
            sec.notes.append("Demo mode: answers may draw on public_unreviewed demo sources.")
        sec.notes.append(f"Groups and cells with fewer than {self.settings.k_anonymity} observations are reported as counts only.")
        if self.limit:
            sec.notes.append(f"--limit {self.limit}: every dataset was truncated to its first {self.limit} rows.")
        if self.args.keep_session:
            sec.notes.append("The evaluation session and its events were kept in the database (--keep-session).")
        else:
            sec.notes.append("The evaluation session created for this run and its events were deleted afterwards.")
        self.sections.append(sec)

    # --- configuration ------------------------------------------------------------------------
    def config(self) -> dict[str, Any]:
        s = self.settings
        try:
            from app.core.gate import GATE_VERSION

            gate_version = GATE_VERSION
        except Exception:
            gate_version = "unknown"
        sources = "n/a"
        try:
            from sqlalchemy import select

            from app.models import Source, SourceVersion

            rows = self.db.execute(
                select(Source.id, Source.review_status, SourceVersion.version_hash)
                .join(SourceVersion, SourceVersion.source_id == Source.id)
                .where(SourceVersion.is_current.is_(True))
                .order_by(Source.id)
            ).all()
            sources = "; ".join(f"{sid} ({status}, {vh[:12]})" for sid, status, vh in rows) or "none"
        except Exception as exc:
            sources = f"unavailable ({type(exc).__name__})"
        datasets = {
            "in-KB questions": INKB_FILE if INKB_FILE.exists() else ONKB_FILE_LEGACY,
            "off-KB questions": OFFKB_FILE,
            "red-flag inputs": REDFLAG_INPUTS_FILE,
            "red-flag negatives": REDFLAG_NEGATIVES_FILE,
            "WER utterances": WER_MANIFEST_FILE,
        }
        sizes = ", ".join(
            f"{name}={sum(1 for line in open(p, encoding='utf-8') if line.strip()) if p.exists() else 'missing'}"
            for name, p in datasets.items()
        )
        return {
            "git commit": _git_commit(),
            "gate version": gate_version,
            "date": self.date,
            "dry run": "yes" if is_dry_run(self.providers) else "no",
            "MILA_APP_ENV": s.app_env,
            "MILA_DEMO_MODE": s.demo_mode,
            "MILA_LLM_PROVIDER": s.llm_provider,
            "MILA_LLM_MODEL": s.llm_model if s.llm_provider != "mock" else "(mock)",
            "MILA_JUDGE_PROVIDER": s.judge_provider,
            "MILA_EMBEDDER": s.embedder,
            "MILA_STT_PROVIDER": s.stt_provider,
            "MILA_TTS_PROVIDER": s.tts_provider,
            "MILA_RETRIEVAL_TOP_K": s.retrieval_top_k,
            "MILA_GATE_MIN_SUPPORT_RATIO": s.gate_min_support_ratio,
            "MILA_GATE_MIN_CONFIDENCE": s.gate_min_confidence,
            "MILA_VERIFIER_SUPPORT_THRESHOLD": s.verifier_support_threshold,
            "MILA_REDFLAG_CLASSIFIER_THRESHOLD": s.redflag_classifier_threshold,
            "MILA_K_ANONYMITY": s.k_anonymity,
            "database": s.database_url.split("://", 1)[0] + "://...",
            "hardware": f"{platform.machine()}, {os.cpu_count() or '?'} CPUs, {platform.python_implementation()} {platform.python_version()}",
            "dataset sizes": sizes,
            "KB sources (current versions)": sources,
            "skipped": ", ".join(sorted(self.skip)) or "none",
            "limit": self.limit or "none",
        }

    # --- orchestration ------------------------------------------------------------------------
    def run_sections(self) -> None:
        for fn in (
            self.section_support,
            self.section_refusal,
            self.section_redflags,
            self.section_latency,
            self.section_wer,
            self.section_usability,
        ):
            try:
                fn()
            except Exception as exc:  # a broken section never hides the others
                name = fn.__name__.replace("section_", "")
                sec = Section(f"{name} (failed)")
                sec.notes.append(_error_note(name, exc))
                self.sections.append(sec)
                self.data[name] = {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}
        self.section_spot_check_and_incidents()
        self.section_caveats()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="measure.py",
        description="Run the MILA evaluation datasets and write reports/<date>_measurement.{md,json}.",
    )
    parser.add_argument("--date", default=date_type.today().isoformat(), help="report date (YYYY-MM-DD), default today")
    parser.add_argument("--out", type=Path, default=None, help="Markdown path; default reports/<date>_measurement.md")
    parser.add_argument(
        "--skip",
        default="",
        help="comma-separated sections to skip: " + ",".join(SKIPPABLE),
    )
    parser.add_argument("--limit", type=int, default=None, help="use only the first N rows of every dataset")
    parser.add_argument("--database-url", default=None, help="SQLAlchemy URL (default: MILA_DATABASE_URL or a local SQLite file)")
    parser.add_argument("--keep-session", action="store_true", help="do not delete the evaluation session afterwards")
    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    args = build_parser().parse_args(argv)
    skip = [s.strip() for s in args.skip.split(",") if s.strip()]
    unknown = sorted(set(skip) - set(SKIPPABLE))
    if unknown:
        build_parser().error(f"unknown --skip values {unknown}; allowed: {', '.join(SKIPPABLE)}")
    args.skip = skip
    if args.out is None:
        args.out = REPORTS_DIR / f"{args.date}_measurement.md"
    args.out = Path(args.out)
    if args.limit is not None and args.limit <= 0:
        build_parser().error("--limit must be a positive integer")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    run = MeasurementRun(args)
    config: dict[str, Any]
    try:
        run.setup()
        run.run_sections()
        config = run.config()
    except Exception as exc:
        sec = Section("Run failed before any section completed")
        sec.notes.append(_error_note("setup", exc))
        run.sections.append(sec)
        config = {"git commit": _git_commit(), "date": args.date, "error": f"{type(exc).__name__}"}
    finally:
        run.teardown()
    dry = is_dry_run(run.providers) if run.providers else True
    markdown = render_report(run.sections, args.date, config=config, dry_run=dry, providers=run.providers)
    data = {
        "date": args.date,
        "dry_run": dry,
        "providers": run.providers,
        "config": config,
        "sections": [s.to_dict() for s in run.sections],
        "results": run.data,
    }
    try:
        written = write_report(args.out, markdown, data)
    except OSError as exc:
        print(f"could not write report: {exc}", file=sys.stderr)
        return 1
    for p in written:
        print(f"wrote {p}")
    if dry:
        print("DRY RUN (mock providers): do not quote these numbers.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
