# -*- coding: utf-8 -*-
import json
import logging
from datetime import datetime, timezone
from typing import Optional, Union, List
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


# pylint: disable=too-many-branches,too-many-statements
def agentscope_msg_to_message(
    messages: Union[Msg, List[Msg]],
) -> List[Message]:
    """
    Convert AgentScope Msg(s) into one or more runtime Message objects

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
            # Only text
            rb = ResponseBuilder()
            mb = rb.create_message_builder(
                role=role,
                message_type=MessageType.MESSAGE,
            )
            # add meta field to store old id and name
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

        # msg.content is a list of blocks
        # We group blocks by high-level message type
        current_mb = None
        current_type = None

        for block in msg.content:
            if isinstance(block, dict):
                btype = block.get("type", "text")
            else:
                continue

            if btype == "text":
                # Create/continue MESSAGE type
                if current_type != MessageType.MESSAGE:
                    if current_mb:
                        current_mb.complete()
                        results.append(current_mb.get_message_data())
                    rb = ResponseBuilder()
                    current_mb = rb.create_message_builder(
                        role=role,
                        message_type=MessageType.MESSAGE,
                    )
                    # add meta field to store old id and name
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
                # Create/continue REASONING type
                if current_type != MessageType.REASONING:
                    if current_mb:
                        current_mb.complete()
                        results.append(current_mb.get_message_data())
                    rb = ResponseBuilder()
                    current_mb = rb.create_message_builder(
                        role=role,
                        message_type=MessageType.REASONING,
                    )
                    # add meta field to store old id and name
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
                # Always start a new PLUGIN_CALL message
                if current_mb:
                    current_mb.complete()
                    results.append(current_mb.get_message_data())
                rb = ResponseBuilder()
                current_mb = rb.create_message_builder(
                    role=role,
                    message_type=MessageType.PLUGIN_CALL,
                )
                # add meta field to store old id and name
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
                # Always start a new PLUGIN_CALL_OUTPUT message
                if current_mb:
                    current_mb.complete()
                    results.append(current_mb.get_message_data())
                rb = ResponseBuilder()
                current_mb = rb.create_message_builder(
                    role=role,
                    message_type=MessageType.PLUGIN_CALL_OUTPUT,
                )
                # add meta field to store old id and name
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
                # Create/continue MESSAGE type with image
                if current_type != MessageType.MESSAGE:
                    if current_mb:
                        current_mb.complete()
                        results.append(current_mb.get_message_data())
                    rb = ResponseBuilder()
                    current_mb = rb.create_message_builder(
                        role=role,
                        message_type=MessageType.MESSAGE,
                    )
                    # add meta field to store old id and name
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
                    cb.set_image_url(block.get("source", {}).get("url"))

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
                # Create/continue MESSAGE type with audio
                if current_type != MessageType.MESSAGE:
                    if current_mb:
                        current_mb.complete()
                        results.append(current_mb.get_message_data())
                    rb = ResponseBuilder()
                    current_mb = rb.create_message_builder(
                        role=role,
                        message_type=MessageType.MESSAGE,
                    )
                    # add meta field to store old id and name
                    current_mb.message.metadata = {
                        "original_id": msg.id,
                        "original_name": msg.name,
                        "metadata": msg.metadata,
                    }
                    current_type = MessageType.MESSAGE
                cb = current_mb.create_content_builder(content_type="audio")
                # URLSource runtime check (dict with type == "url")
                if (
                    isinstance(block.get("source"), dict)
                    and block.get("source", {}).get(
                        "type",
                    )
                    == "url"
                ):
                    url = block.get("source", {}).get("url")
                    cb.content.data = url
                    try:
                        cb.content.format = urlparse(url).path.split(".")[-1]
                    except (AttributeError, IndexError, ValueError):
                        cb.content.format = None

                # Base64Source runtime check (dict with type == "base64")
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
                # Fallback to MESSAGE type
                if current_type != MessageType.MESSAGE:
                    if current_mb:
                        current_mb.complete()
                        results.append(current_mb.get_message_data())
                    rb = ResponseBuilder()
                    current_mb = rb.create_message_builder(
                        role=role,
                        message_type=MessageType.MESSAGE,
                    )
                    # add meta field to store old id and name
                    current_mb.message.metadata = {
                        "original_id": msg.id,
                        "original_name": msg.name,
                        "metadata": msg.metadata,
                    }
                    current_type = MessageType.MESSAGE
                cb = current_mb.create_content_builder(content_type="text")
                cb.set_text(str(block))
                cb.complete()

        # finalize last open message builder
        if current_mb:
            current_mb.complete()
            results.append(current_mb.get_message_data())

    return results
