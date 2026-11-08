"""Versioned AgentConfig: an agent is data, one generic runtime interprets it."""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

_TEMPLATE_VAR = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")
_TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]{0,47}$")

# Variables the runtime always provides to prompts.
SYSTEM_VARIABLES: frozenset[str] = frozenset(
    {"agent_name", "current_time", "caller_number", "called_number", "call_direction"}
)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProviderChoice(_Strict):
    provider: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=128)
    params: dict[str, str | int | float | bool] = Field(default_factory=dict)


class VoiceChoice(ProviderChoice):
    voice_id: str = Field(min_length=1, max_length=128)
    speed: float = Field(default=1.0, ge=0.7, le=1.3)


class LanguageConfig(_Strict):
    code: str = Field(pattern=r"^[a-z]{2}(-[A-Z]{2})?$")
    stt: ProviderChoice | None = None
    tts: VoiceChoice | None = None
    greeting: str | None = Field(default=None, max_length=500)


class TurnConfig(_Strict):
    vad_threshold: float = Field(default=0.5, ge=0.1, le=0.95)
    min_endpointing_delay_ms: int = Field(default=300, ge=0, le=3000)
    max_endpointing_delay_ms: int = Field(default=1500, ge=100, le=6000)
    allow_interruptions: bool = True
    interruption_min_words: int = Field(default=1, ge=0, le=10)
    backchannel: bool = False
    fillers: list[str] = Field(default_factory=list, max_length=10)
    max_silence_s: int = Field(default=15, ge=3, le=120)
    max_call_duration_s: int = Field(default=900, ge=30, le=7200)

    @model_validator(mode="after")
    def _delays_ordered(self) -> TurnConfig:
        if self.max_endpointing_delay_ms < self.min_endpointing_delay_ms:
            raise ValueError("max_endpointing_delay_ms must be >= min_endpointing_delay_ms")
        return self


class BuiltinTool(_Strict):
    kind: Literal["builtin"] = "builtin"
    name: Literal["transfer_call", "end_call", "send_sms", "collect_fields"]
    config: dict[str, str | int | bool | list[str]] = Field(default_factory=dict)


def _empty_object_schema() -> dict[str, object]:
    return {"type": "object"}


class HttpTool(_Strict):
    kind: Literal["http"] = "http"
    name: str
    description: str = Field(min_length=1, max_length=1000)
    url: HttpUrl
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "POST"
    parameters_schema: dict[str, object] = Field(default_factory=_empty_object_schema)
    # Secrets are referenced by name and resolved server-side; never stored inline.
    auth_secret_ref: str | None = Field(default=None, max_length=128)
    timeout_s: float = Field(default=5.0, gt=0, le=15)

    @model_validator(mode="after")
    def _valid_name(self) -> HttpTool:
        if not _TOOL_NAME.match(self.name):
            raise ValueError("tool name must be snake_case, start with a letter, max 48 chars")
        if self.url.scheme != "https":
            raise ValueError("http tools must use https")
        return self


Tool = Annotated[BuiltinTool | HttpTool, Field(discriminator="kind")]


class VariableDef(_Strict):
    name: str = Field(pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$")
    default: str | None = None
    required: bool = False


class PolicyConfig(_Strict):
    record_calls: bool = False
    recording_disclosure: str | None = Field(default=None, max_length=500)
    retention_days: int = Field(default=30, ge=0, le=3650)
    redact_pii: bool = True

    @model_validator(mode="after")
    def _disclosure_when_recording(self) -> PolicyConfig:
        if self.record_calls and not self.recording_disclosure:
            raise ValueError("recording_disclosure is required when record_calls is true")
        return self


class PostCallConfig(_Strict):
    summary_prompt: str | None = Field(default=None, max_length=2000)
    extraction_schema: dict[str, object] | None = None
    dispositions: list[str] = Field(default_factory=list, max_length=30)


class AgentConfig(_Strict):
    name: str = Field(min_length=1, max_length=100)
    system_prompt: str = Field(min_length=1, max_length=20000)
    variables: list[VariableDef] = Field(default_factory=list, max_length=50)
    default_language: str = "en"
    languages: list[LanguageConfig] = Field(
        default_factory=lambda: [LanguageConfig(code="en")], min_length=1
    )
    stt: ProviderChoice
    llm: ProviderChoice
    tts: VoiceChoice
    turn: TurnConfig = Field(default_factory=TurnConfig)
    tools: list[Tool] = Field(default_factory=list, max_length=30)
    knowledge_collection_ids: list[str] = Field(default_factory=list, max_length=20)
    policy: PolicyConfig = Field(default_factory=PolicyConfig)
    post_call: PostCallConfig = Field(default_factory=PostCallConfig)

    @model_validator(mode="after")
    def _consistent(self) -> AgentConfig:
        codes = [lang.code for lang in self.languages]
        if len(set(codes)) != len(codes):
            raise ValueError("duplicate language codes")
        if self.default_language not in codes:
            raise ValueError("default_language must be one of languages")

        declared = {v.name for v in self.variables}
        if declared & SYSTEM_VARIABLES:
            raise ValueError("variables may not shadow system variables")
        unknown = set(_TEMPLATE_VAR.findall(self.system_prompt)) - declared - SYSTEM_VARIABLES
        if unknown:
            raise ValueError(f"prompt uses undeclared variables: {', '.join(sorted(unknown))}")

        names = [t.name for t in self.tools]
        if len(set(names)) != len(names):
            raise ValueError("duplicate tool names")
        return self


def render_prompt(template: str, values: dict[str, str]) -> str:
    """Substitute {{vars}} in one pass; substituted values are never re-scanned."""

    def repl(match: re.Match[str]) -> str:
        return values.get(match.group(1), "")

    return _TEMPLATE_VAR.sub(repl, template)
