"""Referral service: a localised instruction plus an ordered list of places to contact.

Every MILA response ends with a referral block. ``ReferralService.for_context`` picks the
message and the kinds of referral points for a red-flag category (or none), filters them by
region and minor status and orders them so that the most urgent contact comes first.

``seed_referral_points`` loads the pilot seed data for Bosnia and Herzegovina (``BA``) and
Montenegro (``ME``). The only phone numbers it fills in are the standard emergency numbers
(124 ambulance, 122 police). Every other number is left empty with ``to verify: <number>`` in
``notes`` so that nobody can mistake an unverified number for a verified one; the pilot clinic
fills ``phone`` / ``verified_on`` / ``verified_by`` before launch (see docs/safety.md, T9).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.core.i18n import coerce_lang, t
from app.core.types import RED_FLAG_CATEGORIES, Referral, ReferralPointOut
from app.models import ReferralPoint

EMERGENCY_CATEGORIES: frozenset[str] = frozenset(
    {
        "bleeding_pregnancy",
        "severe_abdominal_pain",
        "fever_pregnancy",
        "preeclampsia",
        "reduced_fetal_movement",
    }
)

# Referral-point kinds, in display order, per situation. Kinds absent from a plan are not shown.
_PLAN_EMERGENCY: tuple[str, ...] = ("er", "clinic")
_PLAN_SUICIDAL: tuple[str, ...] = ("mental_health", "er", "helpline")
_PLAN_VIOLENCE: tuple[str, ...] = ("violence", "er", "helpline")
_PLAN_CHILD: tuple[str, ...] = ("child_protection", "violence", "er")
_PLAN_GENERAL: tuple[str, ...] = ("clinic", "helpline", "mental_health")
_CHILD_KIND = "child_protection"


def referral_plan(
    category: str | None, *, emergency: bool, is_minor: bool | None
) -> tuple[tuple[str, ...], str, bool]:
    """Return ``(kinds in display order, i18n message key, emergency flag)`` for a context."""
    if category is not None and category not in RED_FLAG_CATEGORIES:
        raise ValueError(f"unknown red-flag category: {category!r}")
    if emergency or category in EMERGENCY_CATEGORIES:
        return _PLAN_EMERGENCY, "redflag_emergency", True
    if category == "suicidal_ideation":
        kinds, key, urgent = _PLAN_SUICIDAL, "redflag_support", True
    elif category == "violence_coercion":
        kinds, key, urgent = _PLAN_VIOLENCE, "redflag_support", False
    elif category == "minor_sexual_adult":
        return _PLAN_CHILD, "redflag_child_protection", False
    else:
        kinds, key, urgent = _PLAN_GENERAL, "referral_general", False
    if is_minor and _CHILD_KIND not in kinds:
        kinds = kinds + (_CHILD_KIND,)
    return kinds, key, urgent


def to_out(point: ReferralPoint) -> ReferralPointOut:
    return ReferralPointOut(
        name=point.name,
        kind=point.kind,
        region=point.region,
        city=point.city or "",
        phone=point.phone or "",
        address=point.address or "",
        url=point.url or "",
        hours=point.hours or "",
        emergency=bool(point.emergency),
        verified_on=point.verified_on or "",
        notes=point.notes or "",
    )


class ReferralService:
    def __init__(self, db: DbSession) -> None:
        self.db = db

    def _candidates(self, region: str, is_minor: bool | None) -> list[ReferralPoint]:
        """Points for ``region`` (all regions when the region has none), minors-only when asked."""
        points = list(self.db.scalars(select(ReferralPoint)))
        region = (region or "").strip().upper()
        regional = [p for p in points if (p.region or "").upper() == region]
        chosen = regional or points
        if is_minor:
            chosen = [p for p in chosen if p.for_minors]
        return chosen

    def for_context(
        self,
        *,
        region: str,
        lang: str,
        script: str = "latin",
        category: str | None = None,
        is_minor: bool | None = None,
        emergency: bool = False,
    ) -> Referral:
        """Build the referral block for one response.

        ``emergency=True`` forces the emergency plan whatever the category. The message is
        rendered through ``t`` so that ``script="cyrillic"`` yields Cyrillic for BCMS languages.
        """
        lang = coerce_lang(lang)
        kinds, key, urgent = referral_plan(category, emergency=emergency, is_minor=is_minor)
        rank = {kind: i for i, kind in enumerate(kinds)}
        candidates = [p for p in self._candidates(region, is_minor) if p.kind in rank]
        candidates.sort(key=lambda p: (rank[p.kind], p.priority, p.name))
        return Referral(
            emergency=urgent, message=t(key, lang, script), points=[to_out(p) for p in candidates]
        )


# ---------------------------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------------------------

_FILL_BEFORE_PILOT = "fill from official source before pilot"
_GENERIC_CLINIC_NOTE = (
    "generic entry: the nearest primary-care centre (Dom zdravlja) runs antenatal counselling; "
    "add the local address and phone before pilot"
)
_GENERIC_MH_NOTE = (
    "generic entry: community mental-health centre inside the local Dom zdravlja; add the local "
    "address and phone before pilot"
)


def _emergency_numbers(region: str, languages: list[str]) -> list[dict]:
    return [
        dict(
            name="Hitna pomoć 124",
            kind="er",
            region=region,
            phone="124",
            hours="0-24",
            languages=languages,
            emergency=True,
            priority=1,
            notes="standard emergency medical number (ambulance)",
        ),
        dict(
            name="Policija 122",
            kind="er",
            region=region,
            phone="122",
            hours="0-24",
            languages=languages,
            emergency=True,
            priority=2,
            notes="standard police emergency number",
        ),
        dict(
            name="Dom zdravlja - savjetovalište za trudnice",
            kind="clinic",
            region=region,
            languages=languages,
            priority=20,
            notes=_GENERIC_CLINIC_NOTE,
        ),
        dict(
            name="Centar za mentalno zdravlje - Dom zdravlja",
            kind="mental_health",
            region=region,
            languages=languages,
            priority=20,
            notes=_GENERIC_MH_NOTE,
        ),
    ]


def seed_points() -> list[dict]:
    """The seed rows (plain dicts). Keyed by ``(name, region)``; see the module docstring."""
    ba = ["bs", "sr", "hr"]
    me = ["me", "sr"]
    return [
        *_emergency_numbers("BA", ba),
        dict(
            name="Alivija Clinic",
            kind="clinic",
            region="BA",
            city="Banja Luka",
            phone="",
            address="",
            url="",
            hours="",
            languages=ba,
            priority=10,
            verified_on="",
            notes=_FILL_BEFORE_PILOT,
        ),
        dict(
            name="SOS telefon za žrtve nasilja u porodici - Republika Srpska",
            kind="violence",
            region="BA",
            hours="0-24",
            languages=ba,
            priority=5,
            notes="to verify: 1264",
        ),
        dict(
            name="SOS telefon za žrtve nasilja - Federacija BiH",
            kind="violence",
            region="BA",
            hours="0-24",
            languages=ba,
            priority=5,
            notes="to verify: 1265",
        ),
        dict(
            name="Plavi telefon - linija za djecu i mlade (BiH)",
            kind="child_protection",
            region="BA",
            languages=ba,
            priority=5,
            for_minors=True,
            notes="to verify: 080 05 03 05",
        ),
        *_emergency_numbers("ME", me),
        dict(
            name="SOS linija za žrtve nasilja u porodici - Crna Gora",
            kind="violence",
            region="ME",
            hours="0-24",
            languages=me,
            priority=5,
            notes="to verify: 080 111 111",
        ),
        dict(
            name="Nacionalna SOS linija za djecu - Crna Gora",
            kind="child_protection",
            region="ME",
            languages=me,
            priority=5,
            for_minors=True,
            notes="to verify: 116 111",
        ),
    ]


def seed_referral_points(db: DbSession) -> int:
    """Insert the seed rows that are missing (keyed by name + region). Returns the number added."""
    existing = {
        (name, region) for name, region in db.execute(select(ReferralPoint.name, ReferralPoint.region))
    }
    added = 0
    for row in seed_points():
        if (row["name"], row["region"]) in existing:
            continue
        db.add(ReferralPoint(**row))
        existing.add((row["name"], row["region"]))
        added += 1
    if added:
        db.commit()
    return added


def ensure_referral_points(db: DbSession) -> int:
    """Seed only when the table is empty (used by the API and meant for app start-up)."""
    if db.execute(select(ReferralPoint.id).limit(1)).first() is None:
        return seed_referral_points(db)
    return 0
