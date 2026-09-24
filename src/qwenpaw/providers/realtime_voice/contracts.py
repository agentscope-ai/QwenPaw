"""Provider-layer contracts for native realtime voice sessions.

These are the vendor-neutral types a Provider implementation (e.g. DashScope)
must satisfy: session config, wire events and the ``RealtimeProviderSession``
protocol. The application-layer counterpart lives in
``qwenpaw.app.realtime_voice.contracts`` and depends on this module, never the
other way around.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RealtimeVoiceVadConfig(BaseModel):
    """Server-side turn detection settings."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["server_vad", "smart_turn"] = "server_vad"
    threshold: float = Field(default=0.5, ge=-1.0, le=1.0)
    silence_duration_ms: int = Field(default=600, ge=200, le=6000)


class RealtimeVoiceModelConfig(BaseModel):
    """User-configurable native speech-to-speech model settings."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=256)
    name: str = Field(min_length=1, max_length=256)
    region: str = Field(min_length=1, max_length=64)
    realtime_model: str = Field(min_length=1, max_length=256)
    endpoint: str | None = Field(default=None, max_length=2048)
    voice: str = Field(min_length=1, max_length=128)
    language: str = Field(min_length=1, max_length=64)
    vad: RealtimeVoiceVadConfig
    presentation_capacity: int = Field(default=32, ge=1, le=128)
    playback_timeout_seconds: int = Field(default=90, ge=10, le=300)
    max_history_turns: int = Field(default=20, ge=1, le=50)
    max_session_seconds: int = Field(ge=60, le=14400)

    @field_validator("endpoint")
    @classmethod
    def _require_secure_websocket(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        if not value.startswith("wss://"):
            raise ValueError("realtime voice endpoint must use wss://")
        return value


class MediaConfig(BaseModel):
    """Negotiated renderer media format."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    encoding: str = "pcm_s16le"
    input_sample_rate: int = Field(ge=8000, le=192000)
    output_sample_rate: int = Field(ge=8000, le=192000)
    channels: int = Field(default=1, ge=1, le=8)


class RegionOption(BaseModel):
    id: str
    label: str


class SpeechModelOption(BaseModel):
    id: str
    label: str


class EndpointOverrideInfo(BaseModel):
    scheme: str = "wss"
    optional: bool = True


class RealtimeVoiceCapabilityInfo(BaseModel):
    """Sanitized native-realtime capability exposed with ProviderInfo."""

    regions: list[RegionOption]
    vad_modes: list[str]
    speech_models: list[SpeechModelOption]
    media: MediaConfig
    endpoint_override: EndpointOverrideInfo = Field(
        default_factory=EndpointOverrideInfo,
    )
    supports_context_items: bool = True
    supports_item_deletion: bool = True
    supports_manual_response: bool = True
    supports_output_cancel: bool = True
    supports_native_tools: bool = False


class EffectiveRealtimeVoiceConfig(BaseModel):
    """Complete immutable configuration used for one native voice session."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_id: str = Field(min_length=1, max_length=128)
    model: str = Field(min_length=1, max_length=256)
    region: str = Field(min_length=1, max_length=64)
    realtime_model: str = Field(min_length=1, max_length=256)
    endpoint: str | None = Field(default=None, max_length=2048)
    voice: str = Field(min_length=1, max_length=128)
    language: str = Field(min_length=1, max_length=64)
    vad_mode: str = Field(min_length=1, max_length=64)
    vad_threshold: float = Field(ge=-1.0, le=1.0)
    vad_silence_duration_ms: int = Field(ge=200, le=6000)
    presentation_capacity: int = Field(default=32, ge=1, le=128)
    playback_timeout_seconds: int = Field(default=90, ge=10, le=300)
    max_history_turns: int = Field(ge=1, le=50)
    max_session_seconds: int = Field(ge=60, le=14400)

    @classmethod
    def from_model(
        cls,
        provider_id: str,
        model: RealtimeVoiceModelConfig,
    ) -> EffectiveRealtimeVoiceConfig:
        return cls(
            provider_id=provider_id,
            model=model.id,
            region=model.region,
            realtime_model=model.realtime_model,
            endpoint=model.endpoint,
            voice=model.voice,
            language=model.language,
            vad_mode=model.vad.mode,
            vad_threshold=model.vad.threshold,
            vad_silence_duration_ms=model.vad.silence_duration_ms,
            presentation_capacity=model.presentation_capacity,
            playback_timeout_seconds=model.playback_timeout_seconds,
            max_history_turns=model.max_history_turns,
            max_session_seconds=model.max_session_seconds,
        )


ProviderResponseOrigin = Literal["provider_auto", "application"]
ConversationRole = Literal["system", "user"]


@dataclass(frozen=True)
class RealtimeSessionConfig:
    """Application-owned speech instructions for one session."""

    instructions: str
    tools: tuple[RealtimeTool, ...] = ()


@dataclass(frozen=True)
class RealtimeTool:
    """Provider-neutral function available to the native audio model."""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class ProviderResponseResult:
    """Terminal result for one manually requested Voice response."""

    status: str
    item_ids: tuple[str, ...] = ()
    transcript: str = ""


@dataclass(frozen=True)
class ProviderEvent:
    """Provider-neutral event emitted by one native voice session.

    ``correlation_id`` identifies the same input item for speech.started,
    speech.stopped and input_transcript events, and the response for output
    events. An input terminates with input_transcript.final (including empty
    text) or input_transcript.failed; neither may silently disappear.
    ``response_origin`` is mandatory for response
    lifecycle and output events so the application can reject unsolicited
    Provider output independently of any one vendor's wire protocol.

    ``input_transcript.partial`` carries the current input item's complete
    preview in ``data["text"]``, not an append-only delta. It may shrink,
    change,
    or become empty as recognition revises tentative text.
    """

    kind: str
    event_id: str
    data: dict[str, Any] = field(default_factory=dict)
    audio: bytes | None = None
    correlation_id: str | None = None
    response_origin: ProviderResponseOrigin | None = None


class RealtimeProviderSession(Protocol):
    """Native realtime session commands required by the application."""

    async def connect(self, session: RealtimeSessionConfig) -> None: ...

    async def send_audio(self, pcm16: bytes) -> None: ...

    async def create_message(
        self,
        role: ConversationRole,
        text: str,
    ) -> str: ...

    async def request_response(self) -> ProviderResponseResult: ...

    async def complete_tool_call(
        self,
        call_id: str,
        output: dict[str, Any],
    ) -> str:
        """Acknowledge application custody of one native tool call."""
        ...

    async def delete_items(self, item_ids: Iterable[str]) -> None: ...

    async def interrupt_output(self) -> None: ...

    def events(self) -> AsyncIterator[ProviderEvent]: ...

    async def close(self) -> None: ...


ProviderFactory = Callable[
    [EffectiveRealtimeVoiceConfig, str],
    RealtimeProviderSession,
]


@dataclass(frozen=True)
class RealtimeProviderRegistration:
    """Internal native-realtime registration owned by ProviderManager."""

    provider_id: str
    models: tuple[RealtimeVoiceModelConfig, ...]
    regions: tuple[RegionOption, ...]
    vad_modes: tuple[str, ...]
    speech_models: tuple[SpeechModelOption, ...]
    media: MediaConfig
    factory: ProviderFactory
    supports_native_tools: bool = False

    def public_capability(self) -> RealtimeVoiceCapabilityInfo:
        return RealtimeVoiceCapabilityInfo(
            regions=list(self.regions),
            vad_modes=list(self.vad_modes),
            speech_models=list(self.speech_models),
            media=self.media,
            supports_native_tools=self.supports_native_tools,
        )


__all__ = [
    "ConversationRole",
    "EffectiveRealtimeVoiceConfig",
    "MediaConfig",
    "ProviderEvent",
    "ProviderResponseOrigin",
    "ProviderResponseResult",
    "RealtimeProviderRegistration",
    "RealtimeProviderSession",
    "RealtimeSessionConfig",
    "RealtimeTool",
    "RealtimeVoiceCapabilityInfo",
    "RealtimeVoiceModelConfig",
    "RealtimeVoiceVadConfig",
    "RegionOption",
    "SpeechModelOption",
]
