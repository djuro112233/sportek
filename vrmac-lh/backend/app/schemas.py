"""Shared Pydantic schemas (auth + read models of content items). Router-specific request/response
models live next to their router to keep module ownership clear."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserOut(ORMModel):
    id: uuid.UUID
    email: str
    role: str
    display_name: str
    sex: str | None = None
    is_sample: bool


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=72)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class ProvenanceOut(ORMModel):
    id: uuid.UUID
    item_type: str
    item_id: uuid.UUID
    version: int
    action: str
    from_status: str | None
    to_status: str | None
    actor_user_id: uuid.UUID | None
    actor_role: str
    source: str
    note: str
    created_at: datetime


class SourceRef(BaseModel):
    title: str
    url: str | None = None


class HeritageEntryOut(ORMModel):
    id: uuid.UUID
    slug: str
    kind: str
    title_local: str
    title_en: str
    summary_local: str
    summary_en: str
    body_local: str
    body_en: str
    lat: float | None
    lng: float | None
    coords_approximate: bool
    coords_source: str
    elevation_m: int | None
    event_date: date | None
    recurrence_rule: str | None
    established_year: int | None
    source: str
    sources: list
    tags: list
    status: str
    version: int
    approved_at: datetime | None
    updated_at: datetime


class ListingOut(ORMModel):
    id: uuid.UUID
    slug: str
    category: str
    title_local: str
    title_en: str
    description_local: str
    description_en: str
    price_min: float | None
    price_max: float | None
    currency: str
    season: str | None
    capacity: int | None
    accessibility_local: str
    accessibility_en: str
    lat: float | None
    lng: float | None
    coords_approximate: bool
    photo_url: str
    is_sample: bool
    missing_fields: list
    extraction_method: str
    translation_pending: bool
    status: str
    version: int
    approved_at: datetime | None
    published_at: datetime | None
    updated_at: datetime


class TrailReportOut(ORMModel):
    id: uuid.UUID
    segment_id: uuid.UUID
    lat: float
    lng: float
    condition: str
    note_local: str
    note_en: str
    reported_at: datetime
    reporter_role: str
    is_sample: bool
    status: str
    version: int
    approved_at: datetime | None


class TrailSegmentOut(ORMModel):
    id: uuid.UUID
    slug: str
    name_local: str
    name_en: str
    description_local: str
    description_en: str
    from_name: str
    to_name: str
    gpx_file: str | None
    geometry: dict
    length_m: int | None
    ascent_m: int | None
    difficulty: str
    lat: float | None
    lng: float | None
    coords_approximate: bool
    source: str
    status: str
    version: int
    approved_at: datetime | None


class StatusTransitionIn(BaseModel):
    to_status: str = Field(pattern="^(draft|reviewed|approved|rejected)$")
    note: str = Field(default="", max_length=2000)


class Citation(BaseModel):
    entry_id: uuid.UUID
    slug: str
    title: str
    source: str
    lang: str
    chunk_index: int
    score: float
    excerpt: str
