# -*- coding: utf-8 -*-
import json
import logging
import platform
import os
from datetime import datetime, timezone
from typing import List, Optional, Union
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from agentscope.message import Msg
from agentscope_runtime.engine.schemas.agent_schemas import (
    Message,
    TextContent,
    ImageContent,
    AudioContent,
    VideoContent,
    FileContent,
    DataContent,
    FunctionCall,
    FunctionCallOutput,
    MessageType,
)

from ...config import load_config

logger = logging.getLogger(__name__)


def build_env_context(
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    channel: Optional[str] = None,
    working_dir: Optional[str] = None,
    add_hint: bool = True,
) -> str:
    """
    Build environment context with current request context prepended.

    Args:
        session_id: Current session ID
        user_id: Current user ID
        channel: Current channel name
        working_dir: Working directory path
        add_hint: Whether to add hint context
    Returns:
        Formatted environment context string
    """
    parts = []
    user_tz = load_config().user_timezone or "UTC"
    try:
        now = datetime.now(ZoneInfo(user_tz))
    except (ZoneInfoNotFoundError, KeyError):
        logger.warning("Invalid timezone %r, falling back to UTC", user_tz)
        now = datetime.now(timezone.utc)
        user_tz = "UTC"

    if session_id is not None:
        parts.append(f"- Session ID: {session_id}")
    if user_id is not None:
        parts.append(f"- User ID: {user_id}")
    if channel is not None:
        parts.append(f"- Channel: {channel}")

    parts.append(
        f"- OS: {platform.system()} {platform.release()} "
        f"({platform.machine()})",
    )

    if working_dir is not None:
        parts.append(f"- Working directory: {working_dir}")
    parts.append(
        f"- Current time: {now.strftime('%Y-%m-%d %H:%M:%S')} "
        f"{user_tz} ({now.strftime('%A')})",
    )

    if add_hint:
        parts.append(
            "- Important:\n"
            "  1. Prefer using skills when completing tasks "
            "(e.g. use the cron skill for scheduled tasks). "
            "Consult the relevant skill documentation if unsure.\n"
            "  2. When using write_file, if you want to avoid overwriting "
            "existing content, use read_file first to inspect the file, "
            "then use edit_file for partial updates or appending.",
        )

    return (
        "====================\n" + "\n".join(parts) + "\n===================="
    )


def _is_local_file_url(url: str) -> bool:
    """True if url is a local file reference (file:// or absolute path)."""
    if not url or not isinstance(url, str):
        return False
    s = url.strip()
    if not s:
        return False
    lower = s.lower()

    # Check for remote URLs
    if lower.startswith(("http://", "https://", "data:")):
        return False

    # Check for local file patterns: file://, Unix paths, or Windows drives
    return (
        lower.startswith("file:")
        or (s.startswith("/") and not s.startswith("//"))
        or (len(s) >= 2 and s[1] == ":" and s[0].isalpha())
    )


def _basename_from_url(url: str) -> str:
    """Extract filename from file:// or path."""
    s = url.strip()
    if s.lower().startswith("file:"):
        s = s[5:].lstrip("/")
    return os.path.basename(s.rstrip("/") or "file")


def _resolve_content_url(url: str) -> str:
    """If url is local, return filename only; frontend builds URL."""
    if not isinstance(url, str):
        return url
    if not _is_local_file_url(url):
        return url
    return _basename_from_url(url)


# pylint: disable=too-many-branches,too-many-statements
def agentscope_msg_to_message(
    messages: Union[Msg, List[Msg]],
) -> List[Message]:
    """
    Convert AgentScope Msg(s) into one or more runtime Message objects.

    Args:
        messages: AgentScope message(s) from streaming.

    Returns:
        List[Message]: One or more constructed runtime Message objects.
    """
    if isinstance(messages, Msg):
        msgs = [messages]
    elif isinstance(messages, list):
        msgs = messages
    else:
        raise TypeError(f"Expected Msg or list[Msg], got {type(messages)}")

    results: List[Message] = []

    for msg in msgs:
        role = msg.role or "assistant"
        metadata = {
            "original_id": msg.id,
            "original_name": msg.name,
            "metadata": msg.metadata,
        }

        if isinstance(msg.content, str):
            message = Message(type=MessageType.MESSAGE, role=role)
            message.metadata = metadata
            text_content = TextContent(
                delta=False,
                index=None,
                text=msg.content,
            )
            message.add_content(new_content=text_content)
            results.append(message)
            continue

        current_message = None
        current_type = None

        for block in msg.content:
            if isinstance(block, dict):
                btype = block.get("type", "text")
            else:
                continue

            if btype == "text":
                if current_type != MessageType.MESSAGE:
                    if current_message:
                        results.append(current_message)
                    current_message = Message(
                        type=MessageType.MESSAGE,
                        role=role,
                    )
                    current_message.metadata = metadata
                    current_type = MessageType.MESSAGE

                text_content = TextContent(
                    delta=False,
                    index=None,
                    text=block.get("text", ""),
                )
                current_message.add_content(new_content=text_content)

            elif btype == "thinking":
                if current_type != MessageType.REASONING:
                    if current_message:
                        results.append(current_message)
                    current_message = Message(
                        type=MessageType.REASONING,
                        role=role,
                    )
                    current_message.metadata = metadata
                    current_type = MessageType.REASONING

                text_content = TextContent(
                    delta=False,
                    index=None,
                    text=block.get("thinking", ""),
                )
                current_message.add_content(new_content=text_content)

            elif btype == "tool_use":
                if current_message:
                    results.append(current_message)

                current_message = Message(
                    type=MessageType.PLUGIN_CALL,
                    role=role,
                )
                current_message.metadata = metadata
                current_type = MessageType.PLUGIN_CALL

                if isinstance(block.get("input"), (dict, list)):
                    arguments = json.dumps(
                        block.get("input"),
                        ensure_ascii=False,
                    )
                else:
                    arguments = block.get("input")

                call_data = FunctionCall(
                    call_id=block.get("id"),
                    name=block.get("name"),
                    arguments=arguments,
                ).model_dump()

                data_content = DataContent(
                    delta=False,
                    index=None,
                    data=call_data,
                )
                current_message.add_content(new_content=data_content)

            elif btype == "tool_result":
                if current_message:
                    results.append(current_message)

                current_message = Message(
                    type=MessageType.PLUGIN_CALL_OUTPUT,
                    role=role,
                )
                current_message.metadata = metadata
                current_type = MessageType.PLUGIN_CALL_OUTPUT

                if isinstance(block.get("output"), (dict, list)):
                    output = json.dumps(
                        block.get("output"),
                        ensure_ascii=False,
                    )
                else:
                    output = block.get("output")

                output_data = FunctionCallOutput(
                    call_id=block.get("id"),
                    name=block.get("name"),
                    output=output,
                ).model_dump(exclude_none=True)

                data_content = DataContent(
                    delta=False,
                    index=None,
                    data=output_data,
                )
                current_message.add_content(new_content=data_content)

            elif btype == "image":
                if current_type != MessageType.MESSAGE:
                    if current_message:
                        results.append(current_message)
                    current_message = Message(
                        type=MessageType.MESSAGE,
                        role=role,
                    )
                    current_message.metadata = metadata
                    current_type = MessageType.MESSAGE

                kwargs = {}
                if (
                    isinstance(block.get("source"), dict)
                    and block.get("source", {}).get("type") == "url"
                ):
                    url = block.get("source", {}).get("url")
                    url = _resolve_content_url(url)
                    kwargs["image_url"] = url

                elif (
                    isinstance(block.get("source"), dict)
                    and block.get("source").get("type") == "base64"
                ):
                    media_type = block.get("source", {}).get(
                        "media_type",
                        "image/jpeg",
                    )
                    base64_data = block.get("source", {}).get("data", "")
                    url = f"data:{media_type};base64,{base64_data}"
                    kwargs["image_url"] = url

                image_content = ImageContent(
                    delta=False,
                    index=None,
                    **kwargs,
                )
                current_message.add_content(new_content=image_content)

            elif btype == "audio":
                if current_type != MessageType.MESSAGE:
                    if current_message:
                        results.append(current_message)
                    current_message = Message(
                        type=MessageType.MESSAGE,
                        role=role,
                    )
                    current_message.metadata = metadata
                    current_type = MessageType.MESSAGE

                kwargs = {}
                if (
                    isinstance(block.get("source"), dict)
                    and block.get("source", {}).get("type") == "url"
                ):
                    url = block.get("source", {}).get("url")
                    url = _resolve_content_url(url)
                    kwargs["data"] = url
                    try:
                        kwargs["format"] = urlparse(url).path.split(".")[-1]
                    except (AttributeError, IndexError, ValueError):
                        kwargs["format"] = None

                elif (
                    isinstance(block.get("source"), dict)
                    and block.get("source").get("type") == "base64"
                ):
                    media_type = block.get("source", {}).get("media_type")
                    base64_data = block.get("source", {}).get("data", "")
                    url = f"data:{media_type};base64,{base64_data}"
                    kwargs["data"] = url
                    kwargs["format"] = media_type

                audio_content = AudioContent(
                    delta=False,
                    index=None,
                    **kwargs,
                )
                current_message.add_content(new_content=audio_content)

            elif btype == "video":
                if current_type != MessageType.MESSAGE:
                    if current_message:
                        results.append(current_message)
                    current_message = Message(
                        type=MessageType.MESSAGE,
                        role=role,
                    )
                    current_message.metadata = metadata
                    current_type = MessageType.MESSAGE

                kwargs = {}
                if (
                    isinstance(block.get("source"), dict)
                    and block.get("source", {}).get("type") == "url"
                ):
                    url = block.get("source", {}).get("url")
                    url = _resolve_content_url(url)
                    kwargs["video_url"] = url

                elif (
                    isinstance(block.get("source"), dict)
                    and block.get("source").get("type") == "base64"
                ):
                    media_type = block.get("source", {}).get(
                        "media_type",
                        "video/mp4",
                    )
                    base64_data = block.get("source", {}).get("data", "")
                    url = f"data:{media_type};base64,{base64_data}"
                    kwargs["video_url"] = url

                video_content = VideoContent(
                    delta=False,
                    index=None,
                    **kwargs,
                )
                current_message.add_content(new_content=video_content)

            elif btype == "file":
                if current_type != MessageType.MESSAGE:
                    if current_message:
                        results.append(current_message)
                    current_message = Message(
                        type=MessageType.MESSAGE,
                        role=role,
                    )
                    current_message.metadata = metadata
                    current_type = MessageType.MESSAGE

                kwargs = {
                    "filename": block.get("filename"),
                }
                if (
                    isinstance(block.get("source"), dict)
                    and block.get("source", {}).get("type") == "url"
                ):
                    url = block.get("source", {}).get("url")
                    url = _resolve_content_url(url)
                    kwargs["file_url"] = url

                elif (
                    isinstance(block.get("source"), dict)
                    and block.get("source").get("type") == "base64"
                ):
                    media_type = block.get("source", {}).get(
                        "media_type",
                        "application/octet-stream",
                    )
                    base64_data = block.get("source", {}).get("data", "")
                    url = f"data:{media_type};base64,{base64_data}"
                    kwargs["file_url"] = url
                elif isinstance(block.get("source"), str):
                    url = _resolve_content_url(block.get("source", ""))
                    kwargs["file_url"] = url

                file_content = FileContent(
                    delta=False,
                    index=None,
                    **kwargs,
                )
                current_message.add_content(new_content=file_content)

            else:
                if current_type != MessageType.MESSAGE:
                    if current_message:
                        results.append(current_message)
                    current_message = Message(
                        type=MessageType.MESSAGE,
                        role=role,
                    )
                    current_message.metadata = metadata
                    current_type = MessageType.MESSAGE

                text_content = TextContent(
                    delta=False,
                    index=None,
                    text=str(block),
                )
                current_message.add_content(new_content=text_content)

        if current_message:
            results.append(current_message)

    return results
