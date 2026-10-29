"""每请求重建 agent；连续性在 session + case store。"""

from __future__ import annotations

from dataclasses import dataclass

from airport_sms.governance.governor import Governor
from airport_sms.models.gateway import ModelGateway


@dataclass
class AgentBundle:
    """轻量 agent 句柄。"""

    gateway: ModelGateway
    governor: Governor


def build_agent(gateway: ModelGateway, governor: Governor) -> AgentBundle:
    """构建受治理包装的 agent。"""
    return AgentBundle(gateway=gateway, governor=governor)


__all__ = ["AgentBundle", "build_agent"]
