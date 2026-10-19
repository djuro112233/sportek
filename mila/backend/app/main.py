"""FastAPI application factory for MILA."""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque

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


class _RateLimiter:
    """Tiny in-memory sliding-window limiter keyed by session id (never by IP; IPs are not stored)."""

    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        q = self._hits[key]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= self.per_minute:
            return False
        q.append(now)
        return True


def create_app(settings: Settings | None = None) -> FastAPI:
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

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type", "X-Admin-Token"],
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Permissions-Policy"] = "camera=(), geolocation=()"
        return response

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        # Never leak internals (or user text) in error bodies.
        log.exception("unhandled error on %s", request.url.path)
        return JSONResponse(status_code=500, content={"detail": "internal error"})

    from app.api import admin, ask, consent, metrics, referral, speak, transcribe

    for router_module in (consent, ask, transcribe, speak, referral, metrics, admin):
        app.include_router(router_module.router, prefix="/api")

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "demo_mode": settings.demo_mode, "version": app.version}

    return app


app = create_app() if __name__ == "app.main" and False else None  # uvicorn uses `app.main:create_app` factory
