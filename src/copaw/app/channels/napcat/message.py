# -*- coding: utf-8 -*-
"""NapCat message parsing and building."""

import re
from typing import Any, Dict, List

from agentscope_runtime.engine.schemas.agent_schemas import (
    TextContent,
    ImageContent,
    VideoContent,
    AudioContent,
    FileContent,
    ContentType,
)

from ..base import OutgoingContentPart
from .constants import MARKDOWN_PATTERNS


def parse_message(  # pylint: disable=R0912
    message: Any,
) -> List[OutgoingContentPart]:
    """Parse OneBot 11 message to content parts.

    Handles:
    - Plain text (str)
    - Array of message segments
    - Message segments: text, image, record, video, file, etc.
    """
    parts: List[OutgoingContentPart] = []

    if not message:
        return parts

    # If message is a string (plain text)
    if isinstance(message, str):
        if message.strip():
            parts.append(
                TextContent(
                    type=ContentType.TEXT,
                    text=message.strip(),
                ),
            )
        return parts

    # If message is a list of segments
    if isinstance(message, list):
        for segment in message:
            seg_type = segment.get("type", "")
            seg_data = segment.get("data", {})

            if seg_type == "text":
                text = seg_data.get("text", "").strip()
                if text:
                    parts.append(TextContent(type=ContentType.TEXT, text=text))

            elif seg_type == "image":
                # Image can be file path, URL, or base64
                image_data = seg_data.get("file", seg_data.get("url", ""))
                if image_data:
                    parts.append(
                        ImageContent(
                            type=ContentType.IMAGE,
                            image_url=image_data,
                        ),
                    )

            elif seg_type == "record":  # Voice
                record_data = seg_data.get("file", seg_data.get("url", ""))
                if record_data:
                    parts.append(
                        AudioContent(
                            type=ContentType.AUDIO,
                            data=record_data,
                        ),
                    )

            elif seg_type == "video":
                video_data = seg_data.get("file", seg_data.get("url", ""))
                if video_data:
                    parts.append(
                        VideoContent(
                            type=ContentType.VIDEO,
                            video_url=video_data,
                        ),
                    )

            elif seg_type == "file":
                file_data = seg_data.get("file", seg_data.get("url", ""))
                file_name = seg_data.get("name", "file")
                if file_data:
                    parts.append(
                        FileContent(
                            type=ContentType.FILE,
                            filename=file_name,
                            file_url=file_data,
                        ),
                    )

    return parts


def build_message_segment(  # pylint: disable=R0912
    text: str,
    auto_escape: bool = True,
) -> Any:
    """Build OneBot 11 message segment from text.

    Args:
        text: Message text
        auto_escape: Whether to escape special characters

    Returns:
        Message segment (string or list of segments)
    """
    if auto_escape:
        # Simple escape for CQ codes
        text = text.replace("&", "&amp;")
        text = text.replace(",", "&#44;")
        text = text.replace("[", "&#91;")
        text = text.replace("]", "&#93;")
    return text


def _contains_markdown(text: str) -> bool:
    """Detect if text contains Markdown syntax.

    Args:
        text: Text to check

    Returns:
        True if text appears to contain Markdown syntax
    """
    # Quick check: if no special characters, likely not markdown
    if not any(c in text for c in "#*_`~-|[]"):
        return False

    # Check each pattern
    for pattern in MARKDOWN_PATTERNS:
        if re.search(pattern, text, re.MULTILINE):
            return True

    return False


def build_markdown_message(text: str) -> List[Dict[str, Any]]:
    """Build message segment with Markdown if detected.

    Args:
        text: Message text

    Returns:
        Message segment (string or list of segments)
    """
    if _contains_markdown(text):
        # Escape special CQ code characters but allow markdown
        escaped = text.replace("&", "&amp;")
        return [{"type": "markdown", "data": {"content": escaped}}]
    else:
        return [build_message_segment(text, auto_escape=True)]


def is_markdown_error(exc: Exception) -> bool:
    """Check if exception is related to markdown sending failure.

    NapCat timeout errors often occur when sending markdown messages.
    We fallback to plaintext for these errors.

    Args:
        exc: Exception to check

    Returns:
        True if this looks like a markdown-related error
    """
    error_msg = str(exc).lower()
    # Timeout errors are likely markdown-related
    if "timeout" in error_msg:
        return True
    # Check for other markdown-related keywords
    markdown_keywords = ["markdown", "json", "ntEvent"]
    return any(kw in error_msg for kw in markdown_keywords)
