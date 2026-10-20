"""FastAPI application factory for MILA."""

from __future__ import annotations

import logging
import time
from collections import OrderedDict, deque

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import Settings, get_settings
from app.db import init_engine

log = logging.getLogger("mila")


def _install_logging(settings: Settings) -> None:
    try:
        from app.core.privacy import RedactionFilter  # provided by core/privacy.py
    except Exception:  # pragma: no cover - during scaffolding
        RedactionFilter = None  # type: ignore[assignment]
    level = logging.DEBUG if settings.app_env == "dev" else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if RedactionFilter is not None:
        flt = RedactionFilter()
        for handler in logging.getLogger().handlers:
            handler.addFilter(flt)


_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "Permissions-Policy": "camera=(), geolocation=()",
}
MAX_JSON_BODY_BYTES = 1_000_000
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


class _RateLimiter:
    """Tiny in-memory sliding-window limiter keyed by session id (never by IP; IPs are not stored).

    Bounded: at most ``max_keys`` keys are tracked (least recently used first out) and empty
    windows are dropped, so a flood of fresh ids cannot grow memory without limit.
    """

    def __init__(self, per_minute: int, max_keys: int = 10_000) -> None:
        self.per_minute = per_minute
        self.max_keys = max_keys
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()

    def allow(self, key: str, limit: int | None = None) -> bool:
        now = time.monotonic()
        q = self._hits.get(key)
        if q is None:
            q = deque()
        else:
            self._hits.move_to_end(key)
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= (limit or self.per_minute):
            self._hits[key] = q
            return False
        q.append(now)
        self._hits[key] = q
        while len(self._hits) > self.max_keys:
            self._hits.popitem(last=False)
        return True

    def forget(self, key: str) -> None:
        self._hits.pop(key, None)

    def __len__(self) -> int:
        return len(self._hits)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Application factory (``uvicorn app.main:create_app --factory``); no arguments needed."""
    settings = settings or get_settings()
    _install_logging(settings)
    init_engine(settings.database_url)

    app = FastAPI(
        title="MILA",
        version="0.1.0",
        description="Information + referral for reproductive and maternal health. Not a diagnosis tool.",
        docs_url="/api/docs" if settings.app_env != "prod" else None,
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.rate_limiter = _RateLimiter(settings.rate_limit_per_minute)
    # Providers (LLM, embedder, judge, STT, TTS) are built on the first request through
    # app.core.container.get_providers, so start-up stays cheap and tests never load a model
    # they do not use; the voice routers fill stt/tts the same way. A test may place fakes
    # here before the first request. The referral directory is seeded (idempotently) on the
    # first request that needs it: the answer pipeline and GET /api/referral both call
    # app.core.referral.ensure_referral_points.
    app.state.providers = None
    app.state.stt = None
    app.state.tts = None

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type", "X-Admin-Token"],
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        # Oversized bodies are refused before they are read (Content-Length is a hint; the upload
        # endpoint enforces its own limit while reading as well).
        length = request.headers.get("content-length")
        if length and length.isdigit():
            content_type = request.headers.get("content-type", "")
            limit = MAX_UPLOAD_BYTES if content_type.startswith("multipart/") else MAX_JSON_BODY_BYTES
            if int(length) > limit:
                return JSONResponse(
                    status_code=413, content={"detail": "request too large"}, headers=_SECURITY_HEADERS
                )
        response = await call_next(request)
        for name, value in _SECURITY_HEADERS.items():
            response.headers[name] = value
        return response

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        # Never leak internals (or user text) in error bodies.
        log.exception("unhandled error on %s", request.url.path)  # path is redacted by the filter
        return JSONResponse(status_code=500, content={"detail": "internal error"}, headers=_SECURITY_HEADERS)

    from app.api import admin, ask, consent, metrics, referral, speak, transcribe

    for router_module in (consent, ask, transcribe, speak, referral, metrics, admin):
        app.include_router(router_module.router, prefix="/api")

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "demo_mode": settings.demo_mode, "version": app.version}

    return app


app = create_app() if __name__ == "app.main" and False else None  # uvicorn uses `app.main:create_app` factory
