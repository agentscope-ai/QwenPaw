# -*- coding: utf-8 -*-
"""Factory for creating chat models and formatters.

This module provides a unified factory for creating chat model instances
and their corresponding formatters based on configuration.

Example:
    >>> from qwenpaw.agents.model_factory import create_model_and_formatter
    >>> model, formatter = create_model_and_formatter()
"""

import asyncio
import base64
from collections import defaultdict, deque
import hashlib
import logging
import os
import re
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import List, Sequence, Tuple, Type, Any, Union, Optional
from urllib.parse import urlparse

import httpx
from agentscope.formatter import (
    DashScopeChatFormatter,
    FormatterBase,
    OpenAIChatFormatter,
)
from agentscope.message import Base64Source, TextBlock
from agentscope.model import ChatModelBase

try:
    from agentscope.formatter import AnthropicChatFormatter
except ImportError:
    AnthropicChatFormatter = None

try:
    from agentscope.formatter import GeminiChatFormatter
except ImportError:
    GeminiChatFormatter = None

from agentscope.formatter import OpenAIResponseFormatter

from .utils.message_request_normalizer import (
    normalize_messages_for_model_request,
)
from ..exceptions import ProviderError, ModelFormatterError
from ..providers import ProviderManager
from ..providers.capping_formatter import MAX_INLINE_MEDIA_BYTES
from ..utils.tool_call_extra import tool_call_extras_for_provider
from ..providers.retry_chat_model import (
    RetryChatModel,
    RetryConfig,
    RateLimitConfig,
)
from ..token_usage import TokenRecordingModelWrapper
from ..utils.io_utils import run_sync_io
from ..utils.logging import sanitize_log_value
from ..utils.media_paths import (
    file_url_to_path as _file_url_to_path,
    local_media_path as _local_media_path,
)

# TODO(AgentScope compatibility): This is a temporary workaround for
# AgentScope releases that emit random promoted-media identifiers. Remove it
# once QwenPaw's minimum AgentScope version provides stable, request-unique
# identifiers; QwenPaw should then preserve the upstream identifiers.
_PROMOTED_TOOL_MEDIA_LABEL = re.compile(r"^-\s+([^\s]+)\s+\(")


def _stabilize_promoted_tool_result_media_identifiers(
    text: str,
    promoted: Sequence[Any],
) -> tuple[str, Sequence[Any]]:
    """Replace formatter-generated media labels with stable identifiers."""
    rewritten = list(promoted)
    for index, item in enumerate(rewritten[:-1]):
        if not isinstance(item, TextBlock):
            continue
        match = _PROMOTED_TOOL_MEDIA_LABEL.match(item.text)
        source = getattr(rewritten[index + 1], "source", None)
        if match is None or source is None:
            continue
        old = match.group(1)
        media_type = str(getattr(source, "media_type", "") or "")
        value = str(
            getattr(source, "url", None)
            or getattr(source, "data", None)
            or getattr(source, "path", None)
            or "",
        )
        digest = hashlib.sha256(
            f"{index}\0{media_type}\0{value}".encode("utf-8"),
        ).hexdigest()[:12]
        stable = f"qwenpaw-media-{digest}"
        text = text.replace(f"[{old}]", f"[{stable}]")
        rewritten[index] = TextBlock(text=item.text.replace(old, stable))
    return text, rewritten


logger = logging.getLogger(__name__)

_SUPPORTED_IMAGE_EXTENSIONS: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


@dataclass(frozen=True)
class _LocalMediaRead:
    """Result of reading one local media file in a worker thread."""

    exists: bool
    size: int
    encoded: str | None
    # False when only "larger than the limit" is known (bounded remote
    # download aborted mid-stream), so messages must not quote `size`.
    size_known: bool = True


_FORMATTER_SEEN_MEDIA_KEYS: ContextVar[set[str] | None] = ContextVar(
    "qwenpaw_formatter_seen_media_keys",
    default=None,
)


def _read_local_media(
    path: str,
    max_bytes: int = MAX_INLINE_MEDIA_BYTES,
) -> _LocalMediaRead:
    """Inspect and, when allowed, encode a local file synchronously."""
    try:
        size = os.path.getsize(path)
        if not os.path.isfile(path):
            return _LocalMediaRead(False, 0, None)
    except OSError:
        return _LocalMediaRead(False, 0, None)

    if 0 < max_bytes < size:
        return _LocalMediaRead(True, size, None)

    try:
        with open(path, "rb") as handle:
            encoded = base64.b64encode(handle.read()).decode("utf-8")
    except OSError:
        return _LocalMediaRead(False, 0, None)
    return _LocalMediaRead(True, size, encoded)


@dataclass(frozen=True)
class _MediaReference:
    """One mutable message-list slot containing a URL-backed media block."""

    items: list
    index: int
    block: Any
    source: Any
    kind: str


def _media_source_value(source: Any, key: str, default: Any = None) -> Any:
    """Read one media source field from a dict or Pydantic model."""
    if isinstance(source, dict):
        return source.get(key, default)
    return getattr(source, key, default)


def _media_kind(block: Any) -> str | None:
    """Return the logical media kind represented by a content block."""
    block_type = (
        block.get("type")
        if isinstance(block, dict)
        else getattr(block, "type", None)
    )
    if block_type in _MEDIA_BLOCK_TYPES:
        return block_type
    if block_type != "data":
        return None
    source = (
        block.get("source")
        if isinstance(block, dict)
        else getattr(block, "source", None)
    )
    media_type = str(_media_source_value(source, "media_type", "") or "")
    kind = media_type.split("/", 1)[0]
    return kind if kind in _MEDIA_BLOCK_TYPES else None


def _collect_media_references(
    items: list,
    references: list[_MediaReference],
    *,
    include_hint_videos: bool = False,
    inside_hint: bool = False,
) -> None:
    """Collect URL-backed media from messages and nested result blocks."""
    for index, block in enumerate(items):
        kind = _media_kind(block)
        source = (
            block.get("source")
            if isinstance(block, dict)
            else getattr(block, "source", None)
        )
        source_type = _media_source_value(source, "type")
        url = str(_media_source_value(source, "url", "") or "")
        if kind is None or source_type != "url" or not url:
            is_url_source = False
        else:
            is_url_source = (
                kind != "video" or not inside_hint or include_hint_videos
            )
        if is_url_source:
            assert kind is not None
            references.append(
                _MediaReference(items, index, block, source, kind),
            )

        block_type = (
            block.get("type")
            if isinstance(block, dict)
            else getattr(block, "type", None)
        )
        nested = None
        if block_type == "tool_result":
            nested = (
                block.get("output")
                if isinstance(block, dict)
                else getattr(block, "output", None)
            )
        elif block_type == "hint":
            nested = (
                block.get("hint")
                if isinstance(block, dict)
                else getattr(block, "hint", None)
            )
        if isinstance(nested, list):
            _collect_media_references(
                nested,
                references,
                include_hint_videos=include_hint_videos,
                inside_hint=block_type == "hint",
            )


def _remote_media_requires_download(
    kind: str,
    base_formatter_class: Type[FormatterBase],
) -> bool:
    """Whether the upstream formatter would synchronously download a URL."""
    if AnthropicChatFormatter is not None and issubclass(
        base_formatter_class,
        AnthropicChatFormatter,
    ):
        return kind == "image"
    if GeminiChatFormatter is not None and issubclass(
        base_formatter_class,
        GeminiChatFormatter,
    ):
        return True
    if issubclass(base_formatter_class, DashScopeChatFormatter):
        return False
    return kind == "audio" and issubclass(
        base_formatter_class,
        (OpenAIChatFormatter, OpenAIResponseFormatter),
    )


async def _download_remote_media(
    url: str,
    max_bytes: int,
) -> _LocalMediaRead:
    """Download bounded remote media without blocking the event loop.

    Failures resolve to a placeholder result instead of raising: a dead
    media URL in history is a content problem, not a model failure.
    Letting the error propagate would be misclassified by the model
    error policy (404 -> model_not_found) and burn the whole fallback
    chain on every turn, so this mirrors ``_read_local_media``, which
    degrades unreadable files the same way.
    """
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=30.0,
        ) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                content_length = response.headers.get("content-length")
                try:
                    reported_size = int(content_length or "")
                except ValueError:
                    reported_size = 0
                if 0 < max_bytes < reported_size:
                    return _LocalMediaRead(True, reported_size, None)

                content = bytearray()
                async for chunk in response.aiter_bytes(
                    chunk_size=64 * 1024,
                ):
                    if 0 < max_bytes:
                        remaining = max_bytes - len(content)
                        if len(chunk) > remaining:
                            return _LocalMediaRead(
                                True,
                                max_bytes + 1,
                                None,
                                size_known=False,
                            )
                    content.extend(chunk)
    except (httpx.HTTPError, OSError) as exc:
        logger.warning(
            "Remote media download failed for %s: %s",
            sanitize_log_value(url),
            exc,
        )
        return _LocalMediaRead(False, 0, None)

    data = bytes(content)
    encoded = await run_sync_io(_encode_media_bytes, data)
    return _LocalMediaRead(True, len(data), encoded)


def _encode_media_bytes(data: bytes) -> str:
    """Encode downloaded media away from the application event loop."""
    return base64.b64encode(data).decode("utf-8")


def _prepared_media_type(
    reference: _MediaReference,
    url: str,
    base_formatter_class: Type[FormatterBase],
) -> str:
    """Return the media type expected by the downstream formatter."""
    media_type = str(
        _media_source_value(reference.source, "media_type", "") or "",
    )
    if reference.kind != "audio" or issubclass(
        base_formatter_class,
        DashScopeChatFormatter,
    ):
        return media_type
    extension = urlparse(url).path.rsplit(".", 1)[-1].lower()
    if extension in ("mp3", "wav"):
        return f"audio/{extension}"
    return media_type


def _replace_media_reference(
    reference: _MediaReference,
    prepared: _LocalMediaRead,
    url: str,
    base_formatter_class: Type[FormatterBase],
    *,
    local: bool,
    max_bytes: int,
) -> None:
    """Commit prepared media data into a copied request message."""
    if not prepared.exists:
        detail = "file deleted from disk" if local else "download failed"
        reference.items[reference.index] = TextBlock(
            type="text",
            text=f"[{reference.kind.title()} unavailable - {detail}]",
        )
        return
    if 0 < max_bytes < prepared.size:
        source = "local file" if local else "remote media"
        if prepared.size_known:
            detail = (
                f"is {prepared.size} bytes, exceeds inline limit of "
                f"{max_bytes} bytes"
            )
        else:
            detail = f"exceeds inline limit of {max_bytes} bytes"
        reference.items[reference.index] = TextBlock(
            type="text",
            text=(
                f"[{reference.kind} omitted from model context: {source} "
                f"{detail}]"
            ),
        )
        return
    if prepared.encoded is None:
        return

    media_type = _prepared_media_type(
        reference,
        url,
        base_formatter_class,
    )
    if isinstance(reference.block, dict):
        reference.block["source"] = {
            "type": "base64",
            "data": prepared.encoded,
            "media_type": media_type,
        }
    else:
        reference.block.source = Base64Source(
            data=prepared.encoded,
            media_type=media_type,
        )


async def _prepare_media_sources(
    msgs: list,
    base_formatter_class: Type[FormatterBase],
    *,
    include_hint_videos: bool = False,
    max_bytes: int = MAX_INLINE_MEDIA_BYTES,
) -> None:
    """Prepare media so downstream formatting performs no blocking I/O."""
    references: list[_MediaReference] = []
    for msg in msgs:
        content = getattr(msg, "content", None)
        if isinstance(content, list):
            _collect_media_references(
                content,
                references,
                include_hint_videos=include_hint_videos,
            )

    pending: dict[tuple[str, str], asyncio.Task[_LocalMediaRead]] = {}
    prepared_keys: list[tuple[str, str] | None] = []
    for reference in references:
        url = str(_media_source_value(reference.source, "url", "") or "")
        local_path = _local_media_path(url)
        key: tuple[str, str] | None = None
        if local_path is not None:
            key = ("local", os.path.normcase(os.path.normpath(local_path)))
            if key not in pending:
                pending[key] = asyncio.create_task(
                    run_sync_io(
                        _read_local_media,
                        local_path,
                        max_bytes,
                    ),
                )
            prepared_keys.append(key)
            continue

        parsed = urlparse(url)
        if parsed.scheme in ("http", "https") and (
            _remote_media_requires_download(
                reference.kind,
                base_formatter_class,
            )
        ):
            key = ("remote", url)
            if key not in pending:
                pending[key] = asyncio.create_task(
                    _download_remote_media(url, max_bytes),
                )
            prepared_keys.append(key)
            continue
        prepared_keys.append(None)

    if pending:
        # Preparation tasks resolve failures to placeholder results, so
        # none should raise; return_exceptions keeps one unexpected
        # error from abandoning the sibling downloads mid-flight.
        await asyncio.gather(*pending.values(), return_exceptions=True)

    for reference, key in zip(references, prepared_keys):
        if key is None:
            continue
        url = str(_media_source_value(reference.source, "url", "") or "")
        _replace_media_reference(
            reference,
            _prepared_task_result(pending[key]),
            url,
            base_formatter_class,
            local=key[0] == "local",
            max_bytes=max_bytes,
        )


def _prepared_task_result(
    task: "asyncio.Task[_LocalMediaRead]",
) -> _LocalMediaRead:
    """Return the task's media result, degrading failures to missing."""
    if task.cancelled() or task.exception() is not None:
        return _LocalMediaRead(False, 0, None)
    return task.result()


def _supports_multimodal_for_current_model() -> bool:
    """Best-effort lookup of current model multimodal support."""
    try:
        from .prompt import get_active_model_supports_multimodal

        return get_active_model_supports_multimodal()
    except Exception:  # pragma: no cover - config lookup safety
        logger.debug(
            "Falling back to multimodal=True during request-time "
            "message normalization",
            exc_info=True,
        )
        return True


def _normalize_messages_for_formatter(
    msgs: list,
    base_formatter_class: Type[FormatterBase],
    formatter_instance: FormatterBase | None = None,
) -> tuple[list, bool, bool, bool]:
    """Return normalized messages and formatter-family flags.

    The returned booleans are
    ``(is_anthropic_formatter, is_gemini_formatter,
    is_response_formatter)``.
    All formatters receive a copied, normalized message list so
    request-time repair does not mutate stored history.
    """
    is_anthropic_formatter = AnthropicChatFormatter is not None and (
        issubclass(base_formatter_class, AnthropicChatFormatter)
    )
    is_gemini_formatter = GeminiChatFormatter is not None and (
        issubclass(base_formatter_class, GeminiChatFormatter)
    )
    is_response_formatter = issubclass(
        base_formatter_class,
        OpenAIResponseFormatter,
    )
    supports_multimodal = _supports_multimodal_for_current_model()
    if getattr(formatter_instance, "_qwenpaw_force_strip_media", False):
        supports_multimodal = False
    strip_audio = bool(
        getattr(formatter_instance, "_qwenpaw_force_strip_audio", False),
    )

    if is_anthropic_formatter:
        target_family = "anthropic"
    elif is_gemini_formatter:
        target_family = "gemini"
    else:
        target_family = "openai"

    normalized_msgs = normalize_messages_for_model_request(
        msgs,
        supports_multimodal=supports_multimodal,
        target_family=target_family,
        strip_audio=strip_audio,
    )

    return (
        normalized_msgs,
        is_anthropic_formatter,
        is_gemini_formatter,
        is_response_formatter,
    )


def _anthropic_media_dedup_key(
    source: Any,
) -> tuple[str, str, str] | None:
    """Return a hashable key identifying a media source for dedup.

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


_WIRE_MEDIA_BLOCK_TYPES = frozenset(
    {
        "audio",
        "image",
        "image_url",
        "input_audio",
        "input_image",
        "input_video",
        "video",
        "video_url",
    },
)
_WIRE_MEDIA_CONTAINER_KEYS = frozenset({"file_data", "inline_data"})
_WIRE_AUDIO_BLOCK_TYPES = frozenset({"audio", "input_audio"})


def _count_wire_media_blocks(value: Any) -> int:
    """Count provider-formatted media blocks in a nested payload."""
    if isinstance(value, list):
        return sum(_count_wire_media_blocks(item) for item in value)
    if not isinstance(value, dict):
        return 0

    if value.get("type") in _WIRE_MEDIA_BLOCK_TYPES:
        return 1
    if any(key in value for key in _WIRE_MEDIA_CONTAINER_KEYS):
        return 1
    return sum(_count_wire_media_blocks(item) for item in value.values())


def _count_wire_audio_blocks(value: Any) -> int:
    """Count provider-formatted audio blocks in a nested payload."""
    if isinstance(value, list):
        return sum(_count_wire_audio_blocks(item) for item in value)
    if not isinstance(value, dict):
        return 0

    if value.get("type") in _WIRE_AUDIO_BLOCK_TYPES:
        return 1
    media_type = value.get("mime_type") or value.get("media_type")
    if isinstance(media_type, str) and media_type.startswith("audio/"):
        return 1
    return sum(_count_wire_audio_blocks(item) for item in value.values())


def _video_oversize_placeholder(
    size: int,
    *,
    response_api: bool = False,
) -> dict:
    """Text placeholder substituted for a video that exceeds
    the inline cap.

    Mirrors the wording used by ``capping_formatter``'s
    ``CappingFormatterMixin._placeholder_text`` so
    oversized-video messages are consistent across every
    provider path.  Tool-result videos inline through these
    helpers bypass the capping formatters (which only see
    ``_format_*_source``), so the cap is enforced here
    instead.

    When *response_api* is True the block uses
    ``input_text`` instead of ``text``, matching the
    Responses API content-type convention.
    """
    txt_type = "input_text" if response_api else "text"
    return {
        "type": txt_type,
        "text": (
            "[video omitted from model context: "
            f"local file is {size} bytes, exceeds "
            f"inline limit of {MAX_INLINE_MEDIA_BYTES}"
            " bytes]"
        ),
    }


def _format_anthropic_video_data_block(block: Any) -> dict | None:
    """Format a 2.0 ``DataBlock`` of video media for Anthropic-compatible APIs.

    agentscope's stock Anthropic formatter drops every non-image
    ``DataBlock``; this helper keeps video support so third-party
    Anthropic-compatible providers that DO accept video keep working.

    Returns the wire dict, or ``None`` if the source is unusable
    (missing file, unsupported extension, exotic scheme).
    """
    # pylint: disable=too-many-branches,too-many-return-statements
    source = getattr(block, "source", None)
    if source is None:
        return None

    media_type = getattr(source, "media_type", None) or ""

    # Base64Source — pass data straight through (after the size cap).
    data_attr = getattr(source, "data", None)
    if data_attr is not None:
        # base64 length -> approximate raw byte count.
        size = len(data_attr or "") * 3 // 4
        if size > MAX_INLINE_MEDIA_BYTES:
            return _video_oversize_placeholder(size)
        return {
            "type": "video",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": data_attr,
            },
        }

    url_str = str(getattr(source, "url", "") or "")
    if not url_str:
        return None

    raw_url = _file_url_to_path(url_str)
    local_path = _local_media_path(url_str)
    if local_path is not None:
        logger.warning(
            "Local video reached Anthropic formatter without preparation: "
            "%s",
            local_path,
        )
        return None

    parsed_url = urlparse(raw_url)
    if parsed_url.scheme in ("http", "https"):
        return {
            "type": "video",
            "source": {"type": "url", "url": url_str},
        }

    return None


# pylint: disable=too-many-branches
def _format_openai_video_block(
    video_block: dict,
    response_api: bool = False,
) -> dict:
    """Format a video block for OpenAI-compatible API.

    Local files are converted to base64 data URLs; web URLs are
    passed through directly.

    When ``response_api`` is True the output uses the
    ``input_video`` content type adopted by Volcengine Ark
    and other providers that extend the OpenAI Responses API
    with native video support.  Official OpenAI and DashScope
    Responses APIs do **not** support video; callers should
    fall back gracefully (the react-agent already retries
    without media on 400 errors).

    Args:
        video_block: The video block to format.
        response_api: When True, emit the Responses API
            ``input_video`` shape instead of the Chat
            Completions ``video_url`` shape.

    Returns:
        Wire-format dict for the provider.

    Raises:
        ModelFormatterError:
            If the source type or video format is not supported.
    """
    source = video_block["source"]
    if source["type"] == "base64":
        media_type = source["media_type"]
        size = len(source.get("data") or "") * 3 // 4
        if size > MAX_INLINE_MEDIA_BYTES:
            return _video_oversize_placeholder(
                size,
                response_api=response_api,
            )
        url = f"data:{media_type};base64,{source['data']}"
    elif source["type"] == "url":
        raw_url = _file_url_to_path(source["url"])
        local_path = _local_media_path(source["url"])
        parsed = urlparse(raw_url)
        if local_path is None and parsed.scheme not in ("", "file"):
            url = source["url"]
        else:
            raise ModelFormatterError(
                message=(
                    f"Local video was not prepared: {source['url']}. "
                    "It should be a readable local file or a web URL."
                ),
            )
    else:
        raise ModelFormatterError(
            message=f"Unsupported video source type: {source['type']}",
        )

    if response_api:
        return {"type": "input_video", "video_url": url}
    return {
        "type": "video_url",
        "video_url": {"url": url},
    }


def _replace_video_placeholders(
    messages: list[dict],
    video_subs: dict[str, dict],
    *,
    response_api: bool = False,
) -> None:
    """Replace video placeholder text blocks with formatted
    video blocks in OpenAI-formatted messages.

    Only ``user``, ``tool``, and ``system`` messages are
    processed; ``assistant`` messages keep placeholders
    as-is because ``input_video`` / ``video_url`` blocks
    are not valid in assistant content for most providers.
    """
    _TEXT_TYPES = ("text", "input_text")
    _REPLACEABLE_ROLES = ("user", "tool", "system")
    for fmt_msg in messages:
        if fmt_msg.get("role") not in _REPLACEABLE_ROLES:
            continue
        content = fmt_msg.get("content")
        if not isinstance(content, list):
            continue
        new_content = []
        for item in content:
            if (
                isinstance(item, dict)
                and item.get("type") in _TEXT_TYPES
                and item.get("text") in video_subs
            ):
                new_content.append(
                    _format_openai_video_block(
                        video_subs[item["text"]],
                        response_api=response_api,
                    ),
                )
            else:
                new_content.append(item)
        fmt_msg["content"] = new_content


def _media_source_key(block: dict) -> str | None:
    """Extract a normalised path/URL from a media block for deduplication.

    Returns ``None`` for base64 sources (nothing to compare) or if no
    usable source URL is present.
    """
    source = block.get("source", {})
    if source.get("type") == "base64":
        return None
    url = source.get("url", "")
    if not url:
        return None
    raw = _file_url_to_path(url)
    if os.path.isabs(raw):
        return os.path.normpath(raw)
    return url


def _block_to_dict(block: Any) -> dict:
    """Coerce a Pydantic block or dict to a plain dict for formatting."""
    if isinstance(block, dict):
        return block
    if hasattr(block, "model_dump"):
        return block.model_dump()
    return dict(block) if hasattr(block, "__iter__") else {"type": "unknown"}


def _substitute_video_blocks(
    msgs: list,
) -> dict[str, dict]:
    """Replace video blocks in msgs with text placeholders.

    Returns a mapping from placeholder text to the original
    video block so they can be restored later.  Handles both
    dict blocks (1.x) and Pydantic DataBlock objects (2.0).

    Assistant messages are skipped because video blocks are
    not valid in assistant content for most providers.
    """
    video_subs: dict[str, dict] = {}
    for msg in msgs:
        if getattr(msg, "role", "") == "assistant":
            continue
        if not isinstance(msg.content, list):
            continue
        for i, blk in enumerate(msg.content):
            btype = (
                blk.get("type")
                if isinstance(blk, dict)
                else getattr(blk, "type", None)
            )
            is_video = False
            if btype == "video":
                is_video = True
            elif btype == "data":
                mt = (
                    getattr(
                        getattr(blk, "source", None),
                        "media_type",
                        "",
                    )
                    or ""
                )
                is_video = mt.startswith("video/")

            if is_video:
                ph = f"__QWENPAW_VID_{id(blk)}__"
                video_subs[ph] = (
                    blk if isinstance(blk, dict) else blk.model_dump()
                )
                msg.content[i] = TextBlock(type="text", text=ph)
    return video_subs


def _restore_video_blocks(
    msgs: list,
    video_subs: dict[str, dict],
) -> None:
    """Restore original video blocks in msgs after formatting."""
    for msg in msgs:
        if not isinstance(msg.content, list):
            continue
        for i, blk in enumerate(msg.content):
            btype = (
                blk.get("type")
                if isinstance(blk, dict)
                else getattr(blk, "type", None)
            )
            text = (
                blk.get("text")
                if isinstance(blk, dict)
                else getattr(blk, "text", None)
            )
            if btype == "text" and text in video_subs:
                msg.content[i] = video_subs[text]


def _promote_tool_result_videos(
    msgs: list,
    messages: list[dict],
    *,
    response_api: bool = False,
) -> list[dict]:
    """Inject promoted video user messages after tool result messages.

    Mirrors the image promotion that agentscope's formatter does
    for ``promote_tool_result_images``, but for video blocks.
    Handles both dict and Pydantic block objects.
    """
    promotions: dict[str, tuple[str, list]] = {}
    for msg in msgs:
        for block in msg.content or []:
            bd = _block_to_dict(block)
            if bd.get("type") != "tool_result":
                continue
            output = bd.get("output")
            if not isinstance(output, list):
                continue
            videos = [
                (
                    (item if isinstance(item, dict) else _block_to_dict(item))
                    .get("source", {})
                    .get("url", ""),
                    item if isinstance(item, dict) else _block_to_dict(item),
                )
                for item in output
                if (
                    (
                        item
                        if isinstance(item, dict)
                        else _block_to_dict(item)
                    ).get("type")
                    in ("video", "data")
                    and (
                        (
                            item
                            if isinstance(item, dict)
                            else _block_to_dict(item)
                        )
                        .get("source", {})
                        .get("media_type", "")
                        .startswith("video/")
                        or (
                            item
                            if isinstance(item, dict)
                            else _block_to_dict(item)
                        ).get("type")
                        == "video"
                    )
                )
            ]
            if videos:
                bd_id = bd.get("id")
                if isinstance(bd_id, str):
                    promotions[bd_id] = (
                        bd.get("name", ""),
                        videos,
                    )

    if not promotions:
        return messages

    new_messages: list[dict] = []
    for fmt_msg in messages:
        new_messages.append(fmt_msg)
        tcid = fmt_msg.get("tool_call_id")
        if not isinstance(tcid, str) or tcid not in promotions:
            continue
        tool_name, videos = promotions[tcid]
        txt_type = "input_text" if response_api else "text"
        promoted: list[dict] = [
            {
                "type": txt_type,
                "text": "<system-info>The following are "
                "the video contents from the tool "
                f"result of '{tool_name}':",
            },
        ]
        for url, vid_block in videos:
            promoted.append(
                {
                    "type": txt_type,
                    "text": f"\n- The video from '{url}': ",
                },
            )
            promoted.append(
                _format_openai_video_block(
                    vid_block,
                    response_api=response_api,
                ),
            )
        promoted.append(
            {
                "type": txt_type,
                "text": "</system-info>",
            },
        )
        new_messages.append(
            {"role": "user", "content": promoted},
        )
    return new_messages


def _reorder_tool_and_promoted_messages(
    messages: list[dict],
) -> list[dict]:
    """Move promoted user messages after all tool results in a sequence.

    When ``promote_tool_result_images`` is True the upstream formatter
    inserts a ``role=user`` message after each ``role=tool`` message to
    carry the promoted image.  The OpenAI / Anthropic APIs require all
    tool-result messages to appear contiguously after the assistant
    message.  This helper collects the interleaved user messages and
    appends them after the last tool message in each sequence.
    """
    result: list[dict] = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            result.append(msg)
            i += 1
            tool_msgs: list[dict] = []
            promoted_msgs: list[dict] = []
            while i < len(messages) and messages[i].get("role") in (
                "tool",
                "user",
            ):
                if messages[i]["role"] == "tool":
                    tool_msgs.append(messages[i])
                else:
                    promoted_msgs.append(messages[i])
                i += 1
            result.extend(tool_msgs)
            result.extend(promoted_msgs)
        else:
            result.append(msg)
            i += 1
    return result


# Mapping of non-standard MIME subtypes to their correct forms.
_MIME_FIXES: dict[str, str] = {
    "image/jpg": "image/jpeg",
}


def _fix_image_mime_types(messages: list[dict]) -> None:
    """Fix non-standard MIME types in base64 data URLs in-place.

    agentscope derives MIME from the file extension literally
    (e.g. ``.jpg`` → ``image/jpg``), but ``image/jpg`` is not a
    valid IANA MIME type — the correct form is ``image/jpeg``.
    Some APIs (Bedrock via litellm) reject the non-standard form.

    Handles both Chat Completions format (``image_url`` is a dict
    with a ``url`` key) and Responses API format (``image_url`` is
    a plain string URL).
    """
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            raw = block.get("image_url")
            if raw is None:
                continue
            if isinstance(raw, dict):
                url = raw.get("url", "")
            elif isinstance(raw, str):
                url = raw
            else:
                continue
            for wrong, right in _MIME_FIXES.items():
                if url.startswith(f"data:{wrong};"):
                    fixed = url.replace(f"data:{wrong};", f"data:{right};", 1)
                    if isinstance(raw, dict):
                        raw["url"] = fixed
                    else:
                        block["image_url"] = fixed


_MEDIA_BLOCK_TYPES = ("image", "audio", "video")

# Block types that the base OpenAI / Gemini formatter processes into
# ``content_blocks`` or ``tool_calls``, guaranteeing the assistant
# message survives formatting.
_SURVIVOR_BLOCK_TYPES = frozenset({"text", "tool_use", "tool_call"})

# Block types that do not contribute content to an assistant wire message.
# Thinking and file blocks are skipped, while a hint becomes a separate user
# message. A source segment consisting entirely of these (plus any
# ``DataBlock`` with unsupported media) emits no assistant message. Used by
# ``_is_block_dropped_by_formatter`` to predict assistant-message survival.
#
# ``file`` is kept for completeness but is effectively dead code:
# ``_fixup_media_list`` converts file blocks to ``TextBlock`` before
# the prediction runs.
_ALWAYS_DROPPED_TYPES = frozenset({"thinking", "file", "hint"})


def _is_block_dropped_by_formatter(
    block: Any,
    formatter: "FormatterBase",
) -> bool:
    """Predict whether *block* is absent from assistant wire content.

    The base ``OpenAIChatFormatter.format()`` only adds a block to
    ``content_blocks`` (text, DataBlock with supported media) or
    ``tool_calls`` (ToolCallBlock). ThinkingBlock, unknown types, and
    unsupported DataBlock values are skipped. HintBlock is emitted as a
    separate user message, so it does not keep an assistant segment alive.

    This function returns ``True`` when a block is predicted to be
    absent from assistant content, enabling ``aligned_reasoning`` to predict
    message drops and stay in sync with the formatted output.  #5858
    """
    btype = (
        block.get("type")
        if isinstance(block, dict)
        else getattr(block, "type", None)
    )

    if btype in _SURVIVOR_BLOCK_TYPES:
        return False

    if btype in _ALWAYS_DROPPED_TYPES:
        return True

    if btype == "data":
        source = getattr(block, "source", None)
        media_type = (
            (getattr(source, "media_type", "") or "") if source else ""
        )
        supported = getattr(formatter, "supported_input_media_types", [])
        if not supported:
            return True
        from fnmatch import fnmatch

        return not any(fnmatch(media_type, pat) for pat in supported)

    # tool_result produces a separate ``role="tool"`` message but causes
    # a flush of current content — it does NOT contribute to assistant
    # ``content_blocks`` itself.  Treat it the same as a dropped block
    # for assistant-survival prediction (the assistant message is
    # preserved only if it has other survivor blocks).
    if btype == "tool_result":
        return True

    # Unknown block type — the base formatter logs a warning and skips.
    return True


def _reasoning_by_assistant_segment(
    blocks: list[Any],
    formatter: "FormatterBase",
) -> list[str | None]:
    """Align thinking content with emitted assistant wire messages.

    OpenAI-family formatters flush the current assistant message before each
    tool result or hint. AgentScope can keep several reasoning/tool cycles in
    one assistant ``Msg``, so each resulting wire segment must receive only
    the thinking blocks that belong to that segment.
    """

    def _get(block: Any, key: str, default: Any = None) -> Any:
        if isinstance(block, dict):
            return block.get(key, default)
        return getattr(block, key, default)

    aligned: list[str | None] = []
    reasoning_parts: list[str] = []
    segment_survives = False

    for block in blocks:
        block_type = _get(block, "type")
        if block_type == "thinking":
            thinking = _get(block, "thinking", "")
            if thinking:
                reasoning_parts.append(thinking)
            continue

        if block_type in ("tool_result", "hint"):
            if segment_survives:
                aligned.append("\n".join(reasoning_parts) or None)
            reasoning_parts = []
            segment_survives = False
            continue

        if not _is_block_dropped_by_formatter(block, formatter):
            segment_survives = True

    if segment_survives:
        aligned.append("\n".join(reasoning_parts) or None)

    return aligned


# pylint: disable=too-many-branches
def _fixup_media_list(items: list) -> None:
    """Normalize media blocks in a list in-place.

    - Strips ``file://`` prefixes from source URLs (dict blocks).
    - Replaces media blocks whose local file no longer exists with
      a text placeholder so the downstream formatter won't throw.
    - Converts ``file`` blocks to text placeholders — neither the
      OpenAI nor the Anthropic top-level formatters accept them and
      the upstream OpenAI path silently drops the whole message when
      nothing else survives.
    - Handles both dict blocks (1.x) and Pydantic block objects (2.0).
    - Recurses into ``tool_result`` output lists.
    """
    for i, block in enumerate(items):
        btype = (
            block.get("type")
            if isinstance(block, dict)
            else getattr(block, "type", None)
        )

        if btype in _MEDIA_BLOCK_TYPES:
            # Dict block (1.x format)
            if isinstance(block, dict):
                source = block.get("source")
                if not (
                    isinstance(source, dict)
                    and source.get("type") == "url"
                    and isinstance(source.get("url"), str)
                ):
                    continue
                if source["url"].startswith("file://"):
                    source["url"] = _file_url_to_path(source["url"])
                url = source["url"]
            else:
                continue  # Pydantic media blocks handled by 2.0 formatter

            if not url.startswith(
                ("http://", "https://", "data:"),
            ) and not os.path.exists(url):
                logger.warning(
                    "Media file no longer exists, "
                    "replacing with placeholder: %s",
                    url,
                )
                items[i] = TextBlock(
                    type="text",
                    text=(
                        f"[{btype.title()} unavailable"
                        f" — file deleted from disk]"
                    ),
                )
        elif btype == "data":
            # 2.0 DataBlock — decode percent-encoded file:// URLs and
            # check if local file still exists.  Pydantic's AnyUrl
            # re-encodes non-ASCII chars; we must undo that before
            # the DashScope formatter tries to open() the path.
            source = getattr(block, "source", None)
            url_str = str(getattr(source, "url", "")) if source else ""
            if url_str.startswith("file://"):
                local_path = _file_url_to_path(url_str)
                if not os.path.exists(local_path):
                    mt = getattr(source, "media_type", "") or ""
                    media_name = mt.split("/")[0] or "media"
                    logger.warning(
                        "Media file no longer exists, "
                        "replacing with placeholder: %s",
                        local_path,
                    )
                    items[i] = TextBlock(
                        type="text",
                        text=(
                            f"[{media_name.title()} unavailable"
                            f" — file deleted from disk]"
                        ),
                    )
                elif source is not None:
                    source.url = local_path
        elif btype == "file":
            if isinstance(block, dict):
                source = block.get("source") or {}
                file_url = (
                    source.get("url", "") if isinstance(source, dict) else ""
                )
                fname_hint = block.get("filename") or block.get("name")
            else:
                source = getattr(block, "source", None)
                file_url = str(getattr(source, "url", "")) if source else ""
                fname_hint = getattr(block, "filename", None) or getattr(
                    block,
                    "name",
                    None,
                )
            readable_path = (
                _file_url_to_path(file_url)
                if isinstance(file_url, str) and file_url.startswith("file://")
                else file_url
            )
            filename = (
                fname_hint
                or (readable_path.rsplit("/", 1)[-1] if readable_path else "")
                or "file"
            )
            items[i] = TextBlock(
                type="text",
                text=(
                    f"File '{filename}' is available at: {readable_path}"
                    if readable_path
                    else f"File '{filename}'"
                ),
            )
        elif btype == "tool_result":
            output = (
                block.get("output")
                if isinstance(block, dict)
                else getattr(block, "output", None)
            )
            if isinstance(output, list):
                _fixup_media_list(output)


# pylint: disable-next=too-many-statements
def _create_file_block_support_formatter(
    base_formatter_class: Type[FormatterBase],
    provider_id: str | None = None,
) -> Type[FormatterBase]:
    """Create a formatter class with file block support.

    This factory function extends any Formatter class to support file blocks
    in tool results, which are not natively supported by AgentScope.

    Args:
        base_formatter_class: Base formatter class to extend.
        provider_id: Provider owning the formatter. Provider-specific
            tool-call metadata is relayed only when this matches the
            provider that originally emitted it.

    Returns:
        Enhanced formatter class with file block support
    """

    class FileBlockSupportFormatter(base_formatter_class):
        """Formatter with file block support for tool results."""

        def __init__(self, **kwargs):
            # Expand the Anthropic formatter's supported_input_media_types
            # to include video — third-party Anthropic-compatible
            # providers can accept video even though Anthropic's own API
            # cannot.  Without this, ``_format_anthropic_data_block``
            # short-circuits and our override below never runs.
            if AnthropicChatFormatter is not None and issubclass(
                base_formatter_class,
                AnthropicChatFormatter,
            ):
                # Direct assignment (not setdefault): kwargs comes from
                # model_dump() and may carry the base class's narrower
                # input_types; we must override to include "video/*".
                kwargs["input_types"] = [
                    "text/plain",
                    "image/*",
                    "video/*",
                ]
            super().__init__(**kwargs)

        def _format_anthropic_data_block(self, block):
            """Route video ``DataBlock``s to our local helper; defer
            everything else to the upstream Anthropic formatter.

            Also dedups the same media within one ``format()`` call:
            the second appearance of a given source becomes a short
            text placeholder instead of another base64 copy.

            Only the Anthropic base invokes this method — it lives on
            our subclass as dead code for OpenAI / Gemini bases.
            """
            source = getattr(block, "source", None)
            media_type = getattr(source, "media_type", "") or ""

            seen = _FORMATTER_SEEN_MEDIA_KEYS.get()
            if seen is None:
                seen = set()
                _FORMATTER_SEEN_MEDIA_KEYS.set(seen)
            key = _anthropic_media_dedup_key(source) if source else None
            if key is not None:
                if key in seen:
                    main_type = media_type.split("/")[0] or "media"
                    return {
                        "type": "text",
                        "text": (
                            f"[{main_type.title()} omitted — "
                            f"already shown above]"
                        ),
                    }
                seen.add(key)

            if media_type.startswith("video/"):
                return _format_anthropic_video_data_block(block)
            return super()._format_anthropic_data_block(block)

        # pylint: disable=too-many-branches, too-many-statements
        async def format(self, msgs):
            """Override ``format`` (2.0 API) to inject normalization,
            reasoning_content relay, and provider-specific fixups.
            """

            # A formatter failure must not leave media evidence from a
            # previous request behind for the capability fallback layer.
            self._qwenpaw_last_wire_media_count = 0
            self._qwenpaw_last_wire_audio_count = 0

            # Per-wire-request dedup scope — second occurrence of the
            # same media source becomes a text placeholder.  Reset on
            # every call so state never leaks across requests.
            seen_media_token = _FORMATTER_SEEN_MEDIA_KEYS.set(set())

            def _battr(block, key, default=None):
                """Get attribute from dict or Pydantic block."""
                if isinstance(block, dict):
                    return block.get(key, default)
                return getattr(block, key, default)

            (
                normalized_msgs,
                is_anthropic_formatter,
                _is_gemini_formatter,
                _is_response_formatter,
            ) = _normalize_messages_for_formatter(
                msgs,
                base_formatter_class,
                self,
            )

            has_reasoning = False
            # Tool-call IDs are required to be unique within one assistant
            # response. A deque still preserves FIFO order when historical
            # messages from separate turns happen to reuse the same ID.
            extra_contents: dict[str, deque[Any]] = defaultdict(deque)
            for msg in normalized_msgs:
                if msg.role != "assistant":
                    continue
                persisted_extras = tool_call_extras_for_provider(
                    msg,
                    provider_id,
                )
                for block in msg.content or []:
                    if _battr(block, "type") == "thinking":
                        thinking = _battr(block, "thinking", "")
                        if thinking:
                            has_reasoning = True
                for block in msg.content or []:
                    btype = _battr(block, "type")
                    if btype in ("tool_use", "tool_call"):
                        ec = _battr(block, "extra_content")
                        if ec is None:
                            ec = persisted_extras.get(
                                _battr(block, "id", ""),
                            )
                        if ec is not None:
                            bid = _battr(block, "id", "")
                            extra_contents[bid].append(ec)

            # Convert file:// URLs to paths for all media blocks,
            # and replace deleted local files with text placeholders.
            fixup_tasks = [
                run_sync_io(_fixup_media_list, msg.content)
                for msg in normalized_msgs
                if isinstance(msg.content, list)
            ]
            if fixup_tasks:
                await asyncio.gather(*fixup_tasks)

            include_hint_videos = (
                is_anthropic_formatter
                or _is_gemini_formatter
                or issubclass(
                    base_formatter_class,
                    DashScopeChatFormatter,
                )
            )
            await _prepare_media_sources(
                normalized_msgs,
                base_formatter_class,
                include_hint_videos=include_hint_videos,
                max_bytes=getattr(
                    self,
                    "max_bytes",
                    MAX_INLINE_MEDIA_BYTES,
                ),
            )

            try:
                # OpenAI-family formatters reject video blocks; substitute
                # them with text placeholders before formatting and restore
                # the wire dicts afterwards.  Anthropic and Gemini skip
                # this dance — Anthropic now handles video via our
                # ``_format_anthropic_data_block`` override, Gemini accepts
                # video natively.
                _needs_video = not _is_gemini_formatter and not (
                    is_anthropic_formatter
                )
                video_subs: dict[str, dict] = {}
                if _needs_video:
                    video_subs = _substitute_video_blocks(normalized_msgs)

                messages = await super().format(normalized_msgs)

                if video_subs:
                    _replace_video_placeholders(
                        messages,
                        video_subs,
                        response_api=_is_response_formatter,
                    )
                    _restore_video_blocks(normalized_msgs, video_subs)

                if _needs_video and getattr(
                    self,
                    "promote_tool_result_images",
                    False,
                ):
                    messages = _promote_tool_result_videos(
                        normalized_msgs,
                        messages,
                        response_api=_is_response_formatter,
                    )
            finally:
                _FORMATTER_SEEN_MEDIA_KEYS.reset(seen_media_token)

            messages = _reorder_tool_and_promoted_messages(messages)
            _fix_image_mime_types(messages)

            # ``extra_content`` is an OpenAI-chat wire extension. Persisted
            # values entered ``extra_contents`` only when ``provider_id``
            # matched their origin, so other compatible providers never see
            # the field merely because they share this formatter family.
            if extra_contents and issubclass(
                base_formatter_class,
                OpenAIChatFormatter,
            ):
                for message in messages:
                    for tc in message.get("tool_calls", []):
                        queued = extra_contents.get(tc.get("id"))
                        if queued:
                            ec = queued.popleft()
                            tc["extra_content"] = ec

            relay_reasoning = getattr(
                self,
                "relay_reasoning_content",
                True,
            )
            require_reasoning = getattr(
                self,
                "_qwenpaw_require_reasoning_content",
                False,
            )
            should_inject_reasoning = has_reasoning or require_reasoning
            formatter_supports_reasoning = (
                not is_anthropic_formatter and not _is_response_formatter
            )
            should_relay_reasoning = relay_reasoning or require_reasoning
            if (
                should_inject_reasoning
                and formatter_supports_reasoning
                and should_relay_reasoning
            ):
                aligned_reasoning = []
                for m in (
                    msg for msg in normalized_msgs if msg.role == "assistant"
                ):
                    blocks = (
                        list(m.content) if isinstance(m.content, list) else []
                    )
                    aligned_reasoning.extend(
                        _reasoning_by_assistant_segment(blocks, self),
                    )

                out_assistant = [
                    m for m in messages if m.get("role") == "assistant"
                ]

                if len(aligned_reasoning) != len(out_assistant):
                    logger.warning(
                        "Assistant message count mismatch after formatting "
                        "(%d expected survivors, %d actual). "
                        "%s reasoning_content injection for this turn. "
                        "A block type may be dropped by the base formatter "
                        "without being handled by "
                        "_is_block_dropped_by_formatter, "
                        "or a new split pattern needs to be predicted.",
                        len(aligned_reasoning),
                        len(out_assistant),
                        (
                            "Falling back to placeholder"
                            if require_reasoning
                            else "Skipping"
                        ),
                    )
                    if logger.isEnabledFor(logging.DEBUG):
                        for _i, m in enumerate(
                            msg
                            for msg in normalized_msgs
                            if msg.role == "assistant"
                        ):
                            types = (
                                [_battr(b, "type") for b in m.content]
                                if isinstance(m.content, list)
                                else []
                            )
                            logger.debug(
                                "  src assistant[%d] blocks=%s",
                                _i,
                                types,
                            )
                    if require_reasoning:
                        # Positional reasoning is unsafe when source and wire
                        # counts differ.  A provider that already rejected the
                        # request still needs the field, so use placeholders
                        # without mutating the original AgentScope messages.
                        for out_msg in out_assistant:
                            out_msg.setdefault("reasoning_content", " ")
                else:
                    for i, out_msg in enumerate(out_assistant):
                        if relay_reasoning and aligned_reasoning[i]:
                            out_msg["reasoning_content"] = aligned_reasoning[i]
                        elif require_reasoning:
                            out_msg.setdefault("reasoning_content", " ")

            wire_messages = _strip_top_level_message_name(messages)
            self._qwenpaw_last_wire_media_count = _count_wire_media_blocks(
                wire_messages,
            )
            self._qwenpaw_last_wire_audio_count = _count_wire_audio_blocks(
                wire_messages,
            )
            return wire_messages

        def convert_tool_result_to_string(
            self,
            output: Union[str, List[dict]],
        ) -> tuple[str, Sequence[Tuple[str, dict]]]:
            """Extend parent class to support file blocks."""
            if isinstance(output, str):
                return output, []

            try:
                text, promoted = super().convert_tool_result_to_string(output)
                return _stabilize_promoted_tool_result_media_identifiers(
                    text,
                    promoted,
                )
            except ValueError as exc:
                if "Unsupported block type: file" not in str(exc):
                    raise ModelFormatterError(
                        message=str(exc),
                    ) from exc

                textual_output = []
                multimodal_data = []

                for block in output:
                    if not isinstance(block, dict) or "type" not in block:
                        raise ModelFormatterError(
                            message=(
                                f"Invalid block: {block}, "
                                "expected a dict with 'type' key"
                            ),
                        ) from exc

                    if block["type"] == "file":
                        file_path = block.get("path", "") or block.get(
                            "url",
                            "",
                        )
                        file_name = block.get("name", file_path)

                        textual_output.append(
                            f"The returned file '{file_name}' "
                            f"can be found at: {file_path}",
                        )
                        multimodal_data.append((file_path, block))
                    else:
                        text, data = super().convert_tool_result_to_string(
                            [block],
                        )
                        textual_output.append(text)
                        multimodal_data.extend(data)

                if len(textual_output) == 0:
                    return "", multimodal_data
                elif len(textual_output) == 1:
                    return textual_output[0], multimodal_data
                else:
                    return (
                        "\n".join("- " + _ for _ in textual_output),
                        multimodal_data,
                    )

    FileBlockSupportFormatter.__name__ = (
        f"FileBlockSupport{base_formatter_class.__name__}"
    )
    return FileBlockSupportFormatter


def _strip_top_level_message_name(
    messages: list[dict],
) -> list[dict]:
    """Strip top-level `name` from OpenAI chat-style messages.

    Some strict OpenAI-compatible backends reject `messages[*].name`
    (especially for assistant/tool roles) and may return 500/400 on
    follow-up turns. Responses API also uses top-level non-message items
    such as ``{"type": "function_call", "name": ...}``, where ``name`` is
    required; those must be left unchanged.
    """
    for message in messages:
        if "role" in message:
            message.pop("name", None)
    return messages


def _resolve_model_slot_override(model_slot_override: Any):
    """Parse an optional per-request model override into a model slot."""
    from ..config.config import ModelSlotConfig

    slot = None
    if isinstance(model_slot_override, ModelSlotConfig):
        slot = model_slot_override
    if isinstance(model_slot_override, dict):
        try:
            slot = ModelSlotConfig.model_validate(model_slot_override)
        except Exception:
            logger.warning(
                "Ignoring invalid model_slot_override dict: %r",
                model_slot_override,
            )
    if isinstance(model_slot_override, str):
        # Use partition so version-tagged model names can contain ':'.
        provider_id, sep, model_name = model_slot_override.partition(":")
        if sep and provider_id.strip() and model_name.strip():
            slot = ModelSlotConfig(
                provider_id=provider_id.strip(),
                model=model_name.strip(),
            )
        else:
            logger.warning(
                "Ignoring invalid model_slot_override string: %r",
                model_slot_override,
            )
    if model_slot_override is not None and not isinstance(
        model_slot_override,
        (ModelSlotConfig, dict, str),
    ):
        logger.warning(
            "Unsupported model_slot_override type: %s",
            type(model_slot_override).__name__,
        )
    return slot


def _bind_provider_id_to_model(
    model: ChatModelBase,
    provider_id: str,
) -> str:
    """Bind the provider identity resolved by ``ProviderManager``."""
    bind_provider_id = getattr(model, "bind_qwenpaw_provider_id", None)
    if callable(bind_provider_id):
        bind_provider_id(provider_id)
    return provider_id


def _resolved_provider_id(provider: Any, configured_provider_id: str) -> str:
    """Return the canonical ID exposed by a resolved provider instance."""
    return str(getattr(provider, "id", "") or configured_provider_id)


@dataclass
class _AgentModelSettings:
    """Model routing settings loaded for one agent."""

    model_slot: Any = None
    retry_config: RetryConfig | None = None
    rate_limit_config: RateLimitConfig | None = None
    fallback_slots: list[Any] = field(default_factory=list)
    fallback_enabled: bool = False
    fallback_free_only: bool = False
    thinking_level: Any = "inherit"
    compact_threshold: Optional[float] = None


def _load_agent_model_settings(
    agent_id: str | None,
    agent_config: Any = None,
) -> _AgentModelSettings:
    """Load agent model settings while tolerating legacy config objects."""
    settings = _AgentModelSettings()

    try:
        if agent_config is None:
            from ..config.config import load_agent_config

            if not agent_id:
                return settings
            agent_config = load_agent_config(agent_id)
        settings.model_slot = agent_config.active_model
        settings.thinking_level = getattr(
            agent_config,
            "thinking_level",
            "inherit",
        )
        settings.fallback_slots = list(
            getattr(agent_config, "fallback_models", []),
        )
        fallback_policy = getattr(agent_config, "fallback_policy", None)
        if fallback_policy is not None:
            settings.fallback_enabled = fallback_policy.enabled
            settings.fallback_free_only = (
                fallback_policy.target_scope == "free_only"
            )
        running = agent_config.running
        settings.retry_config = RetryConfig(
            enabled=running.llm_retry_enabled,
            max_retries=running.llm_max_retries,
            backoff_base=running.llm_backoff_base,
            backoff_cap=running.llm_backoff_cap,
        )
        settings.rate_limit_config = RateLimitConfig(
            max_concurrent=running.llm_max_concurrent,
            max_qpm=running.llm_max_qpm,
            pause_seconds=running.llm_rate_limit_pause,
            jitter_range=running.llm_rate_limit_jitter,
            acquire_timeout=running.llm_acquire_timeout,
        )
        compact_config = running.light_context_config.context_compact_config
        if getattr(compact_config, "enabled", False):
            settings.compact_threshold = compact_config.compact_threshold_ratio
    except Exception:
        pass
    return settings


def _apply_model_fallbacks(
    wrapped_model: ChatModelBase,
    *,
    provider_id: str,
    fallback_slots: list[Any],
    fallback_enabled: bool,
    fallback_free_only: bool,
    thinking_level: str,
    compact_threshold: Optional[float],
    retry_config: RetryConfig | None,
    rate_limit_config: RateLimitConfig | None,
    has_model_override: bool,
) -> ChatModelBase:
    """Build an ordered fallback chain around the primary model."""
    if not fallback_enabled or has_model_override or not fallback_slots:
        return wrapped_model

    from ..providers.fallback_chat_model import FallbackChatModel
    from ..providers.provider import agent_thinking_level

    fallback_models: list[ChatModelBase] = [wrapped_model]
    primary_model_name = getattr(wrapped_model, "model", "")
    seen_slots = {(provider_id, primary_model_name)}
    manager = ProviderManager.get_instance()
    for fallback_slot in fallback_slots:
        fallback_provider = manager.get_provider(fallback_slot.provider_id)
        if fallback_provider is None:
            continue
        fallback_provider_id = _resolved_provider_id(
            fallback_provider,
            fallback_slot.provider_id,
        )
        fallback_key = (fallback_provider_id, fallback_slot.model)
        if fallback_key in seen_slots:
            continue
        fallback_info = fallback_provider.get_model_info(fallback_slot.model)
        if fallback_info is None:
            continue
        if fallback_free_only and not fallback_info.is_free:
            continue
        # A broken fallback slot (stale provider config, deleted chat
        # model class, ...) must never keep a healthy primary model
        # from being built: skip the slot instead of propagating.
        try:
            with agent_thinking_level(thinking_level):
                fallback_model = fallback_provider.get_chat_model_instance(
                    fallback_slot.model,
                )
            fallback_provider_id = _bind_provider_id_to_model(
                fallback_model,
                fallback_provider_id,
            )
            _install_model_formatter(
                fallback_model,
                provider_id=fallback_provider_id,
            )
        except Exception:
            logger.warning(
                "Skipping fallback model slot %s:%s "
                "(failed to instantiate)",
                fallback_provider_id,
                fallback_slot.model,
                exc_info=True,
            )
            continue
        if hasattr(fallback_model, "max_retries"):
            fallback_model.max_retries = 0
        recorded_model = TokenRecordingModelWrapper(
            fallback_provider_id,
            fallback_model,
            compact_threshold=compact_threshold,
        )
        fallback_models.append(
            RetryChatModel(
                recorded_model,
                retry_config=retry_config,
                rate_limit_config=rate_limit_config,
            ),
        )
        seen_slots.add(fallback_key)

    if len(fallback_models) > 1:
        return FallbackChatModel(fallback_models)
    return wrapped_model


def create_model_and_formatter(
    agent_id: Optional[str] = None,
    model_slot_override: Any = None,
    agent_config: Any = None,
) -> Tuple[ChatModelBase, FormatterBase]:
    """Factory method to create model and formatter instances.

    This method handles both local and remote models, selecting the
    appropriate chat model class and formatter based on configuration.

    Args:
        agent_id: Optional agent ID to load agent-specific model config.
            If None, tries to get from context, then falls back to global.
        model_slot_override: Optional per-request model override. When
            provided, it takes precedence over the agent's persisted
            ``active_model``. Accepts a ``ModelSlotConfig``, a dict matching
            its schema, or a string of the form ``"<provider_id>:<model>"``.
            The model name itself may contain ``:`` (e.g. version tags);
            only the first ``:`` is treated as the separator.
        agent_config: Optional config already loaded by an async caller.
            Synchronous callers may omit it to preserve legacy loading.
    Returns:
        Tuple of (model_instance, formatter_instance)

    Example:
        >>> model, formatter = create_model_and_formatter()
    """
    from ..app.agent_context import get_current_agent_id

    # Determine agent_id (parameter > context > None)
    if agent_id is None:
        try:
            agent_id = get_current_agent_id()
        except Exception:
            pass

    settings = _load_agent_model_settings(agent_id, agent_config)
    model_slot = settings.model_slot
    slot = _resolve_model_slot_override(model_slot_override)
    if slot is not None and slot.provider_id and slot.model:
        model_slot = slot

    # Create chat model from agent-specific or global config
    if model_slot and model_slot.provider_id and model_slot.model:
        # Use agent-specific model
        manager = ProviderManager.get_instance()
        provider = manager.get_provider(model_slot.provider_id)
        if provider is None:
            raise ProviderError(
                message=f"Provider '{model_slot.provider_id}' not found.",
            )

        from ..providers.provider import agent_thinking_level

        with agent_thinking_level(settings.thinking_level):
            model = provider.get_chat_model_instance(model_slot.model)
        provider_id = _resolved_provider_id(provider, model_slot.provider_id)
    else:
        # Fallback to global active model
        model = ProviderManager.get_active_chat_model()
        global_model = ProviderManager.get_instance().get_active_model()
        if not global_model:
            raise ProviderError(
                message=(
                    "No active model configured. "
                    "Please configure a model using 'qwenpaw models config' "
                    "or set an agent-specific model."
                ),
            )
        provider_id = _resolved_provider_id(
            ProviderManager.get_instance().get_provider(
                global_model.provider_id,
            ),
            global_model.provider_id,
        )

    provider_id = _bind_provider_id_to_model(model, provider_id)

    # Create the formatter based on the model's native one.  In 2.0 every
    # ``ChatModelBase`` carries its own ``self.formatter`` (set by its
    # ``__init__``), so we just wrap that one with file-block support
    # instead of class-resolving via a brittle map.
    formatter = _install_model_formatter(model, provider_id=provider_id)

    # agentscope 2.0 ChatModelBase has its own retry loop
    # (model/_base.py:162: ``for attempt in range(self.max_retries + 1)``)
    # that catches all Exception, retries non-retryable 4xx, and has no
    # back-off / Retry-After awareness. RetryChatModel (below) is strictly
    # more capable, so collapse the inner loop to a single attempt to avoid
    # 4x4 nested retries on transient errors.
    if hasattr(model, "max_retries"):
        model.max_retries = 0

    # Wrap with retry logic for transient LLM API errors
    wrapped_model = TokenRecordingModelWrapper(
        provider_id,
        model,
        compact_threshold=settings.compact_threshold,
    )
    wrapped_model = RetryChatModel(
        wrapped_model,
        retry_config=settings.retry_config,
        rate_limit_config=settings.rate_limit_config,
    )

    wrapped_model = _apply_model_fallbacks(
        wrapped_model,
        provider_id=provider_id,
        fallback_slots=settings.fallback_slots,
        fallback_enabled=settings.fallback_enabled,
        fallback_free_only=settings.fallback_free_only,
        thinking_level=settings.thinking_level,
        compact_threshold=settings.compact_threshold,
        retry_config=settings.retry_config,
        rate_limit_config=settings.rate_limit_config,
        has_model_override=slot is not None,
    )

    return wrapped_model, formatter


async def create_model_and_formatter_async(
    agent_id: Optional[str] = None,
    model_slot_override: Any = None,
    agent_config: Any = None,
) -> Tuple[ChatModelBase, FormatterBase]:
    """Build a model and formatter without blocking the event loop."""
    return await run_sync_io(
        create_model_and_formatter,
        agent_id=agent_id,
        model_slot_override=model_slot_override,
        agent_config=agent_config,
    )


def _create_formatter_instance(
    model: ChatModelBase,
    provider_id: str | None = None,
) -> FormatterBase:
    """Wrap the model's native formatter with file-block support.

    agentscope 2.0 attaches each model's default formatter at construction
    time (``AnthropicChatModel.__init__`` defaults to
    ``AnthropicChatFormatter()``, etc.), exposed as ``model.formatter``.
    Reading from the instance lets runtime-built compat subclasses
    (``_AnthropicChatModelCompat._Compat(AnthropicChatModel)``) resolve to
    the correct formatter without having to register every subclass in a
    class→formatter map.

    Returns:
        Formatter instance with file-block support (same wire format as
        the model's native one, plus qwenpaw extensions for media
        promotion and file blocks).
    """
    base_formatter = getattr(model, "formatter", None)
    if not isinstance(base_formatter, FormatterBase):
        # All agentscope 2.0 ChatModelBase subclasses default to a real
        # ``FormatterBase`` instance in ``__init__``; arriving here means a
        # subclass returned ``None`` or a wrong type from its constructor.
        # Failing early is better than silently wrapping a non-formatter
        # (which becomes a confusing TypeError deep in ``format()`` later).
        raise TypeError(
            f"Model {type(model).__name__!r} has no usable "
            f"``self.formatter`` (got "
            f"{type(base_formatter).__name__}); cannot derive request "
            f"formatter. agentscope 2.0 models should default to their "
            f"native formatter in __init__.",
        )
    base_formatter_class = type(base_formatter)
    formatter_class = _create_file_block_support_formatter(
        base_formatter_class,
        provider_id=provider_id,
    )
    # Carry over all Pydantic field values (max_bytes,
    # relay_reasoning_content, etc.) from the provider-constructed
    # formatter so they are not silently reset to defaults.
    kwargs: dict[str, Any] = base_formatter.model_dump()
    # OpenAI / Gemini wire formats can't carry image bytes inside tool
    # results — promote them into a follow-up user message instead.
    # Anthropic format keeps images in tool_result natively, so no
    # promotion needed.
    _promote_types = (
        OpenAIChatFormatter,
        GeminiChatFormatter,
        OpenAIResponseFormatter,
    )
    if isinstance(base_formatter, _promote_types):
        kwargs["promote_tool_result_images"] = True
    return formatter_class(**kwargs)


def _install_model_formatter(
    model: ChatModelBase,
    provider_id: str | None = None,
) -> FormatterBase:
    """Install and return the QwenPaw formatter for one model."""
    formatter = _create_formatter_instance(
        model,
        provider_id=provider_id,
    )
    model.formatter = formatter
    return formatter


__all__ = [
    "create_model_and_formatter",
    "create_model_and_formatter_async",
]
