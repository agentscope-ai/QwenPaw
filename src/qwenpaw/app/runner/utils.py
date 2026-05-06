# -*- coding: utf-8 -*-
import json
import logging
import platform
from datetime import datetime, timezone
from typing import List, Optional, Union
from urllib.parse import unquote, urlparse
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
from agentscope_runtime.engine.schemas.exception import (
    AgentRuntimeErrorException,
)

from ...config import load_config

logger = logging.getLogger(__name__)


def build_env_context(
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    channel: Optional[str] = None,
    working_dir: Optional[str] = None,
    add_hint: bool = True,
    user_name: Optional[str] = None,
) -> str:
    """
    Build environment context with current request context prepended.

    Args:
        session_id: Current session ID
        user_id: Current user ID
        channel: Current channel name
        working_dir: Working directory path
        add_hint: Whether to add hint context
        user_name: Display name of the current user
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
    if user_name:
        parts.append(f"-User Nme: {user_name}")
    if channel is not None:
        parts.append(f"- Channel: {channel}")

    parts.append(
        f"- OS: {platform.system()} {platform.release()} "
        f"({platform.machine()})",
    )

    if working_dir is not None:
        parts.append(f"- Working directory: {working_dir}")
    parts.append(
        f"- Current date: {now.strftime('%Y-%m-%d')} "
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
            "then use edit_file for partial updates or appending.\n"
            "  3. Use tool calls to perform actions. A response without a "
            "tool call indicates the task is complete. To continue a task, "
            "you must generate a tool call or provide useful feedback if "
            "you are blocked.\n",
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


def _abspath_from_url(url: str) -> str:
    """Extract absolute path from file:// URL.

    Percent-decodes the path so non-ASCII filenames resolve correctly.
    """
    s = url.strip()
    if s.lower().startswith("file:"):
        s = s[5:]
    s = "/" + s.lstrip("/")
    return unquote(s)


def _resolve_content_url(url: str) -> str:
    """If url is local, return filename only; frontend builds URL."""
    if not isinstance(url, str):
        return url
    if not _is_local_file_url(url):
        return url
    return _abspath_from_url(url)


# pylint: disable=too-many-branches,too-many-statements, too-many-nested-blocks
def _build_media_message_from_block(
    block: dict,
    role: str,
    metadata: dict,
) -> Message:
    output = block.get("output")
    media_message = None
    if isinstance(output, list):
        media_items = [
            item
            for item in output
            if isinstance(item, dict)
            and item.get("type") in ("image", "audio", "video", "file")
        ]
        if media_items:
            media_message = Message(
                type=MessageType.MESSAGE,
                role=role,
            )
            media_message.metadata = metadata

            for item in media_items:
                itype = item.get("type")

                if itype == "image":
                    kwargs = {}
                    source = item.get("source")
                    if (
                        isinstance(source, dict)
                        and source.get("type") == "url"
                    ):
                        kwargs["image_url"] = _resolve_content_url(
                            source.get("url", ""),
                        )
                    elif (
                        isinstance(source, dict)
                        and source.get("type") == "base64"
                    ):
                        media_type = source.get(
                            "media_type",
                            "image/jpeg",
                        )
                        base64_data = source.get("data", "")
                        kwargs[
                            "image_url"
                        ] = f"data:{media_type};base64,{base64_data}"
                    media_message.add_content(
                        new_content=ImageContent(
                            delta=False,
                            index=None,
                            **kwargs,
                        ),
                    )

                elif itype == "audio":
                    kwargs = {}
                    source = item.get("source")
                    if (
                        isinstance(source, dict)
                        and source.get("type") == "url"
                    ):
                        url = _resolve_content_url(
                            source.get("url", ""),
                        )
                        kwargs["data"] = url
                        try:
                            kwargs["format"] = urlparse(
                                url,
                            ).path.split(
                                ".",
                            )[-1]
                        except (
                            AttributeError,
                            IndexError,
                            ValueError,
                        ):
                            kwargs["format"] = None
                    elif (
                        isinstance(source, dict)
                        and source.get("type") == "base64"
                    ):
                        media_type = source.get("media_type")
                        base64_data = source.get("data", "")
                        kwargs[
                            "data"
                        ] = f"data:{media_type};base64,{base64_data}"
                        kwargs["format"] = media_type
                    media_message.add_content(
                        new_content=AudioContent(
                            delta=False,
                            index=None,
                            **kwargs,
                        ),
                    )

                elif itype == "video":
                    kwargs = {}
                    source = item.get("source")
                    if (
                        isinstance(source, dict)
                        and source.get("type") == "url"
                    ):
                        kwargs["video_url"] = _resolve_content_url(
                            source.get("url", ""),
                        )
                    elif (
                        isinstance(source, dict)
                        and source.get("type") == "base64"
                    ):
                        media_type = source.get(
                            "media_type",
                            "video/mp4",
                        )
                        base64_data = source.get("data", "")
                        kwargs[
                            "video_url"
                        ] = f"data:{media_type};base64,{base64_data}"
                    media_message.add_content(
                        new_content=VideoContent(
                            delta=False,
                            index=None,
                            **kwargs,
                        ),
                    )

                elif itype == "file":
                    kwargs = {"filename": item.get("filename", "")}
                    source = item.get("source")
                    if (
                        isinstance(source, dict)
                        and source.get("type") == "url"
                    ):
                        kwargs["file_url"] = _resolve_content_url(
                            source.get("url", ""),
                        )
                    elif (
                        isinstance(source, dict)
                        and source.get("type") == "base64"
                    ):
                        media_type = source.get(
                            "media_type",
                            "application/octet-stream",
                        )
                        base64_data = source.get("data", "")
                        kwargs[
                            "file_url"
                        ] = f"data:{media_type};base64,{base64_data}"
                    elif isinstance(source, str):
                        kwargs["file_url"] = _resolve_content_url(
                            source,
                        )
                    media_message.add_content(
                        new_content=FileContent(
                            delta=False,
                            index=None,
                            **kwargs,
                        ),
                    )
    return media_message


# pylint: disable=too-many-branches,too-many-statements, too-many-nested-blocks
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
        raise AgentRuntimeErrorException(
            code="INVALID_MESSAGE_TYPE",
            message=(
                f"Expected Msg or list[Msg], got {type(messages).__name__}"
            ),
        )

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
                        results.append(current_message.completed())
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
                        results.append(current_message.completed())
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
                    results.append(current_message.completed())

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
                    results.append(current_message.completed())

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

                media_message = _build_media_message_from_block(
                    block,
                    role,
                    metadata,
                )
                if media_message:
                    results.append(media_message)

            elif btype == "image":
                if current_type != MessageType.MESSAGE:
                    if current_message:
                        results.append(current_message.completed())
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
                        results.append(current_message.completed())
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
                        results.append(current_message.completed())
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
                        results.append(current_message.completed())
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
                        results.append(current_message.completed())
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
            results.append(current_message.completed())

    return results
