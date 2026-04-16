# -*- coding: utf-8 -*-
"""Meeting module data models - Participant."""

from typing import Optional
from pydantic import BaseModel, Field

from .types import RoleType


class AgentEndpoint(BaseModel):
    """Agent 端点配置."""

    url: str = Field(..., description="Agent 服务地址")
    auth_key: str = Field(..., description="认证密钥")


class MeetingParticipant(BaseModel):
    """会议参与者模型.

    支持多角色，例如：
    - 主持人兼任汇报人: roles=["HOST", "REPORTER"]
    - 决策者: roles=["DECIDER"]
    """

    id: str = Field(..., description="参与者 ID")
    name: str = Field(..., description="参与者名称")
    roles: list[RoleType] = Field(
        default_factory=lambda: [RoleType.HOST],
        description="角色类型列表，支持多角色组合",
    )
    intent: Optional[str] = Field(None, description="职责描述")
    endpoint: Optional[AgentEndpoint] = Field(None, description="Agent 端点配置")

    def has_role(self, role: RoleType) -> bool:
        """检查是否具有指定角色."""
        return role in self.roles

    def is_host(self) -> bool:
        """是否为主持人."""
        return self.has_role(RoleType.HOST)

    def is_reporter(self) -> bool:
        """是否为汇报人(包括身兼多职的情况)."""
        return self.has_role(RoleType.REPORTER)

    def is_decider(self) -> bool:
        """是否为决策人."""
        return self.has_role(RoleType.DECIDER)

    def can_speak(self) -> bool:
        """是否可以发言（汇报人、主持人或决策人）."""
        return (
            self.has_role(RoleType.REPORTER)
            or self.has_role(RoleType.HOST)
            or self.has_role(RoleType.DECIDER)
        )
