# -*- coding: utf-8 -*-
"""Tests for persisted agent ordering."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from qwenpaw.config.config import (
    AgentProfileConfig,
    AgentProfileRef,
    Config,
)
from qwenpaw.config.utils import load_config, save_config
from qwenpaw.app.routers import agents as agents_router


def _build_config(
    profile_ids: list[str],
    agent_order: list[str] | None = None,
    pinned_ids: set[str] | None = None,
) -> Config:
    """Build a minimal config with agent profiles in the given order."""
    config = Config()
    config.agents.profiles = {
        agent_id: AgentProfileRef(
            id=agent_id,
            workspace_dir=f"/tmp/{agent_id}",
            pinned=agent_id in (pinned_ids or set()),
        )
        for agent_id in profile_ids
    }
    config.agents.agent_order = agent_order or []
    return config


def _agent_config(agent_id: str) -> AgentProfileConfig:
    return AgentProfileConfig(
        id=agent_id,
        name=agent_id.upper(),
        description=f"{agent_id} description",
        workspace_dir=f"/tmp/{agent_id}",
    )


def test_agent_profile_flags_survive_config_round_trip(tmp_path):
    """Adding pinned state must preserve an explicit disabled state."""
    config = _build_config(["default", "disabled"], pinned_ids={"disabled"})
    config.agents.profiles["disabled"].enabled = False
    config_path = tmp_path / "config.json"

    save_config(config, config_path)
    loaded = load_config(config_path)

    assert loaded.agents.profiles["disabled"].enabled is False
    assert loaded.agents.profiles["disabled"].pinned is True


@pytest.mark.asyncio
async def test_list_agents_uses_persisted_order(monkeypatch):
    """List response should follow stored agent order."""
    config = _build_config(
        ["beta", "default", "alpha"],
        agent_order=["default", "alpha", "beta"],
    )

    monkeypatch.setattr(agents_router, "load_config", lambda: config)
    monkeypatch.setattr(
        agents_router,
        "load_agent_config",
        _agent_config,
    )

    response = await agents_router.list_agents()

    assert [agent.id for agent in response.agents] == [
        "default",
        "alpha",
        "beta",
    ]


@pytest.mark.asyncio
async def test_list_agents_appends_missing_ids(monkeypatch):
    """Old configs without complete order should still return all agents."""
    config = _build_config(
        ["beta", "default", "alpha"],
        agent_order=["default"],
    )

    monkeypatch.setattr(agents_router, "load_config", lambda: config)
    monkeypatch.setattr(
        agents_router,
        "load_agent_config",
        _agent_config,
    )

    response = await agents_router.list_agents()

    assert [agent.id for agent in response.agents] == [
        "default",
        "beta",
        "alpha",
    ]


@pytest.mark.asyncio
async def test_list_agents_groups_default_and_pinned_without_reordering_peers(
    monkeypatch,
):
    """Pinned agents should lead while preserving stored peer order."""
    config = _build_config(
        ["beta", "default", "alpha", "gamma"],
        agent_order=["gamma", "alpha", "default", "beta"],
        pinned_ids={"gamma", "beta"},
    )

    monkeypatch.setattr(agents_router, "load_config", lambda: config)
    monkeypatch.setattr(
        agents_router,
        "load_agent_config",
        _agent_config,
    )

    response = await agents_router.list_agents()

    assert [agent.id for agent in response.agents] == [
        "default",
        "gamma",
        "beta",
        "alpha",
    ]
    assert [agent.pinned for agent in response.agents] == [
        True,
        True,
        True,
        False,
    ]


@pytest.mark.asyncio
async def test_pin_agent_persists_without_changing_enabled(monkeypatch):
    """Pinning must not alter an agent's enabled state."""
    config = _build_config(["default", "disabled"])
    config.agents.profiles["disabled"].enabled = False
    saved_configs: list[Config] = []

    monkeypatch.setattr(agents_router, "load_config", lambda: config)
    monkeypatch.setattr(
        agents_router,
        "save_config",
        saved_configs.append,
    )

    response = await agents_router.set_agent_pinned("disabled", True)

    assert response["pinned"] is True
    assert config.agents.profiles["disabled"].pinned is True
    assert config.agents.profiles["disabled"].enabled is False
    assert saved_configs == [config]


@pytest.mark.asyncio
async def test_default_agent_cannot_be_unpinned(monkeypatch):
    """The default agent is always pinned regardless of stored defaults."""
    config = _build_config(["default"])
    monkeypatch.setattr(agents_router, "load_config", lambda: config)

    with pytest.raises(HTTPException) as exc_info:
        await agents_router.set_agent_pinned("default", False)

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_reorder_agents_rejects_incomplete_payload(monkeypatch):
    """Reorder should reject lists that omit configured agents."""
    config = _build_config(
        ["default", "alpha", "beta"],
        agent_order=["default", "alpha", "beta"],
    )

    monkeypatch.setattr(agents_router, "load_config", lambda: config)

    with pytest.raises(HTTPException) as exc_info:
        await agents_router.reorder_agents(
            agents_router.ReorderAgentsRequest(agent_ids=["alpha", "default"]),
        )

    assert exc_info.value.status_code == 400
    assert "exactly once" in exc_info.value.detail


@pytest.mark.asyncio
async def test_reorder_agents_persists_valid_order(monkeypatch):
    """Reorder API should save the new ordered IDs."""
    config = _build_config(
        ["default", "alpha", "beta"],
        agent_order=["default", "alpha", "beta"],
    )
    saved_orders: list[list[str]] = []

    monkeypatch.setattr(agents_router, "load_config", lambda: config)
    monkeypatch.setattr(
        agents_router,
        "save_config",
        lambda updated_config: saved_orders.append(
            list(updated_config.agents.agent_order),
        ),
    )

    response = await agents_router.reorder_agents(
        agents_router.ReorderAgentsRequest(
            agent_ids=["default", "beta", "alpha"],
        ),
    )

    assert response["success"] is True
    assert config.agents.agent_order == ["default", "beta", "alpha"]
    assert saved_orders == [["default", "beta", "alpha"]]


@pytest.mark.asyncio
async def test_reorder_agents_rejects_non_display_order(monkeypatch):
    """A successful PUT must be returned unchanged by the next GET."""
    config = _build_config(
        ["default", "pinned", "regular"],
        agent_order=["default", "pinned", "regular"],
        pinned_ids={"pinned"},
    )
    monkeypatch.setattr(agents_router, "load_config", lambda: config)

    with pytest.raises(HTTPException) as exc_info:
        await agents_router.reorder_agents(
            agents_router.ReorderAgentsRequest(
                agent_ids=["default", "regular", "pinned"],
            ),
        )

    assert exc_info.value.status_code == 400
    assert "pinned agents" in exc_info.value.detail


@pytest.mark.asyncio
async def test_create_agent_appends_new_id_to_order(monkeypatch, tmp_path):
    """New agents should be appended to the saved order."""
    config = _build_config(
        ["default", "alpha"],
        agent_order=["alpha", "default"],
    )

    monkeypatch.setattr(agents_router, "load_config", lambda: config)
    monkeypatch.setattr(agents_router, "save_config", lambda updated: None)
    monkeypatch.setattr(
        agents_router,
        "save_agent_config",
        lambda agent_id, agent_config: None,
    )
    monkeypatch.setattr(
        agents_router,
        "_initialize_agent_workspace",
        lambda workspace_dir, skill_names=None, md_template_id=None, language=None: None,  # noqa: E501  # pylint: disable=line-too-long
    )
    monkeypatch.setattr(
        agents_router,
        "generate_short_agent_id",
        lambda: "beta",
    )
    manager = SimpleNamespace(schedule_agent_startup=lambda agent_id: None)
    scheduled_ids: list[str] = []
    manager.schedule_agent_startup = scheduled_ids.append
    http_request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(multi_agent_manager=manager),
        ),
    )

    await agents_router.create_agent(
        agents_router.CreateAgentRequest(
            name="Beta",
            workspace_dir=str(tmp_path / "beta"),
        ),
        http_request=http_request,
    )

    assert config.agents.agent_order == ["alpha", "default", "beta"]
    assert scheduled_ids == ["beta"]


@pytest.mark.asyncio
async def test_delete_agent_removes_id_from_order(monkeypatch):
    """Deleting an agent should also remove it from the stored order."""
    config = _build_config(
        ["default", "alpha", "beta"],
        agent_order=["alpha", "default", "beta"],
    )

    class DummyManager:
        def is_agent_startup_in_progress(self, _agent_id: str) -> bool:
            return False

        async def stop_agent(self, agent_id: str) -> None:
            assert agent_id == "beta"

    monkeypatch.setattr(agents_router, "load_config", lambda: config)
    monkeypatch.setattr(agents_router, "save_config", lambda updated: None)
    monkeypatch.setattr(
        agents_router,
        "_get_multi_agent_manager",
        lambda request: DummyManager(),
    )

    await agents_router.delete_agent(
        "beta",
        request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())),
    )

    assert config.agents.agent_order == ["alpha", "default"]
