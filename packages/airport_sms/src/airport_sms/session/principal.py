"""主体与会话记录。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from airport_sms.domain.case import CaseId
from airport_sms.domain.roles import Role


@dataclass(frozen=True)
class Principal:
    """已认证主体。"""

    user_id: str
    org_id: str
    role: Role
    site_id: str


@dataclass(frozen=True)
class Session:
    """多用户会话。对话游标与绑定案件 id 分列，都不是案件状态。"""

    session_id: str
    principal: Principal
    channel: str
    created_at: datetime
    last_seen_at: datetime
    conversation_cursor: str = ""
    bound_case_id: CaseId | None = None
    closed: bool = False


__all__ = ["Principal", "Session"]
