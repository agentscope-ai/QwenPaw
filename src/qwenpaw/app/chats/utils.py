# -*- coding: utf-8 -*-
import json
import logging
import platform
import re
from datetime import datetime, timedelta, timezone
from typing import Any, List, Mapping, Optional, Sequence, Union
from urllib.parse import unquote, urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from agentscope.message import Msg
from qwenpaw.agents.context.scroll.serialize import strip_headline
from qwenpaw.schemas import (
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
from qwenpaw.exceptions import (
    AgentRuntimeErrorException,
)

from ...config import load_config
from ...constant import (
    QWENPAW_MESSAGE_TAG_KEY,
    SCROLL_MEMORY_MESSAGE_TAG,
    SYNTHETIC_USER_MESSAGE_TAGS,
)

logger = logging.getLogger(__name__)


def _process_local_tz():
    """Return the process-local timezone used by ``datetime.now()``."""
    return datetime.now().astimezone().tzinfo or timezone.utc


def _normalize_msg_timestamp(ts_value: str, user_tz: ZoneInfo) -> str:
    """Normalize a Msg timestamp string into the user's timezone.

    AgentScope writes ``Msg.created_at`` with ``datetime.now().isoformat()``,
    so a naive value is a process-local wall clock — not UTC and not
    ``user_timezone``. Aware values keep their encoded offset.
    Unparseable inputs are returned unchanged.
    """
    try:
        dt_obj = datetime.fromisoformat(ts_value)
        if dt_obj.tzinfo is None:
            dt_obj = dt_obj.replace(tzinfo=_process_local_tz())
        return dt_obj.astimezone(user_tz).isoformat()
    except (ValueError, TypeError):
        return ts_value


def _is_scroll_memory_placeholder(msg: Msg) -> bool:
    """Return whether *msg* is model-only Scroll context, not transcript.

    New placeholders carry an explicit metadata tag. The structural fallback
    hides already-persisted sessions created before that tag existed, while
    remaining narrow enough not to suppress an ordinary user message that
    merely discusses ``[context compressed]``.
    """
    metadata = getattr(msg, "metadata", None)
    if (
        isinstance(metadata, dict)
        and metadata.get(QWENPAW_MESSAGE_TAG_KEY) == SCROLL_MEMORY_MESSAGE_TAG
    ):
        return True

    if msg.role != "user" or msg.name != "memory":
        return False
    text = msg.get_text_content() or ""
    return (
        text.lstrip().startswith("<system-info>")
        and "[context compressed]" in text
    )


# Visual compression collapses history/context ranges into user-role
# messages with these names. They are model-only reconstructions.
_VISUAL_PLACEHOLDER_NAMES = frozenset(
    {"visual_context", "visual_history"},
)


def _is_synthetic_user_message(msg: Msg) -> bool:
    """Return whether *msg* is a runtime-injected user-role message.

    Loop gates, stop handlers, and rubric evaluation append tagged
    ``role="user"`` stubs to keep a turn going; visual compression
    collapses history into ``visual_history`` / ``visual_context``
    user messages. None of them is user transcript — rendering them as
    user cards made the original instruction appear rewritten after a
    session switch.
    """
    if msg.role != "user":
        return False
    if msg.name in _VISUAL_PLACEHOLDER_NAMES:
        return True
    metadata = getattr(msg, "metadata", None)
    return (
        isinstance(metadata, dict)
        and metadata.get(QWENPAW_MESSAGE_TAG_KEY)
        in SYNTHETIC_USER_MESSAGE_TAGS
    )


def _is_real_user_turn_start(msg: Msg) -> bool:
    """Whether *msg* is a genuine user turn boundary — not a scroll
    placeholder, not a runtime-injected stub. The same test the db read path
    applies via ``MemorySpace._real_user_conditions`` (role='user' minus the
    same synthetic tags), kept in sync manually since one side is live
    ``Msg`` objects and the other is SQL."""
    return (
        msg.role == "user"
        and not _is_scroll_memory_placeholder(msg)
        and not _is_synthetic_user_message(msg)
    )


def first_screen_window(
    messages: List[Msg],
    limit: int,
) -> tuple[List[Msg], Optional[Msg]]:
    """Turn-aligned first-screen window: the tail of ``messages``, extended
    backward to the nearest real user turn boundary (design doc §2.1 "回合对
    齐取窗"). ``limit`` is a target size, not an exact count — keeping a turn
    whole takes priority over hitting the count exactly.

    Returns ``(window, anchor)``. ``anchor`` is the earliest real user Msg in
    the window — the endpoint resolves its id to a db ``seq`` to know where
    "load older" should resume. ``anchor`` is ``None`` when the window has no
    real user message at all (e.g. a brand new chat with nothing to page
    into yet), in which case there is nothing to anchor and pagination stops
    here.
    """
    n = len(messages)
    if n == 0:
        return [], None
    idx = max(0, n - max(1, limit))
    while idx > 0 and not _is_real_user_turn_start(messages[idx]):
        idx -= 1
    window = messages[idx:]
    anchor = next((m for m in window if _is_real_user_turn_start(m)), None)
    return window, anchor


def parse_legacy_memory_state(
    memory_raw: dict,
) -> tuple[List[Msg], str]:
    """Parse a 1.x ``InMemoryMemory.state_dict()`` payload.

    1.x stored ``{"content": [[msg_dict, marks], ...],
    "_compressed_summary": str}``.  2.0 keeps messages on
    ``AgentState.context`` instead, so this helper exists only for
    sessions on disk that pre-date the migration.  ``marks`` are dropped
    (only ``HINT`` / ``COMPRESSED`` were used and neither is reachable
    from the new state schema).

    Returns ``(messages, summary)``; either may be empty.
    """
    messages: List[Msg] = []
    for item in memory_raw.get("content", []) or []:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            payload = item[0]
        else:
            payload = item
        if isinstance(payload, dict):
            messages.append(Msg.from_dict(payload))
        elif isinstance(payload, Msg):
            messages.append(payload)
    summary = memory_raw.get("_compressed_summary") or ""
    return messages, summary


def build_env_context(
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    user_name: Optional[str] = None,
    channel: Optional[str] = None,
    working_dir: Optional[str] = None,
    add_hint: bool = True,
    default_shell: Optional[str] = None,
    project_dir: Optional[str] = None,
    active_model_name: Optional[str] = None,
) -> str:
    """
    Build environment context with current request context prepended.

    Args:
        session_id: Current session ID
        user_id: Current user ID
        user_name: Optional human-readable sender name (e.g. IM nickname).
            Only rendered when provided by the channel via channel_meta.
        channel: Current channel name
        working_dir: Working directory path
        add_hint: Whether to add hint context
        default_shell: Shell executable used by execute_shell_command.
            When provided, included in the context so the LLM can
            generate syntax appropriate for that shell.
        project_dir: When set, the agent's "Working
            directory" line is replaced with an explicit
            "Project directory" + "Agent workspace (internal)" pair
            so the LLM stops treating the workspace as home.
        active_model_name: Current active model name for runtime
            identity (e.g. "qwen-max", "gpt-4o").

    Returns:
        Formatted environment context string
    """
    parts = []

    # Runtime identity
    powered = f", powered by {active_model_name}" if active_model_name else ""
    parts.append(
        f"- About: You are a personal AI assistant{powered}. "
        f"You operate in QwenPaw, an open-source agent "
        f"framework built by AgentScope team from Qwen lab.",
    )
    parts.append(
        "- GitHub: https://github.com/agentscope-ai/QwenPaw",
    )
    parts.append(
        "- Docs: https://qwenpaw.agentscope.io/",
    )
    parts.append(
        f"- OS: {platform.system()} {platform.release()} "
        f"({platform.machine()})",
    )

    if default_shell:
        parts.append(f"- Default Shell: {default_shell}")

    if project_dir:
        parts.append(
            f"- Project directory (relative files and commands resolve "
            f"here): {project_dir}",
        )
        if working_dir is not None and str(working_dir) != str(project_dir):
            parts.append(
                f"- Agent workspace (internal — do NOT touch unless "
                f"the user explicitly asks): {working_dir}",
            )
    elif working_dir is not None:
        parts.append(f"- Working directory: {working_dir}")

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

    # Keep request-specific values after the reusable environment prefix.
    if channel is not None:
        parts.append(f"- Channel: {channel}")
    if user_name:
        parts.append(f"- User Name: {user_name}")
    if user_id is not None:
        parts.append(f"- User ID: {user_id}")
    if session_id is not None:
        parts.append(f"- Session ID: {session_id}")

    user_tz = load_config().user_timezone or "UTC"
    try:
        now = datetime.now(ZoneInfo(user_tz))
    except (ZoneInfoNotFoundError, KeyError):
        logger.warning("Invalid timezone %r, falling back to UTC", user_tz)
        now = datetime.now(timezone.utc)
        user_tz = "UTC"
    parts.append(
        f"- Current date: {now.strftime('%Y-%m-%d')} "
        f"{user_tz} ({now.strftime('%A')})",
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
        parsed = urlparse(s)
        if parsed.netloc and parsed.netloc.lower() != "localhost":
            if len(parsed.netloc) == 2 and parsed.netloc[1] == ":":
                s = f"{parsed.netloc}{parsed.path}"
            else:
                s = f"//{parsed.netloc}{parsed.path}"
        else:
            s = parsed.path
    s = unquote(s)
    if re.match(r"^/[A-Za-z]:[/\\]", s):
        return s[1:]
    return s


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

        def _resolve_media_type(item):
            if not isinstance(item, dict):
                return None
            t = item.get("type")
            if t in ("image", "audio", "video", "file"):
                return t
            if t == "data":
                src = item.get("source") or {}
                mt = src.get("media_type", "") if isinstance(src, dict) else ""
                for prefix in ("image", "audio", "video"):
                    if mt.startswith(f"{prefix}/"):
                        return prefix
                return "file"
            return None

        media_items = [
            item for item in output if _resolve_media_type(item) is not None
        ]
        if media_items:
            media_message = Message(
                type=MessageType.MESSAGE,
                role=role,
            )
            media_message.metadata = metadata

            for item in media_items:
                itype = _resolve_media_type(item)

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


# Matches the trailing <skill> block appended to a user message by
# slash-command skill expansion
# (runtime.builtin_commands._skill_fallback_handler).
_INJECTED_SKILL_BLOCK_RE = re.compile(
    r"\s*<skill\b[^>]*>.*</skill>\s*$",
    re.DOTALL,
)


def strip_injected_skill_block(text: str, role: str) -> str:
    """Hide the system-injected <skill> block from display.

    Slash-command skill expansion keeps the user's typed text at the
    head of the message and appends the skill body in a trailing
    <skill> block. The block is model-facing context; transcripts
    should show only what the user typed.
    """
    if role != "user" or "<skill" not in text:
        return text
    return _INJECTED_SKILL_BLOCK_RE.sub("", text)


def clean_display_text(text: str, role: str) -> str:
    """Hide model-facing artifacts from the transcript: the ``⟦ … ⟧``
    headline fence and the injected ``<skill>`` block. The SSE stream already
    strips the headline; the HTTP history path didn't, so it reappeared on
    reload — do both here so every display path matches. Headline first: the
    ``<skill>`` regex is ``$``-anchored, so a trailing headline would leave it
    un-anchored.
    """
    return strip_injected_skill_block(strip_headline(text) or "", role)


# pylint: disable=too-many-branches,too-many-statements, too-many-nested-blocks
def _blocks_to_messages(
    blocks: List[Any],
    *,
    role: str,
    metadata: dict,
    id_prefix: Optional[str] = None,
) -> List[Message]:
    """Dispatch one Msg's content blocks into one or more display Messages.

    Shared by :func:`agentscope_msg_to_message` (live ``Msg.content``) and
    :func:`history_rows_to_messages` (a db row's deserialized ``blocks``
    column) — both need identical text/thinking/tool_call/tool_result/media
    rendering, so this is the single place that owns it.

    When ``id_prefix`` is given, each Message this call starts gets a
    deterministic id ``f"{id_prefix}:{part_index}"`` (part_index counts every
    new Message started, in order) instead of the default random uuid4 — see
    the design doc's "还原消息 id 唯一性" rule. Passing ``None`` (the live-Msg
    path) preserves the exact previous behavior: default random ids.
    """
    results: List[Message] = []
    current_message: Optional[Message] = None
    current_type: Optional[MessageType] = None
    part_index = 0

    def start_message(msg_type: MessageType) -> Message:
        nonlocal current_message, current_type, part_index
        if current_message:
            results.append(current_message.completed())
        kwargs: dict = {"type": msg_type, "role": role}
        if id_prefix is not None:
            kwargs["id"] = f"{id_prefix}:{part_index}"
        part_index += 1
        current_message = Message(**kwargs)
        current_message.metadata = metadata
        current_type = msg_type
        return current_message

    for block in blocks:
        # Normalize pydantic block models to dict so the rest of
        # this conversion (which uses .get) handles both shapes.
        if hasattr(block, "model_dump"):
            block = block.model_dump()
        if not isinstance(block, dict):
            continue
        btype = block.get("type", "text")

        # DataBlock (2.0): map type="data" to concrete media type
        if btype == "data":
            source = block.get("source") or {}
            mt = (
                source.get("media_type", "")
                if isinstance(source, dict)
                else ""
            )
            if mt.startswith("image/"):
                btype = "image"
            elif mt.startswith("audio/"):
                btype = "audio"
            elif mt.startswith("video/"):
                btype = "video"
            else:
                btype = "file"

        if btype == "text":
            if current_type != MessageType.MESSAGE:
                start_message(MessageType.MESSAGE)

            text_content = TextContent(
                delta=False,
                index=None,
                text=clean_display_text(
                    block.get("text", ""),
                    role,
                ),
            )
            current_message.add_content(new_content=text_content)

        elif btype == "hint":
            # Hint blocks are runtime/model-facing state (for example,
            # current-time reminders). They belong in the agent context,
            # but never in a user-visible transcript restored by either
            # the console chat UI or a PawApp. Skipping it here covers the
            # live path and the db replay path at once, so scroll-back can
            # never surface a hint that live rendering hides.
            continue

        elif btype == "thinking":
            if current_type != MessageType.REASONING:
                start_message(MessageType.REASONING)

            text_content = TextContent(
                delta=False,
                index=None,
                text=block.get("thinking", ""),
            )
            current_message.add_content(new_content=text_content)

        elif btype in ("tool_use", "tool_call"):
            start_message(MessageType.PLUGIN_CALL)

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
            start_message(MessageType.PLUGIN_CALL_OUTPUT)

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

            tool_state = block.get("state")
            if hasattr(tool_state, "value"):
                tool_state = tool_state.value
            if tool_state is not None:
                output_data["state"] = tool_state

            data_content = DataContent(
                delta=False,
                index=None,
                data=output_data,
            )
            current_message.add_content(new_content=data_content)

        elif btype == "image":
            if current_type != MessageType.MESSAGE:
                start_message(MessageType.MESSAGE)

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
                start_message(MessageType.MESSAGE)

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
                start_message(MessageType.MESSAGE)

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
                start_message(MessageType.MESSAGE)

            kwargs = {
                "filename": block.get("filename") or block.get("name"),
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
                start_message(MessageType.MESSAGE)

            text_content = TextContent(
                delta=False,
                index=None,
                text=str(block),
            )
            current_message.add_content(new_content=text_content)

    if current_message:
        results.append(current_message.completed())

    return results


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

    user_tz_name = load_config().user_timezone or "UTC"
    try:
        user_tz = ZoneInfo(user_tz_name)
    except (ZoneInfoNotFoundError, KeyError):
        user_tz = timezone.utc

    for msg in msgs:
        if _is_scroll_memory_placeholder(msg):
            continue
        if _is_synthetic_user_message(msg):
            continue
        role = msg.role or "assistant"

        ts_value = msg.timestamp
        if ts_value:
            ts_value = _normalize_msg_timestamp(ts_value, user_tz)

        # ``finished_at`` marks when the reply actually completed (stamped
        # on REPLY_END by the runtime executor).  ``timestamp`` is the
        # created_at alias — the first-segment save time — which can be
        # far earlier for turns with long tool calls.  Expose both so the
        # frontend can display the true completion time; ``finished_at``
        # stays None for messages that never received a stamp (e.g. legacy
        # sessions), letting consumers fall back to ``timestamp``.
        finished_value = getattr(msg, "finished_at", None)
        if finished_value:
            finished_value = _normalize_msg_timestamp(finished_value, user_tz)

        metadata = {
            "original_id": msg.id,
            "original_name": msg.name,
            "metadata": msg.metadata,
            "timestamp": ts_value,
            "finished_at": finished_value or None,
        }

        if isinstance(msg.content, str):
            message = Message(type=MessageType.MESSAGE, role=role)
            message.metadata = metadata
            text_content = TextContent(
                delta=False,
                index=None,
                text=clean_display_text(msg.content, role),
            )
            message.add_content(new_content=text_content)
            results.append(message)
            continue

        results.extend(
            _blocks_to_messages(
                msg.content,
                role=role,
                metadata=metadata,
                id_prefix=None,
            ),
        )

    return results


# ---------------------------------------------------------------------------
# Reconstruction from ``conversation_history`` db rows (the pagination read
# path — see ``docs/session-scroll-loading-design.md`` §2.2). This mirrors
# ``agentscope_msg_to_message`` above but starts from persisted rows instead
# of live ``Msg`` objects.
# ---------------------------------------------------------------------------


def _row_is_synthetic_user_message(row: Any) -> bool:
    """Row-level analog of :func:`_is_synthetic_user_message`.

    Scroll's model-only placeholders never reach ``conversation_history``
    (``ScrollContextManager._persist_new`` skips them before persisting), so
    only the synthetic-user-stub check applies to db rows.
    """
    if row["role"] != "user":
        return False
    if row["name"] in _VISUAL_PLACEHOLDER_NAMES:
        return True
    raw_metadata = row["metadata"]
    if not raw_metadata:
        return False
    try:
        metadata = json.loads(raw_metadata)
    except (TypeError, ValueError):
        return False
    return (
        isinstance(metadata, dict)
        and metadata.get(QWENPAW_MESSAGE_TAG_KEY)
        in SYNTHETIC_USER_MESSAGE_TAGS
    )


def _parsed_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt_obj = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if dt_obj.tzinfo is None:
        dt_obj = dt_obj.replace(tzinfo=timezone.utc)
    return dt_obj


def _row_display_metadata(row: Any, user_tz: ZoneInfo) -> dict:
    ts_value = row["created_at"]
    if ts_value:
        ts_value = _normalize_msg_timestamp(ts_value, user_tz)
    raw_metadata = row["metadata"]
    parsed_metadata = None
    if raw_metadata:
        try:
            parsed_metadata = json.loads(raw_metadata)
        except (TypeError, ValueError):
            parsed_metadata = None
    return {
        "original_id": row["dedup_key"],
        "original_name": row["name"],
        "metadata": parsed_metadata,
        "timestamp": ts_value,
        # ``conversation_history`` has no ``finished_at`` column, so a
        # scrolled-back message can never carry a real completion stamp.
        # Emit the key anyway (as None) to keep the metadata shape identical
        # to the live path — consumers already fall back to ``timestamp``
        # when it's None, which is exactly the desired behavior here.
        "finished_at": None,
    }


def _row_blocks(row: Any) -> List[Any]:
    raw_blocks = row["blocks"]
    if not raw_blocks:
        return []
    try:
        parsed = json.loads(raw_blocks)
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def _tool_placeholder_message(
    *,
    call_id: Optional[str],
    call_name: Optional[str],
    role: str,
    metadata: dict,
    id_prefix: Optional[str],
    part_index: int,
    expired: bool,
) -> Message:
    """A stand-in card for a tool call whose result row can't be found.

    ``expired`` distinguishes a result the retention policy purged
    (``metadata.tool_result_expired``) from one that simply hasn't landed
    yet within its retention window (``metadata.tool_result_pending`` — the
    caller logs a warning for this case since it should be transient).
    """
    output_data = FunctionCallOutput(
        call_id=call_id,
        name=call_name,
        output="工具详情已过期" if expired else "工具结果暂不可用",
    ).model_dump(exclude_none=True)
    message_metadata = dict(metadata)
    flag = "tool_result_expired" if expired else "tool_result_pending"
    message_metadata[flag] = True
    kwargs: dict = {"type": MessageType.PLUGIN_CALL_OUTPUT, "role": role}
    if id_prefix is not None:
        kwargs["id"] = f"{id_prefix}:{part_index}"
    message = Message(**kwargs)
    message.metadata = message_metadata
    message.add_content(
        new_content=DataContent(delta=False, index=None, data=output_data),
    )
    return message.completed()


def missing_tool_call_ids(rows: Sequence[Any]) -> List[str]:
    """Tool_call ids referenced within ``rows`` with no matching tool_result
    row also in ``rows`` — candidates for a supplemental cross-page db lookup
    (``history.fetch_tool_results_by_call_ids``) before calling
    :func:`history_rows_to_messages`, so a call split across a page boundary
    isn't confused with one whose result was genuinely never persisted.
    """
    in_page_results: set = set()
    for row in rows:
        if row["kind"] == "tool_result":
            call_id = row["tool_call_id"] or row["dedup_key"]
            if call_id:
                in_page_results.add(call_id)

    call_ids: List[str] = []
    for row in rows:
        if row["kind"] not in ("context_msg", "model_turn"):
            continue
        for block in _row_blocks(row):
            if (
                isinstance(block, dict)
                and block.get("type") in ("tool_use", "tool_call")
                and block.get("id")
            ):
                call_ids.append(block.get("id"))
    return [c for c in dict.fromkeys(call_ids) if c not in in_page_results]


def history_rows_to_messages(
    rows: Sequence[Any],
    *,
    retention_days: int = 30,
    external_tool_results: Optional[Mapping[str, Any]] = None,
) -> List[Message]:
    """Reconstruct display Messages from ``conversation_history`` db rows.

    Mirrors :func:`agentscope_msg_to_message` but reads persisted rows
    instead of live ``Msg`` objects: ``context_msg``/``model_turn`` rows are
    rendered via the same :func:`_blocks_to_messages` dispatcher used by the
    live path (so text, thinking and tool-call parts round-trip identically),
    and a matching ``tool_result`` row is spliced in right after its
    ``tool_call`` block by ``tool_call_id`` (= db ``dedup_key``).

    ``rows`` must already be seq-ascending (oldest first) and is treated as
    one page: a ``tool_result`` row whose call isn't anywhere in ``rows``
    renders as a standalone orphan card instead of being silently dropped.
    ``external_tool_results`` (keyed by ``tool_call_id``) lets the caller
    supply results that live outside this page's seq range, so "no result
    row in this page" and "no result row anywhere in history" aren't
    confused — the latter is what actually drives the expired/pending
    placeholder.

    Each reconstructed Message gets a deterministic id
    ``f"{original_id}:{part_index}"`` (the design doc's "还原消息 id 唯一性"
    rule), so the same db row always reconstructs to the same ids across
    pages and reloads.
    """
    external_tool_results = external_tool_results or {}
    user_tz_name = load_config().user_timezone or "UTC"
    try:
        user_tz = ZoneInfo(user_tz_name)
    except (ZoneInfoNotFoundError, KeyError):
        user_tz = timezone.utc

    cutoff: Optional[datetime] = None
    if retention_days and retention_days > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

    in_page_results: dict = {}
    in_page_calls: set = set()
    for row in rows:
        kind = row["kind"]
        if kind == "tool_result":
            call_id = row["tool_call_id"] or row["dedup_key"]
            if call_id:
                in_page_results[call_id] = row
        elif kind in ("context_msg", "model_turn"):
            for block in _row_blocks(row):
                if (
                    isinstance(block, dict)
                    and block.get("type") in ("tool_use", "tool_call")
                    and block.get("id")
                ):
                    in_page_calls.add(block.get("id"))

    def render_tool_result_row(row: Any) -> List[Message]:
        blocks = _row_blocks(row) or [
            {
                "type": "tool_result",
                "id": row["tool_call_id"],
                "name": row["name"],
                "output": row["content"],
                "state": row["tool_state"],
            },
        ]
        return _blocks_to_messages(
            blocks,
            role=row["role"] or "assistant",
            metadata=_row_display_metadata(row, user_tz),
            id_prefix=row["dedup_key"] or row["tool_call_id"],
        )

    results: List[Message] = []
    for row in rows:
        kind = row["kind"]

        if kind == "tool_result":
            call_id = row["tool_call_id"] or row["dedup_key"]
            if call_id and call_id in in_page_calls:
                # Rendered inline by its tool_call's turn row below (or
                # above it — the pre-scan already accounted for it) — don't
                # double-render the same result.
                continue
            results.extend(render_tool_result_row(row))
            continue

        if kind not in ("context_msg", "model_turn"):
            # Recall-tool turns and any other non-transcript kind are not
            # displayed, mirroring the live path (they never reach the
            # SSE/history transcript either).
            continue
        if _row_is_synthetic_user_message(row):
            continue

        original_id = row["dedup_key"]
        role = row["role"] or ("assistant" if kind == "model_turn" else "user")
        metadata = _row_display_metadata(row, user_tz)
        blocks = _row_blocks(row)

        if blocks:
            turn_messages = _blocks_to_messages(
                blocks,
                role=role,
                metadata=metadata,
                id_prefix=original_id,
            )
            results.extend(turn_messages)
            part_index = len(turn_messages)
            for block in blocks:
                if not (
                    isinstance(block, dict)
                    and block.get("type") in ("tool_use", "tool_call")
                ):
                    continue
                call_id = block.get("id")
                result_row = in_page_results.get(call_id) or (
                    external_tool_results.get(call_id) if call_id else None
                )
                if result_row is not None:
                    results.extend(render_tool_result_row(result_row))
                    continue
                created_dt = _parsed_datetime(row["created_at"])
                expired = bool(
                    cutoff is not None
                    and created_dt is not None
                    and created_dt < cutoff,
                )
                if not expired:
                    logger.warning(
                        "history_rows_to_messages: tool_result missing for "
                        "call_id=%s (turn %s) and not past the retention "
                        "window; rendering as unavailable",
                        call_id,
                        original_id,
                    )
                results.append(
                    _tool_placeholder_message(
                        call_id=call_id,
                        call_name=block.get("name"),
                        role=role,
                        metadata=metadata,
                        id_prefix=original_id,
                        part_index=part_index,
                        expired=expired,
                    ),
                )
                part_index += 1
        elif row["content"]:
            message = Message(
                type=MessageType.MESSAGE,
                role=role,
                **({"id": f"{original_id}:0"} if original_id else {}),
            )
            message.metadata = metadata
            message.add_content(
                new_content=TextContent(
                    delta=False,
                    index=None,
                    text=clean_display_text(row["content"], role),
                ),
            )
            results.append(message.completed())

    return results
