"""FastAPI application: Vrmac Living Heritage prototype API."""
from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from .config import PROTOTYPE_LABEL, settings
from .db import init_db
from .logging_conf import configure_logging
from .ratelimit import limiter
from .routers import (
    ask,
    auth,
    events,
    export,
    heritage,
    itinerary,
    kpi,
    listings,
    map as map_router,
    onboarding,
    requests,
    trails,
    validation,
)

configure_logging()
log = logging.getLogger("vrmac")

DESCRIPTION = f"""
**{PROTOTYPE_LABEL}**

Innovation claims implemented for real (not mocked):

The territory is the rural plateau of **Vrmac on both sides of the ridge**: every point of interest, provider,
trail segment and event belongs to a village with its municipality (Tivat or Kotor), and itineraries span villages.

1. **Validation gate** – every content item is `draft → reviewed → approved | rejected`; visitors only ever read
   `approved` rows (explicit filters + PostgreSQL row-level security on a read-only DB role).
2. **Grounded answers or refusal** – `/api/ask` retrieves only approved entries **and** checks every answer
   sentence against the cited passage; unsupported sentences are dropped and an empty answer is withheld
   with an `answer_withheld` event.
3. **Voice-first onboarding** – offline-capable recording → speech-to-text → the model drafts *title and
   description only*; price, season, capacity and accessibility are host-entered and host-confirmed →
   consent → validation queue → publish (Montenegrin + English).
4. **Events → KPIs** – every step emits a *pseudonymised* event; K01–K23 are computed nightly and published
   only after a disclosure review (k≥5 and small-cell suppression).
5. **Map & directions** – every approved item has WGS84 coordinates, GPX trails and geotagged condition reports.
6. **Interoperability** – NGSI-LD `PointOfInterest` (Smart Data Models) + DCAT-AP export.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.app_env == "prod":
        if settings.secret_key.startswith("replace-with"):
            raise RuntimeError("SECRET_KEY placeholder detected: set a real secret in the environment")
        if not settings.event_pseudonym_key:
            raise RuntimeError("EVENT_PSEUDONYM_KEY must be set in production (events are pseudonymised)")
        if settings.llm_provider == "eu_api" and not settings.llm_no_data_retention_confirmed:
            raise RuntimeError(
                "LLM_PROVIDER=eu_api requires LLM_NO_DATA_RETENTION_CONFIRMED=true — confirm the "
                "no-data-retention contract with the EU inference provider first"
            )
    if settings.auto_init_db:
        init_db()
    log.info(
        "providers: llm=%s/%s (%s) embeddings=%s (%s, %d-d) stt=%s (%s) support=%s queue=%s cap=%.2f EUR/month",
        settings.llm_provider, settings.llm_provider_name, settings.llm_model, settings.embeddings_provider,
        settings.embeddings_model, settings.embedding_dim, settings.stt_provider, settings.stt_model,
        settings.support_check_provider, settings.queue_mode, settings.llm_monthly_cap_eur,
    )
    yield


app = FastAPI(
    title=settings.app_name,
    description=DESCRIPTION,
    version="0.1.0",
    openapi_url="/api/openapi.json",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    license_info={"name": "AGPL-3.0-only", "url": "https://www.gnu.org/licenses/agpl-3.0.html"},
    lifespan=lifespan,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    """Request id + timing log. Deliberately logs no client address, no user, no body."""
    request_id = uuid.uuid4().hex[:12]
    request.state.request_id = request_id
    start = time.perf_counter()
    response = await call_next(request)
    ms = (time.perf_counter() - start) * 1000
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Prototype"] = "SMART ERA prototype; sample data"
    log.info("%s %s -> %s (%.0f ms) rid=%s", request.method, request.url.path, response.status_code, ms, request_id)
    return response


for r in (
    auth, heritage, listings, ask, onboarding, validation, kpi, map_router, trails, itinerary, requests, events, export
):
    app.include_router(r.router)


# SVG placeholder photos of the sample providers
app.mount("/api/static", StaticFiles(directory=str(Path(settings.seed_dir) / "svg")), name="static")


@app.get("/api/health", tags=["meta"])
def health():
    return {
        "status": "ok",
        "prototype": PROTOTYPE_LABEL,
        "providers": {
            "llm": {
                "provider": settings.llm_provider,
                "provider_name": settings.llm_provider_name,
                "model": settings.llm_model,
                "region": settings.llm_region_note,
                "no_data_retention_confirmed": settings.llm_no_data_retention_confirmed,
            },
            "support_check": {"provider": settings.support_check_provider, "min_score": settings.support_min_score},
            "embeddings": {
                "provider": settings.embeddings_provider,
                "model": settings.embeddings_model,
                "dim": settings.embedding_dim,
            },
            "stt": {"provider": settings.stt_provider, "model": settings.stt_model},
        },
        "queue_mode": settings.queue_mode,
        "monthly_cap_eur": settings.llm_monthly_cap_eur,
    }


@app.get("/api/meta", tags=["meta"])
def meta():
    return {
        "prototype_label": PROTOTYPE_LABEL,
        "languages": [settings.local_language, "en"],
        "local_language": settings.local_language,
        "maps_provider": settings.maps_provider,
        "google_maps_api_key": settings.google_maps_api_key if settings.maps_provider == "google" else "",
        "kpi_k_min": settings.kpi_k_min,
        "onboarding_target_minutes": settings.onboarding_target_minutes,
        "municipalities": ["Tivat", "Kotor"],
        "cache_enabled": settings.cache_enabled,
        "support_check": settings.support_check_provider,
    }
