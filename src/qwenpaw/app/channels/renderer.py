# -*- coding: utf-8 -*-
# pylint: disable=too-many-branches,too-many-statements
"""
Pluggable message renderer: Message -> sendable parts (runtime Content).
Style/capabilities control markdown, emoji, code fence.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, List, Union

from qwenpaw.schemas import (
    AudioContent,
    ContentType,
    FileContent,
    ImageContent,
    RefusalContent,
    TextContent,
    VideoContent,
)

logger = logging.getLogger(__name__)

# Same union as base.OutgoingContentPart (renderer must not import base).
_OutgoingPart = Union[
    TextContent,
    ImageContent,
    VideoContent,
    AudioContent,
    FileContent,
    RefusalContent,
]


@dataclass
class ChannelDisplayConfig:
    """Display settings shared by channel rendering and streaming."""

    show_tool_details: bool = True
    show_thinking: bool = True
    show_tool_calls: bool = True
    show_tool_results: bool = True
    # A value of 0 means unlimited (do not truncate).
    tool_call_max_length: int = 200
    tool_result_max_length: int = 500

    @classmethod
    def from_config(
        cls,
        config: Any,
        *,
        show_tool_details: bool = True,
    ) -> "ChannelDisplayConfig":
        """Build display settings from channel and global configuration."""
        if isinstance(config, dict):

            def read(key: str, default: Any) -> Any:
                return config.get(key, default)

        else:

            def read(key: str, default: Any) -> Any:
                return getattr(config, key, default)

        def read_bool(key: str, default: bool) -> bool:
            value = read(key, default)
            if isinstance(value, bool):
                return value
            if value in (0, 1):
                return bool(value)
            if isinstance(value, str):
                normalized = value.strip().lower()
                if normalized in {"true", "1", "yes", "on"}:
                    return True
                if normalized in {"false", "0", "no", "off"}:
                    return False
            return default

        def read_length(key: str, default: int) -> int:
            value = read(key, default)
            if isinstance(value, bool):
                return default
            try:
                return max(0, int(value))
            except (TypeError, ValueError):
                return default

        return cls(
            show_tool_details=show_tool_details,
            show_thinking=read_bool("show_thinking", True),
            show_tool_calls=read_bool("show_tool_calls", True),
            show_tool_results=read_bool("show_tool_results", True),
            tool_call_max_length=read_length("tool_call_max_length", 200),
            tool_result_max_length=read_length(
                "tool_result_max_length",
                500,
            ),
        )


@dataclass
class RenderStyle:
    """Channel capabilities for rendering (no hardcoded markdown/emoji)."""

    display_config: ChannelDisplayConfig = field(
        default_factory=ChannelDisplayConfig,
    )
    supports_markdown: bool = True
    supports_code_fence: bool = True
    use_emoji: bool = True
    # Builtin tools with display_to_user=False (e.g. view_image/view_video).
    # Their media output is withheld from users when tool results are hidden.
    internal_tools: frozenset = frozenset()


def _truncate_tool_text(value: Any, limit: int) -> str:
    """Return a tool preview; zero means unlimited."""
    text = str(value or "")
    if limit <= 0 or len(text) <= limit:
        return text
    return text[:limit] + "..."


def _fmt_tool_call(
    name: str,
    args_preview: str,
    style: RenderStyle,
) -> str:
    if style.supports_markdown and style.use_emoji:
        return f"🔧 **{name}**\n```\n{args_preview}\n```"
    if style.supports_markdown:
        return f"**{name}**\n```\n{args_preview}\n```"
    if style.supports_code_fence:
        return f"{name}\n```\n{args_preview}\n```"
    return f"{name}: {args_preview}"


def _fmt_tool_output_label(name: str, style: RenderStyle) -> str:
    if style.use_emoji:
        return f"✅ **{name}**:"
    if style.supports_markdown:
        return f"**{name}**:"
    return f"{name}:"


def _fmt_code_block(preview: str, style: RenderStyle) -> str:
    if style.supports_code_fence:
        return f"\n```\n{preview}\n```"
    return f"\n{preview}"


class MessageRenderer:
    """
    Converts a Message (object=='message') into sendable parts.
    Style controls markdown/emoji/code fence; no hardcoded format.
    """

    def __init__(self, style: RenderStyle | None = None):
        self.style = style or RenderStyle()

    def message_to_parts(self, message: Any) -> List[_OutgoingPart]:
        """Convert Message to list of sendable parts (runtime Content)."""
        from qwenpaw.agents.context.scroll.serialize import strip_headline
        from qwenpaw.schemas import MessageType

        msg_type = getattr(message, "type", None)
        content = getattr(message, "content", None) or []
        s = self.style

        if (
            not s.display_config.show_thinking
            and msg_type == MessageType.REASONING
        ):
            return []

        logger.debug(
            "renderer message_to_parts: msg_type=%s content_len=%s",
            msg_type,
            len(content),
        )

        def _parts_for_tool_call(content_list: list) -> List[_OutgoingPart]:
            out: List[_OutgoingPart] = []
            for c in content_list:
                if getattr(c, "type", None) != ContentType.DATA:
                    continue
                data = getattr(c, "data", None) or {}
                name = data.get("name") or "tool"
                if not s.display_config.show_tool_calls:
                    continue
                args = data.get("arguments") or "{}"
                args_preview = (
                    "..."
                    if not s.display_config.show_tool_details
                    else _truncate_tool_text(
                        args,
                        s.display_config.tool_call_max_length,
                    )
                )
                text = _fmt_tool_call(name, args_preview, s)
                out.append(TextContent(text=text))
            return out

        def _blocks_to_parts(blocks: list) -> List[_OutgoingPart]:
            result: List[_OutgoingPart] = []
            for b in blocks:
                if hasattr(b, "model_dump"):
                    b = b.model_dump()
                if not isinstance(b, dict):
                    continue
                btype = b.get("type")
                if btype == "data":
                    src = b.get("source") or {}
                    mt = (
                        src.get("media_type", "")
                        if isinstance(src, dict)
                        else ""
                    )
                    for prefix in ("image", "audio", "video"):
                        if mt.startswith(f"{prefix}/"):
                            btype = prefix
                            break
                    else:
                        btype = "file"
                if btype == "text" and b.get("text"):
                    result.append(TextContent(text=b["text"]))
                    continue
                if btype in ("image", "audio", "video", "file"):
                    src = b.get("source") or {}
                    stype = src.get("type")
                    url = None
                    if stype == "url" and src.get("url"):
                        url = src["url"]
                    elif stype == "base64" and src.get("data"):
                        mt = (
                            src.get("media_type") or "application/octet-stream"
                        )
                        url = f"data:{mt};base64,{src['data']}"
                    if url:
                        if btype == "image":
                            result.append(ImageContent(image_url=url))
                        elif btype == "video":
                            result.append(VideoContent(video_url=url))
                        elif btype == "audio":
                            result.append(
                                AudioContent(
                                    data=url,
                                    format=b.get("media_type"),
                                ),
                            )
                        else:
                            result.append(
                                FileContent(
                                    file_url=url,
                                    filename=b.get("filename")
                                    or b.get("name"),
                                ),
                            )
                if btype == "thinking" and b.get("thinking"):
                    if s.display_config.show_thinking:
                        result.append(TextContent(text=b["thinking"]))
            return result

        def _parts_for_tool_output(content_list: list) -> List[_OutgoingPart]:
            out: List[_OutgoingPart] = []
            for c in content_list:
                if getattr(c, "type", None) != ContentType.DATA:
                    continue
                data = getattr(c, "data", None) or {}
                name = data.get("name") or "tool"
                output = data.get("output", "")

                try:
                    output = json.loads(output)
                except (json.JSONDecodeError, TypeError):
                    pass

                if isinstance(output, list):
                    block_parts = _blocks_to_parts(output)
                    media_types = (
                        ContentType.IMAGE,
                        ContentType.AUDIO,
                        ContentType.VIDEO,
                        ContentType.FILE,
                    )
                    # Internal tools (e.g. view_image/view_video) load media
                    # into the LLM context, not for the user. Withhold their
                    # media when tool results are hidden.
                    media_parts = (
                        []
                        if (
                            not s.display_config.show_tool_results
                            and name in s.internal_tools
                        )
                        else [
                            p
                            for p in block_parts
                            if getattr(p, "type", None) in media_types
                        ]
                    )
                    out.extend(media_parts)
                    if s.display_config.show_tool_results:
                        if not s.display_config.show_tool_details:
                            out.append(
                                TextContent(
                                    text=_fmt_tool_output_label(name, s)
                                    + _fmt_code_block("...", s),
                                ),
                            )
                        else:
                            out.append(
                                TextContent(
                                    text=_fmt_tool_output_label(name, s),
                                ),
                            )
                            text = "\n".join(
                                getattr(p, "text", "")
                                for p in block_parts
                                if getattr(p, "type", None) == ContentType.TEXT
                                and getattr(p, "text", "")
                            )
                            if text:
                                result_limit = (
                                    s.display_config.tool_result_max_length
                                )
                                out.append(
                                    TextContent(
                                        text=_truncate_tool_text(
                                            text,
                                            result_limit,
                                        ),
                                    ),
                                )
                    continue

                if isinstance(output, str):
                    if s.display_config.show_tool_results:
                        preview = (
                            "..."
                            if not s.display_config.show_tool_details
                            else _truncate_tool_text(
                                output,
                                s.display_config.tool_result_max_length,
                            )
                        )
                        out.append(
                            TextContent(
                                text=_fmt_tool_output_label(name, s)
                                + _fmt_code_block(preview, s),
                            ),
                        )
                    continue

                if output is not None:
                    raw = str(output)
                    if s.display_config.show_tool_results:
                        preview = (
                            "..."
                            if not s.display_config.show_tool_details
                            else _truncate_tool_text(
                                raw,
                                s.display_config.tool_result_max_length,
                            )
                        )
                        out.append(
                            TextContent(
                                text=_fmt_tool_output_label(name, s)
                                + _fmt_code_block(preview, s),
                            ),
                        )
            return out

        if msg_type in (
            MessageType.FUNCTION_CALL,
            MessageType.PLUGIN_CALL,
            MessageType.MCP_TOOL_CALL,
        ):
            parts = _parts_for_tool_call(content)
            if not parts and s.display_config.show_tool_calls:
                parts = [TextContent(text=f"[{msg_type}]")]
            return parts

        if msg_type in (
            MessageType.FUNCTION_CALL_OUTPUT,
            MessageType.PLUGIN_CALL_OUTPUT,
            MessageType.MCP_TOOL_CALL_OUTPUT,
        ):
            parts = _parts_for_tool_output(content)
            if not parts and s.display_config.show_tool_results:
                parts = [TextContent(text=f"[{msg_type}]")]
            return parts

        result: List[_OutgoingPart] = []
        suppressed_tool_data = False
        for c in content:
            ctype = getattr(c, "type", None)
            if ctype == ContentType.TEXT and getattr(c, "text", None):
                # Hide the scroll headline (⟦ … ⟧) from display; it stays in
                # context and the durable index. No-op when absent.
                text = strip_headline(c.text)
                if text:
                    result.append(TextContent(text=text))
            elif ctype == ContentType.REFUSAL and getattr(c, "refusal", None):
                result.append(RefusalContent(refusal=c.refusal))
            elif ctype == ContentType.IMAGE and getattr(c, "image_url", None):
                result.append(ImageContent(image_url=c.image_url))
            elif ctype == ContentType.VIDEO and getattr(c, "video_url", None):
                result.append(VideoContent(video_url=c.video_url))
            elif ctype == ContentType.AUDIO:
                data = getattr(c, "data", None)
                fmt = getattr(c, "format", None)
                if data:
                    result.append(AudioContent(data=data, format=fmt))
            elif ctype == ContentType.FILE:
                result.append(
                    FileContent(
                        file_url=getattr(c, "file_url", None),
                        file_id=getattr(c, "file_id", None),
                        filename=getattr(c, "filename", None),
                        file_data=getattr(c, "file_data", None),
                    ),
                )
            elif ctype == ContentType.DATA and getattr(c, "data", None):
                data = c.data
                if isinstance(data, dict):
                    name = data.get("name")
                    output = data.get("output")
                    args = data.get("arguments")
                    if name is not None and (
                        output is not None or args is not None
                    ):
                        is_call = args is not None and output is None
                        allowed = (
                            s.display_config.show_tool_calls
                            if is_call
                            else s.display_config.show_tool_results
                        )
                        if not allowed:
                            suppressed_tool_data = True
                            continue
                        preview_limit = (
                            s.display_config.tool_result_max_length
                            if output is not None
                            else s.display_config.tool_call_max_length
                        )
                        preview = (
                            "..."
                            if not s.display_config.show_tool_details
                            else _truncate_tool_text(
                                output if output is not None else args,
                                preview_limit,
                            )
                        )
                        result.append(
                            TextContent(
                                text=_fmt_tool_output_label(name, s)
                                + _fmt_code_block(preview, s),
                            ),
                        )
        if not result and msg_type and not suppressed_tool_data:
            result = [TextContent(text=f"[Message type: {msg_type}]")]
        return result

    def parts_to_text(
        self,
        parts: List[_OutgoingPart],
        prefix: str = "",
    ) -> str:
        """Merge text/refusal parts and append media as fallback text."""
        text_parts: List[str] = []
        for p in parts:
            t = getattr(p, "type", None)
            if t == ContentType.TEXT and getattr(p, "text", None):
                text_parts.append(p.text or "")
            elif t == ContentType.REFUSAL and getattr(p, "refusal", None):
                text_parts.append(p.refusal or "")
        body = "\n".join(text_parts) if text_parts else ""
        if prefix and body:
            body = prefix + "  " + body
        for p in parts:
            t = getattr(p, "type", None)
            if t == ContentType.IMAGE and getattr(p, "image_url", None):
                body += f"\n[Image: {p.image_url}]"
            elif t == ContentType.VIDEO and getattr(p, "video_url", None):
                body += f"\n[Video: {p.video_url}]"
            elif t == ContentType.FILE:
                file_ref = getattr(p, "file_url", None) or getattr(
                    p,
                    "file_id",
                    None,
                )
                body += f"\n[File: {file_ref}]"
            elif t == ContentType.AUDIO and getattr(p, "data", None):
                body += "\n[Audio]"
        return body.strip()
