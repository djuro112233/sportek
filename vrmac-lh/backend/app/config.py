"""Runtime configuration. Every value comes from the environment (or a local .env file).

No secret has a usable default: SECRET_KEY and EVENT_PSEUDONYM_KEY must be provided.
"""
from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROTOTYPE_LABEL = (
    "Prototype built for the SMART ERA application, September–October 2026. Sample data."
)
BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- app -----------------------------------------------------------------
    app_name: str = "VRMAC-LH prototype API"
    app_env: str = "dev"  # dev | test | prod
    secret_key: str = Field(..., min_length=16, description="JWT signing key (env only)")
    event_pseudonym_key: str = Field(
        default="", description="HMAC key for event pseudonyms; required in prod (env only)"
    )
    jwt_expire_minutes: int = 720
    cors_origins: str = "http://localhost:3000"
    auto_init_db: bool = True
    local_language: str = "cnr"  # ISO 639-3 for Montenegrin (Latin script)

    # --- storage -------------------------------------------------------------
    database_url: str = "postgresql+psycopg://vrmac:vrmac@localhost:5432/vrmac"
    public_db_user: str = "vrmac_public"  # read-only role, row-level security → approved rows only
    public_db_password: str = "vrmac_public"
    redis_url: str = "redis://localhost:6379/0"
    queue_mode: str = "rq"  # rq | sync
    upload_dir: str = "./data/uploads"
    keep_audio: bool = False  # audio is deleted after transcription unless explicitly kept
    export_dir: str = "./exports"
    seed_dir: str = str(BACKEND_DIR / "seed_data")
    seed_password: str = "prototype123"  # sample accounts only

    # --- LLM -----------------------------------------------------------------
    # Primary for the pilot: an open-weight model consumed pay-per-use from an EU inference
    # provider under a no-data-retention contract (LLM_PROVIDER=eu_api). ollama/vllm are the
    # self-hosted options for a demo laptop; "none" disables generation (extractive answers only).
    llm_provider: str = "eu_api"  # eu_api | ollama | vllm | none
    llm_provider_name: str = "eu-inference-provider"  # e.g. scaleway | ovhcloud | mistral | nebius
    llm_model: str = "qwen2.5:1.5b"
    llm_api_base: str = ""  # OpenAI-compatible base URL of the EU provider
    llm_api_key: str = ""
    llm_no_data_retention_confirmed: bool = False  # must be true in prod for eu_api
    llm_region_note: str = "EU"
    ollama_url: str = "http://localhost:11434"
    llm_timeout_s: float = 180.0

    # Monthly spend cap, enforced in code. When it is reached the assistant serves cached answers
    # and otherwise pauses politely — it never produces unsourced text.
    llm_monthly_cap_eur: float = 50.0
    llm_price_input_eur_per_mtok: float = 0.20
    llm_price_output_eur_per_mtok: float = 0.60
    stt_price_eur_per_minute: float = 0.006

    # --- embeddings / RAG ----------------------------------------------------
    embeddings_provider: str = "ollama"  # eu_api | ollama | sentence-transformers | hash
    embeddings_model: str = "paraphrase-multilingual"
    embeddings_api_base: str = ""  # defaults to llm_api_base when empty
    embeddings_api_key: str = ""
    embedding_dim: int = 768
    rag_top_k: int = 5
    rag_min_similarity: float | None = None  # None → provider default (providers/embeddings.py)
    rag_min_coverage: float = 0.34  # share of question content-words present in the cited chunk

    # --- support check (claim 2b: every answer sentence must be attributable) ---
    support_check_provider: str = "llm_judge"  # llm_judge | lexical
    support_min_score: float = 0.75  # conservative; below this a sentence is dropped
    support_check_model: str = ""  # defaults to llm_model

    # --- response cache ------------------------------------------------------
    cache_enabled: bool = True
    cache_semantic_min_similarity: float = 0.92
    cache_max_age_days: int = 30

    # --- speech-to-text ------------------------------------------------------
    stt_provider: str = "faster-whisper"  # eu_api | faster-whisper | fixture
    stt_model: str = "small"
    stt_language: str = "hr"  # Whisper has no 'cnr' code; 'hr' yields Latin-script output
    stt_compute_type: str = "int8"
    stt_api_base: str = ""
    stt_api_key: str = ""
    stt_api_model: str = "whisper-1"

    # --- maps ----------------------------------------------------------------
    maps_provider: str = "osm"  # osm | google
    google_maps_api_key: str = ""

    # --- KPIs ----------------------------------------------------------------
    kpi_k_min: int = 5
    kpi_definitions_path: str = str(BACKEND_DIR / "kpi_definitions" / "sip_section_11.json")
    k11_dedup_days: int = 180
    pilot_start_date: str = "2026-09-01"
    onboarding_target_minutes: int = 30  # median ACTIVE authoring time, excluding review waiting

    # --- security ------------------------------------------------------------
    rate_limit_public: str = "120/minute"
    rate_limit_ask: str = "20/minute"

    @property
    def is_test(self) -> bool:
        return self.app_env == "test"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def embeddings_base_url(self) -> str:
        return self.embeddings_api_base or self.llm_api_base

    @property
    def support_model(self) -> str:
        return self.support_check_model or self.llm_model


settings = Settings()
