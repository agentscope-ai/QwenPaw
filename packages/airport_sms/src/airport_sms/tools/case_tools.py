"""案件类工具处理器桩。真正落库在 runtime 接线后完成。"""

from __future__ import annotations

from dataclasses import dataclass

from airport_sms.domain.case import Case, CaseId, CaseState, new_draft
from airport_sms.domain.roles import Role
from airport_sms.domain.transitions import transition
from airport_sms.tools.registry import UnknownToolError


@dataclass(frozen=True)
class ToolResult:
    """工具调用结果。"""

    ok: bool
    case: Case | None
    message: str


def draft_case(
    *,
    case_id: CaseId,
    hazard: str,
    location: str,
    severity: int = 1,
    likelihood: int = 1,
) -> ToolResult:
    """起草草稿案件。"""
    case = new_draft(
        case_id=case_id,
        hazard=hazard,
        location=location,
        severity=severity,
        likelihood=likelihood,
    )
    return ToolResult(ok=True, case=case, message="drafted")


def submit_case(case: Case, actor: Role, reason: str) -> ToolResult:
    """提交案件。"""
    updated = transition(case, CaseState.SUBMITTED, actor, reason)
    return ToolResult(ok=True, case=updated, message="submitted")


def invoke_case_tool(name: str, **kwargs: object) -> ToolResult:
    """按名分发案件工具；未知名抛错。"""
    if name == "draft_case":
        return draft_case(
            case_id=CaseId(str(kwargs["case_id"])),
            hazard=str(kwargs["hazard"]),
            location=str(kwargs["location"]),
            severity=int(kwargs.get("severity", 1)),
            likelihood=int(kwargs.get("likelihood", 1)),
        )
    if name == "submit_case":
        return submit_case(
            kwargs["case"],  # type: ignore[arg-type]
            kwargs["actor"],  # type: ignore[arg-type]
            str(kwargs.get("reason", "submit")),
        )
    raise UnknownToolError(name)


__all__ = ["ToolResult", "draft_case", "invoke_case_tool", "submit_case"]
