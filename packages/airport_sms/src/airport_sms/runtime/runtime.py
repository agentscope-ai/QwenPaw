"""AgentScope 运行时入口：单一 Runtime.run。"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from airport_sms.domain.case import Case, CaseId, new_draft
from airport_sms.domain.roles import Role
from airport_sms.governance.governor import Governor
from airport_sms.governance.policy import GovernancePolicy
from airport_sms.models.gateway import ModelGateway
from airport_sms.models.providers import ProviderIds
from airport_sms.runtime.builder import build_agent
from airport_sms.runtime.executor import execute_turn
from airport_sms.runtime.hooks import HookError, Hooks
from airport_sms.session.case_repo import CaseRepo
from airport_sms.session.principal import Principal
from airport_sms.session.store import SessionStore, open_db, open_session
from airport_sms.tools.case_tools import draft_case


@dataclass(frozen=True)
class AgentRequest:
    """一次请求信封。"""

    session_id: str
    principal: Principal
    text: str = ""
    command: str | None = None
    source: str = "console"
    max_iters: int = 8


@dataclass
class Runtime:
    """归一化 → 分发 → 会话 → 构建 → 执行 → 保存 → 收尾。"""

    store: SessionStore
    cases: CaseRepo
    governor: Governor = field(default_factory=lambda: Governor(GovernancePolicy()))
    gateway: ModelGateway = field(
        default_factory=lambda: ModelGateway(ProviderIds())
    )
    hooks: Hooks = field(default_factory=Hooks)
    closed: int = 0

    @classmethod
    def in_memory(cls) -> Runtime:
        """测试用内存运行时。"""
        conn = open_db(":memory:")
        return cls(store=SessionStore(conn), cases=CaseRepo(conn))

    def run(self, request: AgentRequest) -> Iterator[dict[str, Any]]:
        """唯一对外入口。产出流式事件。"""
        try:
            self.hooks.pre_dispatch(request)
        except HookError as exc:
            yield {"type": "error", "message": str(exc)}
            return

        session = self.store.get(request.session_id)
        if session is None:
            session = self.store.create(
                open_session(
                    request.session_id, request.principal, request.source
                )
            )

        agent = build_agent(self.gateway, self.governor)
        case: Case | None = None
        if session.bound_case_id:
            try:
                case = self.cases.get(request.principal, session.bound_case_id)
            except Exception:
                case = None

        events, case = execute_turn(
            request,
            agent=agent,
            governor=self.governor,
            gateway=self.gateway,
            case=case,
            draft_fn=draft_case,
        )
        for event in events:
            yield event
            if event.get("type") == "max_iters":
                break

        if case is not None and session.bound_case_id is None:
            self.cases.save_new(request.principal, case)
            self.store.bind_case(request.session_id, case.id)
        elif case is not None and session.bound_case_id:
            try:
                existing = self.cases.get(request.principal, case.id)
                self.cases.write(
                    request.principal, case, expected_version=existing.version
                )
            except Exception:
                self.cases.save_new(request.principal, case)

        if request.text:
            self.store.add_message(request.session_id, "user", request.text)

        self.hooks.finalize(request)
        self.closed += 1
        yield {"type": "done", "case_id": str(case.id) if case else None}


__all__ = ["AgentRequest", "Runtime"]
