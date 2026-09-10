"""Innovation claim #2 — grounded answers or refusal.

The two controls of the claim are tested here, not mocked:

a. **human approval before publication** — retrieval goes through the visitor role and the
   ``approved`` filter, and the gate is *dynamic*: moving an entry back to draft removes it from
   the answers within the same session (``test_gate_is_dynamic_st_vitus``);
b. **the automatic per-sentence support check** — an answer sentence that is not attributable to a
   cited approved passage is dropped, and an answer with nothing left is withheld
   (``test_support_check_drops_invented_number``).

The headline test runs the two launch-language question sets (20 answerable + 10 unanswerable
each, with independently prepared expected answers) through exactly the function the API uses.
"""
from __future__ import annotations

import csv
import random

import pytest
from sqlalchemy import func, select

from app.models import EntryChunk, AnswerRecord, Event, HeritageEntry, User
from app.services import rag, review
from app.services import validation as validation_service

CNR_ST_VITUS = "Iz kojeg vijeka je crkva Svetog Vida iznad Gornje Lastve?"
#: verbatim from the *draft* sample entry `sample-draft-zlatno-zvono`, which is never approved
DRAFT_QUOTE = "Da li je zlatno zvono sakriveno u pećini ispod Svetog Vida 1687. godine?"


@pytest.fixture()
def validator(db) -> User:
    user = db.scalars(select(User).where(User.role == "validator")).first()
    assert user is not None, "the seed must provide a validator account"
    return user


# --- 1. the required test outcome ---------------------------------------------------------------
def test_grounding_sets_per_launch_language(db, capsys):
    """Per launch language: 100 % of the unanswerable questions withheld, ≥90 % of the answerable
    ones answered from an approved source (the definition of done aims at 20/20)."""
    report = rag.run_grounding_test(db)
    summary = report["summary"]
    assert set(summary["languages"]) == set(rag.SUPPORTED_LANGS)

    approved = {
        str(i) for i in db.scalars(select(HeritageEntry.id).where(HeritageEntry.status == "approved"))
    }
    with capsys.disabled():
        for lang, stats in summary["languages"].items():
            print(
                f"\n  {lang}: answerable {stats['answered_ok']}/{stats['answerable']} "
                f"({stats['answerable_rate']:.0%}), unanswerable withheld "
                f"{stats['withheld_ok']}/{stats['unanswerable']} ({stats['withheld_rate']:.0%})"
            )

    for lang, stats in summary["languages"].items():
        assert stats["answerable"] == 20, f"{lang}: the set must hold 20 answerable questions"
        assert stats["unanswerable"] == 10, f"{lang}: the set must hold 10 unanswerable questions"
        # 100 % of the unanswerable questions must be withheld — no tolerance at all.
        assert stats["withheld_ok"] == 10, f"{lang} leaked an answer: {stats['failures']}"
        assert stats["withheld_rate"] == 1.0
        # ≥90 % is the hard floor of the brief; the build aims at 100 %.
        assert stats["answerable_rate"] >= rag.ANSWERABLE_FLOOR, (
            f"{lang}: only {stats['answerable_rate']:.0%} of the answerable questions were answered "
            f"({stats['failures']})"
        )

    for row in report["results"]:
        if row["expected"] == "withhold":
            assert row["outcome"] == "withhold", f"{row['id']} was answered but must be withheld"
            assert row["cited_slugs"] == [], f"{row['id']} cited something while withholding"
            continue
        if not row["passed"]:
            continue
        assert row["citations"], f"{row['id']} answered without a citation"
        for citation in row["citations"]:
            assert citation["entry_id"] in approved, f"{row['id']} cited a non-approved entry"
            assert citation["source"].strip(), f"{row['id']} cited an entry without a source"
            assert citation["entry_version"] >= 1
        assert row["slug_ok"], f"{row['id']} cited {row['cited_slugs']}, expected {row['expected_slugs']}"

    assert summary["passed"] is True


def test_report_files_are_written():
    md = rag.DEFAULT_RESULTS_PATH.with_suffix(".md")
    assert rag.DEFAULT_RESULTS_PATH.exists() and md.exists()
    text = md.read_text(encoding="utf-8")
    assert "Signal distribution" in text and "Per launch language" in text


# --- 2. the human-approval control is dynamic ----------------------------------------------------
def test_gate_is_dynamic_st_vitus(db, public_db, validator):
    """Withdrawing approval takes effect immediately: the entry is never cited again.

    The corpus is realistic rather than one-fact-per-entry — the village overview `gornja-lastva`
    repeats the St Vitus fact and cites its own source — so the guarantee under test is the one the
    brief states: *only approved items are retrievable*. A different approved entry answering a
    related question is correct behaviour, not a leak. (What the offline extractive mode can still
    do in that situation is documented in docs/grounding.md, "Relevance versus attribution".)
    """
    entry = db.scalars(select(HeritageEntry).where(HeritageEntry.slug == "crkva-sv-vida")).one()
    assert entry.status == "approved"

    before = rag.ask(public_db, db, CNR_ST_VITUS, lang="cnr", use_cache=False)
    assert before.answered and any(c.slug == "crkva-sv-vida" for c in before.citations)
    assert db.scalar(select(func.count(EntryChunk.id)).where(EntryChunk.entry_id == entry.id)) > 0

    try:
        validation_service.transition(
            db, "heritage_entry", entry.id, "draft", actor=validator, note="test: withdraw approval"
        )
        public_db.rollback()  # the visitor session must see the new state, not its snapshot

        during = rag.ask(public_db, db, CNR_ST_VITUS, lang="cnr", use_cache=False)
        assert all(c.slug != "crkva-sv-vida" for c in during.citations), (
            "an entry that left 'approved' was still cited"
        )
        assert db.scalar(select(func.count(EntryChunk.id)).where(EntryChunk.entry_id == entry.id)) == 0, (
            "the chunks of an unapproved entry must leave the retrieval index"
        )
        # Its text is unreachable through the visitor role as well as through the assistant.
        assert public_db.scalars(
            select(HeritageEntry).where(HeritageEntry.slug == "crkva-sv-vida")
        ).first() is None
    finally:
        validation_service.transition(
            db, "heritage_entry", entry.id, "approved", actor=validator, note="test: restore"
        )
        public_db.rollback()

    after = rag.ask(public_db, db, CNR_ST_VITUS, lang="cnr", use_cache=False)
    assert after.answered and any(c.slug == "crkva-sv-vida" for c in after.citations)
    assert not after.served_from_cache, "the cache must not survive the entry leaving 'approved'"


def test_answer_is_withheld_when_no_approved_entry_covers_the_subject(db, public_db, validator):
    """The other half of the gate: with every covering entry withdrawn, the answer is withheld."""
    slugs = ["dani-pejzaza", "gornja-lastva"]
    entries = [db.scalars(select(HeritageEntry).where(HeritageEntry.slug == s)).one() for s in slugs]
    question = "Od koje godine se održavaju Dani pejzaža?"
    assert rag.ask(public_db, db, question, lang="cnr", use_cache=False).answered

    n_withheld = db.scalar(select(func.count(Event.id)).where(Event.event_type == "answer_withheld"))
    try:
        for entry in entries:
            validation_service.transition(
                db, "heritage_entry", entry.id, "draft", actor=validator, note="test: withdraw"
            )
        public_db.rollback()
        result = rag.ask(public_db, db, question, lang="cnr", use_cache=False)
        assert not result.answered and result.citations == []
        assert result.refusal_message == rag.REFUSAL_MESSAGES["cnr"]
        assert (
            db.scalar(select(func.count(Event.id)).where(Event.event_type == "answer_withheld"))
            > n_withheld
        )
    finally:
        for entry in entries:
            validation_service.transition(
                db, "heritage_entry", entry.id, "approved", actor=validator, note="test: restore"
            )
        public_db.rollback()


def test_draft_entry_is_never_quoted(db, public_db):
    """A question quoting the never-approved draft entry verbatim is withheld and cites nothing."""
    result = rag.ask(public_db, db, DRAFT_QUOTE, lang="cnr", use_cache=False)
    assert not result.answered
    assert result.citations == []
    assert result.answer is None
    assert result.refusal_reason in (rag.REFUSAL_LOW_CONFIDENCE, rag.REFUSAL_NO_SOURCE)
    assert "1687" not in (result.refusal_message or "")


# --- 3. the API ------------------------------------------------------------------------------------
def test_api_shape_and_localised_refusal(client):
    r = client.post("/api/ask", json={"question": "Kojeg dana se održava Lastovska fešta?", "lang": "cnr"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {
        "answered", "answer", "citations", "confidence", "support", "dropped_sentences",
        "refusal_reason", "refusal_message", "served_from_cache", "provider", "event",
    }
    assert body["answered"] is True
    assert body["event"] == "answer_served"
    assert body["refusal_reason"] is None and body["refusal_message"] is None
    assert body["citations"] and body["citations"][0]["slug"] == "lastovska-festa"
    citation = body["citations"][0]
    assert set(citation) >= {"entry_id", "slug", "title", "source", "lang", "chunk_index", "score",
                             "excerpt", "entry_version", "village_slug"}
    assert citation["village_slug"] == "gornja-lastva"
    assert body["provider"] == {"llm": "none", "embeddings": "hash", "support_check": "lexical"}
    assert body["dropped_sentences"] == 0
    assert all(s["supported"] for s in body["support"])

    for lang, message in (("cnr", rag.REFUSAL_MESSAGES["cnr"]), ("en", rag.REFUSAL_MESSAGES["en"])):
        question = "Kada polazi trajekt za Bari?" if lang == "cnr" else "What time does the ferry to Bari leave?"
        r = client.post("/api/ask", json={"question": question, "lang": lang, "session_id": "s-test"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["answered"] is False
        assert body["answer"] is None and body["citations"] == []
        assert body["event"] == "answer_withheld"
        assert body["refusal_message"] == message
        assert body["refusal_reason"] in (rag.REFUSAL_LOW_CONFIDENCE, rag.REFUSAL_NO_SOURCE)


def test_language_is_detected_when_not_given(client):
    r = client.post("/api/ask", json={"question": "How high is the Njegoš mausoleum on Lovćen?"})
    assert r.status_code == 200
    assert r.json()["refusal_message"] == rag.REFUSAL_MESSAGES["en"]


# --- 4. the support check bites --------------------------------------------------------------------
def test_support_check_drops_invented_number(db, public_db, monkeypatch):
    """A generated sentence with a number that is in no cited passage is dropped; being the only
    sentence, the answer is withheld with `unsupported_answer`."""
    invented = "Fešta se održava od 1682. godine. [1]"

    def fake_compose(*, question, lang, sources, q_stems, idf, db):  # noqa: A002 - mirrors the seam
        return invented, [(sources[0], sources[0].body())], True  # written by a model

    monkeypatch.setattr(rag, "compose_answer", fake_compose)
    result = rag.ask(
        public_db, db, "Od koje godine se održava Lastovska fešta?", lang="cnr", use_cache=False
    )
    assert not result.answered
    assert result.refusal_reason == rag.REFUSAL_UNSUPPORTED
    assert result.answer is None and result.citations == []
    assert result.dropped_sentences == 1
    assert result.support and result.support[0].supported is False
    assert "1682" in result.support[0].reason


def test_support_check_keeps_only_the_supported_sentence(db, public_db, monkeypatch):
    """One good sentence + one invented one → the invented one is dropped, the answer survives."""

    def fake_compose(*, question, lang, sources, q_stems, idf, db):  # noqa: A002
        good = rag.split_sentences(sources[0].body())[0]
        return (
            f"{good} [1] Fešta se održava od 1682. godine. [1]",
            [(sources[0], sources[0].body())],
            True,  # written by a model
        )

    monkeypatch.setattr(rag, "compose_answer", fake_compose)
    result = rag.ask(
        public_db, db, "Od koje godine se održava Lastovska fešta?", lang="cnr", use_cache=False
    )
    assert result.answered
    assert result.dropped_sentences == 1
    assert "1682" not in (result.answer or "")
    assert result.citations and all(c.source for c in result.citations)


# --- 5. the review sample carries no visitor identifier ---------------------------------------------
def test_answer_records_carry_no_identifier(db, public_db):
    rag.ask(public_db, db, "Šta je Tivat?", lang="cnr", session_id="s-1", device_id="d-1", use_cache=False)
    columns = set(AnswerRecord.__table__.columns.keys())
    assert not {c for c in columns if any(k in c for k in ("session", "device", "actor", "pseudonym", "user"))}
    record = db.scalars(select(AnswerRecord).order_by(AnswerRecord.occurred_at.desc())).first()
    assert record is not None
    values = " ".join(str(v) for v in record.__dict__.values())
    assert "s-1" not in values and "d-1" not in values


def test_export_review_sheet(db, tmp_path):
    random.seed(20260909)
    available = db.scalar(select(func.count(AnswerRecord.id)))
    assert available, "the grounding run must have produced answer records"
    result = review.export_review_sheet(db, n=30, out_dir=tmp_path, days=31)

    assert result["contains_visitor_identifier"] is False
    with open(result["csv"], encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == min(30, result["available"])
    assert list(rows[0]) == review.CSV_COLUMNS
    assert not {c for c in review.CSV_COLUMNS if any(k in c for k in ("session", "device", "pseudonym", "ip"))}
    assert all(r["reviewer verdict"] == "" and r["reviewer note"] == "" for r in rows)
    assert any(r["citations"] or r["answer"].startswith("— withheld") for r in rows)
    instructions = (tmp_path / ("answer_review_%s.md" % result["period_end"][:7])).read_text(encoding="utf-8")
    assert "no visitor identifier" in instructions
