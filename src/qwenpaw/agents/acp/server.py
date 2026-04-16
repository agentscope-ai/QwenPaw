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

from ...__version__ import __version__

logger = logging.getLogger(__name__)


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
    """Track cumulative text/thinking to emit only incremental deltas."""

    def __init__(self) -> None:
        self._prev_text: str = ""
        self._prev_thinking: str = ""

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
            updates.append(
                start_tool_call(
                    str(tc.get("id") or uuid4().hex[:8]),
                    str(tc.get("name") or "tool"),
                    status="in_progress",
                ),
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
                    content=[
                        tool_content(
                            text_block(
                                str(tr.get("output", "")),
                            ),
                        ),
                    ],
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
            updates.append(
                start_tool_call(
                    str(block_data.get("id") or uuid4().hex[:8]),
                    str(block_data.get("name") or "tool"),
                    status="in_progress",
                ),
            )
        elif block_type == "tool_result":
            updates.append(
                update_tool_call(
                    str(block_data.get("id") or uuid4().hex[:8]),
                    status="completed",
                    content=[
                        tool_content(
                            text_block(
                                str(block_data.get("output", "")),
                            ),
                        ),
                    ],
                ),
            )


def _normalise_block(block: Any) -> tuple[str, dict[str, Any]]:
    """Return ``(block_type, data_dict)`` for both dict and object blocks."""
    if isinstance(block, dict):
        return block.get("type", "text"), block
    btype = getattr(block, "type", "text") or "text"
    data: dict[str, Any] = {}
    for attr in ("text", "thinking", "id", "name", "output"):
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
        self._session_mode: str = self.MODE_DEFAULT

    def on_connect(self, conn: Client) -> None:
        self._conn = conn

    # ------------------------------------------------------------------
    # Workspace bootstrap (mirrors the web-app lifespan)
    # ------------------------------------------------------------------

    def _resolve_agent_id(self) -> str:
        """Return the effective agent id."""
        if self._agent_id is not None:
            return self._agent_id

        from ...config import load_config

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

        from ...constant import WORKING_DIR

        return WORKING_DIR / "workspaces" / agent_id

    async def _ensure_workspace(self) -> Any:
        """Boot a full ``Workspace`` (once) and return its runner."""
        if self._workspace is not None and self._workspace_ready:
            return self._workspace.runner

        from ...app.workspace.workspace import Workspace

        agent_id = self._resolve_agent_id()
        workspace_dir = self._resolve_workspace_dir(agent_id)

        workspace = Workspace(
            agent_id=agent_id,
            workspace_dir=str(workspace_dir),
        )
        await workspace.start()

        runner = workspace.runner
        if runner is not None:
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
            "mcp_servers": mcp_servers,
        }
        logger.info(
            "ACP new_session: id=%s cwd=%s",
            session_id,
            cwd,
        )
        return NewSessionResponse(
            session_id=session_id,
            config_options=self._build_config_options(),
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
            "mcp_servers": mcp_servers,
        }
        logger.info(
            "ACP load_session: id=%s cwd=%s",
            session_id,
            cwd,
        )
        return LoadSessionResponse()

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

        from agentscope.message import Msg
        from agentscope_runtime.engine.schemas.agent_schemas import (
            AgentRequest,
            Message,
        )

        msgs = [
            Msg(
                name="user",
                role="user",
                content=text,
            ),
        ]

        request_context: dict[str, str] = {}
        if self._session_mode == self.MODE_BYPASS:
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
        except Exception:
            logger.exception(
                "ACP prompt error: session=%s",
                session_id,
            )
        finally:
            self._cancel_events.pop(session_id, None)

        # Emit a final empty chunk with usage metadata (like QwenCode)
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
                "mcp_servers": mcp_servers,
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
            self._session_mode = str(value)
            return SetSessionConfigOptionResponse(
                config_options=self._build_config_options(),
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

    @staticmethod
    def _pop_session_usage(
        session_id: str,
    ) -> dict[str, Any] | None:
        """Retrieve and clear token usage recorded for *session_id*.

        Returns a ``_meta``-shaped dict with ``usage`` and ``durationMs``
        keys, matching the format used by QwenCode, or ``None`` if no
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
            },
        }

    def _build_config_options(
        self,
    ) -> list[SessionConfigOptionSelect]:
        """Return the current set of session config options."""
        return [
            SessionConfigOptionSelect(
                type="select",
                id=self.MODE_CONFIG_ID,
                name="Session Mode",
                category="mode",
                description=("Controls tool guard and permission behavior"),
                current_value=self._session_mode,
                options=[
                    SessionConfigSelectOption(
                        value=self.MODE_DEFAULT,
                        name="Default",
                        description=("Normal mode with Tool Guard enabled"),
                    ),
                    SessionConfigSelectOption(
                        value=self.MODE_BYPASS,
                        name="Bypass Permissions",
                        description=("Skip tool guard checks"),
                    ),
                ],
            ),
        ]

    async def _switch_model(
        self,
        model_spec: str,
    ) -> None:
        """Switch the active model via ``ProviderManager``.

        *model_spec* should be ``"provider_id:model_id"``.
        Falls back to treating the whole string as *model_id* with
        an empty provider search.
        """
        from ...providers.provider_manager import ProviderManager

        if ":" in model_spec:
            provider_id, model_id = model_spec.split(":", 1)
        else:
            provider_id, model_id = "", model_spec

        manager = ProviderManager.get_instance()

        if provider_id:
            await manager.activate_model(provider_id, model_id)
        else:
            # Search all providers for this model_id.
            all_infos = await manager.list_provider_info()
            matched = False
            for pinfo in all_infos:
                all_models = list(pinfo.models) + list(
                    pinfo.extra_models,
                )
                if any(m.id == model_id for m in all_models):
                    await manager.activate_model(pinfo.id, model_id)
                    matched = True
                    break
            if not matched:
                raise ValueError(
                    f"Model {model_id!r} not found in any provider",
                )


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
