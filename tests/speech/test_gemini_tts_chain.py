"""Gemini TTS falls through its model chain on free-tier quota errors."""

from __future__ import annotations

import io
import wave
from types import SimpleNamespace

import pytest

from openjarvis.speech import gemini_tts
from openjarvis.speech.gemini_tts import GeminiTTSBackend


def _wav() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24000)
        wf.writeframes(b"\x00\x00" * 100)
    return buf.getvalue()


class _FakeModels:
    def __init__(self, failing: dict[str, str]) -> None:
        self.failing = failing
        self.calls: list[str] = []

    def generate_content(self, *, model, contents, config):
        self.calls.append(model)
        if model in self.failing:
            raise RuntimeError(self.failing[model])
        part = SimpleNamespace(inline_data=SimpleNamespace(data=_wav()))
        return SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))])


def _backend(monkeypatch, failing):
    monkeypatch.setattr(gemini_tts, "genai", SimpleNamespace(Client=lambda api_key: None))
    b = GeminiTTSBackend(api_key="k")
    b._client = SimpleNamespace(models=_FakeModels(failing))
    return b


def test_quota_error_falls_through_to_next_model(monkeypatch):
    first, second = gemini_tts._TTS_MODEL_CHAIN[:2]
    b = _backend(monkeypatch, {first: "429 RESOURCE_EXHAUSTED"})
    result = b.synthesize("hola")
    assert b._client.models.calls == [first, second]
    assert result.metadata["model"] == second


def test_next_call_skips_the_exhausted_model(monkeypatch):
    first, second = gemini_tts._TTS_MODEL_CHAIN[:2]
    b = _backend(monkeypatch, {first: "429 RESOURCE_EXHAUSTED"})
    b.synthesize("uno")
    b._client.models.calls.clear()
    b.synthesize("dos")
    assert b._client.models.calls == [second]


def test_non_quota_error_is_not_swallowed(monkeypatch):
    b = _backend(monkeypatch, {gemini_tts._TTS_MODEL_CHAIN[0]: "400 invalid argument"})
    with pytest.raises(RuntimeError, match="400"):
        b.synthesize("hola")
    assert len(b._client.models.calls) == 1


def test_all_models_exhausted_raises_last_error(monkeypatch):
    b = _backend(monkeypatch, {m: "429 RESOURCE_EXHAUSTED" for m in gemini_tts._TTS_MODEL_CHAIN})
    with pytest.raises(RuntimeError, match="429"):
        b.synthesize("hola")
    assert len(b._client.models.calls) == len(gemini_tts._TTS_MODEL_CHAIN)
