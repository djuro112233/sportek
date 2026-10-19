"""Shared pydantic types used across the answer pipeline and the API.

These are the contract between modules. Change them only together with the tests.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Lang = Literal["sr", "bs", "hr", "me", "en"]
Script = Literal["latin", "cyrillic"]
Outcome = Literal["answered", "withheld", "redflag"]
ReviewStatus = Literal["reviewed", "public_unreviewed", "blocked"]

SUPPORTED_LANGS: tuple[str, ...] = ("sr", "bs", "hr", "me", "en")
# Languages that share one text normalisation / keyword space (BCMS).
BCMS_LANGS: tuple[str, ...] = ("sr", "bs", "hr", "me")

TOPIC_CLASSES: tuple[str, ...] = (
    "contraception",
    "pregnancy",
    "antenatal_care",
    "postnatal",
    "menstruation",
    "sti",
    "mental_health",
    "adolescent",
    "other",
)

RED_FLAG_CATEGORIES: tuple[str, ...] = (
    "bleeding_pregnancy",
    "severe_abdominal_pain",
    "fever_pregnancy",
    "preeclampsia",
    "reduced_fetal_movement",
    "suicidal_ideation",
    "violence_coercion",
    "minor_sexual_adult",
)


class RetrievedChunk(BaseModel):
    chunk_id: str
    source_id: str
    source_title: str
    source_version: str  # version hash (short)
    published_on: str = ""
    page: int | None = None
    heading_path: str = ""
    text: str
    lang: str = "en"
    score: float = 0.0
    review_status: str = "public_unreviewed"


class Citation(BaseModel):
    marker: str  # "S1"
    chunk_id: str
    source_id: str
    source_title: str
    section: str = ""
    version: str = ""
    date: str = ""
    page: int | None = None
    review_status: str = "public_unreviewed"
    lang: str = "en"


class AnswerSentence(BaseModel):
    text: str
    citations: list[str] = Field(default_factory=list)  # markers, e.g. ["S1"]
    supported: bool = False
    support_score: float = 0.0
    flagged_medication: bool = False
    reason: str = ""  # why it was removed / flagged (empty when kept)


class GateDecision(BaseModel):
    status: Literal["approved", "withheld"]
    gate_version: str
    reasons: list[str] = Field(default_factory=list)
    support_ratio: float = 0.0
    confidence: float = 0.0
    kept: list[AnswerSentence] = Field(default_factory=list)
    removed: list[AnswerSentence] = Field(default_factory=list)


class RedFlagResult(BaseModel):
    flagged: bool = False
    category: str | None = None
    matched: str | None = None  # the rule id / keyword that fired
    score: float = 0.0
    source: Literal["rule", "classifier", "none"] = "none"
    child_protection: bool = False


class ReferralPointOut(BaseModel):
    name: str
    kind: str
    region: str
    city: str = ""
    phone: str = ""
    address: str = ""
    url: str = ""
    hours: str = ""
    emergency: bool = False
    verified_on: str = ""
    notes: str = ""


class Referral(BaseModel):
    emergency: bool = False
    message: str = ""  # localised one-paragraph instruction
    points: list[ReferralPointOut] = Field(default_factory=list)


class RawAnswer(BaseModel):
    text: str  # model output with [S1] markers
    model: str = "mock"
    translated: bool = False
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class AskRequest(BaseModel):
    session_id: str
    text: str = Field(min_length=1, max_length=2000)
    lang: Lang | None = None
    script: Script = "latin"
    region: str | None = None
    input_mode: Literal["text", "voice"] = "text"
    want_audio: bool = False
    low_bandwidth: bool = False


class AskResponse(BaseModel):
    outcome: Outcome
    session_id: str
    lang: str
    script: str = "latin"
    topic_class: str = "other"
    sentences: list[AnswerSentence] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    confidence: float = 0.0
    support_ratio: float = 0.0
    message: str = ""  # refusal / red-flag message (localised) when outcome != answered
    referral: Referral | None = None
    disclaimer_short: str = ""
    translated: bool = False
    demo_unreviewed_sources: bool = False
    redflag_category: str | None = None
    gate: GateDecision | None = None
    audio_url: str | None = None
    latency_ms: int = 0


class Transcript(BaseModel):
    text: str
    lang: str = "sr"
    confidence: float = 0.0
    duration_s: float = 0.0
