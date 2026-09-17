# -*- coding: utf-8 -*-
"""将文件中的 Agent 模型模式同步到数据库治理摘要。"""

import logging
from collections.abc import Callable
from typing import Any, Literal, Protocol

from ..config.config import AgentProfileConfig, load_agent_config

logger = logging.getLogger(__name__)

ModelMode = Literal["inherited", "explicit"]


class AgentModelModeRepository(Protocol):
    """模型模式迁移所需的最小仓储接口。"""

    async def update_model_mode(
        self,
        agent_key: str,
        mode: ModelMode,
    ) -> bool: ...


def model_mode_from_config(agent_config: AgentProfileConfig) -> ModelMode:
    """根据文件配置事实计算治理摘要。"""
    return "inherited" if agent_config.active_model is None else "explicit"


async def synchronize_agent_model_modes(
    *,
    config: Any,
    repository: AgentModelModeRepository,
    load_agent: Callable[[str], AgentProfileConfig] = load_agent_config,
) -> int:
    """幂等同步所有可读取 Agent 的模型模式，并返回实际变更数。"""
    changed = 0
    for agent_id in config.agents.profiles:
        try:
            agent_config = load_agent(agent_id)
        except Exception:  # noqa: BLE001 - 单个旧配置损坏不应阻断启动
            logger.warning(
                "Skipping model-mode migration for unreadable agent %s",
                agent_id,
                exc_info=True,
            )
            continue
        if await repository.update_model_mode(
            agent_id,
            model_mode_from_config(agent_config),
        ):
            changed += 1
    return changed
