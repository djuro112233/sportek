"""LLM behind one interface, with usage accounting for the monthly spend cap.

``LLM_PROVIDER``:

* ``eu_api``  — **primary for the pilot**: an open-weight model consumed pay-per-use from an EU
  inference provider under a no-data-retention contract (OpenAI-compatible API: Scaleway, OVHcloud,
  Mistral, Nebius…). ``LLM_PROVIDER_NAME`` records which one, and
  ``LLM_NO_DATA_RETENTION_CONFIRMED`` must be true before the app starts in ``APP_ENV=prod``.
* ``ollama`` / ``vllm`` — the same open-weight models self-hosted, for a demo laptop or an offline
  venue. No cost is recorded for these (``billable=False``).
* ``none``   — no generative model at all. Callers fall back to deterministic behaviour (extractive
  answers, host-entered fields) and say so in the response.

Every call returns an :class:`LLMResult` with token counts so ``services/budget.py`` can price it in
euro and enforce ``LLM_MONTHLY_CAP_EUR``.
"""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from typing import Protocol

import httpx

from ..config import settings

log = logging.getLogger(__name__)


class LLMUnavailable(RuntimeError):
    """The configured model could not be reached or is disabled."""


@dataclass
class LLMResult:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    provider: str = ""
    model: str = ""
    billable: bool = False
    raw_usage: dict = field(default_factory=dict)


def estimate_tokens(text: str) -> int:
    """Rough token estimate used when a provider reports no usage (≈ 4 characters per token)."""
    return max(1, math.ceil(len(text) / 4))


class LLM(Protocol):
    name: str
    model: str
    billable: bool

    def complete(
        self, system: str, user: str, *, json_mode: bool = False, max_tokens: int = 800, temperature: float = 0.1
    ) -> LLMResult: ...


class OpenAICompatibleLLM:
    """Any OpenAI-compatible /chat/completions endpoint (the EU provider, vLLM, a hosted API)."""

    def __init__(self, name: str, base_url: str, api_key: str, model: str, timeout: float, billable: bool = True):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.billable = billable

    def complete(self, system, user, *, json_mode=False, max_tokens=800, temperature=0.1) -> LLMResult:
        if not self.base_url:
            raise LLMUnavailable(f"{self.name}: LLM_API_BASE is not configured")
        body: dict = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            r = httpx.post(f"{self.base_url}/chat/completions", json=body, headers=headers, timeout=self.timeout)
            r.raise_for_status()
        except httpx.HTTPError as exc:  # pragma: no cover - network
            raise LLMUnavailable(f"{self.name} request failed: {exc}") from exc
        data = r.json()
        text = data["choices"][0]["message"]["content"] or ""
        usage = data.get("usage") or {}
        return LLMResult(
            text=text,
            input_tokens=int(usage.get("prompt_tokens") or estimate_tokens(system + user)),
            output_tokens=int(usage.get("completion_tokens") or estimate_tokens(text)),
            provider=self.name,
            model=self.model,
            billable=self.billable,
            raw_usage=usage,
        )


class OllamaLLM:
    """Self-hosted open-weight model (demo laptop / offline venue). Not billable."""

    name = "ollama"
    billable = False

    def __init__(self, base_url: str, model: str, timeout: float):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def complete(self, system, user, *, json_mode=False, max_tokens=800, temperature=0.1) -> LLMResult:
        body: dict = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if json_mode:
            body["format"] = "json"
        try:
            r = httpx.post(f"{self.base_url}/api/chat", json=body, timeout=self.timeout)
            r.raise_for_status()
        except httpx.HTTPError as exc:  # pragma: no cover - network
            raise LLMUnavailable(f"ollama request failed: {exc}") from exc
        data = r.json()
        text = data["message"]["content"]
        return LLMResult(
            text=text,
            input_tokens=int(data.get("prompt_eval_count") or estimate_tokens(system + user)),
            output_tokens=int(data.get("eval_count") or estimate_tokens(text)),
            provider=self.name,
            model=self.model,
            billable=False,
        )


class NoLLM:
    name = "none"
    model = "-"
    billable = False

    def complete(self, system, user, *, json_mode=False, max_tokens=800, temperature=0.1) -> LLMResult:
        raise LLMUnavailable("LLM_PROVIDER=none")


_instance: LLM | None = None


def get_llm() -> LLM:
    global _instance
    if _instance is None:
        p = settings.llm_provider
        if p == "eu_api":
            _instance = OpenAICompatibleLLM(
                name=settings.llm_provider_name or "eu_api",
                base_url=settings.llm_api_base,
                api_key=settings.llm_api_key,
                model=settings.llm_model,
                timeout=settings.llm_timeout_s,
                billable=True,
            )
        elif p == "vllm":
            _instance = OpenAICompatibleLLM(
                "vllm", settings.llm_api_base, settings.llm_api_key, settings.llm_model,
                settings.llm_timeout_s, billable=False,
            )
        elif p == "ollama":
            _instance = OllamaLLM(settings.ollama_url, settings.llm_model, settings.llm_timeout_s)
        elif p == "none":
            _instance = NoLLM()
        else:
            raise ValueError(f"unknown LLM_PROVIDER {p}")
    return _instance


def reset_llm_cache() -> None:
    """Test helper: forget the memoised provider after changing settings."""
    global _instance
    _instance = None


def llm_enabled() -> bool:
    return settings.llm_provider != "none"


def parse_json_object(text: str) -> dict:
    """Best-effort extraction of one JSON object from a model reply."""
    text = (text or "").strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        obj = json.loads(text[start : end + 1])
        if isinstance(obj, dict):
            return obj
    raise ValueError("no JSON object in model reply")
