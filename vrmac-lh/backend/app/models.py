"""SQLAlchemy models.

Every *content item* (village, heritage entry, listing, trail segment, trail report) carries
``status ∈ {draft, reviewed, approved, rejected}`` (CHECK constraint), a ``version`` and a provenance
trail in ``provenance``. Only ``approved`` rows are visible to the visitor role (see db.py — the
read-only role plus row-level security).

Territory: the prototype covers the rural plateau of **Vrmac on both sides of the ridge**, not one
village. Every point of interest, provider, trail segment and event belongs to a ``Village`` which
carries its municipality (Tivat or Kotor), so itineraries and KPIs can span villages.

Privacy: the ``events`` table holds **pseudonymised** identifiers only (see app/pseudonym.py); it has
no foreign key to ``users`` and no session or device id in the clear.
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
# Gender is disaggregated only from a voluntary self-report; "undisclosed" is the default and
# "prefer_not_to_say" is an explicit choice. Both are excluded from gender-disaggregated KPIs.
GENDER_VALUES = ("female", "male", "other", "prefer_not_to_say", "undisclosed")
GENDER_REPORTED = ("female", "male", "other")
MUNICIPALITIES = ("Tivat", "Kotor")
ITEM_TYPES = ("village", "heritage_entry", "listing", "trail_segment", "trail_report")
CONDITION_VALUES = ("good", "caution", "blocked")
REQUEST_STATUS_VALUES = ("sent", "confirmed", "completed", "cancelled", "refused", "expired")
ONBOARDING_STATUS_VALUES = (
    "started", "captured_offline", "transcribed", "drafted", "confirmed", "published", "abandoned"
)

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
    "request_completed",
    "request_cancelled",
    "request_refused",
    "request_expired",
    "trail_report",
    # additional, documented in docs/events.md
    "item_rejected",
    "visit_recorded",
    "assistant_paused",
)

REQUEST_STATUS_EVENT = {
    "confirmed": "request_confirmed",
    "completed": "request_completed",
    "cancelled": "request_cancelled",
    "refused": "request_refused",
    "expired": "request_expired",
}


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
        CheckConstraint(
            "gender IN ('female','male','other','prefer_not_to_say','undisclosed')", name="ck_users_gender"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    # Voluntary self-report only. "undisclosed" = never asked/answered; both it and
    # "prefer_not_to_say" are excluded from gender-disaggregated KPIs.
    gender: Mapped[str] = mapped_column(String(20), nullable=False, default="undisclosed")
    gender_self_reported: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    village_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("villages.id"), nullable=True
    )
    is_sample: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Village(Base):
    """A settlement of the Vrmac territory (both sides of the ridge).

    Reference data on purpose: a village row carries only its names, municipality, approximate
    coordinates and the source of those facts. Every *claim* about a village lives in a heritage
    entry that goes through the validation gate. ``facts_verified=False`` marks a village whose
    public sources could not be checked yet; the UI and the exports show that flag.
    """

    __tablename__ = "villages"
    __table_args__ = (
        CheckConstraint("municipality IN ('Tivat','Kotor')", name="ck_villages_municipality"),
        CheckConstraint("ridge_side IN ('tivat','kotor','ridge')", name="ck_villages_ridge_side"),
        _coords_check("ck_villages_coords"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    name_local: Mapped[str] = mapped_column(String(160), nullable=False)
    name_en: Mapped[str] = mapped_column(String(160), nullable=False)
    municipality: Mapped[str] = mapped_column(String(32), nullable=False)
    ridge_side: Mapped[str] = mapped_column(String(16), nullable=False, default="tivat")
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    coords_approximate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    elevation_m: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="")
    facts_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    verification_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
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
    village_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("villages.id"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
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
    facts_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    verification_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft", index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    village: Mapped[Village] = relationship()
    chunks: Mapped[list["EntryChunk"]] = relationship(back_populates="entry", cascade="all, delete-orphan")

    @property
    def village_slug(self) -> str | None:
        """Convenience for the read models, so a client need not join /api/villages by hand."""
        return self.village.slug if self.village else None

    @property
    def municipality(self) -> str | None:
        return self.village.municipality if self.village else None



class EntryChunk(Base):
    """Embedded text chunk of an *approved* heritage entry (index for retrieval)."""

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
    entry_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    embedding_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding = mapped_column(Vector(settings.embedding_dim), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    entry: Mapped[HeritageEntry] = relationship(back_populates="chunks")


class Listing(Base):
    """A provider offer (accommodation, food, guiding, craft…). No payments, no bookings.

    ``price_*``, ``season``, ``capacity`` and ``accessibility_*`` are **never inferred** by a model:
    they are explicit fields confirmed by the host (see services/onboarding.py). ``confirmed_fields``
    records which of them the host actually confirmed.
    """

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
    village_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("villages.id"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="other")
    title_local: Mapped[str] = mapped_column(String(255), nullable=False)
    title_en: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    description_local: Mapped[str] = mapped_column(Text, nullable=False, default="")
    description_en: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # --- host-confirmed structured fields (never model-inferred) ---
    price_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    price_note_local: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    price_note_en: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    season_from: Mapped[int | None] = mapped_column(Integer, nullable=True)  # month 1-12
    season_to: Mapped[int | None] = mapped_column(Integer, nullable=True)
    season_all_year: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    accessibility_step_free: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    accessibility_note_local: Mapped[str] = mapped_column(Text, nullable=False, default="")
    accessibility_note_en: Mapped[str] = mapped_column(Text, nullable=False, default="")
    confirmed_fields: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # --- location & media ---
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    coords_approximate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    photo_url: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    is_sample: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    missing_fields: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # "llm" only ever refers to title + description; structured fields are host-entered.
    extraction_method: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    translation_pending: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    onboarding_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("onboarding_sessions.id", use_alter=True, name="fk_listings_onboarding_session"),
        nullable=True,
    )
    consent_record_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("consent_records.id", use_alter=True, name="fk_listings_consent_record"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft", index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    village: Mapped[Village] = relationship()

    @property
    def village_slug(self) -> str | None:
        """Convenience for the read models, so a client need not join /api/villages by hand."""
        return self.village.slug if self.village else None

    @property
    def municipality(self) -> str | None:
        return self.village.municipality if self.village else None


class TrailSegment(Base):
    """A trail segment. It starts in ``village_id`` and may connect several villages (``village_slugs``)."""

    __tablename__ = "trail_segments"
    __table_args__ = (
        _status_check("ck_trail_segments_status"),
        CheckConstraint("version >= 1", name="ck_trail_segments_version"),
        _coords_check("ck_trail_segments_coords"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    village_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("villages.id"), nullable=False, index=True
    )
    village_slugs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    name_local: Mapped[str] = mapped_column(String(255), nullable=False)
    name_en: Mapped[str] = mapped_column(String(255), nullable=False)
    description_local: Mapped[str] = mapped_column(Text, nullable=False, default="")
    description_en: Mapped[str] = mapped_column(Text, nullable=False, default="")
    from_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    to_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    gpx_file: Mapped[str | None] = mapped_column(String(255), nullable=True)
    geometry: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)  # GeoJSON LineString
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
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    village: Mapped[Village] = relationship()
    reports: Mapped[list["TrailReport"]] = relationship(back_populates="segment", cascade="all, delete-orphan")

    @property
    def village_slug(self) -> str | None:
        """Convenience for the read models, so a client need not join /api/villages by hand."""
        return self.village.slug if self.village else None

    @property
    def municipality(self) -> str | None:
        return self.village.municipality if self.village else None



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
    village_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("villages.id"), nullable=True, index=True
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
    village: Mapped[Village | None] = relationship()

    @property
    def village_slug(self) -> str | None:
        """Convenience for the read models, so a client need not join /api/villages by hand."""
        return self.village.slug if self.village else None

    @property
    def municipality(self) -> str | None:
        return self.village.municipality if self.village else None



class Provenance(Base):
    """Who did what, when, to which version of a content item, and from which source."""

    __tablename__ = "provenance"
    __table_args__ = (
        CheckConstraint(
            "item_type IN ('village','heritage_entry','listing','trail_segment','trail_report')",
            name="ck_provenance_item_type",
        ),
        Index("ix_provenance_item", "item_type", "item_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    item_type: Mapped[str] = mapped_column(String(32), nullable=False)
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False, default="system")
    source: Mapped[str] = mapped_column(Text, nullable=False, default="")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ConsentRecord(Base):
    __tablename__ = "consent_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    host_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    ambassador_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    onboarding_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("onboarding_sessions.id", use_alter=True, name="fk_consent_onboarding_session"),
        nullable=True,
    )
    listing_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    consent_text_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")
    consent_given: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    method: Mapped[str] = mapped_column(String(32), nullable=False, default="checkbox")
    given_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OnboardingSession(Base):
    """One voice-first onboarding run.

    Two durations are logged separately, as the brief requires:

    * ``active_seconds`` — the host's **active authoring time** (client heartbeats while the tab is
      focused and the wizard is open). The ≤ 30 minute target refers to the *median* of this value.
    * ``elapsed_to_publish_seconds`` — wall-clock from start to publication, which includes waiting
      for the validator and is therefore never compared against the target.

    ``offline_captured`` marks a recording that was taken without connectivity, stored in the
    browser (IndexedDB) and uploaded later; ``upload_deferred_seconds`` is how long that took.
    """

    __tablename__ = "onboarding_sessions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('started','captured_offline','transcribed','drafted','confirmed','published','abandoned')",
            name="ck_onboarding_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    host_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    ambassador_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    village_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("villages.id"), nullable=True)
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="cnr")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="started")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    transcript_ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    draft_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    active_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    elapsed_to_confirm_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    elapsed_to_publish_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    offline_captured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    upload_deferred_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
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
        CheckConstraint(
            "status IN ('sent','confirmed','completed','cancelled','refused','expired')",
            name="ck_visitor_requests_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    listing_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("listings.id", ondelete="CASCADE"), nullable=False
    )
    visitor_session_id: Mapped[str] = mapped_column(String(64), nullable=False)  # random client id, not PII
    message: Mapped[str] = mapped_column(Text, nullable=False)
    requested_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    party_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="sent")
    host_reply: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Event(Base):
    """Append-only, **pseudonymised** event stream. KPIs are computed from this table only.

    There is no foreign key to ``users`` and no identifier in the clear: actors, visitor sessions and
    devices appear as keyed HMAC pseudonyms (app/pseudonym.py). ``actor_gender`` is a snapshot of a
    *voluntary self-report* and is null unless the person reported it.
    """

    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN (" + ",".join(f"'{e}'" for e in EVENT_TYPES) + ")", name="ck_events_type"
        ),
        CheckConstraint(
            "actor_gender IS NULL OR actor_gender IN ('female','male','other','prefer_not_to_say')",
            name="ck_events_gender",
        ),
        Index("ix_events_type_time", "event_type", "occurred_at"),
        Index("ix_events_device", "device_pseudonym"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    actor_pseudonym: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    actor_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    actor_gender: Mapped[str | None] = mapped_column(String(20), nullable=True)
    gender_self_reported: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    session_pseudonym: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    device_pseudonym: Mapped[str | None] = mapped_column(String(32), nullable=True)
    item_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    village_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    municipality: Mapped[str | None] = mapped_column(String(32), nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    properties: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class AnswerRecord(Base):
    """One assistant answer, stored **unlinked** for the monthly human review sample.

    Deliberately carries no session, device or actor pseudonym: a reviewer can judge the answer and
    its citations, but the record cannot be tied back to the person who asked.
    """

    __tablename__ = "answer_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    lang: Mapped[str] = mapped_column(String(8), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    answered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    refusal_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    citations: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    support_results: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    dropped_sentences: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    llm_provider: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    support_provider: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    served_from_cache: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class ResponseCache(Base):
    """Exact and semantic cache of visitor answers.

    ``question_hash`` gives the exact hit; ``embedding`` gives the semantic hit at cosine similarity
    ≥ ``CACHE_SEMANTIC_MIN_SIMILARITY`` (0.92). ``entry_versions`` records the version of every cited
    entry, so the cache is invalidated the moment any of them changes.
    """

    __tablename__ = "response_cache"
    __table_args__ = (Index("ix_cache_hash_lang", "question_hash", "lang"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    question_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    question_norm: Mapped[str] = mapped_column(Text, nullable=False)
    lang: Mapped[str] = mapped_column(String(8), nullable=False)
    embedding = mapped_column(Vector(settings.embedding_dim), nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    entry_versions: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    hits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invalidation_reason: Mapped[str] = mapped_column(String(120), nullable=False, default="")


class LlmUsage(Base):
    """Every paid model call, priced in euro, so the monthly cap can be enforced in code."""

    __tablename__ = "llm_usage"
    __table_args__ = (Index("ix_llm_usage_month", "month_key"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    month_key: Mapped[str] = mapped_column(String(7), nullable=False)  # YYYY-MM (UTC)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)  # answer|support_check|extraction|stt|embeddings
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    audio_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    cost_eur: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    billable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class SttEvaluation(Base):
    """Word-error-rate of the speech-to-text provider on the Montenegrin elderly-speaker test set.

    Internal quality metric shown on the institutions' dashboard; the five samples are synthetic
    stand-ins until the team records real consented samples (see docs/samples/README.md).
    """

    __tablename__ = "stt_evaluations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    sample_id: Mapped[str] = mapped_column(String(64), nullable=False)
    speaker_note: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    reference_text: Mapped[str] = mapped_column(Text, nullable=False)
    hypothesis_text: Mapped[str] = mapped_column(Text, nullable=False)
    wer: Mapped[float] = mapped_column(Float, nullable=False)
    n_reference_words: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_synthetic_sample: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class KpiRun(Base):
    """One KPI computation. Nothing is published before a disclosure review approves the run."""

    __tablename__ = "kpi_runs"
    __table_args__ = (
        CheckConstraint("status IN ('computed','reviewed','published','rejected')", name="ck_kpi_runs_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    k_min: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    definitions_version: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    definitions_provisional: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="computed")
    n_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    n_suppressed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str] = mapped_column(Text, nullable=False, default="")


class KpiAggregate(Base):
    """Published aggregates. The dashboard reads only rows of a run whose status is ``published``."""

    __tablename__ = "kpi_aggregates"
    __table_args__ = (Index("ix_kpi_run", "run_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("kpi_runs.id"), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    kpi_key: Mapped[str] = mapped_column(String(64), nullable=False)  # K01 … K23
    kpi_label: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    dimension: Mapped[str] = mapped_column(String(64), nullable=False, default="total")
    dimension_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="total")  # total|gender|village|activity_date
    value: Mapped[float | None] = mapped_column(Float, nullable=True)  # NULL when suppressed
    unit: Mapped[str] = mapped_column(String(16), nullable=False, default="count")
    n_persons: Mapped[int | None] = mapped_column(Integer, nullable=True)
    n_events: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    suppressed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    suppression_reason: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    provisional_definition: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    note: Mapped[str] = mapped_column(String(255), nullable=False, default="")


class HeatCell(Base):
    """Aggregated visit counts per grid cell (k≥5). The dashboard heat map reads this only."""

    __tablename__ = "kpi_heat_cells"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("kpi_runs.id"), nullable=False, index=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    cell_lat: Mapped[float] = mapped_column(Float, nullable=False)  # cell centre
    cell_lng: Mapped[float] = mapped_column(Float, nullable=False)
    cell_size_deg: Mapped[float] = mapped_column(Float, nullable=False)
    n_visits: Mapped[int] = mapped_column(Integer, nullable=False)
    n_devices: Mapped[int] = mapped_column(Integer, nullable=False)
    municipality: Mapped[str | None] = mapped_column(String(32), nullable=True)


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
