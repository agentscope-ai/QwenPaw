# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: 2024 2019-2024 The MCP OpenCode Agents Authors
# SPDX-License-Identifier: MIT

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class SACPAgentConfig(BaseModel):
    """SACP Agent Configuration — stored in ~/.qwenpaw/sacp_agents.json."""

    id: str = Field(..., description="唯一标识符 (UUID)")
    name: str = Field(..., description="Agent 显示名称")
    description: str = Field("", description="Agent 功能描述")
    url: Optional[str] = Field(
        None,
        description="Agent SACP 服务地址 (http/https)，内部 Agent 可为空",
    )
    auth_key: Optional[str] = Field(None, description="认证密钥，内部 Agent 可为空")

    is_internal: bool = Field(False, description="是否为内部 Agent")
    internal_agent_id: Optional[str] = Field(
        None,
        description="内部 Agent ID (当 is_internal=True 时)",
    )

    # Health check fields
    health_status: HealthStatus = Field(
        default=HealthStatus.UNKNOWN,
        description="健康状态",
    )
    last_health_check: Optional[datetime] = Field(None, description="上次健康检查时间")
    last_health_error: Optional[str] = Field(None, description="上次健康检查错误信息")
    consecutive_failures: int = Field(default=0, description="连续失败次数")
    health_check_enabled: bool = Field(default=True, description="是否启用健康检查")
    health_check_interval: int = Field(default=300, description="健康检查间隔 (秒)")

    # Timestamps
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="创建时间",
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="更新时间",
    )

    def mark_healthy(self) -> None:
        """Mark agent as healthy after a successful health check."""
        self.health_status = HealthStatus.HEALTHY
        self.last_health_check = datetime.utcnow()
        self.last_health_error = None
        self.consecutive_failures = 0
        self.updated_at = datetime.utcnow()

    def mark_unhealthy(self, error: str) -> None:
        """Mark agent as unhealthy after a failed health check."""
        self.health_status = HealthStatus.UNHEALTHY
        self.last_health_check = datetime.utcnow()
        self.last_health_error = error
        self.consecutive_failures += 1
        self.updated_at = datetime.utcnow()


class CreateSACPAgentRequest(BaseModel):
    """Request body for POST /sacp-agents."""

    name: str = Field(
        ...,
        description="Agent 显示名称",
        min_length=1,
        max_length=100,
    )
    description: str = Field("", description="Agent 功能描述", max_length=500)
    url: Optional[str] = Field(
        None,
        description="Agent SACP 服务地址，内部 Agent 可为空",
    )
    auth_key: Optional[str] = Field(None, description="认证密钥，内部 Agent 可为空")

    is_internal: bool = Field(False, description="是否为内部 Agent")
    internal_agent_id: Optional[str] = Field(
        None,
        description="内部 Agent ID (当 is_internal=True 时)",
    )
    health_check_enabled: bool = Field(default=True, description="是否启用健康检查")
    health_check_interval: int = Field(
        default=300,
        description="健康检查间隔 (秒)",
        ge=60,
        le=3600,
    )


class UpdateSACPAgentRequest(BaseModel):
    """Request body for PUT /sacp-agents/{id}."""

    name: Optional[str] = Field(
        None,
        description="Agent 显示名称",
        min_length=1,
        max_length=100,
    )
    description: Optional[str] = Field(
        None,
        description="Agent 功能描述",
        max_length=500,
    )
    url: Optional[str] = Field(None, description="Agent SACP 服务地址")
    auth_key: Optional[str] = Field(None, description="认证密钥")

    is_internal: Optional[bool] = Field(None, description="是否为内部 Agent")
    internal_agent_id: Optional[str] = Field(
        None,
        description="内部 Agent ID (当 is_internal=True 时)",
    )
    health_check_enabled: Optional[bool] = Field(None, description="是否启用健康检查")
    health_check_interval: Optional[int] = Field(
        None,
        description="健康检查间隔 (秒)",
        ge=60,
        le=3600,
    )


class SACPAgentHealthCheckResult(BaseModel):
    """Result of a health check operation."""

    agent_id: str = Field(..., description="Agent ID")
    status: HealthStatus = Field(..., description="健康状态")
    checked_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="检查时间",
    )
    error: Optional[str] = Field(None, description="错误信息 (如有)")


class SACPAgentsStorage(BaseModel):
    """Root structure of ~/.qwenpaw/sacp_agents.json."""

    version: str = Field(default="1.0", description="存储格式版本")
    global_internal_auth_key: Optional[str] = Field(
        None,
        description="全局内部认证密钥",
    )
    agents: list[SACPAgentConfig] = Field(
        default_factory=list,
        description="Agent 列表",
    )
