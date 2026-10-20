"""GET /api/referral - the referral block for a region, red-flag category and minor status."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session as DbSession

from app.api.deps import get_db, get_settings_dep
from app.config import Settings
from app.core.events import log_event
from app.core.i18n import coerce_lang
from app.core.referral import REGIONS, ReferralService, ensure_referral_points
from app.core.types import RED_FLAG_CATEGORIES, Referral, Script

router = APIRouter()


@router.get("/referral", response_model=Referral)
def get_referral(
    region: str | None = Query(default=None, max_length=8),
    category: str | None = Query(default=None, max_length=40),
    minor: bool | None = Query(default=None),
    lang: str | None = Query(default=None, max_length=8),
    script: Script = Query(default="latin"),
    db: DbSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> Referral:
    """Referral points for the context. Seeds the table on first use; logs an aggregate event only."""
    if category is not None and category not in RED_FLAG_CATEGORIES:
        raise HTTPException(status_code=422, detail="unknown category")
    region_code = (region or settings.default_region).strip().upper()
    if region_code not in REGIONS:
        raise HTTPException(status_code=422, detail=f"region must be one of {sorted(REGIONS)}")
    language = coerce_lang(lang)
    ensure_referral_points(db)
    referral = ReferralService(db).for_context(
        region=region_code, lang=language, script=script, category=category, is_minor=minor
    )
    log_event(
        db,
        type="referral_view",
        session_id=None,
        lang=language,
        outcome="ok",
        redflag_category=category or "",
        payload={
            "region": region_code,
            "minor": bool(minor),
            "emergency": referral.emergency,
            "n_points": len(referral.points),
        },
    )
    return referral
