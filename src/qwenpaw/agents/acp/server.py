# -*- coding: utf-8 -*-
"""QwenPaw ACP Agent server.

Exposes QwenPaw as an ACP-compliant agent that external clients
(Zed, OpenCode, etc.) can connect to via stdio JSON-RPC.

Uses the full ``Workspace`` lifecycle so the ACP agent has exactly
the same capabilities as the web console (MCP tools, memory,
sub-agent delegation, etc.).
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

from acp import (
    Agent,
    InitializeResponse,
    LoadSessionResponse,
    NewSessionResponse,
    PromptResponse,
    SetSessionModelResponse,
    run_agent,
    start_tool_call,
    text_block,
    tool_content,
    update_agent_message,
    update_agent_thought,
    update_tool_call,
)
from acp.interfaces import Client
from acp.schema import (
    AgentCapabilities,
    AgentMessageChunk,
    AudioContentBlock,
    AvailableCommand,
    AvailableCommandsUpdate,
    ClientCapabilities,
    CloseSessionResponse,
    EmbeddedResourceContentBlock,
    HttpMcpServer,
    ImageContentBlock,
    Implementation,
    ListSessionsResponse,
    McpServerStdio,
    ResourceContentBlock,
    ResumeSessionResponse,
    SessionCapabilities,
    SessionCloseCapabilities,
    SessionConfigOptionSelect,
    SessionConfigSelectOption,
    SessionInfo,
    SessionListCapabilities,
    SessionResumeCapabilities,
    SetSessionConfigOptionResponse,
    SseMcpServer,
    TextContentBlock,
)
from agentscope.message import Msg
from agentscope_runtime.engine.schemas.agent_schemas import (
    AgentRequest,
    Message,
)

from ...__version__ import __version__
from ...constant import WORKING_DIR
from ...config.config import ModelSlotConfig
from ...providers.provider_manager import ProviderManager
from ...agents.command_handler import SYSTEM_COMMAND_DESCRIPTIONS
from ...agents.mission.handler import MISSION_COMMAND_DESCRIPTIONS

logger = logging.getLogger(__name__)

# Control commands that have a dedicated ACP affordance and would be
# redundant (or confusing) as typed slash commands over ACP:
#   /model    → session/set_model
#   /approval, /approve, /deny → session/request_permission round-trip
#   /stop     → session/cancel notification
# They are handled natively and so are not advertised for autocompletion.
_ACP_REDUNDANT_COMMANDS = frozenset(
    {"model", "approval", "approve", "deny", "stop"},
)

# ``_meta`` key set on an ``agent_message_chunk`` to mark it as an error,
# so ACP clients can render it distinctly (e.g. the paw TUI shows it in its
# error style). Clients that ignore ``_meta`` still display the text.
ACP_ERROR_META_KEY = "qwenpaw.error"

# ``_meta`` key on the new/load-session response carrying the resolved agent
# id, so ACP clients can show which agent they're talking to (the protocol
# has no standard field for it).
ACP_AGENT_META_KEY = "qwenpaw.agent"


PromptBlocks = list[
    TextContentBlock
    | ImageContentBlock
    | AudioContentBlock
    | ResourceContentBlock
    | EmbeddedResourceContentBlock
]


def _extract_text(
    blocks: PromptBlocks,
) -> str:
    """Pull plain text from ACP prompt content blocks."""
    parts: list[str] = []
    for block in blocks:
        if isinstance(block, dict):
            text = block.get("text", "")
        elif isinstance(block, TextContentBlock):
            text = block.text
        else:
            text = getattr(block, "text", "")
        if text:
            parts.append(str(text))
    return "\n".join(parts)


class _StreamTracker:
    """Convert agentscope's snapshot-style messages to ACP event stream.

    agentscope emits cumulative snapshots (each message contains the full
    state so far).  ACP expects an event stream (each update is a delta).
    This tracker maintains the necessary state to perform that conversion
    for text, thinking, and tool-call events.
    """

    def __init__(self) -> None:
        self._prev_text: str = ""
        self._prev_thinking: str = ""
        self._seen_tool_ids: set[str] = set()
        self._tool_inputs: dict[str, Any] = {}

    def delta_text(self, cumulative: str) -> str:
        """Return only the new portion of the text."""
        if cumulative.startswith(self._prev_text):
            delta = cumulative[len(self._prev_text) :]
        else:
            delta = cumulative
        self._prev_text = cumulative
        return delta

    def delta_thinking(self, cumulative: str) -> str:
        """Return only the new portion of the thinking."""
        if cumulative.startswith(self._prev_thinking):
            delta = cumulative[len(self._prev_thinking) :]
        else:
            delta = cumulative
        self._prev_thinking = cumulative
        return delta

    def is_new_tool_call(self, tool_id: str) -> bool:
        """Return True only the first time *tool_id* is seen."""
        if tool_id in self._seen_tool_ids:
            return False
        self._seen_tool_ids.add(tool_id)
        return True

    def tool_input_changed(self, tool_id: str, raw_input: Any) -> bool:
        """Return True when *raw_input* is non-empty and differs from the
        last value recorded for *tool_id*, recording the new value.

        Tool-call arguments stream in, so the first sighting of a call
        often carries empty/partial input; this lets the caller emit an
        ``update`` once the populated arguments arrive (the initial
        ``start`` would otherwise pin an empty ``rawInput``).
        """
        if not raw_input:
            return False
        if self._tool_inputs.get(tool_id) == raw_input:
            return False
        self._tool_inputs[tool_id] = raw_input
        return True


def _msg_to_updates(  # pylint: disable=too-many-branches
    msg: Any,
    tracker: _StreamTracker | None = None,
) -> list[Any]:
    """Convert a QwenPaw Msg into ACP session update(s).

    When *tracker* is provided, text and thinking content blocks are
    emitted as **incremental** deltas rather than cumulative snapshots,
    matching the ACP standard used by QwenCode and Qoder.
    """
    updates: list[Any] = []
    metadata = getattr(msg, "metadata", {}) or {}
    content = getattr(msg, "content", None)
    role = getattr(msg, "role", "assistant")

    if role == "system":
        if isinstance(content, list):
            _content_blocks_to_updates(content, updates, tracker)
        if not updates:
            text = _get_msg_text(msg)
            if text:
                updates.append(
                    update_agent_thought(text_block(text)),
                )
        return updates

    tool_calls = metadata.get("tool_calls")
    if isinstance(tool_calls, list):
        for tc in tool_calls:
            if not isinstance(tc, dict):
                continue
            tc_id = str(tc.get("id") or uuid4().hex[:8])
            inp = tc.get("input")
            if not tracker or tracker.is_new_tool_call(tc_id):
                updates.append(
                    start_tool_call(
                        tc_id,
                        str(tc.get("name") or "tool"),
                        status="in_progress",
                        raw_input=inp,
                    ),
                )
                if tracker:
                    # Record what we sent so a later, fuller input is
                    # recognised as a change (see tool_input_changed).
                    tracker.tool_input_changed(tc_id, inp)
            elif tracker and tracker.tool_input_changed(tc_id, inp):
                # Arguments finished streaming after the start event.
                updates.append(
                    update_tool_call(tc_id, raw_input=inp),
                )
        return updates

    tool_responses = metadata.get("tool_responses")
    if isinstance(tool_responses, list):
        for tr in tool_responses:
            if not isinstance(tr, dict):
                continue
            updates.append(
                update_tool_call(
                    str(tr.get("id") or uuid4().hex[:8]),
                    status="completed",
                    content=_tool_result_content(tr.get("output", "")),
                ),
            )
        return updates

    if isinstance(content, list):
        _content_blocks_to_updates(content, updates, tracker)

    if not updates:
        text = _get_msg_text(msg)
        if text:
            if tracker:
                text = tracker.delta_text(text)
            if text:
                updates.append(
                    update_agent_message(text_block(text)),
                )

    return updates


def _content_blocks_to_updates(
    content: list[Any],
    updates: list[Any],
    tracker: _StreamTracker | None = None,
) -> None:
    """Map Msg content blocks to ACP updates."""
    for block in content:
        block_type, block_data = _normalise_block(block)
        if block_type == "thinking":
            _emit_thinking(block_data, tracker, updates)
        elif block_type == "text":
            _emit_text(block_data, tracker, updates)
        elif block_type == "tool_use":
            tc_id = str(block_data.get("id") or uuid4().hex[:8])
            inp = block_data.get("input")
            if not tracker or tracker.is_new_tool_call(tc_id):
                updates.append(
                    start_tool_call(
                        tc_id,
                        str(block_data.get("name") or "tool"),
                        status="in_progress",
                        raw_input=inp,
                    ),
                )
                if tracker:
                    tracker.tool_input_changed(tc_id, inp)
            elif tracker and tracker.tool_input_changed(tc_id, inp):
                updates.append(
                    update_tool_call(tc_id, raw_input=inp),
                )
        elif block_type == "tool_result":
            updates.append(
                update_tool_call(
                    str(block_data.get("id") or uuid4().hex[:8]),
                    status="completed",
                    content=_tool_result_content(
                        block_data.get("output", ""),
                    ),
                ),
            )


def _extract_tool_output(output: Any) -> str:
    """Extract plain text from a tool output value.

    The output may be a string, a list of content blocks, or another
    structure — normalise everything to a flat string. File/media blocks
    (image/audio/video/file with a URL source, e.g. from
    ``send_file_to_user``) are rendered as a readable ``filename`` line
    rather than a raw dict repr; the URL itself travels as a separate
    ``resource_link`` content block (see ``_tool_result_content``).
    """
    if isinstance(output, str):
        return output
    if isinstance(output, list):
        parts = []
        for item in output:
            # Works for both dict blocks and attribute-style block objects
            # (e.g. agentscope ImageBlock/TextBlock from send_file_to_user).
            text = (
                item.get("text")
                if isinstance(item, dict)
                else getattr(item, "text", None)
            )
            if text:
                parts.append(text)
                continue
            media = _media_block_url(item)
            if media is not None:
                _url, name, _mime = media
                parts.append(f"📎 {name}")
                continue
            parts.append(str(item))
        return "\n".join(p for p in parts if p)
    return str(output)


def _media_block_url(
    item: Any,
) -> tuple[str, str, str | None] | None:
    """Return ``(url, name, mime_type)`` for an image/audio/video/file block
    that carries a URL source, else ``None``.

    Handles both dict blocks (e.g. agentscope ``ImageBlock``/``FileBlock``)
    and attribute-style objects.
    """
    if isinstance(item, dict):
        btype = item.get("type")
        source = item.get("source")
        name = item.get("filename") or item.get("name")
        mime = item.get("mime_type") or item.get("mimeType")
    else:
        btype = getattr(item, "type", None)
        source = getattr(item, "source", None)
        name = getattr(item, "filename", None) or getattr(item, "name", None)
        mime = getattr(item, "mime_type", None)
    if btype not in ("image", "audio", "video", "file"):
        return None
    if isinstance(source, dict):
        url = source.get("url")
    else:
        url = getattr(source, "url", None)
    if not url or not isinstance(url, str):
        return None
    if not name:
        name = url.rstrip("/").rsplit("/", 1)[-1] or url
    return url, name, mime


def _tool_result_content(output: Any) -> list[Any]:
    """Build the ACP tool-call ``content`` for a completed tool result.

    Always includes the flattened text; additionally appends a
    ``resource_link`` block for every **local** ``file://`` media block in
    the output so ACP clients (e.g. the paw TUI) can offer a clickable link
    to the file the agent sent via ``send_file_to_user``. Remote URLs
    (http/https/...) are intentionally not turned into resource links — they
    still appear as a readable ``📎`` line in the text — so clients are not
    nudged into treating untrusted remote URLs as openable resources.
    """
    contents: list[Any] = [
        tool_content(text_block(_extract_tool_output(output))),
    ]
    if isinstance(output, list):
        for item in output:
            media = _media_block_url(item)
            if media is None:
                continue
            url, name, mime = media
            if not url.startswith("file://"):
                continue
            contents.append(
                tool_content(
                    ResourceContentBlock(
                        type="resource_link",
                        uri=url,
                        name=name,
                        mime_type=mime,
                    ),
                ),
            )
    return contents


def _normalise_block(block: Any) -> tuple[str, dict[str, Any]]:
    """Return ``(block_type, data_dict)`` for both dict and object blocks."""
    if isinstance(block, dict):
        return block.get("type", "text"), block
    btype = getattr(block, "type", "text") or "text"
    data: dict[str, Any] = {}
    for attr in ("text", "thinking", "id", "name", "output", "input"):
        val = getattr(block, attr, None)
        if val is not None:
            data[attr] = val
    return btype, data


def _emit_thinking(
    data: dict[str, Any],
    tracker: _StreamTracker | None,
    updates: list[Any],
) -> None:
    thinking = data.get("thinking", "")
    if tracker:
        thinking = tracker.delta_thinking(thinking)
    if thinking:
        updates.append(update_agent_thought(text_block(thinking)))


def _emit_text(
    data: dict[str, Any],
    tracker: _StreamTracker | None,
    updates: list[Any],
) -> None:
    text = data.get("text", "")
    if tracker:
        text = tracker.delta_text(text)
    if text:
        updates.append(update_agent_message(text_block(text)))


def _get_msg_text(msg: Any) -> str:
    """Extract plain text from a Msg."""
    get_text = getattr(msg, "get_text_content", None)
    if callable(get_text):
        return get_text() or ""
    content = getattr(msg, "content", "")
    if isinstance(content, str):
        return content
    return ""


class QwenPawACPAgent(Agent):
    """ACP Agent backed by a full ``Workspace``.

    Instead of creating a bare ``AgentRunner``, this class boots a
    complete ``Workspace`` — the same lifecycle the web console uses —
    so MCP tools, memory, chat persistence, sub-agent calls, etc. are
    all available.
    """

    _conn: Client

    MODE_CONFIG_ID = "mode"
    MODE_DEFAULT = "default"
    MODE_BYPASS = "bypassPermissions"

    def __init__(
        self,
        agent_id: str | None = None,
        workspace_dir: Path | None = None,
    ):
        self._agent_id = agent_id
        self._workspace_dir = workspace_dir
        self._sessions: dict[str, dict[str, Any]] = {}
        self._cancel_events: dict[str, asyncio.Event] = {}
        self._workspace: Any | None = None
        self._workspace_ready = False

    def on_connect(self, conn: Client) -> None:
        self._conn = conn

    # ------------------------------------------------------------------
    # Workspace bootstrap (mirrors the web-app lifespan)
    # ------------------------------------------------------------------

    def _resolve_agent_id(self) -> str:
        """Return the effective agent id."""
        if self._agent_id is not None:
            return self._agent_id

        from ...config.utils import load_config

        config = load_config()
        agents_cfg = getattr(config, "agents", None)
        if agents_cfg is not None:
            aid = getattr(agents_cfg, "active_agent", None)
            if aid:
                return aid
        return "default"

    def _resolve_workspace_dir(
        self,
        agent_id: str,
    ) -> Path:
        """Return the effective workspace directory."""
        if self._workspace_dir is not None:
            return self._workspace_dir
        return WORKING_DIR / "workspaces" / agent_id

    async def _ensure_workspace(self) -> Any:
        """Boot a full ``Workspace`` (once) and return its runner."""
        if self._workspace is not None and self._workspace_ready:
            runner = self._workspace.runner
            if runner is None:
                raise RuntimeError(
                    "Workspace runner is not available after startup",
                )
            return runner

        from ...app.workspace.workspace import Workspace

        agent_id = self._resolve_agent_id()
        workspace_dir = self._resolve_workspace_dir(agent_id)

        workspace = Workspace(
            agent_id=agent_id,
            workspace_dir=str(workspace_dir),
            defer_mcp_startup=True,
        )
        await workspace.start()

        runner = workspace.runner
        if runner is None:
            raise RuntimeError(
                "Workspace started but runner is not available. "
                "Check agent configuration and workspace setup.",
            )
        await runner.init_handler()

        self._workspace = workspace
        self._workspace_ready = True
        logger.info(
            "QwenPaw ACP Agent workspace started: agent_id=%s workspace=%s",
            agent_id,
            workspace_dir,
        )
        return runner

    async def _shutdown_workspace(self) -> None:
        """Gracefully stop the workspace."""
        if self._workspace is not None:
            try:
                await self._workspace.stop(final=True)
            except Exception:
                logger.exception(
                    "Error stopping ACP workspace",
                )
            self._workspace = None
            self._workspace_ready = False

    # ------------------------------------------------------------------
    # ACP protocol methods
    # ------------------------------------------------------------------

    async def initialize(  # pylint: disable=unused-argument
        self,
        protocol_version: int,
        client_capabilities: ClientCapabilities | None = None,
        client_info: Implementation | None = None,
        **kwargs: Any,
    ) -> InitializeResponse:
        logger.info(
            "ACP initialize: version=%d client=%s",
            protocol_version,
            client_info,
        )
        return InitializeResponse(
            protocol_version=protocol_version,
            agent_capabilities=AgentCapabilities(
                load_session=True,
                session_capabilities=SessionCapabilities(
                    close=SessionCloseCapabilities(),
                    list=SessionListCapabilities(),
                    resume=SessionResumeCapabilities(),
                ),
            ),
            agent_info=Implementation(
                name="qwenpaw",
                title="QwenPaw",
                version=__version__,
            ),
        )

    async def new_session(  # pylint: disable=unused-argument
        self,
        cwd: str,
        mcp_servers: (
            list[HttpMcpServer | SseMcpServer | McpServerStdio] | None
        ) = None,
        **kwargs: Any,
    ) -> NewSessionResponse:
        session_id = uuid4().hex
        self._sessions[session_id] = {
            "cwd": cwd,
            "user_id": f"acp_{session_id[:8]}",
            "mode": self.MODE_DEFAULT,
        }
        logger.info(
            "ACP new_session: id=%s cwd=%s",
            session_id,
            cwd,
        )
        # Advertise slash commands after the response is sent, so the
        # client has learned this session_id first.
        asyncio.create_task(self._advertise_commands(session_id))
        return NewSessionResponse(
            session_id=session_id,
            config_options=self._build_config_options(session_id),
            field_meta=self._session_meta(),
        )

    async def load_session(  # pylint: disable=unused-argument
        self,
        cwd: str,
        session_id: str,
        mcp_servers: (
            list[HttpMcpServer | SseMcpServer | McpServerStdio] | None
        ) = None,
        **kwargs: Any,
    ) -> LoadSessionResponse | None:
        self._sessions[session_id] = {
            "cwd": cwd,
            "user_id": f"acp_{session_id[:8]}",
            "mode": self.MODE_DEFAULT,
        }
        logger.info(
            "ACP load_session: id=%s cwd=%s",
            session_id,
            cwd,
        )
        asyncio.create_task(self._advertise_commands(session_id))
        return LoadSessionResponse(field_meta=self._session_meta())

    async def prompt(  # pylint: disable=too-many-locals,unused-argument
        self,
        prompt: PromptBlocks,
        session_id: str,
        message_id: str | None = None,
        **kwargs: Any,
    ) -> PromptResponse:
        logger.info(
            "ACP prompt: session=%s",
            session_id,
        )

        text = _extract_text(prompt)
        if not text:
            return PromptResponse(stop_reason="end_turn")

        runner = await self._ensure_workspace()
        session_info = self._sessions.get(
            session_id,
            {},
        )
        user_id = session_info.get(
            "user_id",
            f"acp_{session_id[:8]}",
        )

        cancel_event = asyncio.Event()
        self._cancel_events[session_id] = cancel_event

        msgs = [
            Msg(
                name="user",
                role="user",
                content=text,
            ),
        ]

        session_mode = session_info.get("mode", self.MODE_DEFAULT)
        request_context: dict[str, str] = {}
        if session_mode == self.MODE_BYPASS:
            request_context["_headless_tool_guard"] = "false"

        request = AgentRequest(
            input=[
                Message(
                    role="user",
                    content=[
                        {"type": "text", "text": text},
                    ],
                ),
            ],
            session_id=session_id,
            user_id=user_id,
            request_context=request_context or None,
        )

        tracker = _StreamTracker()

        try:
            async for msg, _is_last in runner.query_handler(
                msgs,
                request=request,
            ):
                if cancel_event.is_set():
                    logger.info(
                        "ACP prompt cancelled: session=%s",
                        session_id,
                    )
                    break

                updates = _msg_to_updates(msg, tracker)
                for upd in updates:
                    await self._conn.session_update(
                        session_id=session_id,
                        update=upd,
                    )

                # After each message, check for new usage data.
                # Each LLM invocation writes usage; poll here so
                # multi-step prompts (with tool calls) report usage
                # per LLM call, matching QwenCode behaviour.
                await self._emit_usage_if_available(session_id)
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception(
                "ACP prompt error: session=%s",
                session_id,
            )
            # Surface the failure to the client instead of ending the turn
            # silently, so ACP UIs (e.g. the paw TUI) can show it.
            await self._report_prompt_error(session_id, exc)
        finally:
            self._cancel_events.pop(session_id, None)

        # Final sweep: catch any usage that arrived after the last
        # streamed message (e.g., single-turn prompts with no tools).
        await self._emit_usage_if_available(session_id)

        return PromptResponse(stop_reason="end_turn")

    async def close_session(  # pylint: disable=unused-argument
        self,
        session_id: str,
        **kwargs: Any,
    ) -> CloseSessionResponse | None:
        logger.info("ACP close_session: session=%s", session_id)
        self._sessions.pop(session_id, None)
        self._cancel_events.pop(session_id, None)
        return CloseSessionResponse()

    async def list_sessions(  # pylint: disable=unused-argument
        self,
        cursor: str | None = None,
        cwd: str | None = None,
        **kwargs: Any,
    ) -> ListSessionsResponse:
        logger.info("ACP list_sessions: cwd=%s", cwd)
        sessions: list[SessionInfo] = []
        for sid, info in self._sessions.items():
            sess_cwd = info.get("cwd", "")
            if cwd is not None and sess_cwd != cwd:
                continue
            sessions.append(
                SessionInfo(
                    session_id=sid,
                    cwd=sess_cwd,
                    title=f"ACP session {sid[:8]}",
                ),
            )
        return ListSessionsResponse(sessions=sessions)

    async def resume_session(  # pylint: disable=unused-argument
        self,
        cwd: str,
        session_id: str,
        mcp_servers: (
            list[HttpMcpServer | SseMcpServer | McpServerStdio] | None
        ) = None,
        **kwargs: Any,
    ) -> ResumeSessionResponse:
        logger.info(
            "ACP resume_session: id=%s cwd=%s",
            session_id,
            cwd,
        )
        if session_id not in self._sessions:
            self._sessions[session_id] = {
                "cwd": cwd,
                "user_id": f"acp_{session_id[:8]}",
                "mode": self.MODE_DEFAULT,
            }
        else:
            self._sessions[session_id]["cwd"] = cwd
        return ResumeSessionResponse()

    async def set_session_model(  # pylint: disable=unused-argument
        self,
        model_id: str,
        session_id: str,
        **kwargs: Any,
    ) -> SetSessionModelResponse | None:
        logger.info(
            "ACP set_session_model: session=%s model=%s",
            session_id,
            model_id,
        )
        try:
            await self._switch_model(model_id)
        except Exception:
            logger.exception(
                "Failed to switch model to %s",
                model_id,
            )
            return None
        logger.info(
            "Model switched to %s for agent %s",
            model_id,
            self._resolve_agent_id(),
        )
        return SetSessionModelResponse()

    async def set_config_option(  # pylint: disable=unused-argument
        self,
        config_id: str,
        session_id: str,
        value: str | bool,
        **kwargs: Any,
    ) -> SetSessionConfigOptionResponse | None:
        logger.info(
            "ACP set_config_option: session=%s config=%s value=%s",
            session_id,
            config_id,
            value,
        )
        if config_id == self.MODE_CONFIG_ID:
            if value not in (self.MODE_DEFAULT, self.MODE_BYPASS):
                raise ValueError(
                    f"Invalid mode value: {value!r}. "
                    f"Must be '{self.MODE_DEFAULT}' or "
                    f"'{self.MODE_BYPASS}'.",
                )
            str_value = str(value)
            if str_value == self.MODE_BYPASS:
                logger.warning(
                    "Tool guard DISABLED for session %s — all tool "
                    "calls will bypass security checks.",
                    session_id,
                )
            if session_id in self._sessions:
                self._sessions[session_id]["mode"] = str_value
            return SetSessionConfigOptionResponse(
                config_options=self._build_config_options(session_id),
            )
        return None

    async def cancel(  # pylint: disable=unused-argument
        self,
        session_id: str,
        **kwargs: Any,
    ) -> None:
        logger.info(
            "ACP cancel: session=%s",
            session_id,
        )
        event = self._cancel_events.get(session_id)
        if event is not None:
            event.set()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _emit_usage_if_available(
        self,
        session_id: str,
    ) -> None:
        """Send a usage chunk if new usage data is available."""
        usage_meta = self._pop_session_usage(session_id)
        if usage_meta:
            await self._conn.session_update(
                session_id=session_id,
                update=AgentMessageChunk(
                    sessionUpdate="agent_message_chunk",
                    content=text_block(""),
                    field_meta=usage_meta,
                ),
            )

    @staticmethod
    def _pop_session_usage(
        session_id: str,
    ) -> dict[str, Any] | None:
        """Retrieve and clear token usage recorded for *session_id*.

        Returns a ``_meta``-shaped dict with ``usage`` keys,
        matching the format used by QwenCode, or ``None`` if no
        usage was recorded.
        """
        try:
            from ...token_usage.model_wrapper import (
                TokenRecordingModelWrapper,
            )

            raw = TokenRecordingModelWrapper.pop_usage_for_session(
                session_id,
            )
        except Exception:  # noqa: BLE001
            return None
        if not raw:
            return None
        return {
            "usage": {
                "inputTokens": raw.get("prompt_tokens", 0),
                "outputTokens": raw.get("completion_tokens", 0),
                "totalTokens": raw.get("total_tokens", 0),
                # The model that produced this call, so clients can show it
                # (the session is bound late, e.g. via a global fallback).
                "model": raw.get("model_name") or "",
            },
        }

    def _get_session_mode(self, session_id: str) -> str:
        """Return the current mode for *session_id*."""
        info = self._sessions.get(session_id)
        if info is not None:
            return info.get("mode", self.MODE_DEFAULT)
        return self.MODE_DEFAULT

    def _session_meta(self) -> dict[str, Any] | None:
        """``_meta`` for session responses: the resolved agent id.

        Best-effort — returns ``None`` if the agent id can't be resolved,
        so a session is never blocked on it.
        """
        try:
            agent_id = self._resolve_agent_id()
        except Exception:  # pylint: disable=broad-except
            logger.exception("ACP: failed to resolve agent id for _meta")
            return None
        return {ACP_AGENT_META_KEY: agent_id} if agent_id else None

    @staticmethod
    def _build_available_commands() -> list[AvailableCommand]:
        """Build the slash commands to advertise to the ACP client.

        Combines the user-facing conversation commands with the registered
        control commands, skipping those that have a dedicated ACP
        affordance (see ``_ACP_REDUNDANT_COMMANDS``).
        """
        # Imported lazily to avoid a circular import: ``app.runner`` pulls in
        # ``react_agent`` -> ``agents.tools``, which (via the ACP tool adapter)
        # imports this module during ``agents.tools`` package init.
        from ...app.runner.control_commands import iter_commands

        commands = [
            AvailableCommand(name=name, description=desc)
            for name, desc in {
                **SYSTEM_COMMAND_DESCRIPTIONS,
                **MISSION_COMMAND_DESCRIPTIONS,
            }.items()
        ]
        for handler in iter_commands():
            name = handler.command_name.lstrip("/")
            if not name or name in _ACP_REDUNDANT_COMMANDS:
                continue
            commands.append(
                AvailableCommand(
                    name=name,
                    description=handler.description,
                ),
            )
        return commands

    async def _report_prompt_error(
        self,
        session_id: str,
        exc: BaseException,
    ) -> None:
        """Send a prompt failure to the client as a visible message.

        ACP has no dedicated error update, so the message is delivered as
        an ``agent_message_chunk`` tagged via ``_meta`` (see
        ``ACP_ERROR_META_KEY``). Clients can render it distinctly; those
        that ignore ``_meta`` still show the text in the transcript.
        """
        try:
            await self._conn.session_update(
                session_id=session_id,
                update=AgentMessageChunk(
                    sessionUpdate="agent_message_chunk",
                    content=text_block(f"Error: {exc}"),
                    field_meta={ACP_ERROR_META_KEY: True},
                ),
            )
        except Exception:  # pylint: disable=broad-except
            logger.exception(
                "ACP: failed to report prompt error to client (session=%s)",
                session_id,
            )

    async def _advertise_commands(self, session_id: str) -> None:
        """Send the ``available_commands_update`` for a session."""
        try:
            await self._conn.session_update(
                session_id=session_id,
                update=AvailableCommandsUpdate(
                    sessionUpdate="available_commands_update",
                    availableCommands=self._build_available_commands(),
                ),
            )
        except Exception:  # pylint: disable=broad-except
            # Advertising commands is best-effort; never fail a session
            # because the notification could not be delivered.
            logger.exception(
                "ACP: failed to advertise available commands (session=%s)",
                session_id,
            )

    def _build_config_options(
        self,
        session_id: str,
    ) -> list[SessionConfigOptionSelect]:
        """Return the current set of session config options."""
        current_mode = self._get_session_mode(session_id)
        return [
            SessionConfigOptionSelect(
                type="select",
                id=self.MODE_CONFIG_ID,
                name="Session Mode",
                category="mode",
                description=(
                    "Controls tool guard and permission behavior. "
                    "'Bypass Permissions' disables all security checks."
                ),
                current_value=current_mode,
                options=[
                    SessionConfigSelectOption(
                        value=self.MODE_DEFAULT,
                        name="Default",
                        description=("Normal mode with Tool Guard enabled"),
                    ),
                    SessionConfigSelectOption(
                        value=self.MODE_BYPASS,
                        name="Bypass Permissions",
                        description=("Skip all tool guard security checks"),
                    ),
                ],
            ),
        ]

    async def _switch_model(
        self,
        model_spec: str,
    ) -> None:
        """Switch the active model for the current agent.

        Validates the provider/model pair exists, then writes the
        choice into ``agent.json`` so ``create_model_and_formatter``
        picks it up on the next ``prompt()`` call.  The global
        ``ProviderManager`` state is **not** modified — the change
        is scoped to this agent only.

        *model_spec* should be ``"provider_id:model_id"``.
        Falls back to treating the whole string as *model_id* with
        an automatic provider search.
        """
        if ":" in model_spec:
            provider_id, model_id = model_spec.split(":", 1)
        else:
            provider_id, model_id = "", model_spec

        manager = ProviderManager.get_instance()

        if provider_id:
            provider = manager.get_provider(provider_id)
            if not provider:
                raise ValueError(
                    f"Provider {provider_id!r} not found",
                )
            if not provider.has_model(model_id):
                raise ValueError(
                    f"Model {model_id!r} not found in "
                    f"provider {provider_id!r}",
                )
        else:
            all_infos = await manager.list_provider_info()
            matched = False
            for pinfo in all_infos:
                all_models = list(pinfo.models) + list(
                    pinfo.extra_models,
                )
                if any(m.id == model_id for m in all_models):
                    provider_id = pinfo.id
                    matched = True
                    break
            if not matched:
                raise ValueError(
                    f"Model {model_id!r} not found in any provider",
                )

        from ...config.config import (
            load_agent_config,
            save_agent_config,
        )

        agent_id = self._resolve_agent_id()
        agent_config = load_agent_config(agent_id)
        agent_config.active_model = ModelSlotConfig(
            provider_id=provider_id,
            model=model_id,
        )
        save_agent_config(agent_id, agent_config)


async def run_qwenpaw_agent(
    agent_id: str | None = None,
    workspace_dir: Path | None = None,
) -> None:
    """Entry point: run QwenPaw as an ACP agent over stdio."""
    agent = QwenPawACPAgent(
        agent_id=agent_id,
        workspace_dir=workspace_dir,
    )
    try:
        await run_agent(agent, use_unstable_protocol=True)
    finally:
        await agent._shutdown_workspace()  # pylint: disable=protected-access
