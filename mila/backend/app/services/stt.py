"""Speech-to-text providers: a protocol, a deterministic mock and faster-whisper.

* :class:`MockSTT` is the default and the one tests use. It never looks at audio content
  except for one documented hook: a file whose bytes start with ``MOCK:`` and decode as
  UTF-8 yields the remainder as the transcript (``MOCK:<text>`` or ``MOCK:<text>|<lang>``).
  Anything else, including real recordings, yields a fixed Serbian sentence with
  confidence 0.5, so a voice demo without a real recogniser still produces an answerable
  question. ``duration_s`` is read from the WAV header when the file is RIFF, else 0.
* :class:`FasterWhisperSTT` wraps ``faster_whisper`` (imported lazily, optional ``voice``
  extra). Language detection is restricted to the Whisper languages MILA supports
  (``sr``, ``bs``, ``hr``, ``en``; Montenegrin is decoded as Serbian) and the segment
  log-probabilities are folded into one 0..1 confidence. The two mappings are pure
  functions (:func:`restrict_language`, :func:`logprob_to_confidence`) so they are tested
  without a model.

Neither implementation keeps a reference to the audio path or bytes after returning, and
nothing in this module logs transcript text. Deleting the upload is the caller's job
(``POST /api/transcribe`` does it in a ``finally`` block).
"""

from __future__ import annotations

import logging
import math
import wave
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from app.config import Settings
from app.core.i18n import coerce_lang
from app.core.types import Transcript

log = logging.getLogger("mila.stt")

MOCK_PREFIX = b"MOCK:"
MOCK_DEFAULT_TEXT = "Koje metode kontracepcije postoje i kako djeluju?"
MOCK_DEFAULT_CONFIDENCE = 0.5
MOCK_HOOK_CONFIDENCE = 1.0

# Whisper language codes MILA accepts. Whisper has no Montenegrin model; `me` decodes as `sr`.
WHISPER_LANGS: frozenset[str] = frozenset({"sr", "bs", "hr", "en"})
_WHISPER_ALIASES: dict[str, str] = {
    "me": "sr",
    "cnr": "sr",
    "srp": "sr",
    "hrv": "hr",
    "bos": "bs",
    "eng": "en",
}
FALLBACK_LANG = "sr"


@runtime_checkable
class STT(Protocol):
    def transcribe(self, path: Path, *, lang_hint: str | None = None) -> Transcript: ...


# --- pure helpers (unit-tested without any model) -------------------------------------------
def wav_duration_s(path: Path) -> float:
    """Duration from the WAV header, or 0.0 when the file is not a (valid) RIFF/WAVE file."""
    path = Path(path)
    try:
        with open(path, "rb") as fh:
            if fh.read(4) != b"RIFF":
                return 0.0
        with wave.open(str(path), "rb") as wf:
            rate = wf.getframerate()
            frames = wf.getnframes()
    except (OSError, wave.Error, EOFError):
        return 0.0
    if rate <= 0 or frames <= 0:
        return 0.0
    return frames / rate


def parse_mock_payload(data: bytes) -> tuple[str, str | None] | None:
    """Parse the documented test hook ``MOCK:<text>`` / ``MOCK:<text>|<lang>``.

    Returns ``(text, lang_or_None)``, or ``None`` when the bytes are not a hook payload
    (wrong prefix or not valid UTF-8). A trailing ``|xx`` / ``|xxx`` alphabetic suffix is
    the language; any other ``|`` stays part of the text.
    """
    if not data.startswith(MOCK_PREFIX):
        return None
    try:
        rest = data[len(MOCK_PREFIX) :].decode("utf-8")
    except UnicodeDecodeError:
        return None
    text, sep, suffix = rest.rpartition("|")
    suffix = suffix.strip()
    if sep and 2 <= len(suffix) <= 3 and suffix.isalpha():
        return text.strip(), suffix.lower()
    return rest.strip(), None


def restrict_language(detected: str | None, lang_hint: str | None = None) -> str:
    """Map a detected (or requested) language code into :data:`WHISPER_LANGS`.

    ``me`` becomes ``sr``. A code outside the set falls back to ``lang_hint`` (mapped the
    same way) and finally to ``sr``. Region suffixes and case are ignored (``EN-us`` -> ``en``).
    """
    code = _whisper_code(detected)
    if code in WHISPER_LANGS:
        return code
    hint = _whisper_code(lang_hint)
    if hint in WHISPER_LANGS:
        return hint
    return FALLBACK_LANG


def _whisper_code(lang: str | None) -> str:
    if not lang:
        return ""
    code = lang.strip().lower().split("-")[0]
    return _WHISPER_ALIASES.get(code, code)


def logprob_to_confidence(avg_logprob: float) -> float:
    """Whisper's average token log-probability -> 0..1 confidence.

    ``exp(avg_logprob)`` is the geometric-mean token probability, clamped to [0, 1]
    (0.0 -> 1.0, -0.5 -> 0.61, -1.0 -> 0.37). Non-finite input gives 0.0.
    """
    if not math.isfinite(avg_logprob):
        return 0.0
    return min(1.0, max(0.0, math.exp(avg_logprob)))


# --- implementations ------------------------------------------------------------------------
class MockSTT:
    """Deterministic recogniser for tests, demos and CI; see the module docstring for the hook."""

    name = "mock"

    def transcribe(self, path: Path, *, lang_hint: str | None = None) -> Transcript:
        path = Path(path)
        default_lang = coerce_lang(lang_hint, FALLBACK_LANG)
        duration = wav_duration_s(path)
        parsed = parse_mock_payload(path.read_bytes())
        if parsed is None:
            return Transcript(
                text=MOCK_DEFAULT_TEXT,
                lang=default_lang,
                confidence=MOCK_DEFAULT_CONFIDENCE,
                duration_s=duration,
            )
        text, suffix = parsed
        lang = coerce_lang(suffix, default_lang) if suffix else default_lang
        return Transcript(text=text, lang=lang, confidence=MOCK_HOOK_CONFIDENCE, duration_s=duration)


class FasterWhisperSTT:
    """Local Whisper via ``faster_whisper`` (CTranslate2). No audio leaves the host.

    The model is loaded in the constructor so a misconfigured deployment fails at start-up
    rather than on a user's first recording. ``device="auto"`` picks CUDA when available,
    ``compute_type="int8"`` keeps CPU inference practical.
    """

    name = "faster_whisper"

    def __init__(self, model_name: str, *, device: str = "auto", compute_type: str = "int8") -> None:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:  # pragma: no cover - depends on the optional extra
            raise ImportError("faster-whisper is not installed; install the 'voice' extra") from exc
        self.model_name = model_name
        self._model = WhisperModel(model_name, device=device, compute_type=compute_type)
        log.info(
            "faster-whisper model %s loaded (device=%s, compute_type=%s)", model_name, device, compute_type
        )

    def transcribe(self, path: Path, *, lang_hint: str | None = None) -> Transcript:
        path = Path(path)
        forced = restrict_language(lang_hint) if lang_hint else None
        segments, info = self._decode(path, forced)
        detected = getattr(info, "language", None) or ""
        lang = restrict_language(detected, lang_hint)
        if forced is None and lang != detected:
            # Auto-detection landed outside the supported set (e.g. mk, sl): the text was decoded
            # in that language, so decode again in the language we fall back to.
            segments, info = self._decode(path, lang)
        text = " ".join(seg.text.strip() for seg in segments if seg.text and seg.text.strip())
        duration = float(getattr(info, "duration", 0.0) or 0.0) or wav_duration_s(path)
        return Transcript(
            text=text, lang=lang, confidence=_segments_confidence(segments), duration_s=duration
        )

    def _decode(self, path: Path, language: str | None) -> tuple[list[Any], Any]:
        segments, info = self._model.transcribe(
            str(path), language=language, beam_size=5, vad_filter=True, condition_on_previous_text=False
        )
        return list(segments), info


def _segments_confidence(segments: list[Any]) -> float:
    """Duration-weighted mean of the segments' ``avg_logprob``, mapped to 0..1 (0.0 for silence)."""
    if not segments:
        return 0.0
    weights = [max(float(seg.end) - float(seg.start), 0.0) for seg in segments]
    total = sum(weights)
    if total <= 0.0:
        mean = sum(float(seg.avg_logprob) for seg in segments) / len(segments)
    else:
        mean = sum(float(seg.avg_logprob) * w for seg, w in zip(segments, weights, strict=True)) / total
    return logprob_to_confidence(mean)


def get_stt(settings: Settings) -> STT:
    """Provider selected by ``MILA_STT_PROVIDER`` (``mock`` by default)."""
    if settings.stt_provider == "mock":
        return MockSTT()
    if settings.stt_provider == "faster_whisper":
        return FasterWhisperSTT(settings.stt_model)
    raise ValueError(f"unknown STT provider: {settings.stt_provider}")
