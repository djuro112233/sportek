"""Tests for app.core.retrieval: hybrid search over the demo knowledge base, filters, boosts."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from conftest import make_test_settings
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.core.retrieval import BM25Okapi, Retriever, reciprocal_rank_fusion, same_language_family
from app.core.types import RetrievedChunk
from app.db import make_engine
from app.kb.embed import HashEmbedder
from app.kb.ingest import ManifestDoc, ingest_document, ingest_manifest, load_manifest
from app.models import Base, Chunk

EN_QUESTIONS = [
    ("Which contraception methods are available and how do they work?", "demo-en-contraception-methods"),
    ("How soon after unprotected sex can I use emergency contraception?", "demo-en-emergency-contraception"),
    ("What happens at antenatal care visits during pregnancy?", "demo-en-antenatal-care-visits"),
    (
        "What are the danger signs in pregnancy that mean I should seek care immediately?",
        "demo-en-pregnancy-danger-signs",
    ),
    ("How do I know my baby is breastfeeding well and getting enough milk?", "demo-en-breastfeeding-basics"),
    ("What is the baby blues and when should I seek help?", "demo-en-perinatal-mental-health"),
]
SR_QUESTIONS = [
    ("Koje metode kontracepcije postoje i kako djeluju?", "demo-sr-contraception-methods"),
    (
        "Koliko dugo nakon nezaštićenog odnosa mogu uzeti hitnu kontracepciju?",
        "demo-sr-emergency-contraception",
    ),
    ("Šta se dešava na pregledima u trudnoći?", "demo-sr-antenatal-care-visits"),
    (
        "Koji su znaci opasnosti u trudnoći kada treba odmah potražiti pomoć?",
        "demo-sr-pregnancy-danger-signs",
    ),
    ("Kako da znam da li beba dobro doji i dobija dovoljno mlijeka?", "demo-sr-breastfeeding-basics"),
    ("Шта је хитна контрацепција?", "demo-sr-emergency-contraception"),
]


@pytest.fixture(scope="module")
def demo_kb(tmp_path_factory):
    """The full demo KB (real manifest, demo ids only) ingested once per module with the hash embedder."""
    tmp_path: Path = tmp_path_factory.mktemp("demo_kb")
    settings = make_test_settings(tmp_path)
    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    demo_ids = {d.id for d in load_manifest(settings.manifest_path) if d.id.startswith("demo-")}
    embedder = HashEmbedder(dim=settings.embedding_dim)
    started = time.perf_counter()
    report = ingest_manifest(db, settings, embedder, only=demo_ids)
    elapsed = time.perf_counter() - started
    try:
        yield settings, db, embedder, report, elapsed
    finally:
        db.close()
        engine.dispose()


@pytest.fixture
def retriever(demo_kb) -> Retriever:
    settings, db, embedder, _report, _elapsed = demo_kb
    return Retriever(db, embedder, settings)


def _seed(db, tmp_path: Path, docs: list[tuple[str, str, str, dict]]) -> None:
    """Ingest small documents given as (id, lang, markdown text, extra manifest fields)."""
    for doc_id, lang, text, extra in docs:
        path = tmp_path / f"{doc_id}.md"
        path.write_text(text, encoding="utf-8")
        doc = ManifestDoc(id=doc_id, title=doc_id.title(), file=path.name, language=lang, **extra)
        ingest_document(db, doc, path, HashEmbedder(dim=64))


# --- demo knowledge base ------------------------------------------------------------------------
def test_demo_kb_ingests_completely_and_fast(demo_kb) -> None:
    _settings, _db, _embedder, report, elapsed = demo_kb
    assert elapsed < 10.0
    assert report.errors == {} and report.missing_files == []
    assert len(report.ingested) == 22
    assert report.chunks_current == sum(report.chunks_by_doc.values()) > 22


@pytest.mark.parametrize(("question", "expected"), EN_QUESTIONS)
def test_top_result_for_english_questions(retriever: Retriever, question: str, expected: str) -> None:
    results = retriever.search(question, lang="en", top_k=3)
    assert results and results[0].source_id == expected, [r.source_id for r in results]


@pytest.mark.parametrize(("question", "expected"), SR_QUESTIONS)
def test_top_result_for_bcms_questions(retriever: Retriever, question: str, expected: str) -> None:
    results = retriever.search(question, lang="sr", top_k=3)
    assert results and results[0].source_id == expected, [r.source_id for r in results]


def test_result_shape_and_metadata(retriever: Retriever) -> None:
    results = retriever.search(
        "How soon after unprotected sex can I use emergency contraception?", lang="en", top_k=2
    )
    assert len(results) == 2
    top = results[0]
    assert isinstance(top, RetrievedChunk)
    assert top.source_id == "demo-en-emergency-contraception"
    assert top.source_title == "Emergency contraception (demo)"
    assert len(top.source_version) == 8 and top.chunk_id.startswith(f"{top.source_id}:{top.source_version}:")
    assert top.published_on == "2026-10-19"
    assert top.page is not None and top.page >= 1
    assert top.heading_path.startswith("Emergency contraception")
    assert top.lang == "en"
    assert top.review_status == "public_unreviewed"
    assert top.score > results[1].score > 0.0
    assert any("five days" in r.text for r in results)


def test_results_are_deterministic(retriever: Retriever) -> None:
    first = [r.chunk_id for r in retriever.search("danger signs in pregnancy", lang="en")]
    second = [r.chunk_id for r in retriever.search("danger signs in pregnancy", lang="en")]
    assert first == second and first


def test_top_k_limits_and_defaults(retriever: Retriever, demo_kb) -> None:
    settings = demo_kb[0]
    query = "contraception"
    assert len(retriever.search(query, top_k=1)) == 1
    assert len(retriever.search(query, top_k=3)) == 3
    assert len(retriever.search(query)) == settings.retrieval_top_k
    assert retriever.search(query, top_k=0) == []


def test_empty_query_returns_nothing(retriever: Retriever) -> None:
    assert retriever.search("") == []
    assert retriever.search("   ") == []


def test_demo_mode_false_excludes_unreviewed_sources(demo_kb) -> None:
    settings, db, embedder, _report, _elapsed = demo_kb
    strict = Retriever(db, embedder, settings.model_copy(update={"demo_mode": False}))
    assert strict.default_statuses() == ("reviewed",)
    assert strict.search("emergency contraception", lang="en") == []
    assert strict.search(
        "emergency contraception", lang="en", allowed_statuses=("reviewed", "public_unreviewed")
    )


def test_topic_restricts_to_sources_declaring_it(retriever: Retriever, demo_kb) -> None:
    results = retriever.search("bleeding", lang="en", topic="menstruation", top_k=5)
    assert results
    assert {r.source_id for r in results} <= {"demo-en-menstrual-health", "demo-sr-menstrual-health"}
    # A topic no source declares must not empty the retrieval.
    assert retriever.search("bleeding", lang="en", topic="other", top_k=5)


# --- controlled corpora -------------------------------------------------------------------------
def test_empty_knowledge_base_returns_empty_list(db, settings) -> None:
    assert Retriever(db, HashEmbedder(dim=64), settings).search("anything at all") == []


def test_blocked_sources_are_never_returned(db, settings, tmp_path: Path) -> None:
    text = "# Condoms\n\nCondoms protect against pregnancy and infections.\n"
    _seed(
        db,
        tmp_path,
        [
            ("blocked-doc", "en", text, {"status": "blocked", "reviewed_by": "Dr X"}),
            ("open-doc", "en", text, {}),
        ],
    )
    retriever = Retriever(db, HashEmbedder(dim=64), settings)
    everything = ("reviewed", "public_unreviewed", "blocked")
    assert {r.source_id for r in retriever.search("condoms", allowed_statuses=everything)} == {"open-doc"}
    assert retriever.search("condoms", allowed_statuses=("blocked",)) == []
    assert retriever.search("condoms", allowed_statuses=()) == []


def test_reviewed_sources_are_returned_outside_demo_mode(db, settings, tmp_path: Path) -> None:
    text = "# Breastfeeding\n\nBreastfeeding is recommended for six months.\n"
    _seed(
        db, tmp_path, [("reviewed-doc", "en", text, {"reviewed_by": "Dr X"}), ("draft-doc", "en", text, {})]
    )
    strict = Retriever(db, HashEmbedder(dim=64), settings.model_copy(update={"demo_mode": False}))
    results = strict.search("breastfeeding")
    assert {r.source_id for r in results} == {"reviewed-doc"}
    assert results[0].review_status == "reviewed"


def test_language_boost_prefers_the_query_language_family(db, settings, tmp_path: Path) -> None:
    # Identical text under two languages: dense and BM25 scores tie, only the boost decides.
    text = "# HPV\n\nHPV vakcina hepatitis B HIV test.\n"
    _seed(db, tmp_path, [("same-en", "en", text, {}), ("same-sr", "sr", text, {})])
    retriever = Retriever(db, HashEmbedder(dim=64), settings)
    query = "HPV vakcina hepatitis"
    assert retriever.search(query, lang="en")[0].source_id == "same-en"
    assert retriever.search(query, lang="sr")[0].source_id == "same-sr"
    assert retriever.search(query, lang="bs")[0].source_id == "same-sr"
    assert retriever.search(query, lang="me")[0].source_id == "same-sr"
    assert retriever.search(query, lang="hr")[0].source_id == "same-sr"
    en_score = retriever.search(query, lang="en")[0].score
    sr_score = retriever.search(query, lang="en")[1].score
    assert en_score == pytest.approx(sr_score * 1.3, rel=1e-4)
    neutral = retriever.search(query)
    assert neutral[0].score == neutral[1].score


def test_only_current_version_chunks_are_searched(db, settings, tmp_path: Path) -> None:
    path = tmp_path / "doc.md"
    path.write_text("# Guide\n\nOld sentence about folic acid.\n", encoding="utf-8")
    doc = ManifestDoc(id="versioned", title="Versioned", file="doc.md", language="en")
    old = ingest_document(db, doc, path, HashEmbedder(dim=64))
    path.write_text("# Guide\n\nNew sentence about folic acid and iron.\n", encoding="utf-8")
    new = ingest_document(db, doc, path, HashEmbedder(dim=64))
    results = Retriever(db, HashEmbedder(dim=64), settings).search("folic acid")
    assert results and all(r.source_version == new.version_hash[:8] for r in results)
    assert old.version_hash[:8] not in {r.source_version for r in results}


def test_bm25_only_fallback_when_embeddings_are_missing(db, settings, tmp_path: Path) -> None:
    _seed(db, tmp_path, [("no-vec", "en", "# Iron\n\nIron supplements prevent anaemia.\n", {})])
    for chunk in db.scalars(select(Chunk)).all():
        chunk.embedding = None
    db.commit()
    results = Retriever(db, HashEmbedder(dim=64), settings).search("iron supplements")
    assert [r.source_id for r in results] == ["no-vec"]
    assert Retriever(db, HashEmbedder(dim=64), settings).search("zzzz unknown words") == []


# --- building blocks ----------------------------------------------------------------------------
def test_bm25_okapi_scores() -> None:
    corpus = [["iron", "folic", "acid"], ["iron", "iron", "tablets"], ["condom", "use"]]
    bm25 = BM25Okapi(corpus)
    scores = bm25.get_scores(["iron"])
    assert scores[0] > 0 and scores[1] > 0 and scores[2] == 0.0
    assert scores[1] > scores[0]  # higher term frequency, same length
    assert bm25.get_scores(["unknown"]) == [0.0, 0.0, 0.0]
    assert bm25.get_scores([]) == [0.0, 0.0, 0.0]
    assert BM25Okapi([]).get_scores(["iron"]) == []
    rare, common = bm25.idf["condom"], bm25.idf["iron"]
    assert rare > common > 0.0


def test_reciprocal_rank_fusion_math() -> None:
    fused = reciprocal_rank_fusion([[(0, 1.0), (1, 0.5)], [(1, 1.0), (0, 0.5)]], k=60)
    assert fused[0] == pytest.approx(fused[1]) == pytest.approx(1 / 61 + 1 / 62)
    assert reciprocal_rank_fusion([[(7, 0.3)], [(7, 0.9)]], k=60)[7] == pytest.approx(2 / 61)
    tied = reciprocal_rank_fusion([[(0, 1.0), (1, 1.0), (2, 0.2)]], k=60)
    assert tied[0] == tied[1] == pytest.approx(1 / 61)
    assert tied[2] == pytest.approx(1 / 63)
    assert reciprocal_rank_fusion([]) == {}


def test_same_language_family() -> None:
    assert (
        same_language_family("sr", "bs")
        and same_language_family("me", "hr")
        and same_language_family("en", "en")
    )
    assert not same_language_family("en", "sr") and not same_language_family("hr", "en")
