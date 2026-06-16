# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""PolicyGuardedTool — Governance policy-checked tool wrapper.

Replaces the existing GuardedFunctionTool. Each tool call goes through
two layers:
1. check_permissions: pre-execution decision
2. __call__: actual execution — handles sandbox violation retry loop
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Optional

from agentscope.message import TextBlock
from agentscope.tool import ToolChunk

from .policy import (
    GovernanceRule,
    GovernanceAction,
    ToolCallSpec,
)
from .resource_governor import ResourceGovernor
from .tool_registry import DEFAULT_REGISTRY

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PolicyGuardedTool
# ---------------------------------------------------------------------------


class PolicyGuardedTool:
    """Governance policy-checked tool wrapper.

    Dynamically inherits from FunctionTool, implementing:
    - check_permissions: calls governor.assert_and_audit() for policy decision
    - __call__: overrides to handle sandbox execution + violation retry

    .. warning:: Known limitation — dynamic anonymous class

        ``__new__`` creates a fresh class via ``type(...)`` on every call,
        so ``isinstance(tool, PolicyGuardedTool)`` always returns False.
        This is the same pattern used by ``GuardedFunctionTool`` and
        ``DriverCapabilityTool``.  A unified refactor (metaclass or mixin)
        is tracked as a follow-up task.
    """

    def __new__(cls, *args: Any, **kwargs: Any) -> Any:
        from agentscope.tool import FunctionTool

        if cls is PolicyGuardedTool:
            real_cls = type(
                "PolicyGuardedTool",
                (FunctionTool,),
                {
                    "__init__": _policy_tool_init,
                    "check_permissions": _policy_tool_check_permissions,
                    "__call__": _policy_tool_call,
                    "__doc__": cls.__doc__,
                },
            )
            return real_cls(*args, **kwargs)
        return object.__new__(cls)


def _policy_tool_init(
    self: Any,
    func: Any,
    *,
    governor: Optional[ResourceGovernor] = None,
    request_context: dict[str, str] | None = None,
    **kwargs: Any,
) -> None:
    from agentscope.tool import FunctionTool

    FunctionTool.__init__(self, func, **kwargs)
    # pylint: disable=protected-access
    self._qp_governor = governor
    self._qp_request_context = request_context or {}
    self._qp_policy_decision = None  # Pre-evaluation result
    self._qp_sandbox_mode = False  # Whether to execute in sandbox


async def _policy_tool_check_permissions(
    self: Any,
    input_data: dict[str, Any] | None = None,
    context: Any = None,
    *_extra_args: Any,
    **_extra_kwargs: Any,
) -> Any:
    """Perform governance policy evaluation for a tool call.

    Flow:
        1. Construct ToolCallSpec(tool_name, target, agent_id, session_id)
        2. governor.assert_and_audit(tool_call) → GovernanceDecision
        3. Map to PermissionDecision
    """
    from agentscope.permission import PermissionBehavior, PermissionDecision

    del context

    governor = getattr(self, "_qp_governor", None)
    if governor is None:
        # Fail-closed: if governance layer failed to initialize, deny all
        # tool calls rather than silently allowing unguarded execution.
        logger.error(
            "PolicyGuardedTool: governor is None for tool '%s' — "
            "governance layer not initialized; denying (fail-closed).",
            getattr(self, "name", "Unknown"),
        )
        return PermissionDecision(
            behavior=PermissionBehavior.DENY,
            message=(
                "Governance layer unavailable (governor not initialized). "
                "All tool calls are denied until governance is restored. "
                "Please check server logs for initialization errors."
            ),
        )

    tool_name = DEFAULT_REGISTRY.python_to_policy_name(
        getattr(self, "name", "Unknown"),
    )
    input_data = input_data or {}
    # Store input_data for potential violation handling in __call__
    self._qp_last_input_data = input_data
    target = DEFAULT_REGISTRY.extract_target(tool_name, input_data)

    # Resolve file-tool targets to absolute paths so workspace ALLOW
    # rules (e.g. "Read(/home/user/project/**)") match even when the
    # LLM passes a relative path like "src/main.py".  Empty targets
    # (e.g. Grep/Glob with no explicit path) default to workspace root.
    tool_type = DEFAULT_REGISTRY.get_type(tool_name)
    if tool_type == "file":
        ws_dir = getattr(governor, "workspace_dir", None)
        if not target:
            if ws_dir:
                target = str(ws_dir)
        elif not os.path.isabs(target):
            if ws_dir:
                target = os.path.normpath(os.path.join(ws_dir, target))

    agent_id = getattr(self, "_qp_request_context", {}).get("agent_id", "")
    session_id = getattr(self, "_qp_request_context", {}).get(
        "session_id",
        "",
    )

    tc_spec = ToolCallSpec(
        tool_name=tool_name,
        target=target,
        agent_id=agent_id,
        session_id=session_id,
    )

    decision = governor.assert_and_audit(tc_spec)

    # Cache the decision for __call__ to use
    self._qp_policy_decision = decision
    self._qp_sandbox_mode = False

    if decision.action is GovernanceAction.ALLOW:
        return PermissionDecision(
            behavior=PermissionBehavior.ALLOW,
            message="governance: tool allowed.",
        )
    elif decision.action is GovernanceAction.DENY:
        return PermissionDecision(
            behavior=PermissionBehavior.DENY,
            message=f"Tool '{tool_name}' is denied by governance policy "
            f"(target: {target}).",
        )
    elif decision.action is GovernanceAction.SANDBOX_FALLBACK:
        # Bash tool with no rule match → allow execution in sandbox
        self._qp_sandbox_mode = True
        self._qp_sandbox_config = decision.sandbox_config
        return PermissionDecision(
            behavior=PermissionBehavior.ALLOW,
            message="governance: sandbox fallback.",
        )
    elif decision.action is GovernanceAction.ASK:
        # Requires user confirmation
        self._qp_policy_decision = decision

        return await _ask_user_approval(
            governor=governor,
            tool_name=tool_name,
            target=target,
            input_data=input_data,
            agent_id=agent_id,
            session_id=session_id,
            request_context=getattr(self, "_qp_request_context", {}) or {},
        )
    else:
        # Unknown decision → deny as safe default
        return PermissionDecision(
            behavior=PermissionBehavior.DENY,
            message=f"Unknown policy decision: {decision.action}",
        )


async def _policy_tool_call(
    self: Any,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Override FunctionTool.__call__ for sandbox execution + retry.

    If sandbox execution triggers a violation (ToolChunk state=DENIED),
    request user approval.
    If the user approves, retry without sandbox.
    """
    sandbox_mode = getattr(self, "_qp_sandbox_mode", False)
    if sandbox_mode:
        sandbox_config = getattr(self, "_qp_sandbox_config", None)
        if sandbox_config is not None:
            kwargs["sandbox_config"] = sandbox_config

    # Call the original function
    from agentscope.tool import FunctionTool
    from agentscope.message import ToolResultState

    result = await FunctionTool.__call__(self, *args, **kwargs)

    # Check if sandbox violation was returned (state=DENIED)
    if not (
        isinstance(result, ToolChunk)
        and result.state == ToolResultState.DENIED
    ):
        return result

    # Extract violation message from metadata or content
    violation_msg = ""
    if hasattr(result, "metadata") and result.metadata:
        violation_msg = result.metadata.get("sandbox_violation", "")
    if not violation_msg:
        # Fallback: extract from content text
        for block in result.content or []:
            if hasattr(block, "text") and "Sandbox violation:" in block.text:
                violation_msg = (
                    block.text.split("Sandbox violation:", 1)[1]
                    .split("\n")[0]
                    .strip()
                )
                break

    logger.info(
        "PolicyGuardedTool: sandbox violation for '%s': %s",
        getattr(self, "name", "Unknown"),
        violation_msg,
    )

    governor = getattr(self, "_qp_governor", None)
    request_context = getattr(self, "_qp_request_context", {}) or {}

    if governor is None:
        # No governor, can't approve — return the violation as DENIED
        return ToolChunk(
            is_last=True,
            state=ToolResultState.DENIED,
            content=[
                TextBlock(
                    type="text",
                    text=f"Sandbox violation: {violation_msg}\n"
                    f"Command was blocked by sandbox security policy.",
                ),
            ],
        )

    # Trigger approval flow
    tool_name = DEFAULT_REGISTRY.python_to_policy_name(
        getattr(self, "name", "Unknown"),
    )
    input_data = getattr(self, "_qp_last_input_data", {}) or {}
    target = DEFAULT_REGISTRY.extract_target(tool_name, input_data)
    agent_id = request_context.get("agent_id", "")
    session_id = request_context.get("session_id", "")

    from agentscope.permission import PermissionBehavior

    governance_reason = getattr(
        getattr(self, "_qp_policy_decision", None),
        "reason",
        None,
    )
    decision = await _ask_user_approval(
        governor=governor,
        tool_name=tool_name,
        target=target,
        input_data=input_data,
        agent_id=agent_id,
        session_id=session_id,
        request_context=request_context,
        violation_msg=violation_msg or None,
        governance_reason=governance_reason,
    )

    if decision.behavior == PermissionBehavior.ALLOW:
        # User approved: retry without sandbox
        logger.info(
            "PolicyGuardedTool: user approved sandbox violation, "
            "retrying without sandbox for '%s'",
            getattr(self, "name", "Unknown"),
        )
        kwargs.pop("sandbox_config", None)
        self._qp_sandbox_mode = False
        return await FunctionTool.__call__(self, *args, **kwargs)
    else:
        # User denied: return the violation as DENIED
        return ToolChunk(
            is_last=True,
            state=ToolResultState.DENIED,
            content=[
                TextBlock(
                    type="text",
                    text=f"Sandbox violation: {violation_msg}\n"
                    f"Command was blocked and user denied approval.\n\n"
                    f"{_NO_RETRY_INSTRUCTION}",
                ),
            ],
        )


# ---------------------------------------------------------------------------
# ASK path: reuse ApprovalService
# ---------------------------------------------------------------------------


async def _ask_user_approval(
    governor: ResourceGovernor,
    tool_name: str,
    target: str,
    input_data: dict[str, Any],
    agent_id: str,
    session_id: str,
    request_context: dict[str, str],
    *,
    violation_msg: str | None = None,
    governance_reason: str | None = None,
) -> Any:
    """Request user approval, blocking until a reply is received."""
    from agentscope.permission import PermissionBehavior, PermissionDecision

    from ..app.approvals import get_approval_service
    from ..constant import TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS
    from ..security.tool_guard.approval import (
        ApprovalDecision,
        format_findings_summary,
    )
    from ..security.tool_guard.models import (
        GuardFinding,
        GuardSeverity,
        GuardThreatCategory,
        ToolGuardResult,
    )

    ctx = request_context or {}
    user_id = str(ctx.get("user_id") or "")
    channel = str(ctx.get("channel") or "")
    root_session_id = str(ctx.get("root_session_id") or session_id)
    root_agent_id = str(ctx.get("root_agent_id") or agent_id or "unknown")

    # Construct a synthetic ToolGuardResult for ApprovalService
    guard_result = ToolGuardResult(
        tool_name=tool_name,
        params=input_data,
        findings=[
            GuardFinding(
                id=uuid.uuid4().hex[:8],
                rule_id="policy_ask",
                category=GuardThreatCategory.RESOURCE_ABUSE,
                severity=(
                    GuardSeverity.HIGH if violation_msg else GuardSeverity.INFO
                ),
                title=(
                    "Sandbox Violation — Approve Unsandboxed Execution?"
                    if violation_msg
                    else "Policy Approval Required"
                ),
                description=(
                    f"Tool '{tool_name}' with target '{target}' "
                    f"requires user approval per governance policy."
                    + (
                        f"\n\nGovernance reason: {governance_reason}"
                        if governance_reason
                        else ""
                    )
                    + (
                        f"\n\n\u26a0\ufe0f Sandbox violation: {violation_msg}"
                        f"\n\n**If you approve, this command will be "
                        f"re-executed WITHOUT sandbox isolation (full host "
                        f"access).** The kernel-level filesystem restrictions "
                        f"that blocked it will no longer apply."
                        if violation_msg
                        else ""
                    )
                ),
                tool_name=tool_name,
                remediation=(
                    "Approve to re-run without sandbox (full host access), "
                    "or deny to block the command."
                    if violation_msg
                    else "Approve or deny this tool call"
                ),
                guardian="governance_policy",
                metadata={
                    "target": target,
                    **(
                        {
                            "sandbox_violation": violation_msg,
                            "escalation": "sandbox_to_host",
                        }
                        if violation_msg
                        else {}
                    ),
                },
            ),
        ],
        guardians_used=["governance_policy"],
    )

    svc = get_approval_service()
    tool_call_id = str(ctx.get("tool_call_id") or "")
    if session_id and tool_call_id:
        await svc.cancel_stale_pending_for_tool_call(session_id, tool_call_id)

    pending = await svc.create_pending(
        session_id=session_id,
        root_session_id=root_session_id,
        owner_agent_id=root_agent_id,
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
        "PolicyGuardedTool: awaiting approval for tool=%s session=%s "
        "request_id=%s target=%s",
        tool_name,
        session_id[:8] if session_id else "",
        pending.request_id[:8],
        target,
    )

    try:
        decision = await svc.wait_for_approval(
            pending.request_id,
            TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        logger.error(
            "PolicyGuardedTool: wait_for_approval crashed (%s); denying",
            exc,
            exc_info=True,
        )
        decision = ApprovalDecision.DENIED

    # Record user approve/deny result to audit log
    tc_spec = ToolCallSpec(tool_name, target, agent_id, session_id)
    approved = decision == ApprovalDecision.APPROVED
    governor.record_approval(tc_spec, approved)

    summary = format_findings_summary(guard_result)
    if decision == ApprovalDecision.APPROVED:
        # ── Distinguish builtin ask vs user ask ──
        # builtin ask → no rule recorded (asks every time, protecting
        # high-risk resources)
        # user ask   → record generalized rule (skip asking next time)
        if not governor.is_builtin_ask(tc_spec):
            try:
                from .policy import generalize_rule_match

                # Rule generalization (§8.2): currently records the exact
                # ``Tool(target)`` match without wildcards (see
                # ``generalize_rule_match`` in ``policy.py``) to avoid the
                # security risks of broad wildcard rules.
                generalized = generalize_rule_match(tool_name, target)
                _, rule_pattern = generalized.split("(", 1)
                rule_pattern = rule_pattern.rstrip(")")

                # Empty pattern guard (§8.1): tools with empty target
                # don't write rules
                if rule_pattern:
                    rule = GovernanceRule(
                        match=generalized,
                        action=GovernanceAction.ALLOW,
                        reason="user approved",
                        grantee=agent_id or "*",
                        duration="session",
                        session_id=session_id,
                    )
                    governor.add_rule(rule)
                    logger.info(
                        "PolicyGuardedTool: added approved rule: %s",
                        rule.match,
                    )
                else:
                    logger.debug(
                        "PolicyGuardedTool: empty pattern, skipping rule "
                        "for tool=%s target=%s",
                        tool_name,
                        target,
                    )
            except Exception:
                logger.debug(
                    "PolicyGuardedTool: failed to persist approved rule",
                    exc_info=True,
                )
        return PermissionDecision(
            behavior=PermissionBehavior.ALLOW,
            message=f"Approved by user.\n{summary}",
        )

    denial_msg = (
        f"User denied the request to run '{tool_name}'.\n{summary}"
        if decision == ApprovalDecision.DENIED
        else (
            f"Approval for '{tool_name}' timed out after "
            f"{int(TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS)}s.\n{summary}"
        )
    )
    return PermissionDecision(
        behavior=PermissionBehavior.DENY,
        message=denial_msg + _NO_RETRY_INSTRUCTION,
    )


_NO_RETRY_INSTRUCTION = (
    "\n\n⚠️ **System instruction**: this denial is final for the current "
    "request. Do not retry this tool with similar parameters. Reply to "
    "the user explaining why the action could not be completed and, if "
    "appropriate, ask them how they want to proceed."
)
