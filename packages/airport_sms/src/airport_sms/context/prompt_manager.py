"""系统提示组装。贡献者只写 system section。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace

from airport_sms.context.manual_index import ManualIndex
from airport_sms.domain.case import Case, CaseId
from airport_sms.domain.roles import Role

PROMPT_SEPARATOR = "\n\n"


def count_tokens(text: str) -> int:
    """粗算 token：每 4 个字符计 1。"""
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


@dataclass(frozen=True)
class PromptContext:
    """一次组装所需的结构化输入。"""

    role: Role
    site_id: str
    case: Case | None = None
    clause_ids: tuple[str, ...] = ()
    hints: tuple[str, ...] = ()
    site_rules: str = ""


@dataclass(frozen=True)
class ProposedDecision:
    """拟议决策载荷。条款 id 记在提案上。"""

    case_id: CaseId | None
    summary: str
    cited_clause_ids: tuple[str, ...]


@dataclass(frozen=True)
class AssembledPrompt:
    """组装结果。"""

    system: str
    cited_clause_ids: tuple[str, ...]
    dropped: tuple[str, ...] = ()
    token_count: int = 0

    def digest(self) -> str:
        """稳定哈希，供重复组装对照。"""
        return hashlib.sha256(self.system.encode("utf-8")).hexdigest()


class PromptContributor:
    """一段系统提示。priority 升序靠前，溢出时先丢数字大的。"""

    name: str
    priority: int = 100

    def contribute(self, ctx: PromptContext) -> str | None:
        """返回一段系统文本，或 None 表示本轮跳过。"""
        raise NotImplementedError


class PromptManager:
    """按优先级登记贡献者并组装系统提示。"""

    def __init__(self, *, token_budget: int = 800) -> None:
        self._contributors: list[PromptContributor] = []
        self._token_budget = token_budget

    def register(self, contributor: PromptContributor) -> None:
        """登记贡献者。同名拒绝。"""
        if not getattr(contributor, "name", None):
            raise ValueError("PromptContributor.name must be a non-empty string")
        if any(item.name == contributor.name for item in self._contributors):
            raise ValueError(f"duplicate contributor {contributor.name}")
        self._contributors.append(contributor)
        self._contributors.sort(key=lambda item: (item.priority, item.name))

    def names(self) -> list[str]:
        """按组装顺序返回贡献者名。"""
        return [item.name for item in self._contributors]

    def build(self, ctx: PromptContext) -> AssembledPrompt:
        """组装系统提示。超预算从最低优先级段开始丢弃。"""
        fragments: list[tuple[int, str, str]] = []
        for contributor in self._contributors:
            text = contributor.contribute(ctx)
            if text:
                fragments.append((contributor.priority, contributor.name, text.strip()))
        dropped: list[str] = []
        kept = list(fragments)
        while kept and count_tokens(_join(kept)) > self._token_budget:
            _priority, name, _text = kept.pop()
            dropped.append(name)
        system = _join(kept)
        return AssembledPrompt(
            system=system,
            cited_clause_ids=ctx.clause_ids,
            dropped=tuple(dropped),
            token_count=count_tokens(system),
        )

    def propose(
        self,
        ctx: PromptContext,
        summary: str,
        *,
        case: Case | None = None,
    ) -> tuple[AssembledPrompt, ProposedDecision, Case | None]:
        """组装提示并生成拟议决策。引用条款写入提案；若有案件则同步到副本。"""
        assembled = self.build(ctx)
        target = case if case is not None else ctx.case
        proposal = ProposedDecision(
            case_id=target.id if target is not None else None,
            summary=summary,
            cited_clause_ids=assembled.cited_clause_ids,
        )
        updated: Case | None = None
        if target is not None:
            cited = tuple(
                dict.fromkeys((*target.cited_clauses, *proposal.cited_clause_ids))
            )
            updated = replace(
                target,
                cited_clauses=cited,
                version=target.version + 1,
            )
        return assembled, proposal, updated


def _join(fragments: list[tuple[int, str, str]]) -> str:
    """按已排序片段拼接系统提示。"""
    return PROMPT_SEPARATOR.join(item[2] for item in fragments)


def build_sms_prompt_manager(
    index: ManualIndex,
    *,
    token_budget: int = 800,
) -> PromptManager:
    """登记默认 SMS 贡献者。"""
    from airport_sms.context.contributors import (
        CaseSnapshotContributor,
        HintContributor,
        ManualClauseContributor,
        RoleContributor,
        SiteRulesContributor,
    )

    manager = PromptManager(token_budget=token_budget)
    manager.register(RoleContributor())
    manager.register(SiteRulesContributor())
    manager.register(CaseSnapshotContributor())
    manager.register(ManualClauseContributor(index))
    manager.register(HintContributor())
    return manager


__all__ = [
    "AssembledPrompt",
    "PROMPT_SEPARATOR",
    "PromptContext",
    "PromptContributor",
    "PromptManager",
    "ProposedDecision",
    "build_sms_prompt_manager",
    "count_tokens",
]
