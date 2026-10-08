"""Gemini speech-to-text backend — transcription via Gemini's native audio
understanding (no separate Whisper/Deepgram dependency)."""

from __future__ import annotations

import os
from typing import List, Optional

from openjarvis.core.registry import SpeechRegistry
from openjarvis.speech._stubs import SpeechBackend, TranscriptionResult

try:
    from google import genai
    from google.genai import types as genai_types
except ImportError:
    genai = None  # type: ignore[assignment]
    genai_types = None  # type: ignore[assignment]

_TRANSCRIBE_PROMPT = (
    "Transcribe exactly what is said in this audio. "
    "Reply with only the transcription, no comments, no quotes."
)


@SpeechRegistry.register("gemini")
class GeminiSpeechBackend(SpeechBackend):
    """Speech-to-text using a Gemini multimodal model's native audio input."""

    backend_id = "gemini"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gemini-3.8-flash",
    ) -> None:
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get(
            "GOOGLE_API_KEY", ""
        )
        self._model = model
        self._client = None
        if self._api_key and genai is not None:
            self._client = genai.Client(api_key=self._api_key)

    def transcribe(
        self,
        audio: bytes,
        *,
        format: str = "wav",
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        if self._client is None:
            raise RuntimeError("Gemini client not initialized (missing API key?)")

        ext = format[1:] if format.startswith(".") else format
        prompt = _TRANSCRIBE_PROMPT
        if language:
            prompt += f" The spoken language is {language}."

        response = self._client.models.generate_content(
            model=self._model,
            contents=[
                prompt,
                genai_types.Part.from_bytes(data=audio, mime_type=f"audio/{ext}"),
            ],
        )

        return TranscriptionResult(
            text=(response.text or "").strip(),
            language=language,
            confidence=None,
            duration_seconds=0.0,
            segments=[],
        )

    def health(self) -> bool:
        return self._client is not None and bool(self._api_key)

    def supported_formats(self) -> List[str]:
        return ["wav", "mp3", "aiff", "aac", "ogg", "flac"]
