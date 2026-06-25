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
    PermissionOption,
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
    ToolCallUpdate,
)
from qwenpaw.schemas import (
    AgentRequest,
    Message,
    MessageType,
    RunStatus,
)

from ...__version__ import __version__
from ...constant import WORKING_DIR
from ...config.config import ModelSlotConfig
from ...exceptions import AppBaseException
from ...providers.provider_manager import ProviderManager
from ...agents.command_handler import SYSTEM_COMMAND_DESCRIPTIONS

logger = logging.getLogger(__name__)

ACP_ERROR_META_KEY = "qwenpaw.error"
ACP_AGENT_META_KEY = "qwenpaw.agent"

_ADVERTISED_COMMAND_ORDER = (
    "clear",
    "compact",
    "skills",
    "model",
)

# Commands that are intentionally hidden from autocomplete because the TUI
# handles them locally or ACP exposes a clearer native affordance.
_ACP_REDUNDANT_COMMANDS = frozenset(
    {
        "approval",
        "approve",
        "deny",
        "new",
        "stop",
    },
)

_GENERIC_PROMPT_ERROR = (
    "QwenPaw failed to process the request. Check server logs for details."
)


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


class _EnvelopeTracker:
    """Track state needed to convert ``stream_query`` envelopes to ACP updates.

    ``stream_query`` emits ``TextContent(delta=True, object="content")`` for
    both text and thinking blocks — the only distinguisher is ``msg_id``.
    This tracker remembers which ``msg_id`` values belong to reasoning
    messages so text deltas and thinking deltas route correctly.
    """

    def __init__(self) -> None:
        self._reasoning_msg_ids: set[str] = set()
        self._streamed_text_msg_ids: set[str] = set()

    # pylint: disable=too-many-return-statements, too-many-branches
    def process(
        self,
        event: Any,
    ) -> list[Any]:
        """Convert one envelope event into zero or more ACP updates."""
        obj = getattr(event, "object", None)

        if obj == "content":
            text = getattr(event, "text", "") or ""
            if not text:
                return []
            msg_id = getattr(event, "msg_id", None)
            is_delta = getattr(event, "delta", False)
            if is_delta and msg_id:
                self._streamed_text_msg_ids.add(msg_id)
            elif msg_id in self._streamed_text_msg_ids:
                return []
            if msg_id in self._reasoning_msg_ids:
                return [update_agent_thought(text_block(text))]
            return [update_agent_message(text_block(text))]

        if obj == "message":
            msg_type = getattr(event, "type", None)
            if hasattr(msg_type, "value"):
                msg_type = msg_type.value
            status = getattr(event, "status", None)
            msg_id = getattr(event, "id", None)

            if msg_type == MessageType.REASONING.value:
                if msg_id:
                    self._reasoning_msg_ids.add(msg_id)
                return []

            if msg_type == MessageType.PLUGIN_CALL.value:
                if status == RunStatus.Completed:
                    for c in getattr(event, "content", []) or []:
                        data = getattr(c, "data", None)
                        if isinstance(data, dict):
                            return [
                                start_tool_call(
                                    str(
                                        data.get("call_id") or uuid4().hex[:8],
                                    ),
                                    str(data.get("name") or "tool"),
                                    status="in_progress",
                                ),
                            ]
                return []

            if msg_type == MessageType.PLUGIN_CALL_OUTPUT.value:
                if status == RunStatus.Completed:
                    for c in getattr(event, "content", []) or []:
                        data = getattr(c, "data", None)
                        if isinstance(data, dict):
                            return [
                                update_tool_call(
                                    str(
                                        data.get("call_id") or uuid4().hex[:8],
                                    ),
                                    status="completed",
                                    content=[
                                        tool_content(
                                            text_block(
                                                str(data.get("output") or ""),
                                            ),
                                        ),
                                    ],
                                ),
                            ]
                return []

            return []

        return []


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
        local_diagnostics: bool = False,
    ):
        self._agent_id = agent_id
        self._workspace_dir = workspace_dir
        self._local_diagnostics = local_diagnostics
        self._sessions: dict[str, dict[str, Any]] = {}
        self._cancel_events: dict[str, asyncio.Event] = {}
        self._workspace: Any | None = None
        self._workspace_ready = False
        self._app_services: Any | None = None
        self._app_services_started = False

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

    async def _ensure_app_services(self) -> Any:
        """Create and start ACP-local cross-workspace services."""
        if self._app_services is None:
            from ...app.app_services import AppServiceManager

            self._app_services = AppServiceManager()
        if not self._app_services_started:
            await self._app_services.start()
            self._app_services_started = True
        return self._app_services

    @staticmethod
    def _build_bootstrap_kwargs(app_services: Any) -> dict[str, Any]:
        """Build the same runtime plugin set used by the web app lifespan."""
        kwargs: dict[str, Any] = {}
        command_specs: list[Any] = []

        try:
            from ...agents.tools import discover_builtin_tool_funcs

            kwargs["builtin_tool_funcs"] = discover_builtin_tool_funcs()
        except Exception:
            logger.debug(
                "ACP bootstrap: built-in tools skipped",
                exc_info=True,
            )

        try:
            from ...runtime.builtin_commands import (
                collect_builtin_command_specs,
                get_skill_fallback_handler,
            )

            command_specs.extend(collect_builtin_command_specs())
            kwargs["builtin_fallback_handler"] = get_skill_fallback_handler()
        except Exception:
            logger.debug(
                "ACP bootstrap: built-in slash commands skipped",
                exc_info=True,
            )

        try:
            from ...app.app_services._builtin_tool_commands import (
                build_tool_command_specs,
            )

            command_specs.extend(
                build_tool_command_specs(app_services.tool_coordinator),
            )
        except Exception:
            logger.debug(
                "ACP bootstrap: HITL tool commands skipped",
                exc_info=True,
            )

        if command_specs:
            kwargs["builtin_command_specs"] = command_specs

        try:
            from ...hooks.bootstrap.bootstrap_hook import BootstrapHook
            from ...hooks.cron.cron_hook import CronContextHook
            from ...hooks.error.error_hook import (
                CancelCleanupHook,
                ErrorNormalizeHook,
            )
            from ...hooks.request_setup.contextvars_hook import (
                ContextVarsSetupHook,
            )
            from ...hooks.request_setup.media_hook import MediaProcessHook
            from ...hooks.session.session_hook import (
                SessionLoadHook,
                SessionSaveHook,
            )
            from ...hooks.skill_env.skill_env_hook import (
                SkillEnvCleanupHook,
                SkillEnvHook,
            )

            kwargs["builtin_hook_clses"] = [
                CronContextHook,
                SessionLoadHook,
                SessionSaveHook,
                BootstrapHook,
                SkillEnvHook,
                SkillEnvCleanupHook,
                ContextVarsSetupHook,
                MediaProcessHook,
                ErrorNormalizeHook,
                CancelCleanupHook,
            ]
        except Exception:
            logger.debug(
                "ACP bootstrap: lifecycle hooks skipped",
                exc_info=True,
            )

        try:
            from ...runtime.prompt_contributors import _ALL_CONTRIBUTORS

            kwargs["builtin_contributor_clses"] = _ALL_CONTRIBUTORS
        except Exception:
            logger.debug(
                "ACP bootstrap: prompt contributors skipped",
                exc_info=True,
            )

        try:
            from ...modes.coding import CodingMode
            from ...modes.mission import MissionMode

            kwargs["builtin_mode_clses"] = [
                CodingMode,
                MissionMode,
            ]
        except Exception:
            logger.debug("ACP bootstrap: modes skipped", exc_info=True)

        return kwargs

    async def _ensure_workspace(self) -> Any:
        """Boot a full ``Workspace`` (once) and return it."""
        if self._workspace is not None and self._workspace_ready:
            return self._workspace

        from ...app.workspace.workspace import Workspace

        agent_id = self._resolve_agent_id()
        workspace_dir = self._resolve_workspace_dir(agent_id)

        workspace = Workspace(
            agent_id=agent_id,
            workspace_dir=str(workspace_dir),
        )
        app_services = await self._ensure_app_services()
        workspace.bootstrap_plugins(
            **self._build_bootstrap_kwargs(app_services),
        )
        workspace.set_app_services(app_services)
        await workspace.start()

        self._workspace = workspace
        self._workspace_ready = True
        logger.info(
            "QwenPaw ACP Agent workspace started: agent_id=%s workspace=%s",
            agent_id,
            workspace_dir,
        )
        return workspace

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
        if self._app_services is not None and self._app_services_started:
            try:
                await self._app_services.stop()
            except Exception:
                logger.exception("Error stopping ACP app services")
            self._app_services_started = False

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
        mcp_servers: list[HttpMcpServer | SseMcpServer | McpServerStdio]
        | None = None,
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
        mcp_servers: list[HttpMcpServer | SseMcpServer | McpServerStdio]
        | None = None,
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

        workspace = await self._ensure_workspace()
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
        approval_bridge = asyncio.create_task(
            self._bridge_approval_requests(session_id),
        )

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
            agent_id=self._resolve_agent_id(),
            request_context=request_context or None,
        )

        tracker = _EnvelopeTracker()

        try:
            async for event in workspace.stream_query(request):
                if cancel_event.is_set():
                    logger.info(
                        "ACP prompt cancelled: session=%s",
                        session_id,
                    )
                    break

                updates = tracker.process(event)
                for upd in updates:
                    await self._conn.session_update(
                        session_id=session_id,
                        update=upd,
                    )

                await self._emit_usage_if_available(session_id)
        except Exception as exc:
            logger.exception(
                "ACP prompt error: session=%s",
                session_id,
            )
            await self._report_prompt_error(session_id, exc)
        finally:
            await self._stop_approval_bridge(approval_bridge)
            self._cancel_events.pop(session_id, None)

        await self._emit_usage_if_available(session_id)

        return PromptResponse(stop_reason="end_turn")

    async def close_session(  # pylint: disable=unused-argument
        self,
        session_id: str,
        **kwargs: Any,
    ) -> CloseSessionResponse | None:
        logger.info("ACP close_session: session=%s", session_id)
        await self._cancel_pending_approvals(session_id)
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
        mcp_servers: list[HttpMcpServer | SseMcpServer | McpServerStdio]
        | None = None,
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
        await self._cancel_pending_approvals(session_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _bridge_approval_requests(
        self,
        session_id: str,
        *,
        poll_interval: float = 0.25,
    ) -> None:
        """Bridge QwenPaw ApprovalService waits to ACP permission prompts."""
        from ...app.approvals import get_approval_service

        svc = get_approval_service()
        seen: set[str] = set()
        while True:
            pending_by_root = await svc.get_pending_by_root_session(
                session_id,
            )
            pending_direct = await svc.get_all_pending_by_session(session_id)
            pending_by_id = {
                p.request_id: p for p in [*pending_by_root, *pending_direct]
            }

            for pending in pending_by_id.values():
                if pending.request_id in seen:
                    continue
                seen.add(pending.request_id)
                await self._request_approval_decision(session_id, pending)

            await asyncio.sleep(poll_interval)

    async def _request_approval_decision(
        self,
        session_id: str,
        pending: Any,
    ) -> None:
        """Ask the ACP client to approve/deny a QwenPaw pending approval."""
        from ...app.approvals import get_approval_service
        from ...security.tool_guard.approval import ApprovalDecision

        svc = get_approval_service()
        try:
            response = await self._conn.request_permission(
                session_id=session_id,
                tool_call=ToolCallUpdate(
                    tool_call_id=pending.request_id,
                    title=(
                        f"{pending.tool_name} requires approval "
                        f"({pending.severity})"
                    ),
                    kind=self._approval_tool_kind(pending.tool_name),
                    raw_input=self._approval_tool_input(pending),
                ),
                options=[
                    PermissionOption(
                        option_id="approve",
                        name="Approve",
                        kind="allow_once",
                    ),
                    PermissionOption(
                        option_id="deny",
                        name="Deny",
                        kind="reject_once",
                    ),
                ],
            )
        except Exception:
            logger.exception(
                "ACP approval bridge failed for request=%s",
                pending.request_id[:8],
            )
            await svc.resolve_request(
                pending.request_id,
                ApprovalDecision.DENIED,
            )
            return

        decision = (
            ApprovalDecision.APPROVED
            if self._permission_option_id(response) == "approve"
            else ApprovalDecision.DENIED
        )
        await svc.resolve_request(pending.request_id, decision)

    @staticmethod
    def _approval_tool_input(pending: Any) -> dict[str, Any] | None:
        """Return the original guarded tool parameters for ACP display."""
        extra = getattr(pending, "extra", None)
        if not isinstance(extra, dict):
            return None
        tool_call = extra.get("tool_call")
        if not isinstance(tool_call, dict):
            return None
        raw_input = tool_call.get("input")
        return raw_input if isinstance(raw_input, dict) else None

    @staticmethod
    def _permission_option_id(response: Any) -> str | None:
        outcome = getattr(response, "outcome", None)
        if isinstance(outcome, dict):
            option_id = outcome.get("option_id") or outcome.get("optionId")
        else:
            option_id = getattr(outcome, "option_id", None) or getattr(
                outcome,
                "optionId",
                None,
            )
        return str(option_id) if option_id else None

    @staticmethod
    def _approval_tool_kind(tool_name: str) -> str:
        lowered = tool_name.lower()
        if "shell" in lowered or "command" in lowered or "execute" in lowered:
            return "execute"
        return "other"

    @staticmethod
    async def _stop_approval_bridge(task: asyncio.Task[Any]) -> None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.debug(
                "ACP approval bridge stopped with error",
                exc_info=True,
            )

    @staticmethod
    async def _cancel_pending_approvals(session_id: str) -> None:
        try:
            from ...app.approvals import get_approval_service

            await get_approval_service().cancel_all_pending_by_root_session(
                session_id,
            )
        except Exception:
            logger.debug(
                "Failed to cancel ACP pending approvals for session=%s",
                session_id,
                exc_info=True,
            )

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
        except Exception:
            return None
        if not raw:
            return None
        return {
            "usage": {
                "inputTokens": raw.get("prompt_tokens", 0),
                "outputTokens": raw.get("completion_tokens", 0),
                "totalTokens": raw.get("total_tokens", 0),
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
        """Return session ``_meta`` with the resolved QwenPaw agent id."""
        try:
            agent_id = self._resolve_agent_id()
        except Exception:
            logger.exception("ACP: failed to resolve agent id for _meta")
            return None
        return {ACP_AGENT_META_KEY: agent_id} if agent_id else None

    @staticmethod
    def _build_available_commands() -> list[AvailableCommand]:
        """Build the curated slash-command list advertised to ACP clients."""
        descriptions: dict[str, str] = {
            **SYSTEM_COMMAND_DESCRIPTIONS,
            "model": "Show or switch AI model",
            "skills": (
                "List chat-available skills and expose explicit skill commands"
            ),
        }
        return [
            AvailableCommand(
                name=name,
                description=descriptions.get(name, ""),
            )
            for name in _ADVERTISED_COMMAND_ORDER
            if name not in _ACP_REDUNDANT_COMMANDS
        ]

    async def _report_prompt_error(
        self,
        session_id: str,
        exc: BaseException,
    ) -> None:
        """Surface a prompt failure to ACP clients as a visible message."""
        try:
            await self._conn.session_update(
                session_id=session_id,
                update=AgentMessageChunk(
                    sessionUpdate="agent_message_chunk",
                    content=text_block(
                        f"Error: {self._safe_prompt_error_text(exc)}",
                    ),
                    field_meta={ACP_ERROR_META_KEY: True},
                ),
            )
        except Exception:
            logger.exception(
                "ACP: failed to report prompt error to client (session=%s)",
                session_id,
            )

    def _safe_prompt_error_text(self, exc: BaseException) -> str:
        """Return a client-safe prompt error message."""
        if isinstance(exc, AppBaseException) and exc.message:
            return str(exc.message)
        if self._local_diagnostics:
            return str(exc) or exc.__class__.__name__
        return _GENERIC_PROMPT_ERROR

    async def _advertise_commands(self, session_id: str) -> None:
        """Send the ``available_commands_update`` for a session."""
        try:
            await self._conn.session_update(
                session_id=session_id,
                update=AvailableCommandsUpdate(
                    sessionUpdate="available_commands_update",
                    available_commands=self._build_available_commands(),
                ),
            )
        except Exception:
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
    local_diagnostics: bool = False,
) -> None:
    """Entry point: run QwenPaw as an ACP agent over stdio."""
    agent = QwenPawACPAgent(
        agent_id=agent_id,
        workspace_dir=workspace_dir,
        local_diagnostics=local_diagnostics,
    )
    try:
        await run_agent(agent, use_unstable_protocol=True)
    finally:
        await agent._shutdown_workspace()  # pylint: disable=protected-access
