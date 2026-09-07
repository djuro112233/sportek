"""Runtime configuration. Every value comes from the environment (or a local .env file).

No secret has a usable default: SECRET_KEY must be provided.
"""
from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROTOTYPE_LABEL = (
    "Prototype built for the SMART ERA application, September–October 2026. Sample data."
)
BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- app -----------------------------------------------------------------
    app_name: str = "VRMAC-LH prototype API"
    app_env: str = "dev"  # dev | test | prod
    secret_key: str = Field(..., min_length=16, description="JWT signing key (env only)")
    jwt_expire_minutes: int = 720
    cors_origins: str = "http://localhost:3000"
    auto_init_db: bool = True
    local_language: str = "cnr"  # ISO 639-3 for Montenegrin (Latin script)

    # --- storage -------------------------------------------------------------
    database_url: str = "postgresql+psycopg://vrmac:vrmac@localhost:5432/vrmac"
    public_db_user: str = "vrmac_public"  # read-only role, row-level-security limited to approved rows
    public_db_password: str = "vrmac_public"
    redis_url: str = "redis://localhost:6379/0"
    queue_mode: str = "rq"  # rq | sync
    upload_dir: str = "./data/uploads"
    keep_audio: bool = False  # audio is deleted after transcription unless explicitly kept
    export_dir: str = "./exports"
    seed_dir: str = str(BACKEND_DIR / "seed_data")
    seed_password: str = "prototype123"  # sample accounts only

    # --- LLM -----------------------------------------------------------------
    llm_provider: str = "ollama"  # ollama | openai | none
    llm_model: str = "qwen2.5:1.5b"
    ollama_url: str = "http://localhost:11434"
    llm_api_base: str = "https://api.openai.com/v1"  # any OpenAI-compatible server (vLLM, Groq, Mistral…)
    llm_api_key: str = ""
    llm_timeout_s: float = 180.0

    # --- embeddings / RAG ----------------------------------------------------
    embeddings_provider: str = "ollama"  # ollama | sentence-transformers | hash
    embeddings_model: str = "paraphrase-multilingual"
    embedding_dim: int = 768
    rag_top_k: int = 5
    rag_min_similarity: float | None = None  # None → provider default (see providers/embeddings.py)
    rag_min_coverage: float = 0.34  # share of question content-words present in the cited chunk

    # --- speech-to-text ------------------------------------------------------
    stt_provider: str = "faster-whisper"  # faster-whisper | api | fixture
    stt_model: str = "small"
    stt_language: str = "hr"  # Whisper has no 'cnr' code; 'hr' yields Latin-script output closest to Montenegrin
    stt_compute_type: str = "int8"
    stt_api_base: str = ""
    stt_api_key: str = ""
    stt_api_model: str = "whisper-1"

    # --- maps ----------------------------------------------------------------
    maps_provider: str = "osm"  # osm | google
    google_maps_api_key: str = ""

    # --- KPIs ----------------------------------------------------------------
    kpi_k_min: int = 5
    onboarding_target_minutes: int = 30

    # --- security ------------------------------------------------------------
    rate_limit_public: str = "120/minute"
    rate_limit_ask: str = "20/minute"

    @property
    def is_test(self) -> bool:
        return self.app_env == "test"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
