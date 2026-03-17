# -*- coding: utf-8 -*-
import json
import logging
import os
from datetime import datetime, timezone
from typing import List, Optional, Union
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from agentscope.message import Msg
from agentscope_runtime.engine.schemas.agent_schemas import (
    Message,
    FunctionCall,
    FunctionCallOutput,
    MessageType,
)
from agentscope_runtime.engine.helpers.agent_api_builder import ResponseBuilder

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
        parts.append(f"- 当前的session_id: {session_id}")
    if user_id is not None:
        parts.append(f"- 当前的user_id: {user_id}")
    if channel is not None:
        parts.append(f"- 当前的channel: {channel}")

    if working_dir is not None:
        parts.append(f"- 工作目录: {working_dir}")

    parts.append(
        f"- 当前时间: {now.strftime('%Y-%m-%d %H:%M:%S')} "
        f"{user_tz} ({now.strftime('%A')})",
    )

    if add_hint:
        parts.append(
            "- 重要提示:\n"
            "  1. 完成任务时，优先考虑使用 skills"
            "（例如定时任务，优先使用 cron skill）。"
            "对于不清楚的 skills，请先查阅相关对应文档。\n"
            "  2. 使用 write_file 写文件时，如果担心覆盖原有内容，"
            "可以先用 read_file 查看文件内容，"
            "再使用 edit_file 工具进行局部内容更新或追加内容。",
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

        if isinstance(msg.content, str):
            rb = ResponseBuilder()
            mb = rb.create_message_builder(
                role=role,
                message_type=MessageType.MESSAGE,
            )
            mb.message.metadata = {
                "original_id": msg.id,
                "original_name": msg.name,
                "metadata": msg.metadata,
            }
            cb = mb.create_content_builder(content_type="text")
            cb.set_text(msg.content)
            cb.complete()
            mb.complete()
            results.append(mb.get_message_data())
            continue

        current_mb = None
        current_type = None

        for block in msg.content:
            if isinstance(block, dict):
                btype = block.get("type", "text")
            else:
                continue

            if btype == "text":
                if current_type != MessageType.MESSAGE:
                    if current_mb:
                        current_mb.complete()
                        results.append(current_mb.get_message_data())
                    rb = ResponseBuilder()
                    current_mb = rb.create_message_builder(
                        role=role,
                        message_type=MessageType.MESSAGE,
                    )
                    current_mb.message.metadata = {
                        "original_id": msg.id,
                        "original_name": msg.name,
                        "metadata": msg.metadata,
                    }
                    current_type = MessageType.MESSAGE
                cb = current_mb.create_content_builder(content_type="text")
                cb.set_text(block.get("text", ""))
                cb.complete()

            elif btype == "thinking":
                if current_type != MessageType.REASONING:
                    if current_mb:
                        current_mb.complete()
                        results.append(current_mb.get_message_data())
                    rb = ResponseBuilder()
                    current_mb = rb.create_message_builder(
                        role=role,
                        message_type=MessageType.REASONING,
                    )
                    current_mb.message.metadata = {
                        "original_id": msg.id,
                        "original_name": msg.name,
                        "metadata": msg.metadata,
                    }
                    current_type = MessageType.REASONING
                cb = current_mb.create_content_builder(content_type="text")
                cb.set_text(block.get("thinking", ""))
                cb.complete()

            elif btype == "tool_use":
                if current_mb:
                    current_mb.complete()
                    results.append(current_mb.get_message_data())
                rb = ResponseBuilder()
                current_mb = rb.create_message_builder(
                    role=role,
                    message_type=MessageType.PLUGIN_CALL,
                )
                current_mb.message.metadata = {
                    "original_id": msg.id,
                    "original_name": msg.name,
                    "metadata": msg.metadata,
                }
                current_type = MessageType.PLUGIN_CALL
                cb = current_mb.create_content_builder(content_type="data")

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
                cb.set_data(call_data)
                cb.complete()

            elif btype == "tool_result":
                if current_mb:
                    current_mb.complete()
                    results.append(current_mb.get_message_data())
                rb = ResponseBuilder()
                current_mb = rb.create_message_builder(
                    role=role,
                    message_type=MessageType.PLUGIN_CALL_OUTPUT,
                )
                current_mb.message.metadata = {
                    "original_id": msg.id,
                    "original_name": msg.name,
                    "metadata": msg.metadata,
                }
                current_type = MessageType.PLUGIN_CALL_OUTPUT
                cb = current_mb.create_content_builder(content_type="data")

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
                cb.set_data(output_data)
                cb.complete()

            elif btype == "image":
                if current_type != MessageType.MESSAGE:
                    if current_mb:
                        current_mb.complete()
                        results.append(current_mb.get_message_data())
                    rb = ResponseBuilder()
                    current_mb = rb.create_message_builder(
                        role=role,
                        message_type=MessageType.MESSAGE,
                    )
                    current_mb.message.metadata = {
                        "original_id": msg.id,
                        "original_name": msg.name,
                        "metadata": msg.metadata,
                    }
                    current_type = MessageType.MESSAGE
                cb = current_mb.create_content_builder(content_type="image")

                if (
                    isinstance(block.get("source"), dict)
                    and block.get("source", {}).get("type") == "url"
                ):
                    url = block.get("source", {}).get("url")
                    url = _resolve_content_url(url)
                    cb.set_image_url(url)

                elif (
                    isinstance(block.get("source"), dict)
                    and block.get("source").get(
                        "type",
                    )
                    == "base64"
                ):
                    media_type = block.get("source", {}).get(
                        "media_type",
                        "image/jpeg",
                    )
                    base64_data = block.get("source", {}).get("data", "")
                    url = f"data:{media_type};base64,{base64_data}"
                    cb.set_image_url(url)

                cb.complete()

            elif btype == "audio":
                if current_type != MessageType.MESSAGE:
                    if current_mb:
                        current_mb.complete()
                        results.append(current_mb.get_message_data())
                    rb = ResponseBuilder()
                    current_mb = rb.create_message_builder(
                        role=role,
                        message_type=MessageType.MESSAGE,
                    )
                    current_mb.message.metadata = {
                        "original_id": msg.id,
                        "original_name": msg.name,
                        "metadata": msg.metadata,
                    }
                    current_type = MessageType.MESSAGE
                cb = current_mb.create_content_builder(content_type="audio")

                if (
                    isinstance(block.get("source"), dict)
                    and block.get("source", {}).get(
                        "type",
                    )
                    == "url"
                ):
                    url = block.get("source", {}).get("url")
                    url = _resolve_content_url(url)
                    cb.content.data = url
                    try:
                        cb.content.format = urlparse(url).path.split(".")[-1]
                    except (AttributeError, IndexError, ValueError):
                        cb.content.format = None

                elif (
                    isinstance(block.get("source"), dict)
                    and block.get("source").get(
                        "type",
                    )
                    == "base64"
                ):
                    media_type = block.get("source", {}).get(
                        "media_type",
                    )
                    base64_data = block.get("source", {}).get("data", "")
                    url = f"data:{media_type};base64,{base64_data}"

                    cb.content.data = url
                    cb.content.format = media_type

                cb.complete()

            else:
                if current_type != MessageType.MESSAGE:
                    if current_mb:
                        current_mb.complete()
                        results.append(current_mb.get_message_data())
                    rb = ResponseBuilder()
                    current_mb = rb.create_message_builder(
                        role=role,
                        message_type=MessageType.MESSAGE,
                    )
                    current_mb.message.metadata = {
                        "original_id": msg.id,
                        "original_name": msg.name,
                        "metadata": msg.metadata,
                    }
                    current_type = MessageType.MESSAGE
                cb = current_mb.create_content_builder(content_type="text")
                cb.set_text(str(block))
                cb.complete()

        if current_mb:
            current_mb.complete()
            results.append(current_mb.get_message_data())

    return results
