# -*- coding: utf-8 -*-
"""把文件智能体目录补登记到 PostgreSQL 治理元数据。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol
from uuid import UUID

from ..config.config import AgentProfileConfig, load_agent_config
from .agent_repository import LegacyAgentRecord


class LegacyAgentRegistrationRepository(Protocol):
    """旧智能体登记所需的最小 Repository 接口。"""

    async def get_first_admin_id(self) -> UUID | None:
        ...

    async def list_registered_keys(self, agent_keys: list[str]) -> set[str]:
        ...

    async def register_owner(
        self,
        *,
        agent: LegacyAgentRecord,
        owner_user_id: UUID,
    ) -> Any:
        ...


ProfileLoader = Callable[[str], AgentProfileConfig]


async def initialize_admin_agents() -> int:
    """Finish first-run metadata after an admin exists; also safe on login retry."""
    from ..config import load_config
    from ..identity.runtime import get_identity_schema
    from ..migrations.agent_model_mode_migration import (
        synchronize_agent_model_modes,
    )
    from .agent_repository import PostgresAgentRepository

    config = load_config()
    repository = PostgresAgentRepository(schema=get_identity_schema())
    count = await synchronize_legacy_agent_governance(
        config=config, repository=repository
    )
    await synchronize_agent_model_modes(config=config, repository=repository)
    return count


def _legacy_agent_records(
    config: Any,
    profile_loader: ProfileLoader,
) -> list[LegacyAgentRecord]:
    records: list[LegacyAgentRecord] = []
    for agent_id, agent_ref in config.agents.profiles.items():
        try:
            profile = profile_loader(agent_id)
            name = profile.name
            description = profile.description or ""
        except Exception:  # noqa: BLE001 - 保留文件目录的兼容降级
            name = agent_id.title()
            description = ""
        records.append(
            LegacyAgentRecord(
                key=agent_id,
                name=name,
                description=description,
                workspace_key=agent_ref.workspace_dir,
                status=(
                    "active"
                    if getattr(agent_ref, "enabled", True)
                    else "disabled"
                ),
            )
        )
    return records


async def synchronize_legacy_agent_governance(
    *,
    config: Any,
    repository: LegacyAgentRegistrationRepository,
    profile_loader: ProfileLoader = load_agent_config,
) -> int:
    """将尚未登记的文件智能体幂等归属给首位有效管理员。"""
    first_admin_id = await repository.get_first_admin_id()
    if first_admin_id is None:
        return 0

    agents = _legacy_agent_records(config, profile_loader)
    registered = await repository.list_registered_keys(
        [agent.key for agent in agents]
    )
    pending = [agent for agent in agents if agent.key not in registered]
    for agent in pending:
        await repository.register_owner(
            agent=agent,
            owner_user_id=first_admin_id,
        )
    return len(pending)
