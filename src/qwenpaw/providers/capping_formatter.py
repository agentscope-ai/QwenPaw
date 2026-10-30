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

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, ClassVar, NamedTuple
from urllib.parse import unquote_to_bytes

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
from .adapters.cache_policy import mark_stable_prefix

# Maximum size (in bytes) of a local media file we are willing to inline as
# base64 into the model request body.  See the module docstring for the
# rationale.
MAX_INLINE_MEDIA_BYTES = 2 * 1024 * 1024  # 2 MB

# Cumulative inline media allowed in a *single* request.  The per-file cap
# alone does not bound the request body: media counts ~0 tokens, so
# token-based context eviction never fires, and a design-review session that
# accumulates ~20 MB of in-spec screenshots still trips a gateway's byte
# limit (HTTP 413) on every later turn until the history is stripped by hand
# (#7671).  Scoped per request so concurrent sessions sharing one formatter
# instance cannot spend each other's budget.
MAX_TOTAL_INLINE_MEDIA_BYTES = 8 * 1024 * 1024  # 8 MB

_DASHSCOPE_AUDIO_FORMAT_BY_MIME = {
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
}


class _MediaOccurrence(NamedTuple):
    """One media block the measuring pass saw, in wire order.

    ``folded`` marks an occurrence the formatter replaced with an
    "already shown above" placeholder before the base formatter saw it:
    it occupies a slot in the wire order but sends no payload bytes.
    """

    key: tuple[str, str, str] | None
    size: int
    folded: bool


@dataclass
class _MediaBudget:
    """Per-request inline media accounting.

    The first format pass *measures*: every media block the formatters
    touch reports its ``_MediaOccurrence`` in wire order and nothing is
    capped by the cumulative budget.  When the measured payload overflows,
    the request is formatted a second time with ``dropped_before`` set —
    the number of oldest occurrences to drop so the deduplicated payload
    of the surviving media fits the budget.

    Occurrence positions and payload bytes are accounted separately: a
    folded duplicate occupies a slot in the wire order (both passes must
    walk the same occurrence sequence) but sends no bytes, so it costs
    nothing — unless the budget dropped every earlier copy of its source
    and the surviving copy has to be re-inlined in its place.
    """

    remaining: int
    occurrences: list[_MediaOccurrence] | None = field(default=None)
    # Enforcing pass only: drop every occurrence with an index below it.
    dropped_before: int = 0
    index: int = 0

    @property
    def measuring(self) -> bool:
        """Whether this budget is in the measure-everything first pass."""
        return self.occurrences is not None


# One budget per in-flight format() call.  A ContextVar (rather than
# instance state) keeps concurrent requests on a shared formatter instance
# from observing each other's running total.
_request_media_budget: ContextVar[_MediaBudget | None] = ContextVar(
    "qwenpaw_request_media_budget",
    default=None,
)

# Per-request dedup scope for media sources: the second occurrence of a
# source within one request becomes a short text placeholder instead of
# another base64 copy.  The scope lives here, next to the per-request
# media budget, because both are request-scoped formatter policy and must
# agree on how many formatting passes a request performs.
SEEN_MEDIA_KEYS: ContextVar[set[str] | None] = ContextVar(
    "qwenpaw_formatter_seen_media_keys",
    default=None,
)


def reset_seen_media_scope() -> None:
    """Clear the active media dedup scope, if there is one.

    The per-request media budget formats a request twice (measure, then
    enforce).  Both passes must observe the same dedup scope: without a
    reset the enforcing pass sees every source as "already shown above"
    and drops all media, including the newest one the budget keeps.
    """
    seen = SEEN_MEDIA_KEYS.get()
    if seen is not None:
        seen.clear()


def _data_url_size(url: str) -> int | None:
    """Byte size of the payload carried by a ``data:`` URL.

    A ``data:`` URL is inlined verbatim into the request body, so it counts
    toward the media budget exactly like a ``Base64Source``. Non-``data:``
    URLs (remote http(s), local ``file://``) return ``None``.
    """
    if not url.startswith("data:"):
        return None
    header, separator, payload = url.partition(",")
    if not separator or not payload:
        # Malformed data URL: leave it for the provider to reject.
        return None
    if ";base64" in header:
        # base64 length -> approximate raw byte count, matching the
        # Base64Source approximation.
        return len(payload.strip()) * 3 // 4
    return len(unquote_to_bytes(payload))


def inline_media_size(source: Any) -> int | None:
    """Return the byte size of *source* if it would be inlined locally.

    Returns ``None`` for remote URLs (not read from disk here) and for
    unrecognised source types so the caller leaves them untouched.
    Inline ``data:`` URLs are sized like ``Base64Source``: their payload
    is embedded in the request body as-is.
    """
    if isinstance(source, URLSource):
        return _data_url_size(str(source.url or ""))
    if isinstance(source, Base64Source):
        data = source.data or ""
        padding = int(data.endswith("=")) + int(data.endswith("=="))
        return len(data) * 3 // 4 - padding
    return None


def media_dedup_key(source: Any) -> tuple[str, str, str] | None:
    """Return a hashable key identifying a media source's content.

    Shared by the per-request media dedup scope (the production formatter
    wrapper folds a repeated source into a short "already shown above"
    placeholder) and the per-request media budget below, so both agree on
    which occurrences carry the same payload.

    A user-uploaded image often re-appears inside ``view_image``'s
    ``ToolResultBlock.output``.  Without dedup both copies get
    base64-encoded into the wire request, doubling payload size and
    occasionally tripping gateway limits (e.g. dash_anthropic's 6 MB
    cap).  This key lets the formatter spot the second occurrence and
    swap it for a short text placeholder.
    """
    media_type = getattr(source, "media_type", "") or ""
    url = getattr(source, "url", None)
    if url is not None:
        return ("url", media_type, str(url))
    data = getattr(source, "data", "") or ""
    if data:
        # Base64 is already a canonical immutable representation here.
        # Using the string itself avoids decoding and hashing every media
        # block again on every accumulated-history request. Python caches
        # string hashes and set equality still compares the full content.
        return ("base64", media_type, data)
    return None


class CappingFormatterMixin:  # pylint: disable=too-few-public-methods
    """Pydantic mixin shared by every capping formatter.

    Holds the configurable ``max_bytes`` cap and the placeholder logic.
    Subclasses override the relevant ``_format_*_source`` methods to call
    :meth:`_maybe_cap` first and defer to ``super()`` otherwise.
    """

    max_bytes: int = Field(default=MAX_INLINE_MEDIA_BYTES, ge=0)
    max_total_bytes: int = Field(
        default=MAX_TOTAL_INLINE_MEDIA_BYTES,
        ge=0,
        description=(
            "Cumulative inline media bytes allowed in one request. Media "
            "beyond it is replaced with a text placeholder, oldest first, "
            "so the request body cannot grow without bound. 0 disables the "
            "cumulative budget (only the per-file cap applies)."
        ),
    )
    resize_images_to_max_bytes: bool = Field(default=False, exclude=True)
    relay_reasoning_content: bool = Field(default=True)
    enable_prompt_cache_breakpoint: bool = Field(default=False)

    _inline_media_size = staticmethod(inline_media_size)

    def _begin_media_budget(self) -> Any:
        """Start a measuring per-request budget; returns its reset token."""
        if self.max_bytes <= 0 or self.max_total_bytes <= 0:
            return None
        return _request_media_budget.set(
            _MediaBudget(remaining=self.max_total_bytes, occurrences=[]),
        )

    def _end_media_budget(self, token: Any) -> None:
        if token is not None:
            _request_media_budget.reset(token)

    async def _format_under_media_budget(
        self,
        format_call: Callable[[], Awaitable[list]],
    ) -> list:
        """Run one format() call under the per-request media budget.

        The first pass measures every media block and does not enforce
        the cumulative budget, so under-budget requests (the common case)
        are returned as formatted.  When the measured payload overflows,
        the request is formatted a second time, dropping the oldest
        occurrences until the deduplicated payload of the surviving media
        fits the budget — formatting walks the conversation oldest-first,
        so this keeps the *newest* media.
        """
        if self.max_bytes <= 0 or self.max_total_bytes <= 0:
            return await format_call()

        token = self._begin_media_budget()
        try:
            result = await format_call()
            budget = _request_media_budget.get()
            occurrences: list[_MediaOccurrence] = []
            if budget is not None and budget.occurrences is not None:
                occurrences = list(budget.occurrences)
        finally:
            self._end_media_budget(token)

        dropped_before = self._plan_dropped_prefix(occurrences)
        if dropped_before <= 0:
            return result

        token = _request_media_budget.set(
            _MediaBudget(
                remaining=self.max_total_bytes,
                dropped_before=dropped_before,
            ),
        )
        try:
            # The measuring pass already consumed the request's media
            # dedup scope; clear it so the enforcing pass formats the same
            # media the measuring pass measured.
            reset_seen_media_scope()
            return await format_call()
        finally:
            self._end_media_budget(token)

    def _payload_keeping_suffix(
        self,
        occurrences: list[_MediaOccurrence],
        dropped_before: int,
    ) -> int:
        """Wire payload after dropping the ``dropped_before`` oldest
        occurrences.

        Simulates the enforcing pass: occurrences before the cut are
        dropped and never reach the wire, a folded duplicate of a source
        still on the wire stays folded (it sends no bytes), and a folded
        duplicate whose every earlier copy was dropped is re-inlined —
        its occurrence slot becomes the surviving copy of that source.
        """
        seen: set[tuple[str, str, str]] = set()
        total = 0
        for index, occurrence in enumerate(occurrences):
            if index < dropped_before:
                continue
            key = occurrence.key
            if occurrence.folded and key is not None and key in seen:
                continue
            if key is not None:
                seen.add(key)
            total += occurrence.size
        return total

    def _plan_dropped_prefix(
        self,
        occurrences: list[_MediaOccurrence],
    ) -> int:
        """Return how many oldest occurrences the enforcing pass drops.

        The budget is spent on the *deduplicated* payload: a folded
        duplicate costs nothing, so media is only dropped once the
        distinct sources that actually reach the wire exceed the budget.
        The cut is the smallest prefix whose removal lets the surviving
        deduplicated payload fit — as much (newest) media as possible is
        kept.  The payload only shrinks as the cut grows, so the first
        fitting cut is the smallest.
        """
        for dropped_before in range(len(occurrences) + 1):
            if (
                self._payload_keeping_suffix(occurrences, dropped_before)
                <= self.max_total_bytes
            ):
                return dropped_before
        return len(occurrences)

    def _placeholder_text(self, kind: str, size: int) -> str:
        return (
            f"[{kind} omitted from model context: local file is "
            f"{size} bytes, exceeds inline limit of "
            f"{self.max_bytes} bytes]"
        )

    def _placeholder_total_text(self, kind: str, inlined: int) -> str:
        return (
            f"[{kind} omitted from model context: this request already "
            f"inlines {inlined} bytes of media, exceeds the "
            f"{self.max_total_bytes}-byte per-request limit]"
        )

    def _placeholder(self, kind: str, size: int) -> dict[str, Any]:
        """Provider-shaped text placeholder for an oversized media block.

        Default shape (``{"type": "text", "text": ...}``) matches the
        OpenAI / Anthropic / DashScope wire formats; Gemini overrides this
        to its ``{"text": ...}`` part shape.
        """
        return {"type": "text", "text": self._placeholder_text(kind, size)}

    def _placeholder_total(self, kind: str, inlined: int) -> dict[str, Any]:
        """Placeholder for media dropped by the cumulative budget."""
        return {
            "type": "text",
            "text": self._placeholder_total_text(kind, inlined),
        }

    def _placeholder_dropped_text(self, kind: str) -> str:
        return (
            f"[{kind} omitted from model context: this request exceeds the "
            f"{self.max_total_bytes}-byte per-request limit; the oldest "
            f"media was dropped to keep the newest]"
        )

    def _placeholder_dropped(self, kind: str) -> dict[str, Any]:
        """Placeholder for the oldest media dropped to fit the budget.

        Unlike the running-budget placeholder this one carries no byte
        count: the dropped media was never inlined, so reporting how many
        bytes the request "already inlines" would be misleading.
        """
        return {
            "type": "text",
            "text": self._placeholder_dropped_text(kind),
        }

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

    def _cap_media(self, source: Any, kind: str) -> dict[str, Any] | None:
        """Apply the per-file cap, then spend the per-request budget."""
        capped = self._maybe_cap(source, kind)
        if capped is not None:
            return capped
        return self._maybe_cap_total(source, kind)

    def _maybe_cap_total(
        self,
        source: Any,
        kind: str,
    ) -> dict[str, Any] | None:
        """Measure the media (first pass) or enforce the budget (second).

        The measuring pass records the occurrence — its dedup key, its
        size, and the fact that it *is* sent — without capping.  The
        enforcing pass replaces the planned ``dropped_before`` oldest
        occurrences with placeholders, so the budget is spent on the
        newest media.  The per-request ``remaining`` check stays as a
        backstop in case the two passes ever disagree.
        """
        budget = _request_media_budget.get()
        if budget is None:
            return None
        size = self._inline_media_size(source)
        if size is None:
            return None
        if budget.measuring:
            budget.occurrences.append(
                _MediaOccurrence(
                    key=media_dedup_key(source),
                    size=size,
                    folded=False,
                ),
            )
            return None
        index = budget.index
        budget.index += 1
        if index < budget.dropped_before:
            # This occurrence lies inside the dropped oldest prefix.
            return self._placeholder_dropped(kind)
        if size > budget.remaining:
            return self._placeholder_total(
                kind,
                self.max_total_bytes - budget.remaining,
            )
        budget.remaining -= size
        return None

    def _account_media_occurrence(
        self,
        source: Any,
        key: tuple[str, str, str] | None = None,
    ) -> None:
        """Account one media occurrence that is folded, not sent.

        A media block the formatter folds before the base formatter sees
        it — a duplicate of media already inlined into this request —
        becomes a short text placeholder: it takes a slot in the wire
        order but sends no payload bytes.  The measuring pass therefore
        records it with ``folded=True`` — payload nothing — while still
        occupying its occurrence slot, so the enforcing pass walks the
        same sequence.  A folded copy is only re-inlined when the budget
        dropped every earlier copy of its source; until then it costs
        the budget nothing.
        """
        budget = _request_media_budget.get()
        if budget is None:
            return
        size = self._inline_media_size(source)
        if size is None:
            return
        if budget.measuring:
            budget.occurrences.append(
                _MediaOccurrence(
                    key=(key if key is not None else media_dedup_key(source)),
                    size=size,
                    folded=True,
                ),
            )
        else:
            budget.index += 1

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

    async def format(self, *args: Any, **kwargs: Any) -> list:
        """Scope the media budget, then mark a stable prefix if opted in."""
        parent = super()
        result = await self._format_under_media_budget(
            lambda: parent.format(*args, **kwargs),
        )
        if self.enable_prompt_cache_breakpoint:
            return mark_stable_prefix(result, responses=False)
        return result

    def _format_file_source(
        self,
        source: URLSource | Base64Source,
        name: str | None,
    ) -> dict[str, Any]:
        """Cap PDF attachments through the same budget as other media."""
        capped = self._cap_media(source, "file")
        if capped is not None:
            return capped
        return super()._format_file_source(source, name)

    def _format_image_source(
        self,
        source: URLSource | Base64Source,
    ) -> dict[str, Any]:
        capped = self._cap_media(source, "image")
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
        capped = self._cap_media(source, "audio")
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
    """Anthropic formatter that caps oversized image and PDF media."""

    async def format(self, msgs: list) -> list:
        """Scope the media budget to this request."""
        parent = super()
        return await self._format_under_media_budget(
            lambda: parent.format(msgs),
        )

    def _format_source(
        self,
        source: URLSource | Base64Source,
        block_type: str,
    ) -> dict[str, Any]:
        capped = self._cap_media(source, block_type)
        if capped is not None:
            return capped
        unprepared = self._unprepared_local_placeholder(source, block_type)
        if unprepared is not None:
            return unprepared
        return super()._format_source(source, block_type)


class _CappingGeminiFormatter(GeminiChatFormatter, CappingFormatterMixin):
    """Gemini formatter that caps oversized local media.

    Gemini handles every media kind through a single
    :meth:`_format_media_source`, and its text-part shape is ``{"text": ...}``
    (not the ``{"type": "text", ...}`` used by OpenAI/Anthropic/DashScope),
    so :meth:`_placeholder` is overridden accordingly.
    """

    async def format(self, msgs: list) -> list:
        """Scope the media budget to this request."""
        parent = super()
        return await self._format_under_media_budget(
            lambda: parent.format(msgs),
        )

    def _placeholder(self, kind: str, size: int) -> dict[str, Any]:
        return {"text": self._placeholder_text(kind, size)}

    def _placeholder_total(self, kind: str, inlined: int) -> dict[str, Any]:
        return {"text": self._placeholder_total_text(kind, inlined)}

    def _placeholder_dropped(self, kind: str) -> dict[str, Any]:
        return {"text": self._placeholder_dropped_text(kind)}

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
        capped = self._cap_media(source, "media")
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

    async def format(self, msgs: list) -> list:
        """Scope the media budget to this request."""
        parent = super()
        return await self._format_under_media_budget(
            lambda: parent.format(msgs),
        )

    def _format_video_source(
        self,
        source: URLSource | Base64Source,
    ) -> dict[str, Any]:
        capped = self._cap_media(source, "video")
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
        capped = self._cap_media(source, "image")
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
        capped = self._cap_media(source, "audio")
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

    async def format(self, *args: Any, **kwargs: Any) -> list:
        """Scope the media budget, then apply Responses breakpoints."""
        parent = super()
        result = await self._format_under_media_budget(
            lambda: parent.format(*args, **kwargs),
        )
        if self.enable_prompt_cache_breakpoint:
            return mark_stable_prefix(result, responses=True)
        return result

    def _placeholder(self, kind: str, size: int) -> dict[str, Any]:
        # Responses API uses ``input_text`` / ``output_text`` — not the
        # generic ``text`` type used by Chat Completions.  Capped media
        # almost always comes from user messages, so ``input_text`` is
        # the correct type here.
        return {
            "type": "input_text",
            "text": self._placeholder_text(kind, size),
        }

    def _placeholder_total(self, kind: str, inlined: int) -> dict[str, Any]:
        return {
            "type": "input_text",
            "text": self._placeholder_total_text(kind, inlined),
        }

    def _placeholder_dropped(self, kind: str) -> dict[str, Any]:
        return {
            "type": "input_text",
            "text": self._placeholder_dropped_text(kind),
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
        capped = self._cap_media(source, "image")
        if capped is not None:
            return capped
        unprepared = self._unprepared_local_placeholder(source, "image")
        if unprepared is not None:
            return unprepared
        return super()._format_image_source(source)

    def _format_file_source(
        self,
        source: URLSource | Base64Source,
        name: str | None,
    ) -> dict[str, Any]:
        """Cap PDF attachments through the same budget as other media."""
        capped = self._cap_media(source, "file")
        if capped is not None:
            return capped
        return super()._format_file_source(source, name)
