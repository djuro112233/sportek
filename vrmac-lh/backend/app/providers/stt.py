"""Speech-to-text behind an interface.

STT_PROVIDER=eu_api         → Whisper hosted by the EU inference provider under the same
                              no-data-retention contract as the LLM (OpenAI-compatible
                              /audio/transcriptions). Billable: priced per audio minute.
STT_PROVIDER=faster-whisper → local CTranslate2 Whisper (CPU, int8). Model downloaded on first use.
STT_PROVIDER=api            → any other OpenAI-compatible /audio/transcriptions endpoint
STT_PROVIDER=fixture        → TEST ONLY: returns the transcript stored next to the audio file
                              (<file>.txt) or in seed_data/stt_fixtures/<stem>.txt. Never use for a live demo.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import httpx

from ..config import settings

log = logging.getLogger(__name__)


@dataclass
class TranscriptResult:
    text: str
    language: str
    duration_s: float | None
    provider: str
    model: str
    billable: bool = False
    segments: list[dict] = field(default_factory=list)


class STT(Protocol):
    name: str
    model: str

    def transcribe(self, path: str | Path, language: str | None = None) -> TranscriptResult: ...


def audio_duration_seconds(path: str | Path) -> float | None:
    try:
        import av  # bundled with faster-whisper

        with av.open(str(path)) as container:
            if container.duration:
                return round(container.duration / av.time_base, 2)
            for s in container.streams:
                if s.duration and s.time_base:
                    return round(float(s.duration * s.time_base), 2)
    except Exception:  # pragma: no cover
        return None
    return None


class FasterWhisperSTT:
    name = "faster-whisper"

    def __init__(self, model: str, compute_type: str):
        self.model = model
        self.compute_type = compute_type
        self._m = None

    def _load(self):
        if self._m is None:
            from faster_whisper import WhisperModel  # lazy import: heavy

            log.info("loading faster-whisper model %s (%s)", self.model, self.compute_type)
            self._m = WhisperModel(self.model, device="cpu", compute_type=self.compute_type)
        return self._m

    def transcribe(self, path, language=None) -> TranscriptResult:
        m = self._load()
        segments, info = m.transcribe(
            str(path), language=language or settings.stt_language, beam_size=1, vad_filter=True
        )
        segs = [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()} for s in segments]
        text = " ".join(s["text"] for s in segs).strip()
        return TranscriptResult(
            text=text,
            language=info.language,
            duration_s=round(info.duration, 2) if info.duration else audio_duration_seconds(path),
            provider=self.name,
            model=self.model,
            segments=segs,
        )


class WhisperAPISTT:
    def __init__(self, base_url: str, api_key: str, model: str, name: str = "api", billable: bool = True):
        self.name = name
        self.billable = billable
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def transcribe(self, path, language=None) -> TranscriptResult:
        p = Path(path)
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        with p.open("rb") as fh:
            r = httpx.post(
                f"{self.base_url}/audio/transcriptions",
                headers=headers,
                data={"model": self.model, "language": language or settings.stt_language, "response_format": "json"},
                files={"file": (p.name, fh)},
                timeout=300,
            )
        r.raise_for_status()
        text = r.json().get("text", "").strip()
        return TranscriptResult(
            text=text,
            language=language or settings.stt_language,
            duration_s=audio_duration_seconds(path),
            provider=self.name,
            model=self.model,
            billable=self.billable,
        )


class FixtureSTT:
    """Test double. Reads the transcript from a sidecar text file."""

    name = "fixture"
    model = "fixture"

    def transcribe(self, path, language=None) -> TranscriptResult:
        p = Path(path)
        candidates = [
            p.with_suffix(p.suffix + ".txt"),
            p.with_suffix(".txt"),
            Path(settings.seed_dir) / "stt_fixtures" / (p.stem + ".txt"),
        ]
        for c in candidates:
            if c.exists():
                log.warning("STT fixture used for %s — test/demo fallback only, not real speech-to-text", p.name)
                return TranscriptResult(
                    text=c.read_text(encoding="utf-8").strip(),
                    language=language or settings.stt_language,
                    duration_s=audio_duration_seconds(path),
                    provider=self.name,
                    model=self.model,
                )
        raise FileNotFoundError(f"no STT fixture transcript for {p.name}")


def word_error_rate(reference: str, hypothesis: str) -> tuple[float, int]:
    """Word error rate (Levenshtein on words) and the reference length.

    Text is lower-cased and stripped of punctuation first, so the metric measures words, not
    formatting. Returns ``(wer, n_reference_words)``; an empty reference gives ``(0.0, 0)``.
    """
    import re as _re

    def words(text: str) -> list[str]:
        return _re.sub(r"[^\w\s]", " ", (text or "").lower()).split()

    ref, hyp = words(reference), words(hypothesis)
    if not ref:
        return (0.0, 0)
    previous = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, start=1):
        current = [i]
        for j, h in enumerate(hyp, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (r != h)))
        previous = current
    return (previous[len(hyp)] / len(ref), len(ref))


_instance: STT | None = None


def get_stt() -> STT:
    global _instance
    if _instance is None:
        p = settings.stt_provider
        if p == "faster-whisper":
            _instance = FasterWhisperSTT(settings.stt_model, settings.stt_compute_type)
        elif p == "eu_api":
            _instance = WhisperAPISTT(
                settings.stt_api_base or settings.llm_api_base,
                settings.stt_api_key or settings.llm_api_key,
                settings.stt_api_model,
                name=settings.llm_provider_name or "eu_api",
                billable=True,
            )
        elif p == "api":
            _instance = WhisperAPISTT(settings.stt_api_base, settings.stt_api_key, settings.stt_api_model)
        elif p == "fixture":
            _instance = FixtureSTT()
        else:
            raise ValueError(f"unknown STT_PROVIDER {p}")
    return _instance


def reset_stt_cache() -> None:
    """Test helper: forget the memoised provider after changing settings."""
    global _instance
    _instance = None
