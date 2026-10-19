"""Tests for app.services.stt: the MockSTT hook, WAV duration, the pure Whisper helpers and
the faster-whisper wrapper driven by a stub module (no model, no download, no network)."""

from __future__ import annotations

import math
import sys
import types
import wave
from pathlib import Path

import pytest
from conftest import make_test_settings

from app.core.types import Transcript
from app.services.stt import (
    MOCK_DEFAULT_CONFIDENCE,
    MOCK_DEFAULT_TEXT,
    STT,
    FasterWhisperSTT,
    MockSTT,
    get_stt,
    logprob_to_confidence,
    parse_mock_payload,
    restrict_language,
    wav_duration_s,
)


def _write_wav(path: Path, *, seconds: float = 0.5, rate: int = 16000) -> Path:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"\x00\x00" * int(seconds * rate))
    return path


def _write(path: Path, data: bytes) -> Path:
    path.write_bytes(data)
    return path


# --- MockSTT ----------------------------------------------------------------------------------
def test_mock_hook_returns_remainder_as_transcript(tmp_path: Path) -> None:
    path = _write(tmp_path / "q.bin", "MOCK:Koliko traje trudnoća?".encode())
    out = MockSTT().transcribe(path)
    assert out == Transcript(text="Koliko traje trudnoća?", lang="sr", confidence=1.0, duration_s=0.0)


@pytest.mark.parametrize(
    ("suffix", "expected"),
    [("en", "en"), ("hr", "hr"), ("bs", "bs"), ("cnr", "me"), ("EN", "en")],
)
def test_mock_hook_lang_suffix(tmp_path: Path, suffix: str, expected: str) -> None:
    path = _write(tmp_path / "q.bin", f"MOCK:How long is a pregnancy?|{suffix}".encode())
    out = MockSTT().transcribe(path)
    assert out.text == "How long is a pregnancy?"
    assert out.lang == expected


def test_mock_hook_unknown_suffix_falls_back_to_hint(tmp_path: Path) -> None:
    path = _write(tmp_path / "q.bin", b"MOCK:tekst|zz")
    assert MockSTT().transcribe(path, lang_hint="hr").lang == "hr"
    assert MockSTT().transcribe(path).lang == "sr"


def test_mock_hook_pipe_inside_text_is_kept() -> None:
    assert parse_mock_payload(b"MOCK:a | b|hr") == ("a | b", "hr")
    assert parse_mock_payload(b"MOCK:a|b") == ("a|b", None)
    assert parse_mock_payload(b"MOCK:  spaced  ") == ("spaced", None)


def test_mock_hook_requires_prefix_and_utf8() -> None:
    assert parse_mock_payload(b"mock:lowercase") is None
    assert parse_mock_payload(b"RIFF\x00\x00MOCK:") is None
    assert parse_mock_payload(b"MOCK:\xff\xfe") is None


@pytest.mark.parametrize("payload", [b"\xff\xfe\x00\x01binary", b"MOCK:\xff\xfe broken utf-8", b"RIFF junk"])
def test_mock_non_hook_bytes_give_fixed_sentence(tmp_path: Path, payload: bytes) -> None:
    path = _write(tmp_path / "q.bin", payload)
    out = MockSTT().transcribe(path, lang_hint="bs")
    assert out.text == MOCK_DEFAULT_TEXT
    assert out.confidence == MOCK_DEFAULT_CONFIDENCE
    assert out.lang == "bs"
    assert out.duration_s == 0.0
    assert MockSTT().transcribe(path).lang == "sr"


def test_mock_reads_duration_from_wav_header(tmp_path: Path) -> None:
    path = _write_wav(tmp_path / "q.wav", seconds=0.5, rate=16000)
    out = MockSTT().transcribe(path, lang_hint="me")
    assert out.text == MOCK_DEFAULT_TEXT
    assert out.lang == "me"
    assert out.duration_s == pytest.approx(0.5)
    assert wav_duration_s(_write_wav(tmp_path / "b.wav", seconds=2.0, rate=8000)) == pytest.approx(2.0)


def test_wav_duration_is_zero_for_non_wav_input(tmp_path: Path) -> None:
    assert wav_duration_s(_write(tmp_path / "t.bin", b"MOCK:hello")) == 0.0
    assert wav_duration_s(_write(tmp_path / "r.bin", b"RIFF" + b"\x00" * 10)) == 0.0
    assert wav_duration_s(_write(tmp_path / "e.bin", b"")) == 0.0
    assert wav_duration_s(tmp_path / "missing.wav") == 0.0


def test_mock_satisfies_protocol_and_is_default_provider(tmp_path: Path) -> None:
    stt = get_stt(make_test_settings(tmp_path))
    assert isinstance(stt, MockSTT)
    assert isinstance(stt, STT)


# --- pure helpers -----------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("detected", "hint", "expected"),
    [
        ("sr", None, "sr"),
        ("bs", None, "bs"),
        ("hr", None, "hr"),
        ("en", None, "en"),
        ("me", None, "sr"),
        ("cnr", None, "sr"),
        ("EN-us", None, "en"),
        ("de", None, "sr"),
        ("mk", "hr", "hr"),
        ("mk", "me", "sr"),
        ("mk", "xx", "sr"),
        (None, "bs", "bs"),
        (None, None, "sr"),
        ("", "", "sr"),
    ],
)
def test_restrict_language(detected: str | None, hint: str | None, expected: str) -> None:
    assert restrict_language(detected, hint) == expected


@pytest.mark.parametrize(
    ("logprob", "expected"),
    [(0.0, 1.0), (0.3, 1.0), (-0.5, math.exp(-0.5)), (-1.0, math.exp(-1.0)), (-50.0, math.exp(-50.0))],
)
def test_logprob_to_confidence_values(logprob: float, expected: float) -> None:
    assert logprob_to_confidence(logprob) == pytest.approx(expected)


def test_logprob_to_confidence_bounds_and_monotonic() -> None:
    assert logprob_to_confidence(float("-inf")) == 0.0
    assert logprob_to_confidence(float("nan")) == 0.0
    assert logprob_to_confidence(float("inf")) == 0.0
    values = [logprob_to_confidence(x / 10) for x in range(-30, 1)]
    assert values == sorted(values)
    assert all(0.0 <= v <= 1.0 for v in values)


# --- FasterWhisperSTT against a stub `faster_whisper` module ---------------------------------
class _Seg:
    def __init__(self, text: str, avg_logprob: float, start: float, end: float) -> None:
        self.text = text
        self.avg_logprob = avg_logprob
        self.start = start
        self.end = end


class _Info:
    def __init__(self, language: str, duration: float) -> None:
        self.language = language
        self.language_probability = 0.9
        self.duration = duration


def _install_fake_whisper(monkeypatch, *, detected: str, segments: list[_Seg], duration: float = 1.5) -> list:
    """Put a fake `faster_whisper` module in sys.modules and return the list of recorded calls."""
    calls: list[dict] = []

    class FakeWhisperModel:
        def __init__(self, model_size_or_path: str, device: str = "auto", compute_type: str = "default"):
            calls.append({"init": (model_size_or_path, device, compute_type)})

        def transcribe(self, audio: str, language: str | None = None, **_: object):
            calls.append({"audio": audio, "language": language})
            return iter(segments), _Info(language or detected, duration)

    module = types.ModuleType("faster_whisper")
    module.WhisperModel = FakeWhisperModel  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "faster_whisper", module)
    return calls


def test_faster_whisper_forces_hint_and_maps_me_to_sr(monkeypatch, tmp_path: Path) -> None:
    segments = [_Seg(" Koje metode ", -0.2, 0.0, 1.0), _Seg("kontracepcije postoje? ", -0.6, 1.0, 3.0)]
    calls = _install_fake_whisper(monkeypatch, detected="sr", segments=segments)
    path = _write_wav(tmp_path / "q.wav")

    stt = FasterWhisperSTT("large-v3")
    out = stt.transcribe(path, lang_hint="me")

    assert calls[0]["init"] == ("large-v3", "auto", "int8")
    assert [c["language"] for c in calls[1:]] == ["sr"]
    assert calls[1]["audio"] == str(path)
    assert out.text == "Koje metode kontracepcije postoje?"
    assert out.lang == "sr"
    assert out.duration_s == 1.5
    # duration-weighted mean of the log-probs: (-0.2 * 1 + -0.6 * 2) / 3
    assert out.confidence == pytest.approx(logprob_to_confidence(-1.4 / 3))
    assert not any(isinstance(v, (Path, bytes)) for v in vars(stt).values()), "must not keep audio"


def test_faster_whisper_redecodes_when_detection_is_outside_the_set(monkeypatch, tmp_path: Path) -> None:
    calls = _install_fake_whisper(monkeypatch, detected="mk", segments=[_Seg("tekst", -0.3, 0.0, 1.0)])
    out = FasterWhisperSTT("small").transcribe(_write_wav(tmp_path / "q.wav"))
    assert [c["language"] for c in calls[1:]] == [None, "sr"]
    assert out.lang == "sr"
    assert out.text == "tekst"


def test_faster_whisper_keeps_supported_detection(monkeypatch, tmp_path: Path) -> None:
    calls = _install_fake_whisper(monkeypatch, detected="hr", segments=[_Seg("tekst", 0.0, 0.0, 1.0)])
    out = FasterWhisperSTT("small").transcribe(_write_wav(tmp_path / "q.wav"))
    assert [c["language"] for c in calls[1:]] == [None]
    assert out.lang == "hr"
    assert out.confidence == 1.0


def test_faster_whisper_silence_gives_empty_text_and_header_duration(monkeypatch, tmp_path: Path) -> None:
    _install_fake_whisper(monkeypatch, detected="sr", segments=[], duration=0.0)
    out = FasterWhisperSTT("small").transcribe(_write_wav(tmp_path / "q.wav", seconds=0.25))
    assert out.text == ""
    assert out.confidence == 0.0
    assert out.duration_s == pytest.approx(0.25)


def test_get_stt_builds_faster_whisper_from_settings(monkeypatch, tmp_path: Path) -> None:
    calls = _install_fake_whisper(monkeypatch, detected="sr", segments=[])
    stt = get_stt(make_test_settings(tmp_path, stt_provider="faster_whisper", stt_model="medium"))
    assert isinstance(stt, FasterWhisperSTT)
    assert isinstance(stt, STT)
    assert calls == [{"init": ("medium", "auto", "int8")}]
