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

1. **Validation gate** – every content item is `draft → reviewed → approved | rejected`; visitors only ever read
   `approved` rows (explicit filters + PostgreSQL row-level security on a read-only DB role).
2. **Grounded answers or refusal** – `/api/ask` answers only from approved heritage entries with citations
   (entry id + source string) or withholds the answer and logs `answer_withheld`.
3. **Voice-first onboarding** – audio → speech-to-text → structured listing → confirmation → consent → validation queue → publish.
4. **Events → KPIs** – every step emits an event; KPI aggregates (k≥5 suppression, sex-disaggregated) are computed from events only.
5. **Map & directions** – every approved item has WGS84 coordinates, GPX trails and geotagged condition reports.
6. **Interoperability** – NGSI-LD `PointOfInterest` (Smart Data Models) + DCAT-AP export.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.app_env == "prod" and settings.secret_key.startswith("replace-with"):
        raise RuntimeError("SECRET_KEY placeholder detected: set a real secret in the environment")
    if settings.auto_init_db:
        init_db()
    log.info(
        "providers: llm=%s (%s) embeddings=%s (%s, %d-d) stt=%s (%s) queue=%s",
        settings.llm_provider, settings.llm_model, settings.embeddings_provider, settings.embeddings_model,
        settings.embedding_dim, settings.stt_provider, settings.stt_model, settings.queue_mode,
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
            "llm": {"provider": settings.llm_provider, "model": settings.llm_model},
            "embeddings": {
                "provider": settings.embeddings_provider,
                "model": settings.embeddings_model,
                "dim": settings.embedding_dim,
            },
            "stt": {"provider": settings.stt_provider, "model": settings.stt_model},
        },
        "queue_mode": settings.queue_mode,
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
    }
