# -*- coding: utf-8 -*-
"""GuardedFunctionTool — permission-checked tool wrapper."""
from __future__ import annotations

import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)


class GuardedFunctionTool:
    """Permission-checked tool wrapper using qwenpaw's tool-guard engine.

    Routes every tool invocation through
    ``qwenpaw.security.tool_guard.engine`` which evaluates guard rules and
    returns a ``PermissionDecision``.  Depending on execution level
    (OFF / AUTO / SMART / STRICT), the decision can be:

    - ALLOW — tool runs immediately
    - DENY  — tool is blocked with an error message
    - ASK   — an approval request is sent to the user via the approval
              service; the tool blocks until the user responds or timeout

    Request context (session_id, user_id, channel, etc.) is passed at
    construction time via the ``request_context`` parameter and stored
    on ``self._qp_request_context``.  This avoids ContextVar-based
    implicit passing.

    Inheriting from ``FunctionTool`` happens lazily inside ``__new__`` so
    importing this module does not require the agentscope package to be
    importable at definition time (the runtime package imports agentscope
    only inside function bodies).
    """

    def __new__(cls, *args: Any, **kwargs: Any) -> Any:  # type: ignore[misc]
        from agentscope.tool import FunctionTool

        if cls is GuardedFunctionTool:
            real_cls = type(
                "GuardedFunctionTool",
                (FunctionTool,),
                {
                    "__init__": _guarded_tool_init,
                    "_resolve_execution_level": (
                        _guarded_tool_resolve_execution_level
                    ),
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
    self._qp_agent_id = agent_id  # pylint: disable=protected-access
    # pylint: disable=protected-access
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
    can't be initialised.
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
    except Exception as exc:
        logger.warning(
            "GuardedFunctionTool: failed to resolve approval_level for "
            "agent=%s (%s); falling back to BYPASS",
            agent_id,
            exc,
        )
        return "bypass"


_NO_RETRY_INSTRUCTION = (
    "\n\n⚠️ **System instruction**: this denial is final for the current "
    "request. Do not retry this tool with similar parameters. Reply to "
    "the user explaining why the action could not be completed and, if "
    "appropriate, ask them how they want to proceed."
)


def _with_no_retry_instruction(body: str) -> str:
    """Append a stop-retry hint to a denial message body.

    1.x's ``_acting_denied`` injected a localized "do not retry" line into
    the synthetic ``ToolResultBlock`` so the model wouldn't immediately
    re-issue the denied tool call with a tweaked argument.  Centralised
    here so every denial path (denied-list / user-denied / approval-timeout)
    sends the same instruction.
    """
    return body + _NO_RETRY_INSTRUCTION


# pylint: disable=too-many-return-statements
async def _guarded_tool_check_permissions(
    self: Any,
    input_data: dict[str, Any] | None = None,
    context: Any = None,
    *_extra_args: Any,
    **_extra_kwargs: Any,
) -> Any:
    """Drive qwenpaw's tool-guard engine + ApprovalService for one tool call.

    Signature matches agentscope's
    :meth:`PermissionEngine.check_permission` call site
    (:file:`agentscope/permission/_engine.py:212`):
    ``await tool.check_permissions(input_data, self.context)``.  The tool
    instance itself is ``self`` — we read ``self.name`` for guard-rule
    matching, not a separate ``tool`` arg.

    ``*_extra_args`` / ``**_extra_kwargs`` swallow any additional positional
    or keyword args agentscope might add in future releases without
    breaking us.

    ASK is implemented by blocking on :class:`PendingApproval.future`
    (resolved by the ``/approval/{approve,deny}`` HTTP endpoints) rather
    than emitting ``PermissionBehavior.ASK`` — the polling-based
    ``/console/push-messages`` path that the frontend already uses for
    approval cards keeps working without an SSE round-trip change.
    """
    del context  # qwenpaw's guard doesn't read PermissionContext yet
    from agentscope.permission import (
        PermissionBehavior,
        PermissionDecision,
    )

    level = self._resolve_execution_level()  # pylint: disable=protected-access

    if level == "bypass":
        return PermissionDecision(
            behavior=PermissionBehavior.ALLOW,
            message="Tool guard BYPASS — no agent_id bound.",
        )

    from ..security.tool_guard.engine import get_guard_engine
    from ..security.tool_guard.execution_level import ToolExecutionLevel
    from ..security.tool_guard.models import GuardSeverity

    # ``self`` IS the tool (GuardedFunctionTool subclasses FunctionTool).
    tool_name = getattr(self, "name", None) or ""
    input_data = input_data or {}
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
        body = (
            f"Tool '{tool_name}' is permanently blocked by the denied-list."
            if denied_result is None or not denied_result.findings
            else _format_guard_message(tool_name, denied_result)
        )
        return PermissionDecision(
            behavior=PermissionBehavior.DENY,
            message=_with_no_retry_instruction(body),
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

    # Log findings so test assertions and operators can observe them.
    from ..security.tool_guard.utils import log_findings

    log_findings(tool_name, guard_result)

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
    agent_id = self._qp_agent_id  # pylint: disable=protected-access
    request_context = getattr(self, "_qp_request_context", None) or {}
    decision = await _ask_user_approval(
        agent_id=agent_id,
        tool_name=tool_name,
        input_data=input_data,
        guard_result=guard_result,
        request_context=request_context,
    )
    return decision


def _strict_info_guard_result(
    tool_name: str,
    params: dict[str, Any],
) -> Any:
    """Synthesise an INFO-level ``ToolGuardResult`` for STRICT tools.

    The approval card in STRICT mode still needs a body even when no
    rule fires.
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
        description=(f"Tool '{tool_name}' requires approval in STRICT mode"),
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
    request_context: dict[str, str] | None = None,
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

    ctx = request_context or {}
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
    except Exception as exc:
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
            message=_with_no_retry_instruction(
                f"User denied the request to run '{tool_name}'.\n{summary}",
            ),
        )
    return PermissionDecision(
        behavior=PermissionBehavior.DENY,
        message=_with_no_retry_instruction(
            f"Approval for '{tool_name}' timed out after "
            f"{int(TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS)}s.\n{summary}",
        ),
    )
