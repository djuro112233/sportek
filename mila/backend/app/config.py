"""Runtime configuration for MILA.

All settings come from environment variables (or a .env file). Defaults are safe for
local development and tests: SQLite, deterministic mock LLM/STT/TTS, hash embedder.
Nothing in the defaults sends data to a third party.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MILA_", env_file=".env", extra="ignore")

    app_env: Literal["dev", "test", "prod"] = "dev"
    # Demo mode allows `public_unreviewed` sources to be used for answers. The UI flags this.
    demo_mode: bool = True

    database_url: str = "sqlite:///./mila.db"

    # --- model providers (all default to local, deterministic mocks) ---
    llm_provider: Literal["mock", "openai_compatible"] = "mock"
    llm_base_url: str = "http://localhost:8001/v1"
    llm_api_key: str = ""
    llm_model: str = "mistralai/Mistral-7B-Instruct-v0.3"
    llm_timeout_s: float = 60.0

    embedder: Literal["hash", "bge_m3"] = "hash"
    embedding_dim: int = 256

    judge_provider: Literal["lexical", "llm"] = "lexical"

    stt_provider: Literal["mock", "faster_whisper"] = "mock"
    stt_model: str = "large-v3"
    tts_provider: Literal["mock", "piper"] = "mock"
    piper_voice_dir: str = str(REPO_ROOT / "models" / "piper")

    # --- pipeline thresholds ---
    retrieval_top_k: int = 8
    gate_min_support_ratio: float = 0.6
    gate_min_confidence: float = 0.35
    gate_min_relevance: float = 0.35  # question coverage of the cited evidence (docs/safety.md)
    relevance_unknown_term_penalty: float = 0.75
    verifier_support_threshold: float = 0.5
    redflag_classifier_threshold: float = 0.85

    # --- privacy ---
    k_anonymity: int = 5
    audio_tmp_dir: str = str(REPO_ROOT / ".audio_tmp")
    admin_token: str = ""  # empty = admin endpoints disabled
    consent_version: str = "2026-10-01"
    default_region: str = "BA"  # ISO country code used for referral lookup (BA, ME)
    rate_limit_per_minute: int = 60

    kb_dir: str = str(REPO_ROOT / "kb")
    manifest_path: str = str(REPO_ROOT / "kb" / "manifest.yaml")

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])


@lru_cache
def get_settings() -> Settings:
    return Settings()
