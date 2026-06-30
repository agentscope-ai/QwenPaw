# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""PolicyGuardedTool — Governance policy-checked tool wrapper.

Replaces the GuardedFunctionTool. Each tool call goes through two layers:
1. check_permissions: pre-execution decision
2. __call__: actual execution — handles sandbox violation retry loop
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from agentscope.message import TextBlock
from agentscope.tool import ToolChunk

from .policy import (
    GovernanceDecision,
    GovernanceAction,
    ToolCallSpec,
)
from .resource_governor import ResourceGovernor
from .tool_registry import DEFAULT_REGISTRY

logger = logging.getLogger(__name__)

_NO_RETRY_INSTRUCTION = (
    "\n\n\u26a0\ufe0f **System instruction**: this denial is final"
    " for the current request. Do not retry this tool with similar"
    " parameters. Reply to the user explaining why the action could"
    " not be completed and, if appropriate, ask them how they want"
    " to proceed."
)


def _is_execution_level_off() -> bool:
    """Check if execution_level is 'off' (dev mode pass-through).

    Reads directly from policy.yaml (without needing a governor) to
    support the case where governor initialization failed but the user
    explicitly configured execution_level=off for development.
    """
    try:
        from pathlib import Path

        import yaml

        from ..constant import WORKING_DIR

        policy_path = Path(WORKING_DIR) / ".qwenpaw" / "policy.yaml"
        if not policy_path.exists():
            return False
        with open(policy_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return isinstance(data, dict) and data.get("execution_level") == "off"
    except Exception:
        return False


def _resolve_agent_approval_level(
    request_context: dict[str, str] | None,
) -> Optional[Any]:
    """Resolve the per-agent approval_level from agent.json.

    This is what the Web UI 'Tool Execution Security' card saves to.
    Returns the ToolExecutionLevel enum, or None if unresolvable.
    """
    if not request_context:
        return None
    agent_id = request_context.get("agent_id", "")
    if not agent_id:
        return None
    try:
        from ..config.config import load_agent_config
        from ..security.tool_guard.execution_level import ToolExecutionLevel

        profile = load_agent_config(agent_id)
        raw = getattr(profile, "approval_level", None)
        return ToolExecutionLevel.from_config(raw)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# PolicyGuardedTool
# ---------------------------------------------------------------------------


class PolicyGuardedTool:
    """Governance policy-checked tool wrapper.

    Dynamically inherits from FunctionTool, implementing:
    - check_permissions: calls assert_policy() + audit() for policy decision
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
                    "_build_tc_spec": _build_tc_spec,
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
    self._qp_governor = governor
    self._qp_request_context = request_context or {}
    self._qp_policy_decision = None  # Pre-evaluation result
    self._qp_sandbox_mode = False  # Whether to execute in sandbox
    self._qp_raw_params = {}  # Set per-call by check_permissions


def _build_tc_spec(self: Any) -> ToolCallSpec:
    """Build ToolCallSpec from instance fields + dynamic target."""
    governor = self._qp_governor
    params = getattr(self, "_qp_raw_params", {})
    tool_name = DEFAULT_REGISTRY.python_to_policy_name(
        getattr(self, "name", "Unknown"),
    )
    request_ctx = getattr(self, "_qp_request_context", {}) or {}
    return ToolCallSpec(
        tool_name=tool_name,
        target=DEFAULT_REGISTRY.extract_target(
            tool_name,
            params,
            workspace_dir=str(governor.workspace_dir) if governor else "",
        ),
        agent_id=request_ctx.get("agent_id", ""),
        session_id=request_ctx.get("session_id", ""),
        raw_params=params,
    )


# pylint: disable=too-many-return-statements
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
        2. governor.assert_policy(tool_call) → GovernanceDecision
        3. governor.audit(tool_call, decision)
        4. Map to PermissionDecision
    """
    from agentscope.permission import PermissionBehavior, PermissionDecision

    del context

    governor = getattr(self, "_qp_governor", None)

    # ── Agent-level approval_level check ──
    # Web UI saves approval_level to agent.json; governance
    # policy.yaml has its own execution_level.  We must honour
    # the agent-level setting so the UI toggle works.
    request_ctx = getattr(self, "_qp_request_context", None) or {}
    agent_level = _resolve_agent_approval_level(request_ctx)
    if agent_level is not None and agent_level.is_disabled():
        return PermissionDecision(
            behavior=PermissionBehavior.ALLOW,
            message="governance: approval_level=off, all tools allowed.",
        )

    # Sync agent-level approval_level to the governor's policy
    # so the three-phase evaluation uses the correct threshold.
    if governor is not None and agent_level is not None:
        governor.policy.execution_level = agent_level.value

    if governor is None:
        # Check if execution_level is "off" (dev mode) — allow pass-through
        if _is_execution_level_off():
            return PermissionDecision(
                behavior=PermissionBehavior.ALLOW,
                message="governance: execution_level=off (dev mode), "
                "governor unavailable — pass-through.",
            )
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

    self._qp_raw_params = input_data or {}

    tc_spec = self._build_tc_spec()

    decision = governor.assert_policy(tc_spec)
    governor.audit(tc_spec, decision)

    # Cache the decision + tc_spec for __call__ to use
    self._qp_policy_decision = decision
    self._qp_tc_spec = tc_spec
    self._qp_sandbox_mode = False

    if decision.action is GovernanceAction.ALLOW:
        return PermissionDecision(
            behavior=PermissionBehavior.ALLOW,
            message="governance: tool allowed.",
        )
    elif decision.action is GovernanceAction.DENY:
        return PermissionDecision(
            behavior=PermissionBehavior.DENY,
            message=f"governance: '{tc_spec.tool_name}' is denied by policy",
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
            tc_spec=tc_spec,
            request_context=getattr(self, "_qp_request_context", {}) or {},
            policy_findings=decision.findings,
            governance_reason=decision.reason,
            source=decision.source,
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

    # Trigger approval flow — reuse tc_spec from check_permissions
    tc_spec = getattr(self, "_qp_tc_spec", None)
    if tc_spec is None:
        # Fallback: reconstruct if check_permissions didn't run
        self._qp_raw_params = {}
        tc_spec = self._build_tc_spec()

    governance_reason = getattr(
        getattr(self, "_qp_policy_decision", None),
        "reason",
        None,
    )
    governance_source = getattr(
        getattr(self, "_qp_policy_decision", None),
        "source",
        "builtin-rules",
    )

    # Record the ASK escalation (sandbox violation → ask user)
    governor.audit(
        tc_spec,
        GovernanceDecision(
            action=GovernanceAction.ASK,
            reason=(
                f"sandbox violation: {violation_msg}"
                if violation_msg
                else "sandbox violation, ask user"
            ),
        ),
    )

    from agentscope.permission import PermissionBehavior

    decision = await _ask_user_approval(
        governor=governor,
        tc_spec=tc_spec,
        request_context=request_context,
        violation_msg=violation_msg or None,
        governance_reason=governance_reason,
        source=governance_source,
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
    tc_spec: ToolCallSpec,
    request_context: dict[str, str],
    *,
    violation_msg: str | None = None,
    governance_reason: str | None = None,
    policy_findings: list[Any] | None = None,
    source: str = "builtin-rules",
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

    tool_name = tc_spec.tool_name
    target = tc_spec.target
    agent_id = tc_spec.agent_id
    session_id = tc_spec.session_id
    params = tc_spec.raw_params

    ctx = request_context or {}
    user_id = str(ctx.get("user_id") or "")
    channel = str(ctx.get("channel") or "")
    root_session_id = str(ctx.get("root_session_id") or session_id)
    root_agent_id = str(ctx.get("root_agent_id") or agent_id or "unknown")

    # Construct a ToolGuardResult for ApprovalService.
    # If deep-scan findings were attached by policy.evaluate(),
    # convert them into GuardFindings for the approval card.
    if policy_findings:
        converted_findings = []
        for pf in policy_findings:
            # pf is a governance.detectors.GuardFinding (dataclass)
            converted_findings.append(
                GuardFinding(
                    id=getattr(pf, "id", uuid.uuid4().hex[:8]),
                    rule_id=getattr(pf, "rule_id", "policy_deep_scan"),
                    category=GuardThreatCategory(
                        getattr(pf, "category", "resource_abuse"),
                    ),
                    severity=GuardSeverity(
                        getattr(pf, "severity", "INFO"),
                    ),
                    title=getattr(pf, "title", "Policy Approval Required"),
                    description=getattr(pf, "description", ""),
                    tool_name=tool_name,
                    param_name=getattr(pf, "param_name", None),
                    matched_value=getattr(pf, "matched_value", None),
                    matched_pattern=getattr(pf, "matched_pattern", None),
                    snippet=getattr(pf, "snippet", None),
                    remediation=getattr(pf, "remediation", None),
                    guardian=getattr(pf, "detector", "governance_policy"),
                    metadata=getattr(pf, "metadata", {}),
                ),
            )
        guard_result = ToolGuardResult(
            tool_name=tool_name,
            params=params,
            findings=converted_findings,
            guardians_used=["governance_policy"],
        )
    else:
        guard_result = ToolGuardResult(
            tool_name=tool_name,
            params=params,
            findings=[
                GuardFinding(
                    id=uuid.uuid4().hex[:8],
                    rule_id="policy_ask",
                    category=GuardThreatCategory.RESOURCE_ABUSE,
                    severity=(
                        GuardSeverity.HIGH
                        if violation_msg
                        else GuardSeverity.INFO
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
                            f"\n\n\u26a0\ufe0f Sandbox violation: "
                            f"{violation_msg}"
                            f"\n\n**If you approve, this command will be "
                            f"re-executed WITHOUT sandbox isolation (full "
                            f"host access).** The kernel-level filesystem "
                            f"restrictions that blocked it will no longer "
                            f"apply."
                            if violation_msg
                            else ""
                        )
                    ),
                    tool_name=tool_name,
                    remediation=(
                        "Approve to re-run without sandbox (full host "
                        "access), or deny to block the command."
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
                "input": dict(params or {}),
            },
            "display": {
                "tool_name": tool_name,
                "tool_source": source,
            },
            "channel_meta": ctx.get("channel_meta"),
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
    approved = decision == ApprovalDecision.APPROVED
    approval_decision = GovernanceDecision(
        action=GovernanceAction.ALLOW if approved else GovernanceAction.DENY,
        reason="User Approve" if approved else "User Deny",
    )
    governor.audit(tc_spec, approval_decision)

    summary = format_findings_summary(guard_result)
    if decision == ApprovalDecision.APPROVED:
        # ── Record approved rule (skip for builtin ask) ──
        governor.add_approved_rule(tc_spec)
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
