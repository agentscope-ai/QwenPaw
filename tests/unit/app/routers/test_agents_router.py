# -*- coding: utf-8 -*-
"""Unit tests for ``qwenpaw.app.routers.agents``.

Covers the highest-value flows:

- ``GET /agents`` — list all agents
- ``GET /agents/{id}`` — fetch single agent, 404 on missing
- ``PUT /agents/order`` — reject duplicate or mismatched IDs (400)
- ``DELETE /agents/{id}`` — refuse to delete ``default`` (400)
- ``DELETE /agents/{id}`` — happy path with manager.stop_agent
- ``POST /agents/{id}/copy`` — selective config copy without assets
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.exceptions import AppBaseException
from qwenpaw.app.agent_startup import AgentStartupStatus
from qwenpaw.app.routers.agents import (
    CopyAgentRequest,
    copy_agent,
    router as agents_router,
)
from qwenpaw.config.config import (
    AgentProfileConfig,
    AgentProfileRef,
    ChannelConfig,
    DingTalkConfig,
    HeartbeatConfig,
    MCPConfig,
    ModelSlotConfig,
    ToolsConfig,
    BuiltinToolConfig,
)


def _ref(agent_id: str, *, enabled: bool = True) -> AgentProfileRef:
    return AgentProfileRef(
        id=agent_id,
        workspace_dir=f"/tmp/ws/{agent_id}",
        enabled=enabled,
    )


@pytest.fixture
def manager_mock():
    mgr = MagicMock(name="MultiAgentManager")
    mgr.stop_agent = AsyncMock(return_value=None)
    mgr.schedule_agent_startup = MagicMock()
    mgr.get_agent_startup_status.side_effect = lambda _agent_id, *, enabled: (
        AgentStartupStatus.RUNNING if enabled else AgentStartupStatus.DISABLED
    )
    mgr.is_agent_startup_in_progress.return_value = False
    return mgr


@pytest.fixture
def app(manager_mock) -> FastAPI:
    application = FastAPI()
    application.state.multi_agent_manager = manager_mock
    application.include_router(agents_router, prefix="/api")
    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture
def fake_config():
    """A minimal load_config() return: two profiles, ``default`` + ``bot``."""
    config = MagicMock(name="AppConfig")
    config.agents = MagicMock()
    config.agents.profiles = {
        "default": _ref("default"),
        "bot": _ref("bot"),
    }
    config.agents.agent_order = ["default", "bot"]
    return config


# ---------------------------------------------------------------------------
# GET /agents
# ---------------------------------------------------------------------------


def test_list_agents_returns_all_profiles(client, fake_config):
    agent_cfg_default = AgentProfileConfig(
        id="default",
        name="Default",
        description="primary",
        workspace_dir="/tmp/ws/default",
    )
    agent_cfg_bot = AgentProfileConfig(
        id="bot",
        name="Bot",
        description="",
        workspace_dir="/tmp/ws/bot",
    )

    def fake_load(agent_id):
        return {
            "default": agent_cfg_default,
            "bot": agent_cfg_bot,
        }[agent_id]

    with (
        patch(
            "qwenpaw.app.routers.agents.load_config",
            return_value=fake_config,
        ),
        patch(
            "qwenpaw.app.routers.agents.load_agent_config",
            side_effect=fake_load,
        ),
    ):
        response = client.get("/api/agents")

    assert response.status_code == 200
    body = response.json()
    assert {a["id"] for a in body["agents"]} == {"default", "bot"}
    assert {a["startup_status"] for a in body["agents"]} == {"running"}


def test_list_agents_falls_back_to_id_when_load_fails(client, fake_config):
    # When ``load_agent_config`` raises, the handler must still surface
    # the agent with a derived name rather than 500-ing the whole list.
    with (
        patch(
            "qwenpaw.app.routers.agents.load_config",
            return_value=fake_config,
        ),
        patch(
            "qwenpaw.app.routers.agents.load_agent_config",
            side_effect=RuntimeError("config broken"),
        ),
    ):
        response = client.get("/api/agents")

    assert response.status_code == 200
    names = {a["name"] for a in response.json()["agents"]}
    # Defaults: title-cased agent IDs.
    assert names == {"Default", "Bot"}


# ---------------------------------------------------------------------------
# GET /agents/{id}
# ---------------------------------------------------------------------------


def test_get_agent_returns_config(client):
    cfg = AgentProfileConfig(
        id="bot",
        name="Bot",
        description="",
        workspace_dir="/tmp/ws/bot",
    )

    with patch(
        "qwenpaw.app.routers.agents.load_agent_config",
        return_value=cfg,
    ):
        response = client.get("/api/agents/bot")

    assert response.status_code == 200
    assert response.json()["id"] == "bot"


def test_get_agent_returns_404_for_missing(client):
    with patch(
        "qwenpaw.app.routers.agents.load_agent_config",
        side_effect=ValueError("no such agent"),
    ):
        response = client.get("/api/agents/ghost")

    assert response.status_code == 404


def test_get_agent_returns_404_for_app_base_exception(client):
    with patch(
        "qwenpaw.app.routers.agents.load_agent_config",
        side_effect=AppBaseException(
            status=404,
            code="agent_not_found",
            message="nope",
        ),
    ):
        response = client.get("/api/agents/ghost")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /agents/{id}/memory/reindex
# ---------------------------------------------------------------------------


def test_rebuild_memory_index_runs_reme_job(
    client,
    fake_config,
    manager_mock,
):
    agent_config = AgentProfileConfig(id="bot", name="Bot")
    reindex_response = MagicMock(success=True, answer="done")
    memory_manager = MagicMock()
    memory_manager.rebuild_index = AsyncMock(return_value=reindex_response)
    manager_mock.get_agent = AsyncMock(
        return_value=MagicMock(memory_manager=memory_manager),
    )

    with (
        patch(
            "qwenpaw.app.routers.agents.load_config",
            return_value=fake_config,
        ),
        patch(
            "qwenpaw.app.routers.agents.load_agent_config",
            return_value=agent_config,
        ),
    ):
        response = client.post("/api/agents/bot/memory/reindex")

    assert response.status_code == 200
    assert response.json() == {"status": "completed"}
    memory_manager.rebuild_index.assert_awaited_once_with()


def test_rebuild_memory_index_rejects_concurrent_run(
    client,
    fake_config,
    manager_mock,
):
    agent_config = AgentProfileConfig(id="bot", name="Bot")
    memory_manager = MagicMock()
    memory_manager.rebuild_index = AsyncMock(
        side_effect=RuntimeError("Memory index rebuild is already running"),
    )
    manager_mock.get_agent = AsyncMock(
        return_value=MagicMock(memory_manager=memory_manager),
    )

    with (
        patch(
            "qwenpaw.app.routers.agents.load_config",
            return_value=fake_config,
        ),
        patch(
            "qwenpaw.app.routers.agents.load_agent_config",
            return_value=agent_config,
        ),
    ):
        response = client.post("/api/agents/bot/memory/reindex")

    assert response.status_code == 409


# ---------------------------------------------------------------------------
# PUT /agents/order
# ---------------------------------------------------------------------------


def test_reorder_agents_rejects_duplicate_ids(client, fake_config):
    with patch(
        "qwenpaw.app.routers.agents.load_config",
        return_value=fake_config,
    ):
        response = client.put(
            "/api/agents/order",
            json={"agent_ids": ["default", "default"]},
        )

    assert response.status_code == 400
    assert "exactly once" in response.json()["detail"]


def test_reorder_agents_rejects_mismatched_ids(client, fake_config):
    with patch(
        "qwenpaw.app.routers.agents.load_config",
        return_value=fake_config,
    ):
        response = client.put(
            "/api/agents/order",
            json={"agent_ids": ["default", "ghost"]},
        )

    assert response.status_code == 400


def test_reorder_agents_happy_path_saves(client, fake_config):
    with (
        patch(
            "qwenpaw.app.routers.agents.load_config",
            return_value=fake_config,
        ),
        patch("qwenpaw.app.routers.agents.save_config") as save_mock,
    ):
        response = client.put(
            "/api/agents/order",
            json={"agent_ids": ["default", "bot"]},
        )

    assert response.status_code == 200
    assert response.json()["success"] is True
    save_mock.assert_called_once()


# ---------------------------------------------------------------------------
# DELETE /agents/{id}
# ---------------------------------------------------------------------------


def test_delete_agent_refuses_default(client, fake_config):
    with patch(
        "qwenpaw.app.routers.agents.load_config",
        return_value=fake_config,
    ):
        response = client.delete("/api/agents/default")

    assert response.status_code == 400
    assert "Cannot delete the default agent" in response.json()["detail"]


def test_delete_agent_404_when_missing(client, fake_config):
    with patch(
        "qwenpaw.app.routers.agents.load_config",
        return_value=fake_config,
    ):
        response = client.delete("/api/agents/ghost")

    assert response.status_code == 404


def test_delete_agent_happy_path_calls_stop_and_saves(
    client,
    fake_config,
    manager_mock,
):
    with (
        patch(
            "qwenpaw.app.routers.agents.load_config",
            return_value=fake_config,
        ),
        patch("qwenpaw.app.routers.agents.save_config") as save_mock,
    ):
        response = client.delete("/api/agents/bot")

    assert response.status_code == 200
    assert response.json() == {"success": True, "agent_id": "bot"}
    manager_mock.stop_agent.assert_awaited_once_with("bot")
    save_mock.assert_called_once()
    assert "bot" not in fake_config.agents.profiles


def test_toggle_rejects_disabling_agent_during_startup(
    client,
    fake_config,
    manager_mock,
):
    manager_mock.is_agent_startup_in_progress.return_value = True

    with patch(
        "qwenpaw.app.routers.agents.load_config",
        return_value=fake_config,
    ):
        response = client.patch(
            "/api/agents/bot/toggle",
            json={"enabled": False},
        )

    assert response.status_code == 409
    manager_mock.stop_agent.assert_not_awaited()


def test_toggle_enable_queues_bounded_startup(
    client,
    fake_config,
    manager_mock,
):
    fake_config.agents.profiles["bot"].enabled = False

    with (
        patch(
            "qwenpaw.app.routers.agents.load_config",
            return_value=fake_config,
        ),
        patch("qwenpaw.app.routers.agents.save_config") as save_mock,
    ):
        response = client.patch(
            "/api/agents/bot/toggle",
            json={"enabled": True},
        )

    assert response.status_code == 200
    assert fake_config.agents.profiles["bot"].enabled is True
    manager_mock.schedule_agent_startup.assert_called_once_with("bot")
    save_mock.assert_called_once()


def test_delete_rejects_agent_during_startup(
    client,
    fake_config,
    manager_mock,
):
    manager_mock.is_agent_startup_in_progress.return_value = True

    with patch(
        "qwenpaw.app.routers.agents.load_config",
        return_value=fake_config,
    ):
        response = client.delete("/api/agents/bot")

    assert response.status_code == 409
    manager_mock.stop_agent.assert_not_awaited()


# ---------------------------------------------------------------------------
# POST /agents/{id}/copy
# ---------------------------------------------------------------------------


def _seed_source_workspace(workspace: Path) -> None:
    """Create config/asset files used by copy tests."""
    workspace.mkdir(parents=True, exist_ok=True)
    for name in (
        "AGENTS.md",
        "SOUL.md",
        "PROFILE.md",
        "HEARTBEAT.md",
        "BOOTSTRAP.md",
    ):
        (workspace / name).write_text(
            f"# {name}\nfrom-source\n",
            encoding="utf-8",
        )

    skills_dir = workspace / "skills" / "demo"
    skills_dir.mkdir(parents=True)
    (skills_dir / "SKILL.md").write_text("# demo\n", encoding="utf-8")
    (workspace / "skill.json").write_text(
        '{"version": 1, "skills": {"demo": {"enabled": true}}}',
        encoding="utf-8",
    )
    (workspace / "jobs.json").write_text(
        '{"version": 1, "jobs": [{"id": "j1"}]}',
        encoding="utf-8",
    )

    sessions_dir = workspace / "sessions"
    sessions_dir.mkdir()
    (sessions_dir / "s1.json").write_text("{}", encoding="utf-8")
    (workspace / "chats.json").write_text(
        '{"version": 1, "chats": [{"id": "c1"}]}',
        encoding="utf-8",
    )


def test_copy_agent_defaults_reset_channels_and_schedules_startup(
    client,
    fake_config,
    manager_mock,
    tmp_path,
    monkeypatch,
):
    source_ws = tmp_path / "source"
    _seed_source_workspace(source_ws)
    fake_config.agents.profiles["bot"] = _ref("bot")
    fake_config.agents.profiles["bot"].workspace_dir = str(source_ws)
    fake_config.agents.language = "en"

    source_cfg = AgentProfileConfig(
        id="bot",
        name="Bot",
        description="src-desc",
        workspace_dir=str(source_ws),
        language="en",
        channels=ChannelConfig(
            dingtalk=DingTalkConfig(
                enabled=True,
                client_id="cid",
                client_secret="secret",
            ),
        ),
        mcp=MCPConfig(migration_version=3),
        heartbeat=HeartbeatConfig(enabled=True, every="10m"),
        tools=ToolsConfig(
            builtin_tools={
                "read_file": BuiltinToolConfig(
                    name="read_file",
                    enabled=False,
                    description="copied-tool",
                ),
            },
        ),
        active_model=ModelSlotConfig(
            provider_id="openai",
            model="gpt-test",
        ),
    )

    working_dir = tmp_path / "working"
    working_dir.mkdir()
    monkeypatch.setattr(
        "qwenpaw.app.routers.agents.WORKING_DIR",
        working_dir,
    )

    saved = {}

    def fake_save_agent_config(agent_id, agent_config):
        saved["id"] = agent_id
        saved["config"] = agent_config

    with (
        patch(
            "qwenpaw.app.routers.agents.load_config",
            return_value=fake_config,
        ),
        patch(
            "qwenpaw.app.routers.agents.load_agent_config",
            return_value=source_cfg,
        ),
        patch("qwenpaw.app.routers.agents.save_config"),
        patch(
            "qwenpaw.app.routers.agents.save_agent_config",
            side_effect=fake_save_agent_config,
        ),
        patch(
            "qwenpaw.app.routers.agents._initialize_agent_workspace",
        ) as init_mock,
        patch(
            "qwenpaw.app.routers.agents._generate_unique_id",
            return_value="copied1",
        ),
    ):
        response = client.post("/api/agents/bot/copy", json={})

    assert response.status_code == 201
    body = response.json()
    assert body["id"] == "copied1"

    assert saved["id"] == "copied1"
    assert saved["config"].id == "copied1"
    assert saved["config"].name == "Bot Copy"
    assert saved["config"].description == "src-desc"
    assert saved["config"].mcp.migration_version == 3
    assert saved["config"].heartbeat.enabled is True
    assert saved["config"].heartbeat.every == "10m"
    assert saved["config"].tools.builtin_tools["read_file"].enabled is False
    assert (
        saved["config"].tools.builtin_tools["read_file"].description
        == "copied-tool"
    )
    assert saved["config"].active_model is not None
    assert saved["config"].active_model.provider_id == "openai"
    assert saved["config"].active_model.model == "gpt-test"
    assert saved["config"].channels.dingtalk.enabled is False
    assert saved["config"].channels.dingtalk.client_secret == ""
    assert saved["config"].workspace_dir == body["workspace_dir"]

    new_ws = Path(body["workspace_dir"])
    assert (
        (new_ws / "BOOTSTRAP.md")
        .read_text(encoding="utf-8")
        .startswith(
            "# BOOTSTRAP.md",
        )
    )
    assert (new_ws / "AGENTS.md").exists()
    assert not (new_ws / "skills").exists()
    assert not (new_ws / "jobs.json").exists()
    assert not (new_ws / "sessions").exists()
    assert not (new_ws / "chats.json").exists()

    init_mock.assert_called_once()
    manager_mock.schedule_agent_startup.assert_called_once_with("copied1")
    assert "copied1" in fake_config.agents.profiles


def test_copy_agent_copies_skills_and_jobs_when_requested(
    client,
    fake_config,
    manager_mock,
    tmp_path,
    monkeypatch,
):
    source_ws = tmp_path / "source"
    _seed_source_workspace(source_ws)
    fake_config.agents.profiles["bot"].workspace_dir = str(source_ws)
    fake_config.agents.language = "en"

    source_cfg = AgentProfileConfig(
        id="bot",
        name="Bot",
        workspace_dir=str(source_ws),
        language="en",
    )

    working_dir = tmp_path / "working"
    working_dir.mkdir()
    monkeypatch.setattr(
        "qwenpaw.app.routers.agents.WORKING_DIR",
        working_dir,
    )

    with (
        patch(
            "qwenpaw.app.routers.agents.load_config",
            return_value=fake_config,
        ),
        patch(
            "qwenpaw.app.routers.agents.load_agent_config",
            return_value=source_cfg,
        ),
        patch("qwenpaw.app.routers.agents.save_config"),
        patch("qwenpaw.app.routers.agents.save_agent_config"),
        patch("qwenpaw.app.routers.agents._initialize_agent_workspace"),
        patch(
            "qwenpaw.app.routers.agents._generate_unique_id",
            return_value="copied2",
        ),
    ):
        response = client.post(
            "/api/agents/bot/copy",
            json={
                "copy_agent_json": True,
                "copy_md_files": False,
                "copy_skills": True,
                "copy_jobs": True,
            },
        )

    assert response.status_code == 201
    new_ws = Path(response.json()["workspace_dir"])
    assert (new_ws / "skills" / "demo" / "SKILL.md").exists()
    assert (new_ws / "skill.json").exists()
    assert (new_ws / "jobs.json").exists()
    assert not (new_ws / "AGENTS.md").exists()
    assert not (new_ws / "sessions").exists()
    assert not (new_ws / "chats.json").exists()
    manager_mock.schedule_agent_startup.assert_called_once_with("copied2")


def test_copy_agent_returns_404_when_missing(client, fake_config):
    with patch(
        "qwenpaw.app.routers.agents.load_config",
        return_value=fake_config,
    ):
        response = client.post("/api/agents/ghost/copy", json={})

    assert response.status_code == 404


def test_copy_agent_rejects_copy_agent_json_false(client, fake_config):
    with patch(
        "qwenpaw.app.routers.agents.load_config",
        return_value=fake_config,
    ):
        response = client.post(
            "/api/agents/bot/copy",
            json={"copy_agent_json": False},
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_copy_agent_skips_startup_without_http_request(
    fake_config,
    manager_mock,
    tmp_path,
    monkeypatch,
):
    source_ws = tmp_path / "source"
    _seed_source_workspace(source_ws)
    fake_config.agents.profiles["bot"].workspace_dir = str(source_ws)
    fake_config.agents.language = "en"

    source_cfg = AgentProfileConfig(
        id="bot",
        name="Bot",
        workspace_dir=str(source_ws),
        language="en",
    )

    working_dir = tmp_path / "working"
    working_dir.mkdir()
    monkeypatch.setattr(
        "qwenpaw.app.routers.agents.WORKING_DIR",
        working_dir,
    )

    with (
        patch(
            "qwenpaw.app.routers.agents.load_config",
            return_value=fake_config,
        ),
        patch(
            "qwenpaw.app.routers.agents.load_agent_config",
            return_value=source_cfg,
        ),
        patch("qwenpaw.app.routers.agents.save_config"),
        patch("qwenpaw.app.routers.agents.save_agent_config"),
        patch("qwenpaw.app.routers.agents._initialize_agent_workspace"),
        patch(
            "qwenpaw.app.routers.agents._generate_unique_id",
            return_value="copied3",
        ),
        patch(
            "qwenpaw.app.routers.agents._get_multi_agent_manager",
        ) as get_manager,
    ):
        result = await copy_agent(
            agentId="bot",
            request=CopyAgentRequest(),
            http_request=None,
        )

    assert result.id == "copied3"
    get_manager.assert_not_called()
    manager_mock.schedule_agent_startup.assert_not_called()
