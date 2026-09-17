# -*- coding: utf-8 -*-
"""Agent 模型继承模式历史治理迁移测试。"""

from types import SimpleNamespace

import pytest

from qwenpaw.config.config import AgentProfileConfig, ModelSlotConfig
from qwenpaw.migrations.agent_model_mode_migration import (
    synchronize_agent_model_modes,
)


class _Repository:
    def __init__(self) -> None:
        self.modes: dict[str, str] = {}
        self.calls: list[tuple[str, str]] = []

    async def update_model_mode(self, agent_key: str, mode: str) -> bool:
        self.calls.append((agent_key, mode))
        changed = self.modes.get(agent_key) != mode
        self.modes[agent_key] = mode
        return changed


@pytest.mark.asyncio
async def test_model_mode_migration_is_idempotent_and_preserves_config() -> None:
    inherited = AgentProfileConfig(
        id="inherited",
        name="Inherited",
        active_model=None,
    )
    explicit = AgentProfileConfig(
        id="explicit",
        name="Explicit",
        active_model=ModelSlotConfig(provider_id="global", model="gpt-test"),
    )
    snapshots = {
        "inherited": inherited.model_dump(),
        "explicit": explicit.model_dump(),
    }
    profiles = {
        "inherited": SimpleNamespace(id="inherited"),
        "explicit": SimpleNamespace(id="explicit"),
    }
    config = SimpleNamespace(agents=SimpleNamespace(profiles=profiles))
    repository = _Repository()

    def load_agent(agent_id: str) -> AgentProfileConfig:
        return {"inherited": inherited, "explicit": explicit}[agent_id]

    first = await synchronize_agent_model_modes(
        config=config,
        repository=repository,
        load_agent=load_agent,
    )
    second = await synchronize_agent_model_modes(
        config=config,
        repository=repository,
        load_agent=load_agent,
    )

    assert first == 2
    assert second == 0
    assert repository.modes == {
        "inherited": "inherited",
        "explicit": "explicit",
    }
    assert inherited.model_dump() == snapshots["inherited"]
    assert explicit.model_dump() == snapshots["explicit"]


@pytest.mark.asyncio
async def test_model_mode_migration_skips_unreadable_agent() -> None:
    config = SimpleNamespace(
        agents=SimpleNamespace(profiles={"healthy": object(), "broken": object()}),
    )
    repository = _Repository()

    def load_agent(agent_id: str) -> AgentProfileConfig:
        if agent_id == "broken":
            raise ValueError("invalid agent.json")
        return AgentProfileConfig(id=agent_id, name=agent_id, active_model=None)

    changed = await synchronize_agent_model_modes(
        config=config,
        repository=repository,
        load_agent=load_agent,
    )

    assert changed == 1
    assert repository.calls == [("healthy", "inherited")]
