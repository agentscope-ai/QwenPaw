# -*- coding: utf-8 -*-
# pylint: disable=too-many-branches,too-many-statements
"""
Pluggable message renderer: Message -> sendable parts (runtime Content).
Style/capabilities control markdown, emoji, code fence.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, List, Union

from agentscope_runtime.engine.schemas.agent_schemas import (
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
class RenderStyle:
    """Channel capabilities for rendering (no hardcoded markdown/emoji)."""

    show_tool_details: bool = True
    supports_markdown: bool = True
    supports_code_fence: bool = True
    use_emoji: bool = True
    filter_tool_messages: bool = False
    filter_thinking: bool = False


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
        from agentscope_runtime.engine.schemas.agent_schemas import MessageType

        msg_type = getattr(message, "type", None)
        content = getattr(message, "content", None) or []
        s = self.style

        if s.filter_thinking and msg_type == MessageType.REASONING:
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
                if s.show_tool_details:
                    args = data.get("arguments") or "{}"
                    args_preview = (
                        args[:200] + "..." if len(args) > 200 else args
                    )
                else:
                    args_preview = "..."
                text = _fmt_tool_call(name, args_preview, s)
                out.append(TextContent(text=text))
            return out

        def _blocks_to_parts(blocks: list) -> List[_OutgoingPart]:
            result: List[_OutgoingPart] = []
            for b in blocks:
                if not isinstance(b, dict):
                    continue
                btype = b.get("type")
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
                                    filename=b.get("filename"),
                                ),
                            )
                if btype == "thinking" and b.get("thinking"):
                    if not s.filter_thinking:
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
                except json.JSONDecodeError:
                    pass

                if isinstance(output, list):
                    block_parts = _blocks_to_parts(output)
                    if s.show_tool_details:
                        out.append(
                            TextContent(
                                text=_fmt_tool_output_label(name, s),
                            ),
                        )
                        out.extend(block_parts)
                    else:
                        media_types = (
                            ContentType.IMAGE,
                            ContentType.AUDIO,
                            ContentType.VIDEO,
                            ContentType.FILE,
                        )
                        media_parts = [
                            p
                            for p in block_parts
                            if getattr(p, "type", None) in media_types
                        ]
                        out.extend(media_parts)
                        if not media_parts:
                            out.append(
                                TextContent(
                                    text=_fmt_tool_output_label(name, s)
                                    + _fmt_code_block("...", s),
                                ),
                            )
                    continue

                if isinstance(output, str):
                    preview = (
                        (output[:500] + "..." if len(output) > 500 else output)
                        if s.show_tool_details
                        else "..."
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
                    preview = (
                        (raw[:500] + "..." if len(raw) > 500 else raw)
                        if s.show_tool_details
                        else "..."
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
            if s.filter_tool_messages:
                return []
            parts = _parts_for_tool_call(content)
            if not parts:
                parts = [TextContent(text=f"[{msg_type}]")]
            return parts

        if msg_type in (
            MessageType.FUNCTION_CALL_OUTPUT,
            MessageType.PLUGIN_CALL_OUTPUT,
            MessageType.MCP_TOOL_CALL_OUTPUT,
        ):
            if s.filter_tool_messages:
                media_types = (
                    ContentType.IMAGE,
                    ContentType.AUDIO,
                    ContentType.VIDEO,
                    ContentType.FILE,
                )
                media_parts = []
                for c in content:
                    if getattr(c, "type", None) != ContentType.DATA:
                        continue
                    data = getattr(c, "data", None) or {}
                    output = data.get("output", "")
                    try:
                        output = json.loads(output)
                    except json.JSONDecodeError:
                        pass
                    if isinstance(output, list):
                        block_parts = _blocks_to_parts(output)
                        media_parts.extend(
                            [
                                p
                                for p in block_parts
                                if getattr(p, "type", None) in media_types
                            ],
                        )
                return media_parts
            parts = _parts_for_tool_output(content)
            if not parts:
                parts = [TextContent(text=f"[{msg_type}]")]
            return parts

        result: List[_OutgoingPart] = []
        for c in content:
            ctype = getattr(c, "type", None)
            if ctype == ContentType.TEXT and getattr(c, "text", None):
                result.append(TextContent(text=c.text))
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
                        if not s.show_tool_details:
                            preview = "..."
                        elif output is not None:
                            preview = str(output)[:500] + (
                                "..." if len(str(output)) > 500 else ""
                            )
                        else:
                            preview = str(args)[:200] + (
                                "..." if len(str(args)) > 200 else ""
                            )
                        result.append(
                            TextContent(
                                text=_fmt_tool_output_label(name, s)
                                + _fmt_code_block(preview, s),
                            ),
                        )
        if not result and msg_type:
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
            body = prefix + body
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
