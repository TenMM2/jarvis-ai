"""Gemini text-to-speech backend — native Gemini audio output (no separate
Kokoro/Cartesia/OpenAI TTS dependency)."""

from __future__ import annotations

import io
import os
import wave
from typing import List

from openjarvis.core.registry import TTSRegistry
from openjarvis.speech.tts import TTSBackend, TTSResult

try:
    from google import genai
    from google.genai import types as genai_types
except ImportError:
    genai = None  # type: ignore[assignment]
    genai_types = None  # type: ignore[assignment]

# The 30 prebuilt voices documented for Gemini's native TTS models.
_VOICES = [
    "Zephyr", "Puck", "Charon", "Kore", "Fenrir", "Leda", "Orus", "Aoede",
    "Callirrhoe", "Autonoe", "Enceladus", "Iapetus", "Umbriel", "Algieba",
    "Despina", "Erinome", "Algenib", "Rasalgethi", "Laomedeia", "Achernar",
    "Alnilam", "Schedar", "Gacrux", "Pulcherrima", "Achird", "Zubenelgenubi",
    "Vindemiatrix", "Sadachbia", "Sadaltager", "Sulafat",
]


# Free-tier quota is tracked *per model*, so when one TTS model returns 429
# the next one usually still has requests left. Order: lightest first.
_TTS_MODEL_CHAIN = (
    "gemini-3.8-flash-lite-tts",
    "gemini-3.1-flash-tts-preview",
    "gemini-3.8-flash-tts",
)


def _is_quota_error(exc: Exception) -> bool:
    text = str(exc)
    return "429" in text or "RESOURCE_EXHAUSTED" in text


def _wav_sample_rate(wav_bytes: bytes) -> int:
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            return wf.getframerate()
    except Exception:
        return 24000


@TTSRegistry.register("gemini_tts")
class GeminiTTSBackend(TTSBackend):
    """Text-to-speech using a Gemini native-audio model."""

    backend_id = "gemini_tts"

    def __init__(self, *, api_key: str = "", model: str = "") -> None:
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get(
            "GOOGLE_API_KEY", ""
        )
        # An explicit model (arg or GEMINI_TTS_MODEL) is tried first, then the
        # rest of the chain as quota fallbacks.
        preferred = model or os.environ.get("GEMINI_TTS_MODEL", "")
        self._models = [preferred] if preferred else []
        self._models += [m for m in _TTS_MODEL_CHAIN if m != preferred]
        self._model = self._models[0]
        self._client = None
        if self._api_key and genai is not None:
            self._client = genai.Client(api_key=self._api_key)

    def synthesize(
        self,
        text: str,
        *,
        voice_id: str = "Kore",
        speed: float = 1.0,
        output_format: str = "wav",
    ) -> TTSResult:
        if self._client is None:
            raise RuntimeError("Gemini client not initialized (missing API key?)")

        voice = voice_id or "Kore"
        config = genai_types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=genai_types.SpeechConfig(
                voice_config=genai_types.VoiceConfig(
                    prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(
                        voice_name=voice
                    )
                )
            ),
        )
        last_exc: Exception | None = None
        audio_bytes = b""
        # Start from the last model that worked so a model that is out of
        # quota isn't retried (and waited on) at the start of every turn.
        order = self._models[self._models.index(self._model):] + self._models[: self._models.index(self._model)]
        for model in order:
            try:
                response = self._client.models.generate_content(
                    model=model, contents=text, config=config
                )
                part = response.candidates[0].content.parts[0]
                audio_bytes = part.inline_data.data
                self._model = model
                break
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if not _is_quota_error(exc):
                    raise
        else:
            assert last_exc is not None
            raise last_exc

        return TTSResult(
            audio=audio_bytes,
            format="wav",
            voice_id=voice,
            sample_rate=_wav_sample_rate(audio_bytes),
            metadata={"backend": "gemini_tts", "model": self._model},
        )

    def available_voices(self) -> List[str]:
        return list(_VOICES)

    def health(self) -> bool:
        return self._client is not None and bool(self._api_key)
