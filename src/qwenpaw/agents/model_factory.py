# -*- coding: utf-8 -*-
"""Factory for creating chat models and formatters.

This module provides a unified factory for creating chat model instances
and their corresponding formatters based on configuration.

Example:
    >>> from qwenpaw.agents.model_factory import create_model_and_formatter
    >>> model, formatter = create_model_and_formatter()
"""


import base64
import logging
import os
from typing import List, Sequence, Tuple, Type, Any, Union, Optional
from urllib.parse import unquote, urlparse

from agentscope.formatter import FormatterBase, OpenAIChatFormatter
from agentscope.message import TextBlock
from agentscope.model import ChatModelBase

try:
    from agentscope.formatter import AnthropicChatFormatter
except ImportError:
    AnthropicChatFormatter = None

try:
    from agentscope.formatter import GeminiChatFormatter
except ImportError:
    GeminiChatFormatter = None

try:
    from agentscope.formatter import OpenAIResponseFormatter
except ImportError:
    OpenAIResponseFormatter = None

from .utils.message_request_normalizer import (
    normalize_messages_for_model_request,
)
from ..exceptions import ProviderError, ModelFormatterError
from ..providers import ProviderManager
from ..providers.capping_formatter import MAX_INLINE_MEDIA_BYTES
from ..providers.retry_chat_model import (
    RetryChatModel,
    RetryConfig,
    RateLimitConfig,
)
from ..token_usage import TokenRecordingModelWrapper


def _file_url_to_path(url: str) -> str:
    """
    Strip file:// to path. On Windows file:///C:/path -> C:/path not /C:/path.
    Percent-decodes the path so non-ASCII filenames resolve correctly.
    """
    s = url.removeprefix("file://")
    # Windows: file:///C:/path yields "/C:/path"; remove leading slash.
    if len(s) >= 3 and s.startswith("/") and s[1].isalpha() and s[2] == ":":
        s = s[1:]
    return unquote(s)


logger = logging.getLogger(__name__)

_SUPPORTED_IMAGE_EXTENSIONS: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

_SUPPORTED_VIDEO_EXTENSIONS: dict[str, str] = {
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mpeg": "video/mpeg",
    ".mov": "video/quicktime",
    ".avi": "video/x-msvideo",
    ".mkv": "video/x-matroska",
}


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
) -> tuple[list, bool, bool]:
    """Return normalized messages and formatter-family flags.

    The returned booleans are
    ``(is_anthropic_formatter, is_gemini_formatter)``.
    All formatters receive a copied, normalized message list so
    request-time repair does not mutate stored history.
    """
    is_anthropic_formatter = AnthropicChatFormatter is not None and (
        issubclass(base_formatter_class, AnthropicChatFormatter)
    )
    is_gemini_formatter = GeminiChatFormatter is not None and (
        issubclass(base_formatter_class, GeminiChatFormatter)
    )
    supports_multimodal = _supports_multimodal_for_current_model()
    if getattr(formatter_instance, "_qwenpaw_force_strip_media", False):
        supports_multimodal = False

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
    )

    return normalized_msgs, is_anthropic_formatter, is_gemini_formatter


def _anthropic_media_dedup_key(source: Any) -> str | None:
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
        return f"url|{media_type}|{url}"
    data = getattr(source, "data", "") or ""
    if data:
        return f"b64|{media_type}|{len(data)}|{data[:128]}"
    return None


def _video_oversize_placeholder(size: int) -> dict:
    """Text placeholder substituted for a video that exceeds the inline cap.

    Mirrors the wording used by ``capping_formatter``'s
    ``CappingFormatterMixin._placeholder_text`` so oversized-video messages
    are consistent across every provider path.  Tool-result videos inline
    through these helpers bypass the capping formatters (which only see
    ``_format_*_source``), so the cap is enforced here instead.
    """
    return {
        "type": "text",
        "text": (
            f"[video omitted from model context: local file is "
            f"{size} bytes, exceeds inline limit of "
            f"{MAX_INLINE_MEDIA_BYTES} bytes]"
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
    # pylint: disable=too-many-return-statements
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
    if os.path.exists(raw_url) and os.path.isfile(raw_url):
        # Cap oversized local files before reading/encoding the whole
        # thing into the request body (see ``capping_formatter``).
        try:
            size = os.path.getsize(raw_url)
        except OSError:
            size = 0
        if size > MAX_INLINE_MEDIA_BYTES:
            return _video_oversize_placeholder(size)
        ext = os.path.splitext(raw_url)[1].lower()
        resolved_media_type = (
            media_type
            if media_type.startswith("video/")
            else _SUPPORTED_VIDEO_EXTENSIONS.get(ext)
        )
        if resolved_media_type:
            with open(raw_url, "rb") as f:
                encoded = base64.b64encode(f.read()).decode("utf-8")
            return {
                "type": "video",
                "source": {
                    "type": "base64",
                    "media_type": resolved_media_type,
                    "data": encoded,
                },
            }

    parsed_url = urlparse(raw_url)
    if parsed_url.scheme in ("http", "https"):
        return {
            "type": "video",
            "source": {"type": "url", "url": url_str},
        }

    return None


def _format_openai_video_block(video_block: dict) -> dict:
    """Format a video block for OpenAI-compatible API.

    Local files are converted to base64 data URLs; web URLs are
    passed through directly.

    Args:
        video_block (`dict`):
            The video block to format.

    Returns:
        `dict`:
            ``{"type": "video_url", "video_url": {"url": ...}}``.

    Raises:
        `ValueError`:
            If the source type or video format is not supported.
    """
    source = video_block["source"]
    if source["type"] == "base64":
        media_type = source["media_type"]
        # base64 length -> approximate raw byte count.
        size = len(source.get("data") or "") * 3 // 4
        if size > MAX_INLINE_MEDIA_BYTES:
            return _video_oversize_placeholder(size)
        url = f"data:{media_type};base64,{source['data']}"
    elif source["type"] == "url":
        raw_url = _file_url_to_path(source["url"])
        if os.path.exists(raw_url) and os.path.isfile(raw_url):
            # Cap oversized local files before reading/encoding the whole
            # thing into the request body (see ``capping_formatter``).
            try:
                size = os.path.getsize(raw_url)
            except OSError:
                size = 0
            if size > MAX_INLINE_MEDIA_BYTES:
                return _video_oversize_placeholder(size)
            ext = os.path.splitext(raw_url)[1].lower()
            media_type = _SUPPORTED_VIDEO_EXTENSIONS.get(ext)
            if not media_type:
                raise ModelFormatterError(
                    f"Unsupported video extension: {ext}",
                )
            with open(raw_url, "rb") as f:
                data = base64.b64encode(
                    f.read(),
                ).decode("utf-8")
            url = f"data:{media_type};base64,{data}"
        else:
            parsed = urlparse(raw_url)
            if parsed.scheme not in ("", "file"):
                url = source["url"]
            else:
                raise ModelFormatterError(
                    message=(
                        f"Invalid video URL: {source['url']}. "
                        "It should be a local file or a web URL."
                    ),
                )
    else:
        raise ModelFormatterError(
            message=f"Unsupported video source type: {source['type']}",
        )

    return {
        "type": "video_url",
        "video_url": {"url": url},
    }


def _replace_video_placeholders(
    messages: list[dict],
    video_subs: dict[str, dict],
) -> None:
    """Replace video placeholder text blocks with formatted
    video blocks in OpenAI-formatted messages."""
    for fmt_msg in messages:
        content = fmt_msg.get("content")
        if not isinstance(content, list):
            continue
        new_content = []
        for item in content:
            if (
                isinstance(item, dict)
                and item.get("type") == "text"
                and item.get("text") in video_subs
            ):
                new_content.append(
                    _format_openai_video_block(
                        video_subs[item["text"]],
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

    Returns a mapping from placeholder text to the original video
    block so they can be restored later.  Handles both dict blocks
    (1.x) and Pydantic DataBlock objects (2.0).
    """
    video_subs: dict[str, dict] = {}
    for msg in msgs:
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
        promoted: list[dict] = [
            {
                "type": "text",
                "text": "<system-info>The following are "
                "the video contents from the tool "
                f"result of '{tool_name}':",
            },
        ]
        for url, vid_block in videos:
            promoted.append(
                {
                    "type": "text",
                    "text": f"\n- The video from '{url}': ",
                },
            )
            promoted.append(
                _format_openai_video_block(vid_block),
            )
        promoted.append(
            {"type": "text", "text": "</system-info>"},
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
    """
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            url = (block.get("image_url") or {}).get("url", "")
            for wrong, right in _MIME_FIXES.items():
                if url.startswith(f"data:{wrong};"):
                    block["image_url"]["url"] = url.replace(
                        f"data:{wrong};",
                        f"data:{right};",
                        1,
                    )


_MEDIA_BLOCK_TYPES = ("image", "audio", "video")

# Block types the upstream agentscope OpenAI / Gemini formatters silently
# drop.  Tracked here so ``aligned_reasoning`` can predict which assistant
# messages will vanish from the formatted output and stay in sync.  Keep
# this in lockstep with the ``else: logger.warning("Unsupported block
# type ...")`` branch in agentscope's ``_openai_formatter``.
_FORMATTER_SKIPPED_TYPES = frozenset({"thinking", "file"})


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
                elif unquote(url_str) != url_str:
                    source.url = unquote(url_str)
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
) -> Type[FormatterBase]:
    """Create a formatter class with file block support.

    This factory function extends any Formatter class to support file blocks
    in tool results, which are not natively supported by AgentScope.

    Args:
        base_formatter_class: Base formatter class to extend

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

            seen: set[str] = getattr(self, "_seen_media_keys", None) or set()
            self._seen_media_keys = seen
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

            # Per-wire-request dedup scope — second occurrence of the
            # same media source becomes a text placeholder.  Reset on
            # every call so state never leaks across requests.
            self._seen_media_keys = set()

            def _battr(block, key, default=None):
                """Get attribute from dict or Pydantic block."""
                if isinstance(block, dict):
                    return block.get(key, default)
                return getattr(block, key, default)

            (
                normalized_msgs,
                is_anthropic_formatter,
                _is_gemini_formatter,
            ) = _normalize_messages_for_formatter(
                msgs,
                base_formatter_class,
                self,
            )

            reasoning_contents = {}
            extra_contents: dict[str, Any] = {}
            for msg in normalized_msgs:
                if msg.role != "assistant":
                    continue
                for block in msg.content or []:
                    if _battr(block, "type") == "thinking":
                        thinking = _battr(block, "thinking", "")
                        if thinking:
                            reasoning_contents[id(msg)] = thinking
                        break
                for block in msg.content or []:
                    btype = _battr(block, "type")
                    if btype in ("tool_use", "tool_call"):
                        ec = _battr(block, "extra_content")
                        if ec is not None:
                            bid = _battr(block, "id", "")
                            extra_contents[bid] = ec

            # Convert file:// URLs to paths for all media blocks,
            # and replace deleted local files with text placeholders.
            for msg in normalized_msgs:
                if isinstance(msg.content, list):
                    _fixup_media_list(msg.content)

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
                _replace_video_placeholders(messages, video_subs)
                _restore_video_blocks(normalized_msgs, video_subs)

            if _needs_video and getattr(
                self,
                "promote_tool_result_images",
                False,
            ):
                messages = _promote_tool_result_videos(
                    normalized_msgs,
                    messages,
                )

            messages = _reorder_tool_and_promoted_messages(messages)
            _fix_image_mime_types(messages)

            if extra_contents and _is_gemini_formatter:
                for message in messages:
                    for tc in message.get("tool_calls", []):
                        ec = extra_contents.get(tc.get("id"))
                        if ec:
                            tc["extra_content"] = ec

            if (
                reasoning_contents
                and not is_anthropic_formatter
                and getattr(
                    self,
                    "relay_reasoning_content",
                    True,
                )
            ):
                aligned_reasoning = []
                for m in (
                    msg for msg in normalized_msgs if msg.role == "assistant"
                ):
                    types = (
                        [_battr(b, "type") for b in m.content]
                        if isinstance(m.content, list)
                        else []
                    )
                    # Drop prediction: a Msg whose blocks are *entirely*
                    # in the skip set vanishes from formatter output
                    # (currently {thinking, file}).  See
                    # ``_FORMATTER_SKIPPED_TYPES``.
                    is_dropped_by_formatter = bool(types) and all(
                        t in _FORMATTER_SKIPPED_TYPES for t in types
                    )
                    if is_dropped_by_formatter:
                        continue
                    # Split prediction: DashScope / OpenAI-family
                    # formatters produce one assistant wire msg per
                    # "segment" — where tool_result blocks act as
                    # separators (they become role="tool" messages).
                    # Each contiguous run of text/tool_call between
                    # tool_results becomes one assistant message.
                    non_thinking = [t for t in types if t != "thinking"]
                    segments = 0
                    in_segment = False
                    for bt in non_thinking:
                        if bt == "tool_result":
                            in_segment = False
                        else:
                            if not in_segment:
                                segments += 1
                                in_segment = True
                    # Within a segment, text+tool_call still counts as
                    # one wire msg (content + tool_calls merged).  But
                    # if a segment has text ONLY or tool_call ONLY,
                    # that's also 1.  The only extra split is text that
                    # follows tool_calls (rare in model output).
                    wire_count = max(segments, 1)
                    aligned_reasoning.extend(
                        [reasoning_contents.get(id(m))] * wire_count,
                    )

                out_assistant = [
                    m for m in messages if m.get("role") == "assistant"
                ]

                if len(aligned_reasoning) != len(out_assistant):
                    logger.warning(
                        "Assistant message count mismatch after formatting "
                        "(%d expected survivors, %d actual). "
                        "Skipping reasoning_content injection for this turn. "
                        "A block type may be dropped by the base formatter "
                        "without being listed in _FORMATTER_SKIPPED_TYPES, "
                        "or a new split pattern needs to be predicted.",
                        len(aligned_reasoning),
                        len(out_assistant),
                    )
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
                        logger.warning(
                            "  src assistant[%d] blocks=%s",
                            _i,
                            types,
                        )
                else:
                    for i, out_msg in enumerate(out_assistant):
                        if aligned_reasoning[i]:
                            out_msg["reasoning_content"] = aligned_reasoning[i]

            return _strip_top_level_message_name(messages)

        def convert_tool_result_to_string(
            self,
            output: Union[str, List[dict]],
        ) -> tuple[str, Sequence[Tuple[str, dict]]]:
            """Extend parent class to support file blocks."""
            if isinstance(output, str):
                return output, []

            # Try parent class method first
            try:
                return super().convert_tool_result_to_string(output)
            except ValueError as e:
                if "Unsupported block type: file" not in str(e):
                    raise ModelFormatterError(
                        message=str(e),
                    ) from e

                # Handle output containing file blocks
                textual_output = []
                multimodal_data = []

                for block in output:
                    if not isinstance(block, dict) or "type" not in block:
                        raise ModelFormatterError(
                            message=(
                                f"Invalid block: {block}, "
                                "expected a dict with 'type' key"
                            ),
                        ) from e

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
                        # Delegate other block types to parent class
                        (
                            text,
                            data,
                        ) = super().convert_tool_result_to_string([block])
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
    """Strip top-level `name` from OpenAI chat messages.

    Some strict OpenAI-compatible backends reject `messages[*].name`
    (especially for assistant/tool roles) and may return 500/400 on
    follow-up turns. Keep function/tool names unchanged.
    """
    for message in messages:
        message.pop("name", None)
    return messages


def create_model_and_formatter(
    agent_id: Optional[str] = None,
) -> Tuple[ChatModelBase, FormatterBase]:
    """Factory method to create model and formatter instances.

    This method handles both local and remote models, selecting the
    appropriate chat model class and formatter based on configuration.

    Args:
        agent_id: Optional agent ID to load agent-specific model config.
            If None, tries to get from context, then falls back to global.

    Returns:
        Tuple of (model_instance, formatter_instance)

    Example:
        >>> model, formatter = create_model_and_formatter()
    """
    from ..app.agent_context import get_current_agent_id
    from ..config.config import load_agent_config

    # Determine agent_id (parameter > context > None)
    if agent_id is None:
        try:
            agent_id = get_current_agent_id()
        except Exception:
            pass

    # Try to get agent-specific model first
    model_slot = None
    retry_config = None
    rate_limit_config = None
    compact_threshold: Optional[float] = None
    if agent_id:
        try:
            agent_config = load_agent_config(agent_id)
            model_slot = agent_config.active_model
            retry_config = RetryConfig(
                enabled=agent_config.running.llm_retry_enabled,
                max_retries=agent_config.running.llm_max_retries,
                backoff_base=agent_config.running.llm_backoff_base,
                backoff_cap=agent_config.running.llm_backoff_cap,
            )
            rate_limit_config = RateLimitConfig(
                max_concurrent=agent_config.running.llm_max_concurrent,
                max_qpm=agent_config.running.llm_max_qpm,
                pause_seconds=agent_config.running.llm_rate_limit_pause,
                jitter_range=agent_config.running.llm_rate_limit_jitter,
                acquire_timeout=agent_config.running.llm_acquire_timeout,
            )
            # Surface the auto-compaction threshold so the UI can mark where
            # context starts getting evicted — only when compaction is on.
            lcc = agent_config.running.light_context_config
            ccc = lcc.context_compact_config
            if getattr(ccc, "enabled", False):
                compact_threshold = ccc.compact_threshold_ratio
        except Exception:
            pass

    # Create chat model from agent-specific or global config
    if model_slot and model_slot.provider_id and model_slot.model:
        # Use agent-specific model
        manager = ProviderManager.get_instance()
        provider = manager.get_provider(model_slot.provider_id)
        if provider is None:
            raise ProviderError(
                message=f"Provider '{model_slot.provider_id}' not found.",
            )

        model = provider.get_chat_model_instance(model_slot.model)
        provider_id = model_slot.provider_id
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
        provider_id = global_model.provider_id

    # Create the formatter based on the model's native one.  In 2.0 every
    # ``ChatModelBase`` carries its own ``self.formatter`` (set by its
    # ``__init__``), so we just wrap that one with file-block support
    # instead of class-resolving via a brittle map.
    formatter = _create_formatter_instance(model)

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
        compact_threshold=compact_threshold,
    )
    wrapped_model = RetryChatModel(
        wrapped_model,
        retry_config=retry_config,
        rate_limit_config=rate_limit_config,
    )

    return wrapped_model, formatter


def _create_formatter_instance(
    model: ChatModelBase,
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
    )
    # Carry over all Pydantic field values (max_bytes,
    # relay_reasoning_content, etc.) from the provider-constructed
    # formatter so they are not silently reset to defaults.
    kwargs: dict[str, Any] = base_formatter.model_dump()
    # OpenAI / Gemini wire formats can't carry image bytes inside tool
    # results — promote them into a follow-up user message instead.
    # Anthropic format keeps images in tool_result natively, so no
    # promotion needed.
    _promote_types = (OpenAIChatFormatter, GeminiChatFormatter)
    if OpenAIResponseFormatter is not None:
        _promote_types = (*_promote_types, OpenAIResponseFormatter)
    if isinstance(base_formatter, _promote_types):
        kwargs["promote_tool_result_images"] = True
    return formatter_class(**kwargs)


__all__ = [
    "create_model_and_formatter",
]
