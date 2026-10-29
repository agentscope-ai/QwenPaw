"""系统提示贡献者。每段只产出 system section。"""

from __future__ import annotations

from airport_sms.context.manual_index import ManualIndex
from airport_sms.context.prompt_manager import PromptContext, PromptContributor
from airport_sms.domain.roles import Role

_ROLE_DUTIES: dict[Role, str] = {
    Role.REPORTER: "职责：报告隐患并补充证据。禁止关闭案件。",
    Role.DEPT_OWNER: "职责：评估风险、落实整改，必要时升级。",
    Role.SAFETY_OFFICE: "职责：校验整改并关闭案件。拥有关闭案件权限。",
    Role.SYSTEM: "职责：调度超期与摘要任务，不代替人工关闭。",
}


class RoleContributor(PromptContributor):
    """角色职责。"""

    name = "role"
    priority = 10

    def contribute(self, ctx: PromptContext) -> str | None:
        """输出角色职责系统段。"""
        return f"## role\n{_ROLE_DUTIES[ctx.role]}"


class SiteRulesContributor(PromptContributor):
    """场站规则。"""

    name = "site_rules"
    priority = 20

    def contribute(self, ctx: PromptContext) -> str | None:
        """输出场站规则系统段。"""
        extra = f"\n{ctx.site_rules}" if ctx.site_rules else ""
        return f"## site_rules\nsite_id={ctx.site_id}{extra}"


class CaseSnapshotContributor(PromptContributor):
    """当前案件快照。"""

    name = "case_snapshot"
    priority = 30

    def contribute(self, ctx: PromptContext) -> str | None:
        """输出案件 id 与状态。"""
        if ctx.case is None:
            return None
        case = ctx.case
        return (
            f"## case_snapshot\n"
            f"case_id={case.id}\n"
            f"state={case.state.value}\n"
            f"hazard={case.hazard}\n"
            f"location={case.location}\n"
            f"risk={case.risk_level.value}"
        )


class ManualClauseContributor(PromptContributor):
    """引用手册条款。"""

    name = "manual_clauses"
    priority = 40

    def __init__(self, index: ManualIndex) -> None:
        self._index = index

    def contribute(self, ctx: PromptContext) -> str | None:
        """输出已引用条款正文。"""
        if not ctx.clause_ids:
            return None
        lines = ["## manual_clauses"]
        for cid in ctx.clause_ids:
            body = self._index.get(cid) or ""
            lines.append(f"{cid}: {body}")
        return "\n".join(lines)


class HintContributor(PromptContributor):
    """动态提示。只进系统段，禁止伪装成用户发言。"""

    name = "hint"
    priority = 90

    def contribute(self, ctx: PromptContext) -> str | None:
        """把 hints 写成 labeled system section。"""
        if not ctx.hints:
            return None
        blocks = ["## system_hint"]
        for hint in ctx.hints:
            blocks.append(hint)
        return "\n".join(blocks)


__all__ = [
    "CaseSnapshotContributor",
    "HintContributor",
    "ManualClauseContributor",
    "RoleContributor",
    "SiteRulesContributor",
]
