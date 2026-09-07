"""LLM behind an interface.

LLM_PROVIDER=ollama   → local open-source model via Ollama (default, no API cost)
LLM_PROVIDER=openai   → any OpenAI-compatible endpoint (hosted API, vLLM, Groq, Mistral…)
LLM_PROVIDER=none     → no generative model; callers fall back to deterministic behaviour
                        (extractive answers, rule-based listing extraction) and say so.
"""
from __future__ import annotations

import json
import logging
from typing import Protocol

import httpx

from ..config import settings

log = logging.getLogger(__name__)


class LLMUnavailable(RuntimeError):
    pass


class LLM(Protocol):
    name: str
    model: str

    def complete(
        self, system: str, user: str, *, json_mode: bool = False, max_tokens: int = 800, temperature: float = 0.1
    ) -> str: ...


class OllamaLLM:
    name = "ollama"

    def __init__(self, base_url: str, model: str, timeout: float):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def complete(self, system, user, *, json_mode=False, max_tokens=800, temperature=0.1) -> str:
        body = {
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
        return r.json()["message"]["content"]


class OpenAICompatibleLLM:
    name = "openai"

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def complete(self, system, user, *, json_mode=False, max_tokens=800, temperature=0.1) -> str:
        body = {
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
            raise LLMUnavailable(f"LLM API request failed: {exc}") from exc
        return r.json()["choices"][0]["message"]["content"]


class NoLLM:
    name = "none"
    model = "-"

    def complete(self, system, user, *, json_mode=False, max_tokens=800, temperature=0.1) -> str:
        raise LLMUnavailable("LLM_PROVIDER=none")


_instance: LLM | None = None


def get_llm() -> LLM:
    global _instance
    if _instance is None:
        p = settings.llm_provider
        if p == "ollama":
            _instance = OllamaLLM(settings.ollama_url, settings.llm_model, settings.llm_timeout_s)
        elif p in ("openai", "vllm", "api"):
            _instance = OpenAICompatibleLLM(
                settings.llm_api_base, settings.llm_api_key, settings.llm_model, settings.llm_timeout_s
            )
        elif p == "none":
            _instance = NoLLM()
        else:
            raise ValueError(f"unknown LLM_PROVIDER {p}")
    return _instance


def llm_enabled() -> bool:
    return settings.llm_provider != "none"


def parse_json_object(text: str) -> dict:
    """Best-effort extraction of one JSON object from a model reply."""
    text = text.strip()
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
