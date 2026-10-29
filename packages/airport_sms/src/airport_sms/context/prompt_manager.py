"""组装系统提示：按优先级拼接，超预算从低优先级丢弃。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from airport_sms.context.contributors import (
    case_section,
    hint_section,
    manual_section,
    role_section,
    site_section,
)
from airport_sms.context.manual_index import ManualIndex, ManualMissingError
from airport_sms.domain.case import Case
from airport_sms.domain.roles import Role


@dataclass(frozen=True)
class PromptBundle:
    """系统提示、引用条款与稳定哈希。"""

    system: str
    cited_clauses: tuple[str, ...]
    digest: str


@dataclass(frozen=True)
class ProposedDecision:
    """拟议决策载荷：条款引用写回案件提案侧。"""

    case_id: str
    action: str
    cited_clauses: tuple[str, ...]


class PromptManager:
    """按固定顺序拼接系统段。hint 只能进系统段。"""

    # 高优先级在前；超预算从尾部丢弃。
    _ORDER = ("role", "site", "case", "manual", "hint")

    def __init__(
        self,
        manuals: dict[str, str],
        *,
        budget_chars: int = 4000,
        site_id: str = "",
    ) -> None:
        self._manuals = manuals
        self._budget = budget_chars
        self._site_id = site_id

    @classmethod
    def from_index(
        cls,
        index: ManualIndex,
        *,
        budget_chars: int = 4000,
        site_id: str = "",
        require_clauses: list[str] | None = None,
    ) -> PromptManager:
        """从手册索引构造。可选强制条款存在。"""
        if require_clauses:
            manuals = index.require(require_clauses)
        else:
            manuals = index.load()
        return cls(manuals, budget_chars=budget_chars, site_id=site_id)

    def build(
        self,
        *,
        role: Role,
        case: Case | None,
        clause_ids: list[str] | None = None,
        hint: str | None = None,
        site_id: str | None = None,
    ) -> PromptBundle:
        """构建系统提示。返回的 cited_clauses 供写回提案。"""
        clause_ids = list(clause_ids or [])
        for cid in clause_ids:
            if cid not in self._manuals:
                raise ManualMissingError(cid)
        site = site_id if site_id is not None else self._site_id
        sections: list[tuple[str, str]] = [
            ("role", role_section(role)),
            ("site", site_section(site)),
            ("case", case_section(case)),
            ("manual", manual_section(clause_ids, self._manuals)),
        ]
        if hint:
            sections.append(("hint", hint_section(hint)))
        assert [n for n, _ in sections] == [
            n for n in self._ORDER if n != "hint" or hint
        ]
        kept: list[str] = []
        for _name, text in sections:
            trial = "\n\n".join(kept + [text])
            if len(trial) > self._budget and kept:
                break
            kept.append(text)
        system = "\n\n".join(kept)
        digest = hashlib.sha256(system.encode("utf-8")).hexdigest()
        return PromptBundle(
            system=system,
            cited_clauses=tuple(clause_ids),
            digest=digest,
        )

    def propose(
        self,
        *,
        role: Role,
        case: Case,
        action: str,
        clause_ids: list[str],
        hint: str | None = None,
    ) -> tuple[PromptBundle, ProposedDecision]:
        """构建提示并产出带条款引用的拟议决策。"""
        bundle = self.build(
            role=role, case=case, clause_ids=clause_ids, hint=hint
        )
        decision = ProposedDecision(
            case_id=str(case.id),
            action=action,
            cited_clauses=bundle.cited_clauses,
        )
        return bundle, decision


__all__ = ["PromptBundle", "PromptManager", "ProposedDecision"]
