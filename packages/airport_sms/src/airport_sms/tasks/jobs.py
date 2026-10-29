"""调度作业定义。执行走与聊天相同的命令总线入口。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from airport_sms.domain.roles import Role
from airport_sms.session.principal import Principal


class JobName(str, Enum):
    """内置作业名。"""

    OVERDUE_CORRECTIVE_ACTION = "overdue_corrective_action"
    DAILY_RISK_DIGEST = "daily_risk_digest"
    HEARTBEAT_INBOX = "heartbeat_inbox"


@dataclass(frozen=True)
class JobEvent:
    """作业落地事件，写入案件或收件箱侧。"""

    name: JobName
    case_id: str | None
    source: str
    principal_role: Role
    at: datetime
    detail: str = ""


@dataclass
class Inbox:
    """简易收件箱，供 digest / heartbeat 使用。"""

    items: list[str] = field(default_factory=list)

    def add(self, text: str) -> None:
        """追加一条收件箱消息。"""
        self.items.append(text)


def system_principal(org_id: str, site_id: str) -> Principal:
    """调度作业使用的系统主体。"""
    return Principal(
        user_id="scheduler",
        org_id=org_id,
        role=Role.SYSTEM,
        site_id=site_id,
    )


__all__ = [
    "Inbox",
    "JobEvent",
    "JobName",
    "system_principal",
]
