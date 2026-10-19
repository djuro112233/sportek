"""Provider container: the one place where real or mock providers are built and cached.

:func:`build_providers` composes the LLM, the embedder (the same one ingestion used), the
support judge, the red-flag router, STT and TTS that the settings select. Nothing is
built at import time and nothing is built eagerly at application start:
:func:`get_providers` builds the set on first use and caches it on ``app.state.providers``,
so test applications with mock settings stay fast and a real deployment loads BGE-M3 or
Whisper only when ``MILA_EMBEDDER`` / ``MILA_STT_PROVIDER`` say so, at most once per process.

The voice routers (``/transcribe``, ``/speak``) look for ``request.app.state.stt`` and
``request.app.state.tts`` first; :func:`get_providers` publishes the container's instances
there and adopts an instance that was placed there before the container was built (tests
inject fakes that way), so a heavy model is never loaded twice.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi import FastAPI

from app.config import Settings
from app.core.redflags import RedFlagRouter, get_router
from app.core.verifier import SupportJudge, get_judge
from app.kb.embed import Embedder, get_embedder
from app.services.llm import LLMClient, get_llm
from app.services.stt import STT, get_stt
from app.services.tts import TTS, get_tts

log = logging.getLogger("mila.container")


@dataclass
class Providers:
    """Everything the answer pipeline composes; swap any field to inject a fake."""

    llm: LLMClient
    embedder: Embedder
    judge: SupportJudge
    redflags: RedFlagRouter
    stt: STT | None = None
    tts: TTS | None = None

    def names(self) -> dict[str, str]:
        """Provider identities for logs and reports (never any content)."""
        return {
            "llm": getattr(self.llm, "name", type(self.llm).__name__),
            "embedder": f"{type(self.embedder).__name__}(dim={getattr(self.embedder, 'dim', '?')})",
            "judge": type(self.judge).__name__,
            "redflags": type(self.redflags).__name__,
            "stt": getattr(self.stt, "name", type(self.stt).__name__) if self.stt is not None else "-",
            "tts": type(self.tts).__name__ if self.tts is not None else "-",
        }


def router_for(settings: Settings) -> RedFlagRouter:
    """The module-level router, unless these settings ask for a different classifier threshold."""
    router = get_router()
    if router.classifier_threshold != settings.redflag_classifier_threshold:
        router = RedFlagRouter(settings.redflag_classifier_threshold)
    return router


def build_providers(settings: Settings, *, stt: STT | None = None, tts: TTS | None = None) -> Providers:
    """Build the provider set the settings select (``stt`` / ``tts`` given are reused, not rebuilt)."""
    llm = get_llm(settings)
    return Providers(
        llm=llm,
        embedder=get_embedder(settings),
        judge=get_judge(settings, llm),
        redflags=router_for(settings),
        stt=stt if stt is not None else get_stt(settings),
        tts=tts if tts is not None else get_tts(settings),
    )


def get_providers(app: FastAPI) -> Providers:
    """The application's providers, built on first use and cached on ``app.state.providers``."""
    providers: Providers | None = getattr(app.state, "providers", None)
    if providers is None:
        providers = build_providers(
            app.state.settings,
            stt=getattr(app.state, "stt", None),
            tts=getattr(app.state, "tts", None),
        )
        app.state.providers = providers
        log.info("providers built: %s", providers.names())
    if getattr(app.state, "stt", None) is None and providers.stt is not None:
        app.state.stt = providers.stt
    if getattr(app.state, "tts", None) is None and providers.tts is not None:
        app.state.tts = providers.tts
    return providers
