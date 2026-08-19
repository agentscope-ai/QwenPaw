# -*- coding: utf-8 -*-
"""Capping formatters that refuse to inline oversized local media.

agentscope's chat formatters (OpenAI, Anthropic, Gemini, DashScope, …) all
read every local ``file://`` media source off disk and base64-encode the
*entire* file into the request body on every API call.  When a large file
persists in conversation history (e.g. a 42 MB generated video produced by
``send_file_to_user``) the request body balloons and the provider drops the
connection on every subsequent turn.

The model does not need such large media echoed back — it already has the
surrounding text context — so anything above a configurable byte cap is
substituted with a small text placeholder.  Capping operates purely on the
ephemeral formatted output, so persisted conversation history and UI media
rendering are unaffected.  ``max_bytes <= 0`` disables capping (everything
is inlined, matching the base formatter).

This module is the single source of truth shared by every provider; each
provider wires the matching ``_Capping<Provider>Formatter`` into its chat
model via the ``formatter=`` constructor kwarg.
"""

from __future__ import annotations

from typing import Any, ClassVar

# The capping formatters below override agentscope's ``_format_*_source``
# methods, which are ``@staticmethod`` on the base classes, with instance
# methods (they need ``self`` for the cap state).  Runtime dispatch goes
# through ``self._format_*_source(...)``, so the instance override is picked
# up and ``super()._format_*_source(source)`` calls the base static method
# correctly — but pylint flags the signature change as ``arguments-differ``.
# It is intentional, so silence it for the whole module.
# pylint: disable=arguments-differ

from agentscope.formatter import (
    AnthropicChatFormatter,
    DashScopeChatFormatter,
    GeminiChatFormatter,
    OpenAIChatFormatter,
)

from agentscope.formatter import OpenAIResponseFormatter
from agentscope.message import Base64Source, URLSource
from pydantic import Field

from ..utils.media_paths import local_media_path

# Maximum size (in bytes) of a local media file we are willing to inline as
# base64 into the model request body.  See the module docstring for the
# rationale.
MAX_INLINE_MEDIA_BYTES = 2 * 1024 * 1024  # 2 MB

_DASHSCOPE_AUDIO_FORMAT_BY_MIME = {
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
}


def inline_media_size(source: Any) -> int | None:
    """Return the byte size of *source* if it would be inlined locally.

    Returns ``None`` for remote URLs (not read from disk here) and for
    unrecognised source types so the caller leaves them untouched.
    """
    if isinstance(source, URLSource):
        return None
    if isinstance(source, Base64Source):
        # base64 length -> approximate raw byte count.
        return len(source.data or "") * 3 // 4
    return None


class CappingFormatterMixin:  # pylint: disable=too-few-public-methods
    """Pydantic mixin shared by every capping formatter.

    Holds the configurable ``max_bytes`` cap and the placeholder logic.
    Subclasses override the relevant ``_format_*_source`` methods to call
    :meth:`_maybe_cap` first and defer to ``super()`` otherwise.
    """

    max_bytes: int = Field(default=MAX_INLINE_MEDIA_BYTES, ge=0)
    relay_reasoning_content: bool = Field(default=True)

    _inline_media_size = staticmethod(inline_media_size)

    def _placeholder_text(self, kind: str, size: int) -> str:
        return (
            f"[{kind} omitted from model context: local file is "
            f"{size} bytes, exceeds inline limit of "
            f"{self.max_bytes} bytes]"
        )

    def _placeholder(self, kind: str, size: int) -> dict[str, Any]:
        """Provider-shaped text placeholder for an oversized media block.

        Default shape (``{"type": "text", "text": ...}``) matches the
        OpenAI / Anthropic / DashScope wire formats; Gemini overrides this
        to its ``{"text": ...}`` part shape.
        """
        return {"type": "text", "text": self._placeholder_text(kind, size)}

    def _maybe_cap(self, source: Any, kind: str) -> dict[str, Any] | None:
        """Return a placeholder dict if *source* exceeds the cap, else None.

        ``None`` means "no capping decision — defer to the base formatter".
        """
        if self.max_bytes <= 0:
            return None
        size = self._inline_media_size(source)
        if size is None or size <= self.max_bytes:
            return None
        return self._placeholder(kind, size)

    def _unprepared_local_placeholder(
        self,
        source: Any,
        kind: str,
    ) -> dict[str, Any] | None:
        """Reject a local URL that bypassed asynchronous preparation."""
        if not isinstance(source, URLSource):
            return None
        if local_media_path(str(source.url)) is None:
            return None
        return self._placeholder_unprepared(kind)

    def _placeholder_unprepared(self, kind: str) -> dict[str, Any]:
        """Return a provider-shaped placeholder for unprepared media."""
        return {
            "type": "text",
            "text": (
                f"[{kind} unavailable to model: local media preparation "
                "was bypassed]"
            ),
        }


class _CappingOpenAIFormatter(OpenAIChatFormatter, CappingFormatterMixin):
    """OpenAI formatter that caps oversized local image/audio media."""

    _qwenpaw_supports_reasoning_content_fallback: ClassVar[bool] = True

    def _format_image_source(
        self,
        source: URLSource | Base64Source,
    ) -> dict[str, Any]:
        capped = self._maybe_cap(source, "image")
        if capped is not None:
            return capped
        unprepared = self._unprepared_local_placeholder(source, "image")
        if unprepared is not None:
            return unprepared
        return super()._format_image_source(source)

    def _format_audio_source(
        self,
        source: URLSource | Base64Source,
    ) -> dict[str, Any]:
        capped = self._maybe_cap(source, "audio")
        if capped is not None:
            return capped
        unprepared = self._unprepared_local_placeholder(source, "audio")
        if unprepared is not None:
            return unprepared
        return super()._format_audio_source(source)


class _CappingAnthropicFormatter(
    AnthropicChatFormatter,
    CappingFormatterMixin,
):
    """Anthropic formatter that caps oversized local image media."""

    def _format_image_source(
        self,
        source: URLSource | Base64Source,
    ) -> dict[str, Any]:
        capped = self._maybe_cap(source, "image")
        if capped is not None:
            return capped
        unprepared = self._unprepared_local_placeholder(source, "image")
        if unprepared is not None:
            return unprepared
        return super()._format_image_source(source)


class _CappingGeminiFormatter(GeminiChatFormatter, CappingFormatterMixin):
    """Gemini formatter that caps oversized local media.

    Gemini handles every media kind through a single
    :meth:`_format_media_source`, and its text-part shape is ``{"text": ...}``
    (not the ``{"type": "text", ...}`` used by OpenAI/Anthropic/DashScope),
    so :meth:`_placeholder` is overridden accordingly.
    """

    def _placeholder(self, kind: str, size: int) -> dict[str, Any]:
        return {"text": self._placeholder_text(kind, size)}

    def _placeholder_unprepared(self, kind: str) -> dict[str, Any]:
        return {
            "text": (
                f"[{kind} unavailable to model: local media preparation "
                "was bypassed]"
            ),
        }

    def _format_media_source(
        self,
        source: URLSource | Base64Source,
    ) -> dict[str, Any]:
        capped = self._maybe_cap(source, "media")
        if capped is not None:
            return capped
        unprepared = self._unprepared_local_placeholder(source, "media")
        if unprepared is not None:
            return unprepared
        return super()._format_media_source(source)


class _CappingDashScopeFormatter(
    DashScopeChatFormatter,
    CappingFormatterMixin,
):
    """DashScope formatter capping oversized local image/video/audio media."""

    _qwenpaw_supports_reasoning_content_fallback: ClassVar[bool] = True

    def _format_video_source(
        self,
        source: URLSource | Base64Source,
    ) -> dict[str, Any]:
        capped = self._maybe_cap(source, "video")
        if capped is not None:
            return capped
        unprepared = self._unprepared_local_placeholder(source, "video")
        if unprepared is not None:
            return unprepared
        return super()._format_video_source(source)

    def _format_image_source(
        self,
        source: URLSource | Base64Source,
    ) -> dict[str, Any]:
        capped = self._maybe_cap(source, "image")
        if capped is not None:
            return capped
        unprepared = self._unprepared_local_placeholder(source, "image")
        if unprepared is not None:
            return unprepared
        return super()._format_image_source(source)

    def _format_audio_source(
        self,
        source: URLSource | Base64Source,
    ) -> dict[str, Any]:
        capped = self._maybe_cap(source, "audio")
        if capped is not None:
            return capped
        # Local files reach the formatter as Base64Source via the async
        # media preparation; a still-local URLSource means prep did not
        # run, and the sync formatter must not read disk to recover.
        unprepared = self._unprepared_local_placeholder(source, "audio")
        if unprepared is not None:
            return unprepared
        # TODO: Remove this workaround after AgentScope formats DashScope
        # Base64Source audio data as a data URL.
        if isinstance(source, Base64Source):
            media_type = source.media_type
            provider_format = _DASHSCOPE_AUDIO_FORMAT_BY_MIME.get(media_type)
            if provider_format is None:
                raise ValueError(
                    f"Unsupported DashScope audio MIME type: {media_type}",
                )
            return {
                "type": "input_audio",
                "input_audio": {
                    "data": (f"data:{media_type};base64,{source.data}"),
                    "format": provider_format,
                },
            }
        return super()._format_audio_source(source)


class _CappingOpenAIResponseFormatter(
    OpenAIResponseFormatter,
    CappingFormatterMixin,
):
    """OpenAI Responses API formatter that caps oversized local media."""

    def _placeholder(self, kind: str, size: int) -> dict[str, Any]:
        # Responses API uses ``input_text`` / ``output_text`` — not the
        # generic ``text`` type used by Chat Completions.  Capped media
        # almost always comes from user messages, so ``input_text`` is
        # the correct type here.
        return {
            "type": "input_text",
            "text": self._placeholder_text(kind, size),
        }

    def _placeholder_unprepared(self, kind: str) -> dict[str, Any]:
        return {
            "type": "input_text",
            "text": (
                f"[{kind} unavailable to model: local media preparation "
                "was bypassed]"
            ),
        }

    def _format_image_source(self, source: Any) -> dict[str, Any]:
        capped = self._maybe_cap(source, "image")
        if capped is not None:
            return capped
        unprepared = self._unprepared_local_placeholder(source, "image")
        if unprepared is not None:
            return unprepared
        return super()._format_image_source(source)
