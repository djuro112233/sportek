"""SQLAlchemy models.

Every *content item* (heritage entry, listing, trail segment, trail report) carries
``status ∈ {draft, reviewed, approved, rejected}`` (CHECK constraint), a ``version`` and a
provenance trail in ``provenance``. Only ``approved`` rows are visible to the visitor role
(see db.py – row level security).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .config import settings
from .db import Base

STATUS_VALUES = ("draft", "reviewed", "approved", "rejected")
ROLE_VALUES = ("host", "ambassador", "validator", "institution")
SEX_VALUES = ("F", "M", "X")  # X = other / not stated
ITEM_TYPES = ("heritage_entry", "listing", "trail_segment", "trail_report")
CONDITION_VALUES = ("good", "caution", "blocked")
REQUEST_STATUS_VALUES = ("sent", "confirmed", "declined")
ONBOARDING_STATUS_VALUES = ("started", "transcribed", "drafted", "confirmed", "published", "abandoned")

EVENT_TYPES = (
    "onboarding_started",
    "transcript_ready",
    "draft_generated",
    "listing_confirmed",
    "entry_approved",
    "itinerary_generated",
    "answer_served",
    "answer_withheld",
    "request_sent",
    "request_confirmed",
    "trail_report",
    # additional, documented in docs/events.md
    "item_rejected",
    "visit_recorded",
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


def _status_check(name: str) -> CheckConstraint:
    return CheckConstraint("status IN ('draft','reviewed','approved','rejected')", name=name)


def _coords_check(name: str) -> CheckConstraint:
    return CheckConstraint(
        "(lat IS NULL AND lng IS NULL) OR (lat BETWEEN -90 AND 90 AND lng BETWEEN -180 AND 180)",
        name=name,
    )


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('host','ambassador','validator','institution')", name="ck_users_role"),
        CheckConstraint("sex IS NULL OR sex IN ('F','M','X')", name="ck_users_sex"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    sex: Mapped[str | None] = mapped_column(String(1), nullable=True)
    is_sample: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class HeritageEntry(Base):
    """A heritage fact sheet (place, building, church, event, tradition, institution)."""

    __tablename__ = "heritage_entries"
    __table_args__ = (
        _status_check("ck_heritage_entries_status"),
        CheckConstraint("version >= 1", name="ck_heritage_entries_version"),
        _coords_check("ck_heritage_entries_coords"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # place|church|building|event|tradition|institution|landscape
    title_local: Mapped[str] = mapped_column(String(255), nullable=False)
    title_en: Mapped[str] = mapped_column(String(255), nullable=False)
    summary_local: Mapped[str] = mapped_column(Text, nullable=False, default="")
    summary_en: Mapped[str] = mapped_column(Text, nullable=False, default="")
    body_local: Mapped[str] = mapped_column(Text, nullable=False, default="")
    body_en: Mapped[str] = mapped_column(Text, nullable=False, default="")
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    coords_approximate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    coords_source: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    elevation_m: Mapped[int | None] = mapped_column(Integer, nullable=True)
    event_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    recurrence_rule: Mapped[str | None] = mapped_column(String(255), nullable=True)
    established_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)  # primary citation string
    sources: Mapped[list] = mapped_column(JSON, nullable=False, default=list)  # [{title,url}]
    tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft", index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    chunks: Mapped[list["EntryChunk"]] = relationship(back_populates="entry", cascade="all, delete-orphan")


class EntryChunk(Base):
    """Embedded text chunk of an *approved* heritage entry (index for RAG)."""

    __tablename__ = "entry_chunks"
    __table_args__ = (UniqueConstraint("entry_id", "lang", "chunk_index", name="uq_entry_chunk"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("heritage_entries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lang: Mapped[str] = mapped_column(String(8), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding = mapped_column(Vector(settings.embedding_dim), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    entry: Mapped[HeritageEntry] = relationship(back_populates="chunks")


class Listing(Base):
    """A provider offer (accommodation, food, guiding, craft…). No payments, no bookings."""

    __tablename__ = "listings"
    __table_args__ = (
        _status_check("ck_listings_status"),
        CheckConstraint("version >= 1", name="ck_listings_version"),
        _coords_check("ck_listings_coords"),
        CheckConstraint(
            "price_min IS NULL OR price_max IS NULL OR price_min <= price_max", name="ck_listings_price"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    host_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="other")  # accommodation|food|guiding|craft|experience|transport|other
    title_local: Mapped[str] = mapped_column(String(255), nullable=False)
    title_en: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    description_local: Mapped[str] = mapped_column(Text, nullable=False, default="")
    description_en: Mapped[str] = mapped_column(Text, nullable=False, default="")
    price_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    season: Mapped[str | None] = mapped_column(String(64), nullable=True)  # e.g. "May–October", "all-year"
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    accessibility_local: Mapped[str] = mapped_column(Text, nullable=False, default="")
    accessibility_en: Mapped[str] = mapped_column(Text, nullable=False, default="")
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    coords_approximate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    photo_url: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    is_sample: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    missing_fields: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    extraction_method: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")  # llm|rules|manual
    translation_pending: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    onboarding_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("onboarding_sessions.id", use_alter=True), nullable=True
    )
    consent_record_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("consent_records.id", use_alter=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft", index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class TrailSegment(Base):
    __tablename__ = "trail_segments"
    __table_args__ = (
        _status_check("ck_trail_segments_status"),
        CheckConstraint("version >= 1", name="ck_trail_segments_version"),
        _coords_check("ck_trail_segments_coords"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    name_local: Mapped[str] = mapped_column(String(255), nullable=False)
    name_en: Mapped[str] = mapped_column(String(255), nullable=False)
    description_local: Mapped[str] = mapped_column(Text, nullable=False, default="")
    description_en: Mapped[str] = mapped_column(Text, nullable=False, default="")
    from_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    to_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    gpx_file: Mapped[str | None] = mapped_column(String(255), nullable=True)  # relative to seed_data/gpx
    geometry: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)  # GeoJSON LineString [lng, lat, ele]
    length_m: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ascent_m: Mapped[int | None] = mapped_column(Integer, nullable=True)
    difficulty: Mapped[str] = mapped_column(String(16), nullable=False, default="moderate")
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)  # start point
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    coords_approximate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft", index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    reports: Mapped[list["TrailReport"]] = relationship(back_populates="segment", cascade="all, delete-orphan")


class TrailReport(Base):
    """Geotagged condition report (segment + point). Goes through the same validation gate."""

    __tablename__ = "trail_reports"
    __table_args__ = (
        _status_check("ck_trail_reports_status"),
        CheckConstraint("condition IN ('good','caution','blocked')", name="ck_trail_reports_condition"),
        CheckConstraint("lat BETWEEN -90 AND 90 AND lng BETWEEN -180 AND 180", name="ck_trail_reports_coords"),
        CheckConstraint("version >= 1", name="ck_trail_reports_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    segment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trail_segments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)
    condition: Mapped[str] = mapped_column(String(16), nullable=False)
    note_local: Mapped[str] = mapped_column(Text, nullable=False, default="")
    note_en: Mapped[str] = mapped_column(Text, nullable=False, default="")
    reported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    reporter_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    reporter_role: Mapped[str] = mapped_column(String(32), nullable=False, default="visitor")
    is_sample: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft", index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    segment: Mapped[TrailSegment] = relationship(back_populates="reports")


class Provenance(Base):
    """Who did what, when, to which version of a content item, and from which source."""

    __tablename__ = "provenance"
    __table_args__ = (
        CheckConstraint(
            "item_type IN ('heritage_entry','listing','trail_segment','trail_report')", name="ck_provenance_item_type"
        ),
        Index("ix_provenance_item", "item_type", "item_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    item_type: Mapped[str] = mapped_column(String(32), nullable=False)
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)  # created|edited|submitted|reviewed|approved|rejected|published
    from_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False, default="system")
    source: Mapped[str] = mapped_column(Text, nullable=False, default="")  # where the content came from
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ConsentRecord(Base):
    __tablename__ = "consent_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    host_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    ambassador_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    onboarding_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("onboarding_sessions.id", use_alter=True), nullable=True
    )
    listing_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    consent_text_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")
    consent_given: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    method: Mapped[str] = mapped_column(String(32), nullable=False, default="checkbox")  # checkbox|voice
    given_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class OnboardingSession(Base):
    """One voice-first onboarding run. Duration is measured from start to confirmation."""

    __tablename__ = "onboarding_sessions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('started','transcribed','drafted','confirmed','published','abandoned')",
            name="ck_onboarding_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    host_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    ambassador_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="cnr")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="started")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    transcript_ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    draft_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    audio_duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    stt_provider: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    stt_model: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    llm_provider: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    transcript: Mapped[str] = mapped_column(Text, nullable=False, default="")
    draft: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    listing_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class VisitorRequest(Base):
    """A visitor's message to a provider. No booking, no payment, no contact details required."""

    __tablename__ = "visitor_requests"
    __table_args__ = (
        CheckConstraint("status IN ('sent','confirmed','declined')", name="ck_visitor_requests_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    listing_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("listings.id", ondelete="CASCADE"), nullable=False)
    visitor_session_id: Mapped[str] = mapped_column(String(64), nullable=False)  # random client id, not PII
    message: Mapped[str] = mapped_column(Text, nullable=False)
    requested_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    party_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="sent")
    host_reply: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Event(Base):
    """Append-only event stream. KPIs are computed from this table only."""

    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN (" + ",".join(f"'{e}'" for e in EVENT_TYPES) + ")", name="ck_events_type"
        ),
        CheckConstraint("actor_sex IS NULL OR actor_sex IN ('F','M','X')", name="ck_events_sex"),
        Index("ix_events_type_time", "event_type", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    actor_role: Mapped[str | None] = mapped_column(String(32), nullable=True)  # host|ambassador|validator|institution|visitor|system
    actor_sex: Mapped[str | None] = mapped_column(String(1), nullable=True)  # snapshot for disaggregation
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # anonymous visitor session
    item_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    properties: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class KpiAggregate(Base):
    """Published aggregates. The dashboard reads ONLY from this table (k>=5 suppression applied)."""

    __tablename__ = "kpi_aggregates"
    __table_args__ = (Index("ix_kpi_run", "run_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    kpi_key: Mapped[str] = mapped_column(String(64), nullable=False)
    dimension: Mapped[str] = mapped_column(String(32), nullable=False, default="total")  # total | sex=F | sex=M | sex=X
    value: Mapped[float | None] = mapped_column(Float, nullable=True)  # NULL when suppressed
    unit: Mapped[str] = mapped_column(String(16), nullable=False, default="count")
    n_persons: Mapped[int | None] = mapped_column(Integer, nullable=True)
    n_events: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    suppressed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    note: Mapped[str] = mapped_column(String(255), nullable=False, default="")


class HeatCell(Base):
    """Aggregated visit counts per grid cell (k>=5 suppression). Dashboard heat map reads this only."""

    __tablename__ = "kpi_heat_cells"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    cell_lat: Mapped[float] = mapped_column(Float, nullable=False)  # cell centre
    cell_lng: Mapped[float] = mapped_column(Float, nullable=False)
    cell_size_deg: Mapped[float] = mapped_column(Float, nullable=False)
    n_visits: Mapped[int] = mapped_column(Integer, nullable=False)
    n_sessions: Mapped[int] = mapped_column(Integer, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="anonymous")
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    resource_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    detail: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)  # never PII
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
