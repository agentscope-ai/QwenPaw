"""一次性审批。超时即 deny，不写永久 allow。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from uuid import uuid4

from airport_sms.governance.policy import GovernanceAction


class ApprovalStatus(str, Enum):
    """审批状态。"""

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    TIMED_OUT = "timed_out"


@dataclass
class ApprovalRequest:
    """挂起的审批。"""

    id: str
    tool_name: str
    case_id: str
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    ttl: timedelta = field(default_factory=lambda: timedelta(minutes=15))


@dataclass
class ApprovalService:
    """一次性审批台。"""

    pending: dict[str, ApprovalRequest] = field(default_factory=dict)
    now_factory: Callable[[], datetime] = field(
        default=lambda: datetime.now(timezone.utc)
    )

    def ask(self, *, tool_name: str, case_id: str) -> ApprovalRequest:
        """创建 pending 审批。"""
        req = ApprovalRequest(
            id=str(uuid4()), tool_name=tool_name, case_id=case_id
        )
        self.pending[req.id] = req
        return req

    def decide(
        self, approval_id: str, *, approve: bool
    ) -> tuple[ApprovalRequest, GovernanceAction]:
        """一次性决定。"""
        req = self.pending[approval_id]
        if req.status is not ApprovalStatus.PENDING:
            raise RuntimeError("already decided")
        if approve:
            req.status = ApprovalStatus.APPROVED
            return req, GovernanceAction.ALLOW
        req.status = ApprovalStatus.DENIED
        return req, GovernanceAction.DENY

    def expire(
        self, approval_id: str
    ) -> tuple[ApprovalRequest, GovernanceAction]:
        """超时 deny。"""
        req = self.pending[approval_id]
        now = self.now_factory()
        if now - req.created_at >= req.ttl:
            req.status = ApprovalStatus.TIMED_OUT
            return req, GovernanceAction.DENY
        raise RuntimeError("not expired")


__all__ = ["ApprovalRequest", "ApprovalService", "ApprovalStatus"]
