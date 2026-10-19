"""Text-to-speech providers: a protocol, a deterministic mock and Piper.

* :class:`MockTTS` (default, tests) writes a real PCM WAV with the stdlib ``wave`` module:
  16 kHz mono 16-bit (8 kHz when ``low_bandwidth``), about 60 ms per word capped at 20 s,
  a soft low-amplitude tone with short fades. The same text always gives the same bytes.
* :class:`PiperTTS` wraps ``piper-tts`` (imported lazily, optional ``voice`` extra). Voices
  are looked up per language in ``MILA_PIPER_VOICE_DIR`` (see :func:`find_voice`); when
  no voice fits, it logs a warning naming only the language and directory and falls back
  to :class:`MockTTS`, so a half-installed deployment degrades instead of failing.

:func:`clean_for_speech` removes ``[S1]`` citation markers and light Markdown so a voice
never reads "bracket S one" aloud; ``POST /api/speak`` applies it and the pipeline should
do the same before :func:`app.api.speak.register_audio`.

Nothing in this module logs the text it is asked to speak.
"""

from __future__ import annotations

import io
import logging
import math
import re
import threading
import wave
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import numpy as np

from app.config import Settings
from app.core.i18n import coerce_lang

log = logging.getLogger("mila.tts")

SAMPLE_RATE = 16000
LOW_BANDWIDTH_RATE = 8000
MOCK_SECONDS_PER_WORD = 0.06
MOCK_MAX_SECONDS = 20.0
_MOCK_TONE_HZ = 220.0
_MOCK_AMPLITUDE = 0.08  # fraction of full scale: clearly audible, never startling
_MOCK_FADE_S = 0.01

# Which voices may stand in for a language, in order of preference. The BCMS languages are
# mutually intelligible and pronounced alike, so a Serbian voice can read Bosnian text.
VOICE_FALLBACKS: dict[str, tuple[str, ...]] = {
    "sr": ("sr", "bs", "hr"),
    "bs": ("bs", "sr", "hr"),
    "hr": ("hr", "bs", "sr"),
    "me": ("me", "sr", "bs", "hr"),
    "en": ("en",),
}

_MARKER_RE = re.compile(r"\[\s*S\d+(?:\s*[,;]\s*S\d+)*\s*\]")
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_HEADING_RE = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+", re.MULTILINE)
_BULLET_RE = re.compile(r"^[ \t]*[-*•][ \t]+", re.MULTILINE)
_EMPHASIS_RE = re.compile(r"\*\*|__|~~|[*`]")
_LONE_UNDERSCORE_RE = re.compile(r"(?<!\w)_+|_+(?!\w)")
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([.,;:!?])")
_WS_RE = re.compile(r"\s+")


@runtime_checkable
class TTS(Protocol):
    def synthesize(self, text: str, lang: str, *, low_bandwidth: bool = False) -> bytes: ...


# --- pure helpers ----------------------------------------------------------------------------
def clean_for_speech(text: str) -> str:
    """Strip ``[S1]``-style markers and light Markdown (links, headings, bullets, emphasis)."""
    text = _LINK_RE.sub(r"\1", text)
    text = _MARKER_RE.sub(" ", text)
    text = _HEADING_RE.sub("", text)
    text = _BULLET_RE.sub("", text)
    text = _EMPHASIS_RE.sub("", text)
    text = _LONE_UNDERSCORE_RE.sub("", text)
    text = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", text)
    return _WS_RE.sub(" ", text).strip()


def pcm16_to_wav(pcm: bytes, rate: int, channels: int = 1) -> bytes:
    """Wrap little-endian 16-bit PCM frames in a WAV container."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def resample_wav(wav: bytes, target_rate: int) -> bytes:
    """Convert a 16-bit PCM WAV to mono at ``target_rate``.

    Linear interpolation after a short moving-average low-pass when downsampling: a
    low-bandwidth profile, not studio quality. Returns the input unchanged when it already
    is mono at the target rate.
    """
    with wave.open(io.BytesIO(wav), "rb") as wf:
        channels, sampwidth, rate, n_frames = (
            wf.getnchannels(),
            wf.getsampwidth(),
            wf.getframerate(),
            wf.getnframes(),
        )
        frames = wf.readframes(n_frames)
    if sampwidth != 2:
        raise ValueError("resample_wav supports 16-bit PCM only")
    if rate == target_rate and channels == 1:
        return wav
    samples = np.frombuffer(frames, dtype="<i2").astype(np.float64)
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    if rate != target_rate and samples.size:
        if target_rate < rate:
            kernel = math.ceil(rate / target_rate)
            samples = np.convolve(samples, np.ones(kernel) / kernel, mode="same")
        n_out = max(1, round(samples.size * target_rate / rate))
        positions = np.arange(n_out) * (rate / target_rate)
        samples = np.interp(positions, np.arange(samples.size), samples)
    pcm = np.clip(np.round(samples), -32768, 32767).astype("<i2").tobytes()
    return pcm16_to_wav(pcm, target_rate)


def find_voice(voice_dir: Path, lang: str) -> Path | None:
    """Locate a Piper ``.onnx`` voice for ``lang`` in ``voice_dir``.

    For each candidate language in :data:`VOICE_FALLBACKS` (the language itself first) it
    accepts ``<lang>.onnx`` or the Piper naming convention ``<lang>_<REGION>-<name>-<quality>.onnx``
    (lowest name first, so the choice is stable). ``None`` when nothing fits.
    """
    voice_dir = Path(voice_dir)
    if not voice_dir.is_dir():
        return None
    for candidate in VOICE_FALLBACKS.get(lang, (lang,)):
        exact = voice_dir / f"{candidate}.onnx"
        if exact.is_file():
            return exact
        matches = sorted(p for p in voice_dir.glob(f"{candidate}_*.onnx") if p.is_file())
        if matches:
            return matches[0]
    return None


def _mock_tone(n_frames: int, rate: int) -> bytes:
    t = np.arange(n_frames, dtype=np.float64) / rate
    signal = np.sin(2.0 * np.pi * _MOCK_TONE_HZ * t)
    fade = min(n_frames // 2, int(rate * _MOCK_FADE_S))
    if fade > 0:
        ramp = np.linspace(0.0, 1.0, fade, endpoint=False)
        signal[:fade] *= ramp
        signal[-fade:] *= ramp[::-1]
    return np.round(signal * (_MOCK_AMPLITUDE * 32767)).astype("<i2").tobytes()


# --- implementations ------------------------------------------------------------------------
class MockTTS:
    """Deterministic placeholder voice: a soft tone whose length follows the word count."""

    name = "mock"

    def synthesize(self, text: str, lang: str, *, low_bandwidth: bool = False) -> bytes:
        rate = LOW_BANDWIDTH_RATE if low_bandwidth else SAMPLE_RATE
        n_words = max(1, len(text.split()))  # at least one word's worth, so the file is playable
        seconds = min(MOCK_MAX_SECONDS, n_words * MOCK_SECONDS_PER_WORD)
        return pcm16_to_wav(_mock_tone(round(seconds * rate), rate), rate)


class PiperTTS:
    """Local neural TTS via ``piper-tts``. Voices load on first use and are cached per language.

    A language without a usable voice falls back to ``fallback`` (default :class:`MockTTS`);
    the warning is logged once per language and never contains the text.
    """

    name = "piper"

    def __init__(self, voice_dir: Path | str, *, fallback: TTS | None = None) -> None:
        self.voice_dir = Path(voice_dir)
        self._fallback: TTS = fallback if fallback is not None else MockTTS()
        self._voices: dict[str, Any] = {}
        self._missing: set[str] = set()
        self._lock = threading.Lock()

    def synthesize(self, text: str, lang: str, *, low_bandwidth: bool = False) -> bytes:
        lang = coerce_lang(lang)
        voice = self._voice_for(lang)
        if voice is None:
            return self._fallback.synthesize(text, lang, low_bandwidth=low_bandwidth)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            # piper-tts >= 1.3 writes WAV through `synthesize_wav`; 1.2 through `synthesize`.
            synth = getattr(voice, "synthesize_wav", None) or voice.synthesize
            synth(text, wf)
        wav = buf.getvalue()
        return resample_wav(wav, LOW_BANDWIDTH_RATE) if low_bandwidth else wav

    def _voice_for(self, lang: str) -> Any | None:
        with self._lock:
            if lang in self._voices:
                return self._voices[lang]
            if lang in self._missing:
                return None
            path = find_voice(self.voice_dir, lang)
            if path is None:
                self._missing.add(lang)
                log.warning(
                    "no Piper voice for lang=%s in %s; falling back to mock TTS", lang, self.voice_dir
                )
                return None
            try:
                from piper import PiperVoice
            except ImportError as exc:  # pragma: no cover - depends on the optional extra
                raise ImportError("piper-tts is not installed; install the 'voice' extra") from exc
            voice = PiperVoice.load(str(path))
            self._voices[lang] = voice
            log.info("Piper voice for lang=%s loaded from %s", lang, path.name)
            return voice


def get_tts(settings: Settings) -> TTS:
    """Provider selected by ``MILA_TTS_PROVIDER`` (``mock`` by default)."""
    if settings.tts_provider == "mock":
        return MockTTS()
    if settings.tts_provider == "piper":
        return PiperTTS(settings.piper_voice_dir)
    raise ValueError(f"unknown TTS provider: {settings.tts_provider}")
