"""Foundation tests: pseudonymisation, event hygiene, spend cap, support check, seed integrity.

These cover the shared machinery every module depends on, independently of the feature modules.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, text

from app.config import settings
from app.events import emit_event
from app.models import (
    GENDER_REPORTED,
    Event,
    HeritageEntry,
    Listing,
    LlmUsage,
    TrailSegment,
    User,
    Village,
)
from app.providers.llm import LLMResult
from app.providers.support import LexicalSupport, split_sentences
from app.pseudonym import DEVICE, pseudonymise
from app.services import budget


# --------------------------------------------------------------------------- pseudonymisation
def test_pseudonyms_are_stable_unlinkable_and_short():
    a = pseudonymise(DEVICE, "device-123")
    b = pseudonymise(DEVICE, "device-123")
    c = pseudonymise("session", "device-123")  # different kind → different pseudonym
    d = pseudonymise(DEVICE, "device-124")
    assert a == b and len(a) == 32
    assert a != c and a != d
    assert "device-123" not in a
    assert pseudonymise(DEVICE, None) is None
    assert pseudonymise(DEVICE, "  ") is None


def test_event_rows_carry_no_identifier_in_the_clear(db):
    host = db.scalars(select(User).where(User.email == "host1@example.org")).one()
    ev = emit_event(
        db, "visit_recorded", actor=host, session_id="sess-abc", device_id="dev-xyz", lat=42.44, lng=18.69
    )
    db.flush()
    assert ev.actor_pseudonym and ev.actor_pseudonym != str(host.id)
    assert ev.session_pseudonym != "sess-abc"
    assert ev.device_pseudonym != "dev-xyz"
    blob = f"{ev.actor_pseudonym}{ev.session_pseudonym}{ev.device_pseudonym}{ev.properties}"
    for secret in (str(host.id), host.email, "sess-abc", "dev-xyz"):
        assert secret not in blob
    db.rollback()


def test_event_properties_reject_personal_data_keys(db):
    for bad in ({"email": "a@b.c"}, {"question": "what?"}, {"message": "hi"}, {"transcript": "…"},
                {"user_id": "x"}, {"ip": "1.2.3.4"}, {"name": "Ana"}, {"phone": "+382"}):
        with pytest.raises(ValueError):
            emit_event(db, "answer_served", **bad)
    # session_id and device_id are named parameters, so they can only ever be pseudonymised —
    # they cannot reach `properties` at all.
    ev = emit_event(db, "answer_served", session_id="sess-1", device_id="dev-1", lang="cnr")
    assert "session_id" not in ev.properties and "device_id" not in ev.properties
    db.rollback()


def test_gender_snapshot_only_from_voluntary_self_report(db):
    reported = db.scalars(
        select(User).where(User.gender_self_reported.is_(True), User.gender.in_(GENDER_REPORTED))
    ).first()
    silent = db.scalars(select(User).where(User.gender_self_reported.is_(False))).first()
    assert reported is not None and silent is not None, "seed must contain both cases"

    ev1 = emit_event(db, "onboarding_started", actor=reported, language="cnr", via_ambassador=False)
    ev2 = emit_event(db, "onboarding_started", actor=silent, language="cnr", via_ambassador=False)
    assert ev1.actor_gender == reported.gender and ev1.gender_self_reported is True
    assert ev2.actor_gender is None and ev2.gender_self_reported is False
    db.rollback()


def test_prefer_not_to_say_is_never_disaggregated(db):
    user = db.scalars(select(User).where(User.gender == "prefer_not_to_say")).first()
    assert user is not None, "seed must contain a prefer_not_to_say account"
    ev = emit_event(db, "onboarding_started", actor=user, language="cnr", via_ambassador=False)
    assert ev.actor_gender is None
    db.rollback()


# --------------------------------------------------------------------------- spend cap
def test_price_and_cap_enforcement(db):
    db.execute(text("DELETE FROM llm_usage"))
    db.commit()
    assert budget.spent_this_month(db) == 0.0
    assert budget.cap_reached(db) is False

    result = LLMResult(text="hi", input_tokens=1_000_000, output_tokens=1_000_000, provider="eu", model="m", billable=True)
    usage = budget.record(db, result, "answer")
    expected = settings.llm_price_input_eur_per_mtok + settings.llm_price_output_eur_per_mtok
    assert usage.cost_eur == pytest.approx(expected, rel=1e-6)
    assert budget.spent_this_month(db) == pytest.approx(expected, rel=1e-6)

    db.add(
        LlmUsage(
            month_key=budget.month_key(), provider="eu", model="m", purpose="answer",
            input_tokens=0, output_tokens=0, cost_eur=settings.llm_monthly_cap_eur, billable=True,
        )
    )
    db.commit()
    assert budget.cap_reached(db) is True
    assert budget.remaining_eur(db) == 0.0

    db.execute(text("DELETE FROM llm_usage"))
    db.commit()


def test_self_hosted_calls_are_not_billed(db):
    db.execute(text("DELETE FROM llm_usage"))
    db.commit()
    budget.record(db, LLMResult(text="x", input_tokens=10_000, output_tokens=10_000, provider="ollama", model="q", billable=False), "answer")
    db.commit()
    assert budget.spent_this_month(db) == 0.0
    db.execute(text("DELETE FROM llm_usage"))
    db.commit()


# --------------------------------------------------------------------------- support check
def test_lexical_support_rejects_invented_numbers_and_uncovered_claims():
    checker = LexicalSupport(min_score=0.75)
    passage = (
        "Lastovska fešta. Lastovska fešta se održava svake prve subote u avgustu, neprekidno od 1974. godine."
    )
    supported = checker.check("Lastovska fešta se održava prve subote u avgustu od 1974. godine. [1]", [passage])
    assert supported.supported and supported.score >= 0.75

    invented_year = checker.check("Lastovska fešta se održava od 1682. godine. [1]", [passage])
    assert not invented_year.supported and invented_year.score == 0.0
    assert "1682" in invented_year.reason

    invented_price = checker.check("Ulaznica košta 20 eura. [1]", [passage])
    assert not invented_price.supported

    off_topic = checker.check("Trajekt za Bari polazi svakog jutra. [1]", [passage])
    assert not off_topic.supported

    assert checker.check("Bilo šta.", []).supported is False


def test_sentence_splitting_keeps_citation_markers():
    parts = split_sentences("Prva rečenica. [1] Druga rečenica! [2]")
    assert len(parts) == 2, parts
    assert parts[0].endswith("[1]") and parts[1].endswith("[2]")


def test_sentence_splitting_does_not_break_on_montenegrin_ordinals():
    # "1974. godine" and "14. vijeka" are ordinals, not sentence ends.
    parts = split_sentences("Fešta se održava od 1974. godine. [1] Crkva je iz 14. vijeka. [2]")
    assert len(parts) == 2, parts
    assert "1974. godine" in parts[0] and "14. vijeka" in parts[1]


def test_support_check_runs_per_sentence_not_per_answer():
    """A supported sentence must survive even when the answer also contains an invented one."""
    checker = LexicalSupport(min_score=0.75)
    passage = "Lastovska fešta se održava svake prve subote u avgustu, neprekidno od 1974. godine."
    answer = "Lastovska fešta se održava prve subote u avgustu od 1974. godine. [1] Ulaznica košta 20 eura. [1]"
    verdicts = [checker.check(s, [passage]) for s in split_sentences(answer)]
    assert len(verdicts) == 2
    assert verdicts[0].supported is True
    assert verdicts[1].supported is False


# --------------------------------------------------------------------------- seed integrity
def test_every_content_item_has_a_village_and_municipality(db):
    for model in (HeritageEntry, Listing, TrailSegment):
        rows = db.scalars(select(model)).all()
        assert rows, f"seed must contain {model.__tablename__}"
        for row in rows:
            assert row.village_id is not None, f"{model.__tablename__} {row.slug} has no village"
            village = db.get(Village, row.village_id)
            assert village is not None and village.municipality in ("Tivat", "Kotor")


def test_territory_spans_both_municipalities_and_several_villages(db):
    villages = db.scalars(select(Village)).all()
    assert len({v.municipality for v in villages}) == 2, "the territory covers both sides of the ridge"
    approved_villages = db.scalars(
        select(Village.slug).join(HeritageEntry, HeritageEntry.village_id == Village.id)
        .where(HeritageEntry.status == "approved").distinct()
    ).all()
    assert len(set(approved_villages)) >= 3, "a multi-village itinerary needs approved content in ≥3 villages"


def test_unverified_content_is_never_approved(db):
    unverified_entries = db.scalars(select(HeritageEntry).where(HeritageEntry.facts_verified.is_(False))).all()
    assert unverified_entries, "the seed must contain unverified content (Gornji Stoliv)"
    assert all(e.status != "approved" for e in unverified_entries)

    unverified_villages = db.scalars(select(Village).where(Village.facts_verified.is_(False))).all()
    assert unverified_villages, "Gornji Stoliv and Pasiglav are seeded as unverified"
    for village in unverified_villages:
        assert village.verification_note, "an unverified village must say what has to be checked"
        approved_here = db.scalar(
            select(func.count()).select_from(HeritageEntry).where(
                HeritageEntry.village_id == village.id, HeritageEntry.status == "approved"
            )
        )
        assert approved_here == 0, f"{village.slug} is unverified but has approved content"


def test_every_approved_entry_cites_a_source(db):
    for entry in db.scalars(select(HeritageEntry).where(HeritageEntry.status == "approved")):
        assert entry.source.strip(), f"{entry.slug} has no source citation"
        assert "UNVERIFIED" not in entry.source.upper()


def test_seed_coordinates_are_flagged_approximate(db):
    for entry in db.scalars(select(HeritageEntry).where(HeritageEntry.status == "approved")):
        if entry.lat is not None:
            assert entry.coords_approximate is True, f"{entry.slug} must be flagged approximate until surveyed"


# --------------------------------------------------------------------------- visitor role
def test_visitor_role_can_read_villages_but_not_people(public_db):
    n = public_db.execute(text("SELECT count(*) FROM villages")).scalar()
    assert n and n >= 2
    for table in ("users", "events", "audit_log", "provenance", "consent_records", "llm_usage", "answer_records"):
        with pytest.raises(Exception):
            public_db.execute(text(f"SELECT count(*) FROM {table}"))
        public_db.rollback()


def test_visitor_role_sees_only_approved_rows(public_db, db):
    visible = public_db.execute(text("SELECT count(*) FROM heritage_entries")).scalar()
    approved = db.scalar(select(func.count()).select_from(HeritageEntry).where(HeritageEntry.status == "approved"))
    total = db.scalar(select(func.count()).select_from(HeritageEntry))
    assert visible == approved < total, "row-level security must hide non-approved rows"


def test_visitor_role_cannot_write(public_db):
    with pytest.raises(Exception):
        public_db.execute(text("UPDATE heritage_entries SET title_en = 'hacked'"))
    public_db.rollback()
