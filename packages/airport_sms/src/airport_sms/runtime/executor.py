"""执行一轮对话或命令快捷方式。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from airport_sms.domain.case import Case, CaseId, CaseState
from airport_sms.domain.roles import Role
from airport_sms.domain.transitions import transition
from airport_sms.governance.governor import Governor
from airport_sms.governance.policy import GovernanceAction
from airport_sms.models.gateway import ModelGateway
from airport_sms.runtime.builder import AgentBundle
from airport_sms.tools.case_tools import ToolResult


def execute_turn(
    request: Any,
    *,
    agent: AgentBundle,
    governor: Governor,
    gateway: ModelGateway,
    case: Case | None,
    draft_fn: Callable[..., ToolResult],
) -> tuple[list[dict[str, Any]], Case | None]:
    """执行命令或聊天。命令与工具共享治理路径。"""
    events: list[dict[str, Any]] = []
    events.append({"type": "delta", "text": ""})

    command = request.command
    text = request.text or ""

    if command == "submit" or text.strip().lower() == "/submit":
        if case is None:
            events.append({"type": "error", "message": "no case"})
            return events, case
        result = governor.invoke(
            "submit_case",
            lambda: transition(
                case, CaseState.SUBMITTED, request.principal.role, "submit"
            ),
            case=case,
        )
        events.append(
            {
                "type": "governance",
                "source": result.decision.source,
                "action": result.decision.action.value,
                "approval_id": result.approval_id,
            }
        )
        if result.decision.action is GovernanceAction.ALLOW and result.value:
            case = result.value
        return events, case

    if "draft" in text.lower() or command == "draft":
        result = governor.invoke(
            "draft_case",
            lambda: draft_fn(
                case_id=CaseId(f"D-{request.session_id}"),
                hazard=text or "hazard",
                location="unknown",
            ),
            case=case,
        )
        events.append(
            {
                "type": "governance",
                "source": result.decision.source,
                "action": result.decision.action.value,
            }
        )
        if result.value and isinstance(result.value, ToolResult):
            case = result.value.case
            events.append(
                {"type": "case", "case_id": str(case.id), "state": case.state.value}
            )
        return events, case

    # 普通聊天：工人模型
    for i in range(request.max_iters):
        chunk = gateway.worker(text or "ping")
        events.append({"type": "delta", "text": chunk})
        if i + 1 >= request.max_iters:
            events.append({"type": "max_iters", "iters": request.max_iters})
            break
        break

    if request.source == "scheduler":
        events.append({"type": "source", "source": "scheduler"})

    return events, case


__all__ = ["execute_turn"]
