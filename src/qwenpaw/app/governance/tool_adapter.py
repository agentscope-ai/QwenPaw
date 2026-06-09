# -*- coding: utf-8 -*-
"""PolicyGuardedTool — governance 策略检查的 tool wrapper。

替代现有的 GuardedFunctionTool。每次 tool 调用走两层：
1. check_permissions: 预执行裁决 — ToolCall → governor.assert_and_audit()
2. __call__: 实际执行 — 处理 sandbox violation retry loop
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)

from .policy import PolicyRule, PolicyAction, PolicyDecision
from .tool_registry import DEFAULT_REGISTRY


# ---------------------------------------------------------------------------
# PolicyGuardedTool
# ---------------------------------------------------------------------------

class PolicyGuardedTool:
    """governance 策略检查的 tool wrapper。

    动态继承 FunctionTool，实现：
    - check_permissions: 调用 governor.assert_and_audit() 做裁决
    - __call__: 重写以处理 sandbox execution + violation retry
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
    governor: Any = None,
    request_context: dict[str, str] | None = None,
    **kwargs: Any,
) -> None:
    from agentscope.tool import FunctionTool

    FunctionTool.__init__(self, func, **kwargs)
    # pylint: disable=protected-access
    self._qp_governor = governor
    self._qp_request_context = request_context or {}
    self._qp_policy_decision = None  # 预裁决结果
    self._qp_sandbox_mode = False    # 是否在 sandbox 中执行


async def _policy_tool_check_permissions(
    self: Any,
    input_data: dict[str, Any] | None = None,
    context: Any = None,
    *_extra_args: Any,
    **_extra_kwargs: Any,
) -> Any:
    """对一次 tool 调用进行 governance 策略裁决。

    流程：
        1. 构造 ToolCall(tool_name, target, agent_id, session_id)
        2. governor.assert_and_audit(tool_call) → PolicyDecision
        3. 映射到 PermissionDecision
    """
    from agentscope.permission import PermissionBehavior, PermissionDecision

    del context

    governor = getattr(self, "_qp_governor", None)
    if governor is None:
        # ResourceGovernor 未初始化 → bypass
        return PermissionDecision(
            behavior=PermissionBehavior.ALLOW,
            message="PolicyGuardedTool: governor not started — bypass.",
        )

    tool_name = DEFAULT_REGISTRY.python_to_policy_name(
        getattr(self, "name", "Unknown"),
    )
    input_data = input_data or {}
    # Store input_data for potential violation handling in __call__
    self._qp_last_input_data = input_data
    target = DEFAULT_REGISTRY.extract_target(tool_name, input_data)

    agent_id = getattr(self, "_qp_request_context", {}).get("agent_id", "")
    session_id = getattr(self, "_qp_request_context", {}).get(
        "session_id", ""
    )

    from .resource_governor import ToolCall

    tool_call = ToolCall(
        tool_name=tool_name,
        target=target,
        agent_id=agent_id,
        session_id=session_id,
    )

    decision = governor.assert_and_audit(tool_call)

    # 缓存裁决结果供 __call__ 使用
    self._qp_policy_decision = decision
    self._qp_sandbox_mode = False

    if decision is PolicyDecision.ALLOW:
        return PermissionDecision(
            behavior=PermissionBehavior.ALLOW,
            message="governance: tool allowed.",
        )
    elif decision is PolicyDecision.DENY:
        return PermissionDecision(
            behavior=PermissionBehavior.DENY,
            message=f"Tool '{tool_name}' is denied by governance policy "
            f"(target: {target}).",
        )
    elif decision is PolicyDecision.SANDBOX_FALLBACK:
        # Bash 类 tool 无规则命中 → 允许进入 sandbox 执行
        self._qp_sandbox_mode = True
        self._qp_sandbox_config = governor.compile_sandbox_config(tool_call)
        return PermissionDecision(
            behavior=PermissionBehavior.ALLOW,
            message="governance: sandbox fallback.",
        )
    elif decision is PolicyDecision.ASK:
        # 需要用户确认
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
        # 未知 decision → deny 作为安全默认
        return PermissionDecision(
            behavior=PermissionBehavior.DENY,
            message=f"Unknown policy decision: {decision}",
        )


async def _policy_tool_call(
    self: Any,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """重写 FunctionTool.__call__，处理 sandbox execution + violation retry。

    如果 sandbox 执行时触发 SandboxViolation，向用户请求审批。
    如果用户批准，则添加规则并重试（不带 sandbox）。
    """
    sandbox_mode = getattr(self, "_qp_sandbox_mode", False)
    if sandbox_mode:
        sandbox_config = getattr(self, "_qp_sandbox_config", None)
        if sandbox_config is not None:
            kwargs["sandbox_config"] = sandbox_config

    # 调原始函数
    from agentscope.tool import FunctionTool
    try:
        return await FunctionTool.__call__(self, *args, **kwargs)
    except Exception as exc:
        # Check if it's a SandboxViolationError
        from ...agents.tools.shell import SandboxViolationError
        if not isinstance(exc, SandboxViolationError):
            raise

        # Sandbox violation: ask user for approval
        logger.info(
            "PolicyGuardedTool: sandbox violation for '%s': %s",
            getattr(self, "name", "Unknown"), exc.violation_msg,
        )

        governor = getattr(self, "_qp_governor", None)
        request_context = getattr(self, "_qp_request_context", {}) or {}

        if governor is None:
            # No governor, can't approve — return the violation as error
            from agentscope.message import TextBlock, ToolResultState
            from agentscope.tool import ToolChunk
            return ToolChunk(
                is_last=True,
                state=ToolResultState.SUCCESS,
                content=[TextBlock(
                    type="text",
                    text=f"Sandbox violation: {exc.violation_msg}\n"
                         f"Command was blocked by sandbox security policy.",
                )],
            )

        # Trigger approval flow
        tool_name = DEFAULT_REGISTRY.python_to_policy_name(
            getattr(self, "name", "Unknown"),
        )
        input_data = getattr(self, "_qp_last_input_data", {}) or {}
        target = DEFAULT_REGISTRY.extract_target(tool_name, input_data)
        agent_id = request_context.get("agent_id", "")
        session_id = request_context.get("session_id", "")

        from agentscope.permission import PermissionBehavior, PermissionDecision
        decision = await _ask_user_approval(
            governor=governor,
            tool_name=tool_name,
            target=target,
            input_data=input_data,
            agent_id=agent_id,
            session_id=session_id,
            request_context=request_context,
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
            # User denied: return the violation as error
            from agentscope.message import TextBlock, ToolResultState
            from agentscope.tool import ToolChunk
            return ToolChunk(
                is_last=True,
                state=ToolResultState.SUCCESS,
                content=[TextBlock(
                    type="text",
                    text=f"Sandbox violation: {exc.violation_msg}\n"
                         f"Command was blocked and user denied approval.\n\n"
                         f"{_NO_RETRY_INSTRUCTION}",
                )],
            )


# ---------------------------------------------------------------------------
# ASK 路径：复用 ApprovalService
# ---------------------------------------------------------------------------

async def _ask_user_approval(
    governor: Any,
    tool_name: str,
    target: str,
    input_data: dict,
    agent_id: str,
    session_id: str,
    request_context: dict,
) -> Any:
    """向用户请求 approve，阻塞等待回复。"""
    from agentscope.permission import PermissionBehavior, PermissionDecision

    from ...app.approvals import get_approval_service
    from ...constant import TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS
    from ...security.tool_guard.approval import (
        ApprovalDecision,
        format_findings_summary,
    )
    from ...security.tool_guard.models import (
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

    # 构造合成 ToolGuardResult 供 ApprovalService 使用
    guard_result = ToolGuardResult(
        tool_name=tool_name,
        params=input_data,
        findings=[
            GuardFinding(
                id=uuid.uuid4().hex[:8],
                rule_id="policy_ask",
                category=GuardThreatCategory.RESOURCE_ABUSE,
                severity=GuardSeverity.INFO,
                title="Policy Approval Required",
                description=(
                    f"Tool '{tool_name}' with target '{target}' "
                    f"requires user approval per governance policy."
                ),
                tool_name=tool_name,
                remediation="Approve or deny this tool call",
                guardian="governance_policy",
                metadata={"target": target},
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

    # 记录用户 approve/deny 结果到审计日志
    from .resource_governor import ToolCall
    approval_call = ToolCall(tool_name, target, agent_id, session_id)
    approved = decision == ApprovalDecision.APPROVED
    governor.record_approval(approval_call, approved)

    summary = format_findings_summary(guard_result)
    if decision == ApprovalDecision.APPROVED:
        # ──  区分 builtin ask 和 user ask ──
        # builtin ask → 不记规则（每次都要问，保护高风险资源）
        # user ask   → 记泛化规则（下次免问）
        if not governor.is_builtin_ask(
            tool_name, target, agent_id, session_id,
        ):
            try:
                from .policy import generalize_rule_match

                # 规则泛化（§8.2）：取首 token + *
                generalized = generalize_rule_match(tool_name, target)
                rule_tool, rule_pattern = generalized.split("(", 1)
                rule_pattern = rule_pattern.rstrip(")")

                # 空 pattern 保护（§8.1）：空 target 的 tool 不写规则
                if rule_pattern:
                    rule = PolicyRule(
                        match=generalized,
                        action=PolicyAction.ALLOW,
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
                        tool_name, target,
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
