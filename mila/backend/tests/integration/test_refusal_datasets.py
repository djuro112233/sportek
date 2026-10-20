"""Dataset-level regression guard for the numbers that go into the measurement report.

Runs the evaluation sets through the real pipeline (mock providers, demo KB) and asserts the
floors the prototype must keep: refusal correctness on eval/offkb_questions.jsonl and the
answered share on eval/inkb_questions.jsonl. scripts/measure.py reports the exact values.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.container import build_providers
from app.core.pipeline import AskPipeline
from app.core.privacy import new_session_id
from app.core.types import AskRequest
from app.db import make_engine
from app.kb.embed import HashEmbedder
from app.kb.ingest import ingest_manifest, load_manifest
from app.models import Base
from app.models import Session as SessionRow
from tests.conftest import REPO_ROOT, make_test_settings

MIN_REFUSAL_CORRECTNESS = 0.90
MIN_INKB_ANSWERED_SHARE = 0.85


def _rows(name: str) -> list[dict]:
    with open(REPO_ROOT / "eval" / name, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


@pytest.fixture(scope="module")
def pipeline(tmp_path_factory):
    tmp_path: Path = tmp_path_factory.mktemp("refusal_datasets")
    settings = make_test_settings(tmp_path)
    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    demo_ids = {d.id for d in load_manifest(settings.manifest_path) if d.id.startswith("demo-")}
    assert ingest_manifest(db, settings, HashEmbedder(dim=settings.embedding_dim), only=demo_ids).ok
    sess = SessionRow(
        id=new_session_id(),
        lang="sr",
        script="latin",
        region="BA",
        is_minor=False,
        consent_given=True,
        consent_version=settings.consent_version,
    )
    db.add(sess)
    db.commit()
    pipe = AskPipeline(settings, db, build_providers(settings))
    try:
        yield pipe, sess
    finally:
        db.close()
        engine.dispose()


def _outcomes(pipeline_and_session, rows: list[dict]) -> dict[str, str]:
    pipe, sess = pipeline_and_session
    out: dict[str, str] = {}
    for row in rows:
        response = pipe.ask(AskRequest(session_id=sess.id, text=row["text"], lang=row.get("lang")), sess)
        out[row["id"]] = response.outcome
    return out


def test_off_kb_questions_are_withheld(pipeline) -> None:
    rows = _rows("offkb_questions.jsonl")
    outcomes = _outcomes(pipeline, rows)
    wrong = sorted(i for i, o in outcomes.items() if o != "withheld")
    correctness = 1 - len(wrong) / len(rows)
    assert correctness >= MIN_REFUSAL_CORRECTNESS, (
        f"refusal correctness {correctness:.2f}; answered/redflag: {wrong}"
    )
    assert "redflag" not in outcomes.values()


def test_in_kb_questions_are_answered(pipeline) -> None:
    rows = _rows("inkb_questions.jsonl")
    outcomes = _outcomes(pipeline, rows)
    withheld = sorted(i for i, o in outcomes.items() if o != "answered")
    share = 1 - len(withheld) / len(rows)
    assert share >= MIN_INKB_ANSWERED_SHARE, f"answered share {share:.2f}; not answered: {withheld}"
