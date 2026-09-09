"""Response cache and monthly spend cap of the visitor assistant.

Both exist so the assistant stays affordable *without* ever loosening the grounding rule: a cache
hit is only served while every cited entry is unchanged and still approved, and when the monthly
euro cap is reached the assistant serves cache or pauses politely — it never produces unsourced
text.
"""
from __future__ import annotations

import pytest
from sqlalchemy import delete, func, select

from app.config import settings
from app.models import Event, HeritageEntry, LlmUsage, ResponseCache, User
from app.providers import llm as llm_module
from app.services import budget, rag
from app.services import validation as validation_service

BASE_QUESTION = "Kada se održava Lastovska fešta?"
#: identical content words, one extra function word → different exact hash, cosine 1.0
PARAPHRASE_HIT = "A kada se održava Lastovska fešta?"
#: same topic, different content words → below CACHE_SEMANTIC_MIN_SIMILARITY
PARAPHRASE_MISS = "Kojeg dana u avgustu je Lastovska fešta?"


@pytest.fixture()
def validator(db) -> User:
    user = db.scalars(select(User).where(User.role == "validator")).first()
    assert user is not None
    return user


def _events(db, event_type: str) -> int:
    return db.scalar(select(func.count(Event.id)).where(Event.event_type == event_type))


def _clear_cache(db) -> None:
    db.execute(delete(ResponseCache))
    db.commit()


# --- 1. exact hit -------------------------------------------------------------------------------
def test_exact_cache_hit(db, public_db):
    _clear_cache(db)
    served_before = _events(db, "answer_served")

    first = rag.ask(public_db, db, BASE_QUESTION, lang="cnr")
    assert first.answered and first.served_from_cache is False

    second = rag.ask(public_db, db, BASE_QUESTION, lang="cnr")
    assert second.answered and second.served_from_cache is True
    assert second.answer == first.answer
    assert [c.slug for c in second.citations] == [c.slug for c in first.citations]
    assert [c.entry_version for c in second.citations] == [c.entry_version for c in first.citations]

    # a cache hit is still an answer the KPIs must see: exactly one more answer_served per call
    assert _events(db, "answer_served") == served_before + 2

    row = db.scalars(select(ResponseCache).where(ResponseCache.lang == "cnr")).first()
    assert row is not None and row.hits >= 1 and row.invalidated_at is None
    assert row.entry_versions and all(int(v) >= 1 for v in row.entry_versions.values())


# --- 2. semantic hit and semantic miss -------------------------------------------------------------
def test_semantic_hit_above_threshold_and_miss_below(db, public_db):
    _clear_cache(db)
    original = rag.ask(public_db, db, BASE_QUESTION, lang="cnr")
    assert original.answered and not original.served_from_cache

    hit = rag.ask(public_db, db, PARAPHRASE_HIT, lang="cnr")
    assert hit.served_from_cache is True, "a paraphrase above the threshold must reuse the answer"
    assert hit.answer == original.answer

    miss = rag.ask(public_db, db, PARAPHRASE_MISS, lang="cnr")
    assert miss.served_from_cache is False, "a paraphrase below the threshold must be answered anew"
    assert miss.answered

    # the threshold is what separates them, measured on the very same vectors
    embed = rag.get_embeddings().embed([BASE_QUESTION, PARAPHRASE_HIT, PARAPHRASE_MISS])
    from app.providers.embeddings import cosine

    assert cosine(embed[0], embed[1]) >= settings.cache_semantic_min_similarity
    assert cosine(embed[0], embed[2]) < settings.cache_semantic_min_similarity


def test_cache_is_per_language(db, public_db):
    _clear_cache(db)
    rag.ask(public_db, db, BASE_QUESTION, lang="cnr")
    english = rag.ask(public_db, db, "On which day is the Lastovska fešta held?", lang="en")
    assert english.served_from_cache is False


# --- 3. invalidation when a cited entry changes ------------------------------------------------------
def test_cache_invalidated_when_cited_entry_version_changes(db, public_db, validator):
    _clear_cache(db)
    question = "Do koje godine su u Gornjoj Lastvi radili mlinovi za masline?"
    first = rag.ask(public_db, db, question, lang="cnr")
    assert first.answered
    cited = {c.slug for c in first.citations}
    assert "mlinovi-za-masline" in cited

    entry = db.scalars(select(HeritageEntry).where(HeritageEntry.slug == "mlinovi-za-masline")).one()
    version_before = entry.version
    note_before = entry.verification_note
    try:
        # an edit bumps the version and (because it was approved) sends the entry back to draft
        validation_service.update_item(
            db, "heritage_entry", entry.id, {"verification_note": "test: source re-checked"},
            actor=validator, note="test",
        )
        db.commit()
        public_db.rollback()
        assert entry.version == version_before + 1

        second = rag.ask(public_db, db, question, lang="cnr")
        assert second.served_from_cache is False, "a stale answer was served after the entry changed"

        row = db.scalars(
            select(ResponseCache).where(ResponseCache.lang == "cnr").order_by(ResponseCache.created_at)
        ).first()
        assert row is not None and row.invalidated_at is not None
        assert "mlinovi-za-masline" in row.invalidation_reason
    finally:
        entry.verification_note = note_before
        db.commit()
        validation_service.transition(
            db, "heritage_entry", entry.id, "approved", actor=validator, note="test: restore"
        )
        public_db.rollback()

    # A fresh answer (cache bypassed) must cite the NEW version of the entry.
    restored = rag.ask(public_db, db, question, lang="cnr", use_cache=False)
    assert restored.answered and not restored.served_from_cache
    assert restored.citations[0].entry_version == version_before + 1

    # And no cache row that still cites the old version may be servable. While the entry was in
    # draft the question could legitimately be answered from another approved entry and cached, so
    # the assertion is about staleness, not about the cache being empty.
    for row in db.scalars(select(ResponseCache).where(ResponseCache.invalidated_at.is_(None))):
        assert row.entry_versions.get(str(entry.id), version_before + 1) == version_before + 1, (
            "a cache row still cites a superseded version of the entry"
        )


# --- 4. the monthly spend cap --------------------------------------------------------------------
class _BillableLLM:
    """Stand-in for the paid EU provider: only ``billable`` matters to the guard."""

    name = "eu_api"
    model = "test-model"
    billable = True

    def complete(self, system, user, **kwargs):  # pragma: no cover - never reached under the cap
        raise AssertionError("no paid call may be made once the cap is reached")


def test_spend_cap_serves_cache_then_pauses(db, public_db, monkeypatch):
    _clear_cache(db)
    cached_question = "Šta je Donja Lastva i gdje se nalazi?"
    fresh_question = "Čemu su posvećeni Dani pejzaža?"
    warm = rag.ask(public_db, db, cached_question, lang="cnr")
    assert warm.answered and not warm.served_from_cache

    db.add(
        LlmUsage(
            month_key=budget.month_key(), provider="eu_api", model="test-model", purpose="answer",
            input_tokens=1_000_000, output_tokens=1_000_000,
            cost_eur=settings.llm_monthly_cap_eur + 1.0, billable=True,
        )
    )
    db.commit()
    monkeypatch.setattr(llm_module, "get_llm", lambda: _BillableLLM())
    try:
        assert budget.cap_reached(db) is True

        # a. a question whose answer is cached is still served, with its citations
        served = rag.ask(public_db, db, cached_question, lang="cnr")
        assert served.answered and served.served_from_cache is True
        assert served.citations and all(c.source for c in served.citations)
        assert served.refusal_reason is None

        # b. an uncached question pauses politely — and produces no text at all
        paused_before = _events(db, "assistant_paused")
        withheld_before = _events(db, "answer_withheld")
        paused = rag.ask(public_db, db, fresh_question, lang="cnr")
        assert paused.answered is False
        assert not paused.answer, "the assistant must never emit unsourced text under the cap"
        assert paused.citations == []
        assert paused.refusal_reason == rag.REFUSAL_PAUSED
        assert paused.refusal_message == rag.PAUSED_MESSAGES["cnr"]
        assert _events(db, "assistant_paused") == paused_before + 1
        assert _events(db, "answer_withheld") == withheld_before + 1

        english = rag.ask(public_db, db, "What are the Landscape Days dedicated to?", lang="en")
        assert english.refusal_message == rag.PAUSED_MESSAGES["en"]
    finally:
        db.execute(delete(LlmUsage).where(LlmUsage.model == "test-model"))
        db.commit()

    assert budget.cap_reached(db) is False
    recovered = rag.ask(public_db, db, fresh_question, lang="cnr")
    assert recovered.answered and recovered.citations
