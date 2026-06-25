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

import base64
import os
from typing import Any
from urllib.parse import urlparse
from urllib.request import url2pathname

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
from agentscope.message import Base64Source, URLSource
from pydantic import Field

# Maximum size (in bytes) of a local media file we are willing to inline as
# base64 into the model request body.  See the module docstring for the
# rationale.
MAX_INLINE_MEDIA_BYTES = 2 * 1024 * 1024  # 2 MB


def inline_media_size(source: Any) -> int | None:
    """Return the byte size of *source* if it would be inlined locally.

    Returns ``None`` for remote URLs (not read from disk here) and for
    unrecognised source types so the caller leaves them untouched.
    """
    if isinstance(source, URLSource):
        url = str(source.url)
        if url.startswith("file://"):
            path = url2pathname(urlparse(url).path)
            try:
                return os.path.getsize(path)
            except OSError:
                return None
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

    @staticmethod
    def _inline_media_size(source: Any) -> int | None:
        """Byte size of *source* if inlined locally, else ``None``.

        Thin wrapper over :func:`inline_media_size` kept as a staticmethod
        so callers (and tests) can invoke it on the class.
        """
        return inline_media_size(source)

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

    @staticmethod
    def _local_source_to_base64(source: Any) -> Any:
        """Convert a local ``file://`` URLSource to a Base64Source.

        Non-local sources (remote URLs, already-base64 sources, anything
        else) are returned unchanged so the base formatter handles them as
        before.
        """
        if not isinstance(source, URLSource):
            return source
        url = str(source.url)
        if not url.startswith("file://"):
            return source
        path = url2pathname(urlparse(url).path)
        with open(path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")
        return Base64Source(data=encoded, media_type=source.media_type)


class _CappingOpenAIFormatter(OpenAIChatFormatter, CappingFormatterMixin):
    """OpenAI formatter that caps oversized local image/audio media."""

    def _format_image_source(self, source: Any) -> dict[str, Any]:
        capped = self._maybe_cap(source, "image")
        if capped is not None:
            return capped
        return super()._format_image_source(
            self._local_source_to_base64(source),
        )

    def _format_audio_source(self, source: Any) -> dict[str, Any]:
        capped = self._maybe_cap(source, "audio")
        if capped is not None:
            return capped
        return super()._format_audio_source(
            self._local_source_to_base64(source),
        )


class _CappingAnthropicFormatter(
    AnthropicChatFormatter,
    CappingFormatterMixin,
):
    """Anthropic formatter that caps oversized local image media."""

    def _format_image_source(self, source: Any) -> dict[str, Any]:
        capped = self._maybe_cap(source, "image")
        if capped is not None:
            return capped
        return super()._format_image_source(
            self._local_source_to_base64(source),
        )


class _CappingGeminiFormatter(GeminiChatFormatter, CappingFormatterMixin):
    """Gemini formatter that caps oversized local media.

    Gemini handles every media kind through a single
    :meth:`_format_media_source`, and its text-part shape is ``{"text": ...}``
    (not the ``{"type": "text", ...}`` used by OpenAI/Anthropic/DashScope),
    so :meth:`_placeholder` is overridden accordingly.
    """

    def _placeholder(self, kind: str, size: int) -> dict[str, Any]:
        return {"text": self._placeholder_text(kind, size)}

    def _format_media_source(self, source: Any) -> dict[str, Any]:
        capped = self._maybe_cap(source, "media")
        if capped is not None:
            return capped
        return super()._format_media_source(
            self._local_source_to_base64(source),
        )


class _CappingDashScopeFormatter(
    DashScopeChatFormatter,
    CappingFormatterMixin,
):
    """DashScope formatter capping oversized local image/video/audio media."""

    def _format_video_source(self, source: Any) -> dict[str, Any]:
        capped = self._maybe_cap(source, "video")
        if capped is not None:
            return capped
        return super()._format_video_source(
            self._local_source_to_base64(source),
        )

    def _format_image_source(self, source: Any) -> dict[str, Any]:
        capped = self._maybe_cap(source, "image")
        if capped is not None:
            return capped
        return super()._format_image_source(
            self._local_source_to_base64(source),
        )

    def _format_audio_source(self, source: Any) -> dict[str, Any]:
        capped = self._maybe_cap(source, "audio")
        if capped is not None:
            return capped
        return super()._format_audio_source(
            self._local_source_to_base64(source),
        )
