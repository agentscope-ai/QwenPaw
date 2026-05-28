# -*- coding: utf-8 -*-
"""Shim for ``agentscope_runtime.engine.runner.Runner``.

In agentscope 1.x ``Runner`` was the base class for any HTTP-served
runner: it owned the streaming/query lifecycle that ``AgentApp`` adapted
to FastAPI endpoints.  qwenpaw's :class:`~qwenpaw.app.runner.runner.AgentRunner`
inherits from it but only relies on ``super().__init__()`` succeeding and
on being able to set arbitrary instance attributes.

agentscope 2.0 has no equivalent — the runner role was absorbed into
:class:`agentscope.agent.Agent` and the HTTP plumbing into
:func:`agentscope.app.create_app`.

For the migration mainline we don't need the full 1.x lifecycle.  This
``stream_query`` instead builds a minimal stock-2.0 ``Agent`` per session
and translates the ``AgentEvent`` stream from ``agent.reply_stream`` into
the 1.x ``Message`` / ``Content`` envelope shape that qwenpaw's console
channel and the ``@agentscope-ai/chat`` frontend already understand.

The complex bits in ``AgentRunner.query_handler`` (plan notebook, tool
guard, mcp clients, hooks, mission mode, skills) are bypassed for now
and re-introduced in later passes once the round-trip works.

TODO(as2-migration): once channels consume agentscope 2.0 event types
directly, delete this file and let routes call ``agent.reply_stream``.
"""
from __future__ import annotations

import contextvars
import json
import logging
import uuid
from typing import Any, AsyncGenerator, Dict, List

logger = logging.getLogger(__name__)


# Module-level per-session agent cache. Keys: (session_id, provider_id, model_id).
# Within a process this gives the agent its short-term memory
# (agent.state.context).  The provider+model is part of the key so that when
# the user switches active model in the frontend, the next request rebuilds
# the agent against the new model instead of reusing the stale one (which
# would silently keep talking to the old endpoint).
_AGENT_CACHE: Dict[tuple, Any] = {}


# Per-request context propagated to ``GuardedFunctionTool.check_permissions``.
# Tools are constructed once per (session, agent, model) in
# ``_build_qwenpaw_toolkit`` and cached, but ``check_permissions`` runs on
# every tool call — set this ContextVar in ``stream_query`` before driving
# the agent so the guard can build a proper ``PendingApproval`` (which
# needs session_id / user_id / channel / agent_id / root_session_id /
# root_agent_id for cross-session approval routing in the frontend).
#
# ``ContextVar.set`` is task-scoped (Starlette starts each HTTP request in
# its own task), so concurrent requests with different sessions don't see
# each other's value.
_REQUEST_CONTEXT_VAR: contextvars.ContextVar[Dict[str, str]] = (
    contextvars.ContextVar("_qp_request_context", default={})
)


def _current_request_context() -> Dict[str, str]:
    """Return the active per-request context (or empty dict)."""
    return _REQUEST_CONTEXT_VAR.get() or {}


class GuardedFunctionTool:
    """Skeleton ``FunctionTool`` that routes permission decisions through
    qwenpaw's tool-guard execution level.

    For the migration mainline ``_resolve_execution_level()`` always
    returns ``"bypass"``, so every tool call is auto-allowed — same
    behavior as the prior ``_AutoAllowFunctionTool``.  The branches for
    OFF / AUTO / SMART / STRICT are stubbed with TODOs; the next pass
    wires them to ``qwenpaw.security.tool_guard.engine`` and emits
    ``PermissionDecision(ASK, ...)`` so agentscope 2.0's
    ``RequireUserConfirmEvent`` plumbing (already translated by
    ``stream_query``) carries the findings to the frontend's
    ``ApprovalCard``.

    The class is defined at module scope (rather than nested inside
    :func:`_build_qwenpaw_toolkit`) so the skeleton survives toolkit
    rebuilds — when the agent cache evicts an entry on active-model
    change, the next ``_build_qwenpaw_toolkit()`` call still wires
    the same ``GuardedFunctionTool``.

    Inheriting from ``FunctionTool`` happens lazily inside ``__new__`` so
    importing this module does not require the agentscope package to be
    importable at definition time (matches the rest of ``runtime_engine``,
    which imports agentscope only inside function bodies).
    """

    def __new__(cls, *args: Any, **kwargs: Any) -> Any:  # type: ignore[misc]
        from agentscope.tool import FunctionTool

        if cls is GuardedFunctionTool:
            real_cls = type(
                "GuardedFunctionTool",
                (FunctionTool,),
                {
                    "__init__": _guarded_tool_init,
                    "_resolve_execution_level":
                        _guarded_tool_resolve_execution_level,
                    "check_permissions": _guarded_tool_check_permissions,
                    "__doc__": cls.__doc__,
                },
            )
            return real_cls(*args, **kwargs)
        return object.__new__(cls)


def _guarded_tool_init(
    self: Any,
    func: Any,
    *,
    agent_id: str | None = None,
    request_context: dict[str, str] | None = None,
    **kwargs: Any,
) -> None:
    from agentscope.tool import FunctionTool

    FunctionTool.__init__(self, func, **kwargs)
    self._qp_agent_id = agent_id
    self._qp_request_context = request_context or {}


def _guarded_tool_resolve_execution_level(self: Any) -> str:
    """Return the active tool execution level for this tool.

    Resolves the per-agent ``approval_level`` from the workspace's
    ``agent.json`` via :func:`load_agent_config`.  Returns one of
    ``"off"`` / ``"auto"`` / ``"smart"`` / ``"strict"`` (canonical lower-case
    values from :class:`ToolExecutionLevel`), or ``"bypass"`` when no
    ``agent_id`` was attached at construction time (mainline single-agent
    dev path doesn't always set one) or when config loading fails — the
    bypass branch keeps the tool runnable in environments where the guard
    can't be initialised, matching the 1.x fallback in
    ``ToolGuardMixin._get_tool_execution_level``.
    """
    agent_id = getattr(self, "_qp_agent_id", None)
    if not agent_id:
        return "bypass"
    try:
        from ..config.config import load_agent_config
        from ..security.tool_guard.execution_level import ToolExecutionLevel

        profile = load_agent_config(agent_id)
        raw = getattr(profile, "approval_level", None)
        return ToolExecutionLevel.from_config(raw).value
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "GuardedFunctionTool: failed to resolve approval_level for "
            "agent=%s (%s); falling back to BYPASS",
            agent_id,
            exc,
        )
        return "bypass"


async def _guarded_tool_check_permissions(
    self: Any,
    tool: Any,
    input_data: dict[str, Any],
) -> Any:
    """Drive qwenpaw's tool-guard engine + ApprovalService for one tool call.

    Ports the 1.x ``ToolGuardMixin._decide_guard_action`` +
    ``_acting_with_approval`` flow to agentscope 2.0's
    ``PermissionDecision`` surface.  ASK is implemented by blocking on
    :class:`PendingApproval.future` (resolved by the
    ``/approval/{approve,deny}`` HTTP endpoints) rather than emitting
    ``PermissionBehavior.ASK`` — the polling-based
    ``/console/push-messages`` path that the frontend already uses for
    1.x approval cards keeps working without an SSE round-trip change.
    """
    from agentscope.permission import (
        PermissionBehavior,
        PermissionDecision,
    )

    level = self._resolve_execution_level()

    if level == "bypass":
        return PermissionDecision(
            behavior=PermissionBehavior.ALLOW,
            message="Tool guard BYPASS — no agent_id bound.",
        )

    from ..security.tool_guard.engine import get_guard_engine
    from ..security.tool_guard.execution_level import ToolExecutionLevel
    from ..security.tool_guard.models import GuardSeverity

    tool_name = getattr(tool, "name", None) or ""
    exec_level = ToolExecutionLevel.from_config(level)
    engine = get_guard_engine()

    # OFF: bypass without engine.
    if exec_level.is_disabled() or not engine.enabled:
        return PermissionDecision(
            behavior=PermissionBehavior.ALLOW,
            message=f"Tool guard {exec_level.value.upper()} — allowed.",
        )

    # Denied list (applies to every mode).
    if engine.is_denied(tool_name):
        denied_result = engine.guard(tool_name, input_data)
        return PermissionDecision(
            behavior=PermissionBehavior.DENY,
            message=(
                f"Tool '{tool_name}' is in the denied set."
                if denied_result is None or not denied_result.findings
                else _format_guard_message(tool_name, denied_result)
            ),
        )

    # Resolve the guard_result that drives the rest of the decisions.
    if exec_level.requires_approval_for_all_tools():
        guard_result = engine.guard(
            tool_name,
            input_data,
            only_always_run=False,
        )
        if guard_result is None or not guard_result.findings:
            guard_result = _strict_info_guard_result(tool_name, input_data)
    else:
        guarded = engine.is_guarded(tool_name)
        guard_result = engine.guard(
            tool_name,
            input_data,
            only_always_run=not guarded,
        )

    # No findings on AUTO/SMART → allow.
    if guard_result is None or not guard_result.findings:
        return PermissionDecision(
            behavior=PermissionBehavior.ALLOW,
            message="Tool guard: no findings.",
        )

    # Auto-deny rules (HIGH-RISK rules flagged by config).
    if engine.should_auto_deny_result(guard_result):
        return PermissionDecision(
            behavior=PermissionBehavior.DENY,
            message=_format_guard_message(tool_name, guard_result),
        )

    # SMART: skip approval for low-risk findings.
    if exec_level.is_smart_mode():
        max_sev = guard_result.max_severity
        if max_sev in (GuardSeverity.INFO, GuardSeverity.LOW):
            return PermissionDecision(
                behavior=PermissionBehavior.ALLOW,
                message=(
                    "Tool guard SMART: auto-allowed low-risk "
                    f"({max_sev.value})."
                ),
            )

    # Anything left needs the user.
    decision = await _ask_user_approval(
        agent_id=self._qp_agent_id,
        tool_name=tool_name,
        input_data=input_data,
        guard_result=guard_result,
    )
    return decision


def _strict_info_guard_result(tool_name: str, params: dict[str, Any]) -> Any:
    """Synthesise an INFO-level ``ToolGuardResult`` for STRICT no-finding tools.

    Mirrors :py:meth:`ToolGuardMixin._create_info_guard_result` so the
    approval card in STRICT mode still has a body even when no rule fires.
    """
    from ..security.tool_guard.models import (
        GuardFinding,
        GuardSeverity,
        GuardThreatCategory,
        ToolGuardResult,
    )

    finding = GuardFinding(
        id=uuid.uuid4().hex[:8],
        rule_id="strict_mode",
        category=GuardThreatCategory.RESOURCE_ABUSE,
        severity=GuardSeverity.INFO,
        title="STRICT Mode Approval",
        description=(
            f"Tool '{tool_name}' requires approval in STRICT mode"
        ),
        tool_name=tool_name,
        remediation="Approve or deny this tool call",
        guardian="strict_mode",
        metadata={"reason": "strict_mode_enabled"},
    )
    return ToolGuardResult(
        tool_name=tool_name,
        params=params,
        findings=[finding],
        guardians_used=["strict_mode"],
    )


def _format_guard_message(tool_name: str, guard_result: Any) -> str:
    """Human-readable message attached to a ``PermissionDecision``."""
    from ..security.tool_guard.approval import format_findings_summary

    return (
        f"Tool '{tool_name}' flagged "
        f"(severity={guard_result.max_severity.value}, "
        f"findings={guard_result.findings_count}):\n"
        f"{format_findings_summary(guard_result)}"
    )


async def _ask_user_approval(
    *,
    agent_id: str,
    tool_name: str,
    input_data: dict[str, Any],
    guard_result: Any,
) -> Any:
    """Create a ``PendingApproval`` and block on its Future.

    The frontend polls ``/console/push-messages`` (which iterates
    ``ApprovalService._pending`` directly) so creating the record is
    sufficient — no extra push needed.  ``/approval/{approve,deny}``
    resolves the Future; we map the resulting ``ApprovalDecision`` to
    ``PermissionBehavior``.
    """
    from agentscope.permission import (
        PermissionBehavior,
        PermissionDecision,
    )

    from ..app.approvals import get_approval_service
    from ..constant import TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS
    from ..security.tool_guard.approval import (
        ApprovalDecision,
        format_findings_summary,
    )

    ctx = _current_request_context()
    session_id = str(ctx.get("session_id") or "")
    user_id = str(ctx.get("user_id") or "")
    channel = str(ctx.get("channel") or "")
    root_session_id = str(ctx.get("root_session_id") or session_id)
    owner_agent_id = str(ctx.get("root_agent_id") or agent_id or "unknown")

    svc = get_approval_service()
    tool_call_id = str(ctx.get("tool_call_id") or "")
    if session_id and tool_call_id:
        await svc.cancel_stale_pending_for_tool_call(
            session_id,
            tool_call_id,
        )

    pending = await svc.create_pending(
        session_id=session_id,
        root_session_id=root_session_id,
        owner_agent_id=owner_agent_id,
        user_id=user_id,
        channel=channel,
        agent_id=agent_id or "unknown",
        tool_name=tool_name,
        result=guard_result,
        timeout_seconds=TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS,
        extra={
            "tool_call": {
                "id": tool_call_id,
                "name": tool_name,
                "input": dict(input_data or {}),
            },
        },
    )

    logger.info(
        "GuardedFunctionTool: awaiting approval for tool=%s session=%s "
        "request_id=%s severity=%s",
        tool_name,
        session_id[:8] if session_id else "",
        pending.request_id[:8],
        pending.severity,
    )

    try:
        decision = await svc.wait_for_approval(
            pending.request_id,
            TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "GuardedFunctionTool: wait_for_approval crashed (%s); denying",
            exc,
            exc_info=True,
        )
        decision = ApprovalDecision.DENIED

    summary = format_findings_summary(guard_result)
    if decision == ApprovalDecision.APPROVED:
        return PermissionDecision(
            behavior=PermissionBehavior.ALLOW,
            message=f"Approved by user.\n{summary}",
        )
    if decision == ApprovalDecision.DENIED:
        return PermissionDecision(
            behavior=PermissionBehavior.DENY,
            message=f"Denied by user.\n{summary}",
        )
    return PermissionDecision(
        behavior=PermissionBehavior.DENY,
        message=(
            "Approval request timed out "
            f"({int(TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS)}s).\n{summary}"
        ),
    )


def _build_qwenpaw_agent(
    session_id: str,
    agent_id: str,
    workspace_dir: Any = None,
) -> Any:
    """Construct a fully-wired :class:`QwenPawAgent` for one session.

    QwenPawAgent owns its own toolkit (built via ``_create_toolkit`` from
    the agent's ``builtin_tools`` config — currently ~17 tools), system
    prompt (assembled from working-dir files), and hook registration
    (bootstrap + context-manager hooks via the 1.x hook compat shim).
    Phase 1 keeps ``memory_manager`` / ``context_manager`` / ``plan_notebook``
    / ``mcp_clients`` as ``None`` so we don't have to rewrite the
    ``AgentContext``-on-``InMemoryMemory`` shim or the missing
    ``_reasoning`` features in the same pass — those come back in Phase 2.

    The tool-guard ASK flow that ``stream_query`` already drives still
    works because we pin :data:`qwenpaw._compat.toolkit._CURRENT_AGENT_ID`
    while ``QwenPawAgent.__init__`` runs.  The shim's
    ``register_tool_function`` reads that ContextVar and wraps every tool
    in :class:`GuardedFunctionTool` (which routes ``check_permissions``
    through qwenpaw's guard engine + ``ApprovalService``).
    """
    from ..agents.react_agent import QwenPawAgent
    from ..config.config import load_agent_config
    from .toolkit import _CURRENT_AGENT_ID

    agent_config = load_agent_config(agent_id)

    token = _CURRENT_AGENT_ID.set(agent_id)
    try:
        agent = QwenPawAgent(
            agent_config=agent_config,
            workspace_dir=workspace_dir,
            request_context={
                "session_id": session_id,
                "agent_id": agent_id,
                "channel": "console",
            },
            memory_manager=None,
            context_manager=None,
            mcp_clients=None,
            plan_notebook=None,
        )
    finally:
        _CURRENT_AGENT_ID.reset(token)
    return agent


def _get_or_build_agent(
    session_id: str,
    agent_id: str | None = None,
    workspace_dir: Any = None,
) -> Any:
    """Return the cached :class:`QwenPawAgent` for the active (provider, model)
    on this session — build on first use, rebuild when the active model changes.

    The cache lives for the process lifetime.  Restarting the daemon wipes
    chat history — full persistence is part of a later migration pass.

    ``agent_id`` is part of the cache key so two workspaces sharing a
    ``session_id`` (rare today, expected once cross-workspace sessions
    land) don't collide on the same cached agent — each gets its own
    toolkit bound to the right per-agent guard config.  When the caller
    passes ``None`` we substitute ``"default"`` so ``load_agent_config``
    succeeds against the default workspace.

    ``workspace_dir`` (typically ``AgentRunner.workspace_dir``) is forwarded
    to ``QwenPawAgent`` so its ``_build_sys_prompt`` reads working-dir files
    from the right place; ``None`` falls back to the env-driven
    ``WORKING_DIR`` global inside the agent.
    """
    from ..providers.provider_manager import ProviderManager

    active = ProviderManager.get_instance().get_active_model()
    if active is None or not active.provider_id or not active.model:
        raise RuntimeError(
            "stream_query: no active model configured; pick one in the UI",
        )
    resolved_agent_id = agent_id or "default"
    key = (session_id, resolved_agent_id, active.provider_id, active.model)
    cached = _AGENT_CACHE.get(key)
    if cached is not None:
        return cached
    agent = _build_qwenpaw_agent(
        session_id,
        resolved_agent_id,
        workspace_dir=workspace_dir,
    )
    _AGENT_CACHE[key] = agent
    logger.info(
        "stream_query: built QwenPawAgent for session=%s agent=%s "
        "provider=%s model=%s tools=%d",
        session_id,
        resolved_agent_id,
        active.provider_id,
        active.model,
        len(agent.toolkit.tool_groups[0].tools),
    )
    return agent


class Runner:  # pragma: no cover - migration shim
    """No-contract stand-in for the deleted runtime ``Runner`` base.

    Provides the lifecycle hooks (``start`` / ``stop``) qwenpaw's
    ``AgentRunner`` expects from its parent, plus a ``stream_query`` that
    bypasses ``AgentRunner.query_handler`` and drives a stock 2.0 ``Agent``
    directly.
    """

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        self.session: Any = None
        return

    async def start(self) -> None:
        """Default start: delegate to ``init_handler`` when defined."""
        init_handler = getattr(self, "init_handler", None)
        if init_handler is not None:
            await init_handler()

    async def stop(self) -> None:
        """Default stop: delegate to ``shutdown_handler`` when defined."""
        shutdown_handler = getattr(self, "shutdown_handler", None)
        if shutdown_handler is not None:
            await shutdown_handler()

    async def stream_query(
        self,
        request: Any,
        *_args: Any,
        **_kwargs: Any,
    ) -> AsyncGenerator[Any, None]:
        """Drive a stock 2.0 agent via ``reply_stream`` and translate the
        ``AgentEvent`` stream into the frontend's envelope protocol.

        Envelope sequence (matches ``Builder.tsx`` in ``@agentscope-ai/chat``)::

            1. response.created     (object=response, status=created)
            2. response.in_progress (object=response, status=in_progress)
            3. message.in_progress  (object=message, id=<msg-id>,
                                     status=in_progress, role=assistant,
                                     content=[])  — one per text block
            4. content (delta=true) (object=content, msg_id=<msg-id>,
                                     type=text, text=<piece>, index=<i>)
               …repeated per ``TextBlockDeltaEvent``…
            5. content (delta=false)(object=content, msg_id=<msg-id>,
                                     type=text, text=<full>, index=<i>)
               on ``TextBlockEndEvent`` to finalize.
            6. message.completed   (object=message, id=<msg-id>,
                                     status=completed, content=[full
                                     TextContent blocks])
            7. response.completed  (object=response, status=completed,
                                     output=[the message])

        Thinking blocks are emitted as a separate ``Message`` envelope with
        ``type=reasoning`` (one message per ``THINKING_BLOCK_START``), so the
        frontend's ``Reasoning`` card picks them up and renders them via
        ``<Thinking />``.  The flow mirrors the text-block path:

            a. message.in_progress  (object=message, id=<r-msg-id>,
                                     type=reasoning, status=in_progress,
                                     content=[])
            b. content (delta=true) (object=content, msg_id=<r-msg-id>,
                                     type=text, index=0, text=<piece>)
               …repeated per ``ThinkingBlockDeltaEvent``…
            c. content (delta=false)(object=content, msg_id=<r-msg-id>,
                                     type=text, index=0, text=<full>)
            d. message.completed   (object=message, id=<r-msg-id>,
                                     type=reasoning, status=completed,
                                     content=[full TextContent])

        Tool invocations are emitted as **two** ``Message`` envelopes per
        call (one ``plugin_call`` + one ``plugin_call_output``) which
        share the same ``call_id``; the frontend's ``mergeToolMessages``
        groups them by ``content[0].data.call_id`` and renders one
        ``<ToolCall>`` accordion whose ``loading`` state is driven by
        the merged message's ``status``:

            i. plugin_call message  (object=message, id=<in-msg-id>,
                                     type=plugin_call, status=completed,
                                     content=[DataContent(data={name,
                                     call_id, arguments})])
               emitted after ``TOOL_CALL_END`` once the JSON args have
               been fully accumulated from ``TOOL_CALL_DELTA`` events.

           ii. plugin_call_output message  (object=message,
                                            id=<out-msg-id>,
                                            type=plugin_call_output,
                                            status=in_progress,
                                            content=[])
               emitted at ``TOOL_RESULT_START`` — its ``in_progress``
               status drives the frontend spinner until the merge
               sibling lands.

          iii. plugin_call_output message  (..., status=completed,
                                            content=[DataContent(data={
                                            name, call_id, output,
                                            state})])
               emitted at ``TOOL_RESULT_END`` with the accumulated
               textual tool output and the final ``ToolResultState``.

        ``TOOL_RESULT_DATA_DELTA`` (binary tool output) is dropped with a
        debug log — none of the four migrated tools produce binary
        results; revisit when ``view_media``/``desktop_screenshot``-style
        tools are re-introduced.

        ``Reply`` and ``ModelCall`` events are still dropped for the
        migration mainline — re-introduced once channels need them.
        """
        from agentscope.event import EventType  # type: ignore
        from .agent_schemas import (
            AgentRequest,
            AgentResponse,
            ContentType,
            DataContent,
            Message,
            MessageType,
            Role,
            RunStatus,
            TextContent,
        )

        if isinstance(request, dict):
            request = AgentRequest(**request)

        if not getattr(request, "session_id", None):
            request.session_id = uuid.uuid4().hex
        if not getattr(request, "user_id", None):
            request.user_id = request.session_id

        session_id = request.session_id

        # Per-workspace tool context.  ``AgentRunner.__init__`` stores
        # ``self.workspace_dir`` (handed in by the workspace manager at
        # construction — one ``AgentRunner`` per ``Workspace`` per agent_id).
        # qwenpaw's file/shell tools call ``get_current_workspace_dir()`` to
        # resolve relative paths and the shell cwd; without setting this
        # ContextVar they fall back to the env-driven global ``WORKING_DIR``
        # — fine for single-agent dev but causes cross-agent file collisions
        # in multi-agent deployments.  Match the 1.x react_agent.py:1450
        # behaviour: set the ContextVar here once, before driving the agent.
        # ``ContextVar.set`` is task-scoped (Starlette starts each request in
        # its own task) so concurrent requests with different workspaces do
        # not see each other's value.
        workspace_dir = getattr(self, "workspace_dir", None)
        if workspace_dir is not None:
            from ..config.context import set_current_workspace_dir
            set_current_workspace_dir(workspace_dir)

        # Stash per-request context for ``GuardedFunctionTool.check_permissions``
        # — the toolkit is built once per (session, agent, model) and cached,
        # so the tool can't capture this at construction time.  Pull from the
        # AgentRequest (channel was attached by the channel layer; root ids
        # come back to the canonical session/agent for now, get re-introduced
        # with sub-agent routing in a later pass).
        agent_id_for_ctx = getattr(self, "agent_id", None) or ""
        _REQUEST_CONTEXT_VAR.set(
            {
                "session_id": session_id or "",
                "user_id": request.user_id or "",
                "channel": getattr(request, "channel", None) or "",
                "agent_id": agent_id_for_ctx,
                "root_session_id": session_id or "",
                "root_agent_id": agent_id_for_ctx,
            },
        )

        logger.info(
            "stream_query: enter session=%s workspace=%s input_len=%s",
            session_id,
            workspace_dir,
            len(getattr(request, "input", []) or []),
        )

        response = AgentResponse(output=[], status=RunStatus.Created)
        response.object = "response"
        response.session_id = session_id
        yield response

        response.status = RunStatus.InProgress
        yield response

        msgs = _request_input_to_msgs(getattr(request, "input", []) or [])

        # The Message envelope we accumulate into and emit twice: once with
        # empty content (in_progress) so the frontend can register the msg.id
        # and route subsequent ``content`` events to it, then again with the
        # finalized content list at completion.
        message_id = uuid.uuid4().hex
        completed_message = Message(
            id=message_id,
            type=MessageType.MESSAGE,
            role=Role.ASSISTANT,
            content=[],
            status=RunStatus.InProgress,
        )
        completed_message.name = "assistant"
        completed_message.object = "message"
        message_started = False

        # block_id -> (index, accumulated_text)
        text_blocks: Dict[str, Dict[str, Any]] = {}
        # block_id -> {msg_id, envelope, text}
        reasoning_blocks: Dict[str, Dict[str, Any]] = {}
        # tool_call_id -> {input_msg_id, output_msg_id, name,
        #                  args_json_acc, output_text_acc}
        tool_calls: Dict[str, Dict[str, Any]] = {}

        error_text: str | None = None
        try:
            agent = _get_or_build_agent(
                session_id,
                agent_id=getattr(self, "agent_id", None),
                workspace_dir=workspace_dir,
            )

            async for event in agent.reply_stream(inputs=msgs):
                evt_type = getattr(event, "type", None)
                if hasattr(evt_type, "value"):
                    evt_type = evt_type.value

                if evt_type == EventType.TEXT_BLOCK_START.value:
                    if not message_started:
                        yield completed_message
                        message_started = True
                    block_id = event.block_id
                    index = len(text_blocks)
                    text_blocks[block_id] = {"index": index, "text": ""}

                elif evt_type == EventType.TEXT_BLOCK_DELTA.value:
                    if not message_started:
                        yield completed_message
                        message_started = True
                    block_id = event.block_id
                    delta = event.delta or ""
                    # Tolerate a missing TEXT_BLOCK_START by registering lazily.
                    state = text_blocks.setdefault(
                        block_id,
                        {"index": len(text_blocks), "text": ""},
                    )
                    state["text"] += delta
                    chunk = TextContent(
                        type=ContentType.TEXT,
                        text=delta,
                        delta=True,
                        index=state["index"],
                    )
                    chunk.msg_id = message_id
                    chunk.object = "content"
                    yield chunk

                elif evt_type == EventType.TEXT_BLOCK_END.value:
                    block_id = event.block_id
                    state = text_blocks.get(block_id)
                    if state is None:
                        continue
                    final_chunk = TextContent(
                        type=ContentType.TEXT,
                        text=state["text"],
                        delta=False,
                        index=state["index"],
                    )
                    final_chunk.msg_id = message_id
                    final_chunk.object = "content"
                    yield final_chunk
                    # Mirror into the completed-message envelope so
                    # downstream consumers that read it directly (e.g. console
                    # terminal pretty-print) see the full text.
                    completed_message.content.append(
                        TextContent(
                            type=ContentType.TEXT,
                            text=state["text"],
                            delta=False,
                            index=state["index"],
                        ),
                    )

                elif evt_type == EventType.THINKING_BLOCK_START.value:
                    block_id = event.block_id
                    r_msg_id = uuid.uuid4().hex
                    r_envelope = Message(
                        id=r_msg_id,
                        type=MessageType.REASONING,
                        role=Role.ASSISTANT,
                        content=[],
                        status=RunStatus.InProgress,
                    )
                    r_envelope.name = "assistant"
                    r_envelope.object = "message"
                    reasoning_blocks[block_id] = {
                        "msg_id": r_msg_id,
                        "envelope": r_envelope,
                        "text": "",
                    }
                    yield r_envelope

                elif evt_type == EventType.THINKING_BLOCK_DELTA.value:
                    block_id = event.block_id
                    delta = getattr(event, "delta", "") or ""
                    state = reasoning_blocks.get(block_id)
                    if state is None:
                        # Lazy-register on a missing THINKING_BLOCK_START.
                        r_msg_id = uuid.uuid4().hex
                        r_envelope = Message(
                            id=r_msg_id,
                            type=MessageType.REASONING,
                            role=Role.ASSISTANT,
                            content=[],
                            status=RunStatus.InProgress,
                        )
                        r_envelope.name = "assistant"
                        r_envelope.object = "message"
                        state = {
                            "msg_id": r_msg_id,
                            "envelope": r_envelope,
                            "text": "",
                        }
                        reasoning_blocks[block_id] = state
                        yield r_envelope
                    state["text"] += delta
                    r_chunk = TextContent(
                        type=ContentType.TEXT,
                        text=delta,
                        delta=True,
                        index=0,
                    )
                    r_chunk.msg_id = state["msg_id"]
                    r_chunk.object = "content"
                    yield r_chunk

                elif evt_type == EventType.THINKING_BLOCK_END.value:
                    block_id = event.block_id
                    state = reasoning_blocks.get(block_id)
                    if state is None:
                        continue
                    r_final = TextContent(
                        type=ContentType.TEXT,
                        text=state["text"],
                        delta=False,
                        index=0,
                    )
                    r_final.msg_id = state["msg_id"]
                    r_final.object = "content"
                    yield r_final
                    state["envelope"].content.append(
                        TextContent(
                            type=ContentType.TEXT,
                            text=state["text"],
                            delta=False,
                            index=0,
                        ),
                    )
                    state["envelope"].status = RunStatus.Completed
                    response.output.append(state["envelope"])
                    yield state["envelope"]

                elif evt_type == EventType.TOOL_CALL_START.value:
                    # Allocate an envelope id but don't emit yet — the
                    # frontend's ToolCall card wants the full args at
                    # render time, which we only have at TOOL_CALL_END.
                    tool_calls[event.tool_call_id] = {
                        "input_msg_id": uuid.uuid4().hex,
                        "name": event.tool_call_name,
                        "args_json_acc": "",
                        "output_text_acc": "",
                    }

                elif evt_type == EventType.TOOL_CALL_DELTA.value:
                    state = tool_calls.get(event.tool_call_id)
                    if state is None:
                        # Lazy-register on a missing TOOL_CALL_START.
                        state = {
                            "input_msg_id": uuid.uuid4().hex,
                            "name": "",
                            "args_json_acc": "",
                            "output_text_acc": "",
                        }
                        tool_calls[event.tool_call_id] = state
                    state["args_json_acc"] += event.delta or ""

                elif evt_type == EventType.TOOL_CALL_END.value:
                    state = tool_calls.get(event.tool_call_id)
                    if state is None:
                        continue
                    raw = state["args_json_acc"]
                    try:
                        parsed_args: Any = json.loads(raw) if raw else {}
                    except json.JSONDecodeError:
                        parsed_args = raw
                    in_data = DataContent(
                        type=ContentType.DATA,
                        data={
                            "name": state["name"],
                            "call_id": event.tool_call_id,
                            "arguments": parsed_args,
                        },
                    )
                    in_envelope = Message(
                        id=state["input_msg_id"],
                        type=MessageType.PLUGIN_CALL,
                        role=Role.ASSISTANT,
                        content=[in_data],
                        status=RunStatus.Completed,
                    )
                    in_envelope.name = "assistant"
                    in_envelope.object = "message"
                    response.output.append(in_envelope)
                    yield in_envelope

                elif evt_type == EventType.TOOL_RESULT_START.value:
                    state = tool_calls.get(event.tool_call_id)
                    if state is None:
                        # Lazy-register so we still emit something coherent.
                        state = {
                            "input_msg_id": uuid.uuid4().hex,
                            "name": event.tool_call_name,
                            "args_json_acc": "",
                            "output_text_acc": "",
                        }
                        tool_calls[event.tool_call_id] = state
                    state["output_msg_id"] = uuid.uuid4().hex
                    # The in_progress envelope needs the call_id in its
                    # ``content[0].data`` so ``mergeToolMessages`` in
                    # Builder.tsx can pair it with the matching plugin_call
                    # while we're still streaming the tool output — that's
                    # the merge that drives ``<ToolCall loading>``.  An
                    # empty content[] would float this message separately
                    # and the spinner wouldn't fire on the unified card.
                    stub_data = DataContent(
                        type=ContentType.DATA,
                        data={
                            "name": state["name"],
                            "call_id": event.tool_call_id,
                            "output": "",
                        },
                    )
                    out_envelope = Message(
                        id=state["output_msg_id"],
                        type=MessageType.PLUGIN_CALL_OUTPUT,
                        role=Role.ASSISTANT,
                        content=[stub_data],
                        status=RunStatus.InProgress,
                    )
                    out_envelope.name = "assistant"
                    out_envelope.object = "message"
                    state["output_envelope"] = out_envelope
                    yield out_envelope

                elif evt_type == EventType.TOOL_RESULT_TEXT_DELTA.value:
                    state = tool_calls.get(event.tool_call_id)
                    if state is None:
                        continue
                    state["output_text_acc"] += event.delta or ""

                elif evt_type == EventType.TOOL_RESULT_DATA_DELTA.value:
                    # Binary tool output — none of the four migrated tools
                    # produce these; revisit when view_media/desktop_screenshot
                    # ship.
                    logger.debug(
                        "stream_query: dropped TOOL_RESULT_DATA_DELTA "
                        "(tool_call_id=%s media_type=%s)",
                        getattr(event, "tool_call_id", None),
                        getattr(event, "media_type", None),
                    )

                elif evt_type == EventType.TOOL_RESULT_END.value:
                    state = tool_calls.get(event.tool_call_id)
                    if state is None:
                        continue
                    tool_state = getattr(event, "state", None)
                    if hasattr(tool_state, "value"):
                        tool_state = tool_state.value
                    out_data = DataContent(
                        type=ContentType.DATA,
                        data={
                            "name": state["name"],
                            "call_id": event.tool_call_id,
                            "output": state["output_text_acc"],
                            "state": tool_state,
                        },
                    )
                    out_envelope = state.get("output_envelope")
                    if out_envelope is None:
                        # No TOOL_RESULT_START seen; build envelope now.
                        out_envelope = Message(
                            id=uuid.uuid4().hex,
                            type=MessageType.PLUGIN_CALL_OUTPUT,
                            role=Role.ASSISTANT,
                            content=[out_data],
                            status=RunStatus.Completed,
                        )
                        out_envelope.name = "assistant"
                        out_envelope.object = "message"
                    else:
                        out_envelope.content = [out_data]
                        out_envelope.status = RunStatus.Completed
                    response.output.append(out_envelope)
                    yield out_envelope

                # Other events (Reply/ModelCall) — drop for the
                # migration mainline.  Re-introduce on the way back.

        except Exception as exc:
            logger.exception("stream_query: reply_stream raised")
            error_text = str(exc) or exc.__class__.__name__

        if message_started:
            completed_message.status = RunStatus.Completed
            response.output.append(completed_message)
            yield completed_message

        if error_text:
            response.status = RunStatus.Failed
            response.error = error_text
        else:
            response.status = RunStatus.Completed
        yield response


def _request_input_to_msgs(input_list: List[Any]) -> List[Any]:
    """Convert ``AgentRequest.input`` (list of 1.x Message) to a list of
    agentscope 2.0 ``Msg`` objects.

    Text-only fast path — anything else is dropped for the round-trip
    mainline.  TODO(as2-migration): port image/audio/file/tool blocks
    once those flows are exercised end-to-end.
    """
    try:
        from agentscope.message import Msg, TextBlock
    except Exception:  # pragma: no cover - defensive
        return []

    out: List[Any] = []
    for m in input_list:
        role = getattr(m, "role", None)
        if hasattr(role, "value"):
            role = role.value
        role = role or "user"
        if role == "tool":
            # agentscope 2.0 only allows system/user/assistant; collapse
            # tool→assistant so the Msg validates.
            role = "assistant"

        blocks: list = []
        for c in getattr(m, "content", None) or []:
            ctype = getattr(c, "type", None)
            if hasattr(ctype, "value"):
                ctype = ctype.value
            if ctype == "text":
                text = getattr(c, "text", None) or ""
                if text:
                    blocks.append(TextBlock(type="text", text=text))

        if not blocks:
            continue

        out.append(Msg(name=role, role=role, content=blocks))
    return out


