"""Curated model choices offered in the dashboard, with what we have actually measured.

Notes come from our own measurements (warm time-to-first-token / first-byte from India South via
LiveKit Inference, small samples) and are guidance, not guarantees. The runtime still validates a
model id against the live provider catalog before a call starts.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelOption:
    provider: str
    model: str
    label: str
    note: str = ""

    @property
    def id(self) -> str:
        return f"{self.provider}/{self.model}"


STT: tuple[ModelOption, ...] = (
    ModelOption("deepgram", "nova-3", "Deepgram Nova 3", "Default; accurate streaming English."),
    ModelOption(
        "deepgram", "nova-2-phonecall", "Deepgram Nova 2 (phone calls)", "Tuned for 8 kHz."
    ),
    ModelOption("assemblyai", "universal-streaming", "AssemblyAI Universal Streaming"),
    ModelOption("cartesia", "ink-whisper", "Cartesia Ink Whisper"),
)

LLM: tuple[ModelOption, ...] = (
    ModelOption("google", "gemini-2.5-flash", "Gemini 2.5 Flash", "Fast: about 480 ms median."),
    ModelOption("google", "gemini-2.5-flash-lite", "Gemini 2.5 Flash-Lite", "About 480 ms median."),
    ModelOption("openai", "gpt-4.1-mini", "GPT-4.1 mini", "About 790 ms median."),
    ModelOption("openai", "gpt-4o-mini", "GPT-4o mini", "About 850 ms median."),
)

TTS: tuple[ModelOption, ...] = (
    ModelOption(
        "cartesia", "sonic-turbo", "Cartesia Sonic Turbo", "Recommended: about 150 ms lead-in."
    ),
    ModelOption(
        "cartesia", "sonic-3", "Cartesia Sonic 3", "Natural, but 300-500 ms of leading silence."
    ),
    ModelOption("deepgram", "aura-2", "Deepgram Aura 2"),
    ModelOption("rime", "mistv2", "Rime Mist v2"),
)

DEFAULT_VOICE_ID = "f786b574-daa5-4673-aa0c-cbe3e8534c02"  # Cartesia voice used in dev
