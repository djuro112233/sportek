"""Admin endpoints (``X-Admin-Token``): source review, gate audit trail, referral seeding.

Every route depends on :func:`app.api.deps.require_admin`, which answers 404 while no token
is configured (the endpoints do not exist as far as the outside is concerned) and 403 on a
wrong token. Nothing here touches user sessions.
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.api.deps import get_db, require_admin
from app.core.types import ReviewStatus
from app.models import Chunk, GateRecord, Source, SourceVersion, utcnow

log = logging.getLogger("mila.admin")

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])

DEFAULT_GATE_LIMIT = 50
MAX_GATE_LIMIT = 500


# --- models ---------------------------------------------------------------------------------
class SourceVersionOut(BaseModel):
    id: int
    version_hash: str
    file_name: str
    published_on: str
    ingested_at: datetime
    n_chunks: int
    is_current: bool


class SourceOut(BaseModel):
    id: str
    title: str
    publisher: str
    year: int | None
    url: str
    licence: str
    lang: str
    allowed_topics: list[str] = Field(default_factory=list)
    review_status: str
    reviewed_by: str
    reviewed_on: datetime | None
    created_at: datetime
    chunk_count: int
    n_versions: int
    current_version: SourceVersionOut | None


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewed_by: str = Field(min_length=1, max_length=200)
    status: ReviewStatus
    note: str | None = Field(default=None, max_length=500)


class ReviewResponse(BaseModel):
    source: SourceOut
    note: str | None


class GateRecordOut(BaseModel):
    id: int
    event_id: int | None
    gate_version: str
    status: str
    reasons: list[str] = Field(default_factory=list)
    support_ratio: float
    confidence: float
    n_sentences_in: int
    n_sentences_kept: int
    created_at: datetime


class SeedResponse(BaseModel):
    seeded: int


# --- helpers --------------------------------------------------------------------------------
def _chunk_counts(db: DbSession) -> dict[str, int]:
    stmt = select(Chunk.source_id, func.count(Chunk.id)).group_by(Chunk.source_id)
    return {source_id: int(count) for source_id, count in db.execute(stmt)}


def _versions_by_source(db: DbSession) -> dict[str, list[SourceVersion]]:
    """All versions grouped by source, newest ingestion first."""
    grouped: dict[str, list[SourceVersion]] = {}
    stmt = select(SourceVersion).order_by(SourceVersion.ingested_at.desc(), SourceVersion.id.desc())
    for version in db.scalars(stmt):
        grouped.setdefault(version.source_id, []).append(version)
    return grouped


def _source_out(source: Source, versions: list[SourceVersion], chunk_count: int) -> SourceOut:
    current = next((v for v in versions if v.is_current), None)
    return SourceOut(
        id=source.id,
        title=source.title,
        publisher=source.publisher,
        year=source.year,
        url=source.url,
        licence=source.licence,
        lang=source.lang,
        allowed_topics=[str(topic) for topic in (source.allowed_topics or [])],
        review_status=source.review_status,
        reviewed_by=source.reviewed_by,
        reviewed_on=source.reviewed_on,
        created_at=source.created_at,
        chunk_count=chunk_count,
        n_versions=len(versions),
        current_version=SourceVersionOut.model_validate(current, from_attributes=True) if current else None,
    )


# --- routes ---------------------------------------------------------------------------------
@router.get("/sources", response_model=list[SourceOut])
def list_sources(db: DbSession = Depends(get_db)) -> list[SourceOut]:
    """Every source with its review state, version history summary and chunk count."""
    chunk_counts = _chunk_counts(db)
    versions = _versions_by_source(db)
    sources = db.scalars(select(Source).order_by(Source.id)).all()
    return [_source_out(s, versions.get(s.id, []), chunk_counts.get(s.id, 0)) for s in sources]


@router.post("/sources/{source_id}/review", response_model=ReviewResponse, responses={404: {}})
def review_source(source_id: str, body: ReviewRequest, db: DbSession = Depends(get_db)) -> ReviewResponse:
    """Record a clinician's decision on a source. ``reviewed_on`` is set to now.

    The optional note is not persisted (``Source`` has no note column); it is echoed back
    and written to the application log, which is redacted like everything else.
    """
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="unknown source")
    source.review_status = body.status
    source.reviewed_by = body.reviewed_by
    source.reviewed_on = utcnow()
    db.commit()
    db.refresh(source)
    log.info("source %s set to %s by %s; note=%r", source.id, body.status, body.reviewed_by, body.note or "")
    versions = _versions_by_source(db).get(source.id, [])
    return ReviewResponse(
        source=_source_out(source, versions, _chunk_counts(db).get(source.id, 0)), note=body.note
    )


@router.get("/gate/records", response_model=list[GateRecordOut])
def gate_records(
    limit: int = Query(DEFAULT_GATE_LIMIT, ge=1, le=MAX_GATE_LIMIT),
    db: DbSession = Depends(get_db),
) -> list[GateRecordOut]:
    """Most recent gate decisions (reasons and counts only; no text is stored in them)."""
    stmt = select(GateRecord).order_by(GateRecord.created_at.desc(), GateRecord.id.desc()).limit(limit)
    return [GateRecordOut.model_validate(record, from_attributes=True) for record in db.scalars(stmt)]


@router.post("/referral/seed", response_model=SeedResponse, responses={501: {}})
def seed_referrals(db: DbSession = Depends(get_db)) -> SeedResponse:
    """Seed the referral directory. Idempotent; 501 while the referral module is not available."""
    try:
        from app.core.referral import seed_referral_points
    except ImportError as exc:
        raise HTTPException(status_code=501, detail="referral module not available") from exc
    return SeedResponse(seeded=int(seed_referral_points(db)))
