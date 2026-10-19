"""Tests for app.services.tts: MockTTS WAV output, the speech cleaner, resampling, voice lookup
and PiperTTS (fallback without the package; synthesis against a stub `piper` module)."""

from __future__ import annotations

import io
import logging
import sys
import types
import wave
from pathlib import Path

import numpy as np
import pytest
from conftest import make_test_settings

from app.services.tts import (
    LOW_BANDWIDTH_RATE,
    SAMPLE_RATE,
    TTS,
    MockTTS,
    PiperTTS,
    clean_for_speech,
    find_voice,
    get_tts,
    pcm16_to_wav,
    resample_wav,
)


def _params(wav: bytes) -> tuple[int, int, int, int]:
    """(channels, sample width, rate, frames) of a WAV byte string."""
    with wave.open(io.BytesIO(wav), "rb") as wf:
        return wf.getnchannels(), wf.getsampwidth(), wf.getframerate(), wf.getnframes()


def _samples(wav: bytes) -> np.ndarray:
    with wave.open(io.BytesIO(wav), "rb") as wf:
        return np.frombuffer(wf.readframes(wf.getnframes()), dtype="<i2")


# --- MockTTS ----------------------------------------------------------------------------------
def test_mock_wav_is_16k_mono_16bit() -> None:
    wav = MockTTS().synthesize("Ovo su opšte informacije.", "sr")
    assert wav[:4] == b"RIFF" and wav[8:12] == b"WAVE"
    assert _params(wav)[:3] == (1, 2, SAMPLE_RATE)


def test_mock_low_bandwidth_is_8k() -> None:
    wav = MockTTS().synthesize("Ovo su opšte informacije.", "sr", low_bandwidth=True)
    assert _params(wav)[:3] == (1, 2, LOW_BANDWIDTH_RATE)


def test_mock_duration_follows_word_count() -> None:
    assert _params(MockTTS().synthesize("jedan dva tri četiri pet", "sr"))[3] == 4800  # 5 * 60 ms * 16 kHz
    assert _params(MockTTS().synthesize("jedan dva tri četiri pet", "sr", low_bandwidth=True))[3] == 2400
    assert _params(MockTTS().synthesize("one", "en"))[3] == 960


def test_mock_empty_text_is_still_playable() -> None:
    assert _params(MockTTS().synthesize("", "sr"))[3] == 960


def test_mock_duration_capped_at_20_seconds() -> None:
    text = " ".join(["riječ"] * 1000)
    assert _params(MockTTS().synthesize(text, "sr"))[3] == 20 * SAMPLE_RATE
    assert _params(MockTTS().synthesize(text, "sr", low_bandwidth=True))[3] == 20 * LOW_BANDWIDTH_RATE


def test_mock_is_deterministic() -> None:
    tts = MockTTS()
    assert tts.synthesize("Pitaj glasom", "sr") == MockTTS().synthesize("Pitaj glasom", "sr")
    assert tts.synthesize("Pitaj glasom", "sr") != tts.synthesize("Pitaj glasom odmah", "sr")


def test_mock_tone_is_soft_but_audible() -> None:
    samples = _samples(MockTTS().synthesize("jedan dva tri četiri pet šest", "sr"))
    peak = int(np.abs(samples).max())
    assert 0 < peak <= int(0.1 * 32767)
    assert int(samples[0]) == 0 and int(samples[-1]) == 0  # fades: no click at either end


def test_mock_satisfies_protocol_and_is_default_provider(tmp_path: Path) -> None:
    tts = get_tts(make_test_settings(tmp_path))
    assert isinstance(tts, MockTTS)
    assert isinstance(tts, TTS)


# --- clean_for_speech -------------------------------------------------------------------------
def test_clean_strips_citation_markers() -> None:
    text = "Pilula se uzima svaki dan [S1]. Kondom štiti od infekcija [S2, S3]. Kraj[S4][S12]."
    assert clean_for_speech(text) == "Pilula se uzima svaki dan. Kondom štiti od infekcija. Kraj."


def test_clean_strips_markdown() -> None:
    text = "# Naslov\n\n**Važno:** pročitaj [upute](https://example.org).\n- prva *stavka*\n- druga `stavka`\n__kraj__"
    assert clean_for_speech(text) == "Naslov Važno: pročitaj upute. prva stavka druga stavka kraj"


def test_clean_keeps_plain_text() -> None:
    text = "Za svoju situaciju razgovaraj sa ljekarom. Broj hitne pomoći je 124."
    assert clean_for_speech(text) == text
    assert clean_for_speech("   [S1]  ") == ""


# --- resample_wav and find_voice ------------------------------------------------------------
def test_resample_halves_frames_and_mixes_to_mono() -> None:
    t = np.arange(16000) / 16000
    mono = np.round(np.sin(2 * np.pi * 440 * t) * 8000).astype("<i2")
    wav = pcm16_to_wav(mono.tobytes(), 16000)
    out = resample_wav(wav, 8000)
    assert _params(out) == (1, 2, 8000, 8000)
    assert int(np.abs(_samples(out)).max()) > 1000  # signal survived the low-pass

    stereo = np.repeat(mono, 2)
    out = resample_wav(pcm16_to_wav(stereo.tobytes(), 16000, channels=2), 16000)
    assert _params(out) == (1, 2, 16000, 16000)
    assert resample_wav(wav, 16000) is wav

    with pytest.raises(ValueError):
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(1)
            wf.setframerate(8000)
            wf.writeframes(b"\x80" * 80)
        resample_wav(buf.getvalue(), 16000)


def test_find_voice_prefers_exact_then_convention_then_fallback(tmp_path: Path) -> None:
    assert find_voice(tmp_path / "missing", "sr") is None
    (tmp_path / "hr_HR-test-medium.onnx").write_bytes(b"")
    assert find_voice(tmp_path, "hr") == tmp_path / "hr_HR-test-medium.onnx"
    assert find_voice(tmp_path, "sr") == tmp_path / "hr_HR-test-medium.onnx"  # BCMS fallback
    assert find_voice(tmp_path, "me") == tmp_path / "hr_HR-test-medium.onnx"
    assert find_voice(tmp_path, "en") is None
    (tmp_path / "sr_RS-a-low.onnx").write_bytes(b"")
    (tmp_path / "sr_RS-b-medium.onnx").write_bytes(b"")
    assert find_voice(tmp_path, "sr") == tmp_path / "sr_RS-a-low.onnx"
    (tmp_path / "sr.onnx").write_bytes(b"")
    assert find_voice(tmp_path, "sr") == tmp_path / "sr.onnx"


# --- PiperTTS ---------------------------------------------------------------------------------
def test_piper_falls_back_to_mock_when_voice_dir_is_missing(tmp_path: Path, caplog) -> None:
    text = "Nisi sama. Ispod su ljudi koji mogu pomoći."
    tts = PiperTTS(tmp_path / "no-such-dir")
    with caplog.at_level(logging.WARNING, logger="mila.tts"):
        wav = tts.synthesize(text, "sr")
        wav_low = tts.synthesize(text, "sr", low_bandwidth=True)
    assert wav == MockTTS().synthesize(text, "sr")
    assert wav_low == MockTTS().synthesize(text, "sr", low_bandwidth=True)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1, "warn once per language"
    assert "lang=sr" in warnings[0].getMessage()
    assert "Nisi" not in warnings[0].getMessage() and "pomo" not in warnings[0].getMessage()
    assert (
        get_tts(make_test_settings(tmp_path, tts_provider="piper", piper_voice_dir=str(tmp_path))).name
        == "piper"
    )


def _install_fake_piper(monkeypatch, *, rate: int = 22050, frames: int = 2205, legacy: bool = False) -> list:
    calls: list = []

    class FakeVoice:
        def _write(self, text: str, wf: wave.Wave_write) -> None:
            calls.append(("synthesize", text))
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(rate)
            wf.writeframes(np.full(frames, 1000, dtype="<i2").tobytes())

        if legacy:
            synthesize = _write
        else:
            synthesize_wav = _write

    class FakePiperVoice:
        @staticmethod
        def load(model_path: str, config_path: str | None = None, use_cuda: bool = False) -> FakeVoice:
            calls.append(("load", model_path))
            return FakeVoice()

    module = types.ModuleType("piper")
    module.PiperVoice = FakePiperVoice  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "piper", module)
    return calls


@pytest.mark.parametrize("legacy", [False, True])
def test_piper_synthesises_with_stub_module(monkeypatch, tmp_path: Path, legacy: bool) -> None:
    calls = _install_fake_piper(monkeypatch, legacy=legacy)
    (tmp_path / "sr_RS-test-medium.onnx").write_bytes(b"")
    tts = PiperTTS(tmp_path)

    wav = tts.synthesize("Pozovi odmah.", "me")
    assert _params(wav) == (1, 2, 22050, 2205)
    low = tts.synthesize("Pozovi odmah.", "me", low_bandwidth=True)
    assert _params(low) == (1, 2, LOW_BANDWIDTH_RATE, 800)

    assert calls[0] == ("load", str(tmp_path / "sr_RS-test-medium.onnx"))
    assert calls[1:] == [("synthesize", "Pozovi odmah."), ("synthesize", "Pozovi odmah.")]
    assert sum(1 for c in calls if c[0] == "load") == 1, "voice cached per language"
