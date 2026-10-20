"""Unit tests for app.core.referral: seed data, plans per category, filtering, ordering, rendering."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.core.i18n import t
from app.core.referral import (
    EMERGENCY_CATEGORIES,
    ReferralService,
    ensure_referral_points,
    referral_plan,
    seed_points,
    seed_referral_points,
)
from app.core.types import RED_FLAG_CATEGORIES, Referral
from app.models import ReferralPoint

STANDARD_NUMBERS = {"124", "122"}


@pytest.fixture
def seeded(db):
    seed_referral_points(db)
    return db


def _count(db) -> int:
    return db.scalar(select(func.count()).select_from(ReferralPoint))


# --- seeding ------------------------------------------------------------------------------------
def test_seed_is_idempotent_and_keyed_by_name_and_region(db):
    first = seed_referral_points(db)
    assert first == len(seed_points()) == _count(db)
    assert seed_referral_points(db) == 0
    assert _count(db) == first
    names = {(name, region) for name, region in db.execute(select(ReferralPoint.name, ReferralPoint.region))}
    assert len(names) == first


def test_ensure_seeds_only_an_empty_table(db):
    assert ensure_referral_points(db) == len(seed_points())
    assert ensure_referral_points(db) == 0


def test_alivija_clinic_has_no_invented_contact_data(seeded):
    alivija = seeded.scalar(select(ReferralPoint).where(ReferralPoint.name == "Alivija Clinic"))
    assert alivija is not None
    assert (alivija.kind, alivija.region, alivija.city) == ("clinic", "BA", "Banja Luka")
    assert alivija.phone == "" and alivija.address == "" and alivija.verified_on == ""
    assert "fill from official source before pilot" in alivija.notes


def test_no_seed_carries_a_number_that_is_not_the_standard_emergency_number(seeded):
    for point in seeded.scalars(select(ReferralPoint)):
        assert point.verified_on == "" and point.verified_by == ""
        if point.phone:
            assert point.phone in STANDARD_NUMBERS and point.kind == "er" and point.emergency
        else:
            assert not point.emergency
        if point.kind in {"violence", "child_protection"}:
            assert point.phone == "" and point.notes.startswith("to verify: ")


def test_both_regions_have_ambulance_police_clinic_mental_health_violence_and_child_lines(seeded):
    for region in ("BA", "ME"):
        rows = list(seeded.scalars(select(ReferralPoint).where(ReferralPoint.region == region)))
        phones = {p.phone for p in rows if p.kind == "er"}
        assert phones == STANDARD_NUMBERS
        assert {p.kind for p in rows} >= {"er", "clinic", "mental_health", "violence", "child_protection"}
        assert all(p.for_minors for p in rows)


# --- plans ----------------------------------------------------------------------------------------
def test_referral_plan_rejects_unknown_category():
    with pytest.raises(ValueError):
        referral_plan("not_a_category", emergency=False, is_minor=None)


@pytest.mark.parametrize("category", sorted(EMERGENCY_CATEGORIES))
def test_emergency_categories_put_er_first(seeded, category):
    referral = ReferralService(seeded).for_context(region="BA", lang="sr", category=category)
    assert referral.emergency is True
    assert referral.message == t("redflag_emergency", "sr")
    assert (
        referral.points[0].kind == "er" and referral.points[0].phone == "124" and referral.points[0].emergency
    )
    assert [p.kind for p in referral.points] == sorted(
        (p.kind for p in referral.points), key=("er", "clinic").index
    )
    assert {p.kind for p in referral.points} <= {"er", "clinic"}


def test_emergency_flag_without_category_uses_emergency_plan(seeded):
    referral = ReferralService(seeded).for_context(region="ME", lang="bs", emergency=True)
    assert (
        referral.emergency
        and referral.points[0].phone == "124"
        and referral.message == t("redflag_emergency", "bs")
    )


def test_suicidal_ideation_mental_health_then_er_with_support_message(seeded):
    referral = ReferralService(seeded).for_context(region="BA", lang="sr", category="suicidal_ideation")
    kinds = [p.kind for p in referral.points]
    assert kinds[0] == "mental_health" and "er" in kinds
    assert kinds.index("mental_health") < kinds.index("er")
    assert referral.message == t("redflag_support", "sr")
    assert referral.emergency is True
    assert any(p.phone == "124" for p in referral.points)


def test_violence_coercion_sos_line_then_police_and_ambulance(seeded):
    referral = ReferralService(seeded).for_context(region="BA", lang="hr", category="violence_coercion")
    kinds = [p.kind for p in referral.points]
    assert kinds[0] == "violence"
    assert any(p.name == "Policija 122" and p.phone == "122" for p in referral.points)
    assert referral.message == t("redflag_support", "hr") and "nazvati" in referral.message
    assert referral.emergency is False
    assert "child_protection" not in kinds


def test_minor_sexual_adult_child_protection_first_then_violence_lines(seeded):
    referral = ReferralService(seeded).for_context(
        region="ME", lang="me", category="minor_sexual_adult", is_minor=True
    )
    kinds = [p.kind for p in referral.points]
    assert kinds[0] == "child_protection" and "violence" in kinds and "er" in kinds
    assert kinds.index("child_protection") < kinds.index("violence") < kinds.index("er")
    assert referral.message == t("redflag_child_protection", "me")
    assert referral.emergency is False


def test_no_category_lists_clinics_first_with_general_message(seeded):
    referral = ReferralService(seeded).for_context(region="BA", lang="sr", category=None)
    assert referral.emergency is False and referral.message == t("referral_general", "sr")
    assert referral.points and referral.points[0].kind == "clinic"
    assert referral.points[0].name == "Alivija Clinic"  # priority 10 before the generic entry (20)
    assert {p.kind for p in referral.points} <= {"clinic", "helpline", "mental_health"}
    assert not any(p.kind == "er" for p in referral.points)


def test_minor_sees_a_child_line_in_every_plan(seeded):
    service = ReferralService(seeded)
    for category in (None, "suicidal_ideation", "violence_coercion"):
        kinds = [
            p.kind
            for p in service.for_context(region="BA", lang="sr", category=category, is_minor=True).points
        ]
        assert "child_protection" in kinds and kinds[-1] == "child_protection", category
    emergency = service.for_context(region="BA", lang="sr", category="bleeding_pregnancy", is_minor=True)
    kinds = [p.kind for p in emergency.points]
    assert kinds[0] == "er" and "child_protection" in kinds and emergency.emergency


# --- filtering and ordering ---------------------------------------------------------------------
@pytest.mark.parametrize("region", ["BA", "ME", "ba"])
def test_points_are_filtered_by_region(seeded, region):
    for category in (None, *RED_FLAG_CATEGORIES):
        referral = ReferralService(seeded).for_context(region=region, lang="sr", category=category)
        assert referral.points and {p.region for p in referral.points} == {region.upper()}


def test_unknown_region_falls_back_to_all_regions(seeded):
    referral = ReferralService(seeded).for_context(region="XX", lang="sr", category="bleeding_pregnancy")
    assert referral.points[0].kind == "er"
    pairs = [(p.name, p.phone) for p in referral.points]
    assert len(pairs) == len(set(pairs)), "fallback must not repeat the same number per region"
    assert sum(1 for p in referral.points if p.phone == "124") == 1


def test_for_minors_filter_hides_adult_only_points(seeded):
    seeded.add(
        ReferralPoint(name="Adults only clinic", kind="clinic", region="BA", for_minors=False, priority=1)
    )
    seeded.commit()
    service = ReferralService(seeded)
    adult = service.for_context(region="BA", lang="sr", category=None, is_minor=None)
    minor = service.for_context(region="BA", lang="sr", category=None, is_minor=True)
    assert adult.points[0].name == "Adults only clinic"
    assert all(p.name != "Adults only clinic" for p in minor.points)


def test_priority_orders_points_inside_a_kind(seeded):
    seeded.add(
        ReferralPoint(name="Zzz hospital ER", kind="er", region="BA", phone="", priority=0, emergency=True)
    )
    seeded.add(
        ReferralPoint(name="Aaa late ER", kind="er", region="BA", phone="", priority=50, emergency=True)
    )
    seeded.commit()
    names = [
        p.name
        for p in ReferralService(seeded).for_context(region="BA", lang="sr", emergency=True).points
        if p.kind == "er"
    ]
    assert names[0] == "Zzz hospital ER" and names[1] == "Hitna pomoć 124" and names[-1] == "Aaa late ER"


def test_kinds_outside_the_plan_are_not_shown(seeded):
    referral = ReferralService(seeded).for_context(region="BA", lang="sr", category="fever_pregnancy")
    assert not any(p.kind in {"violence", "child_protection", "mental_health"} for p in referral.points)


# --- rendering --------------------------------------------------------------------------------------
def test_message_renders_in_cyrillic_for_bcms_only(seeded):
    service = ReferralService(seeded)
    cyr = service.for_context(region="BA", lang="sr", script="cyrillic", category="bleeding_pregnancy")
    assert cyr.message == t("redflag_emergency", "sr", "cyrillic") and "хитно" in cyr.message
    en = service.for_context(region="BA", lang="en", script="cyrillic", category="bleeding_pregnancy")
    assert en.message == t("redflag_emergency", "en")


def test_unknown_language_falls_back_to_serbian(seeded):
    referral = ReferralService(seeded).for_context(region="BA", lang="xx", category=None)
    assert referral.message == t("referral_general", "sr")


def test_for_context_rejects_unknown_category(seeded):
    with pytest.raises(ValueError):
        ReferralService(seeded).for_context(region="BA", lang="sr", category="bogus")


def test_output_is_the_shared_referral_model(seeded):
    referral = ReferralService(seeded).for_context(region="BA", lang="sr", category="violence_coercion")
    assert isinstance(referral, Referral)
    point = referral.points[0]
    assert point.model_dump().keys() >= {
        "name",
        "kind",
        "region",
        "phone",
        "verified_on",
        "emergency",
    }


def test_empty_table_gives_message_without_points(db):
    referral = ReferralService(db).for_context(region="BA", lang="sr", category="bleeding_pregnancy")
    assert referral.points == [] and referral.emergency is True and referral.message
