# -*- coding: utf-8 -*-
"""Unit tests for agent type registry and create/list wiring."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.agents.agent_types import (
    BUSINESS_ANALYSIS_AGENT_TYPE,
    DEFAULT_AGENT_TYPE,
    AgentTypeDefinition,
    get_agent_type,
    is_valid_agent_type,
    list_agent_types,
    list_supported_agent_type_ids,
    register_agent_type,
)
from qwenpaw.app.agent_startup import AgentStartupStatus
from qwenpaw.app.routers.agents import router as agents_router
from qwenpaw.config.config import AgentProfileConfig, AgentProfileRef


def test_builtin_agent_types_are_registered():
    ids = list_supported_agent_type_ids()
    assert DEFAULT_AGENT_TYPE in ids
    assert BUSINESS_ANALYSIS_AGENT_TYPE in ids
    assert is_valid_agent_type(DEFAULT_AGENT_TYPE)
    assert is_valid_agent_type(BUSINESS_ANALYSIS_AGENT_TYPE)
    assert not is_valid_agent_type("unknown_type")


def test_register_agent_type_extends_registry():
    custom_id = "custom_analysis_ext"
    try:
        register_agent_type(
            AgentTypeDefinition(
                id=custom_id,
                name="Custom",
                description="extensibility probe",
            ),
        )
        assert is_valid_agent_type(custom_id)
        assert get_agent_type(custom_id).name == "Custom"
        assert custom_id in {item.id for item in list_agent_types()}
    finally:
        # Keep registry clean for other tests in the same process.
        from qwenpaw.agents import agent_types as mod

        mod._AGENT_TYPES.pop(custom_id, None)


def test_agent_profile_defaults_to_default_type():
    cfg = AgentProfileConfig(id="a", name="A")
    assert cfg.agent_type == DEFAULT_AGENT_TYPE


@pytest.fixture
def manager_mock():
    mgr = MagicMock(name="MultiAgentManager")
    mgr.schedule_agent_startup = MagicMock()
    mgr.get_agent_startup_status.side_effect = lambda _agent_id, *, enabled: (
        AgentStartupStatus.RUNNING if enabled else AgentStartupStatus.DISABLED
    )
    return mgr


@pytest.fixture
def client(manager_mock) -> TestClient:
    application = FastAPI()
    application.state.multi_agent_manager = manager_mock
    application.include_router(agents_router, prefix="/api")
    return TestClient(application)


@pytest.fixture
def fake_config():
    config = MagicMock(name="AppConfig")
    config.agents = MagicMock()
    config.agents.profiles = {
        "default": AgentProfileRef(
            id="default",
            workspace_dir="/tmp/ws/default",
        ),
    }
    config.agents.agent_order = ["default"]
    config.agents.language = "en"
    return config


def test_list_agent_types_endpoint(client):
    response = client.get("/api/agents/types")
    assert response.status_code == 200
    body = response.json()
    ids = {item["id"] for item in body["types"]}
    assert ids == {DEFAULT_AGENT_TYPE, BUSINESS_ANALYSIS_AGENT_TYPE}
    assert all("name" in item and "description" in item for item in body["types"])


def test_create_agent_persists_agent_type(client, fake_config, tmp_path):
    saved: list[AgentProfileConfig] = []

    with (
        patch(
            "qwenpaw.app.routers.agents.load_config",
            return_value=fake_config,
        ),
        patch("qwenpaw.app.routers.agents.save_config"),
        patch(
            "qwenpaw.app.routers.agents.save_agent_config",
            side_effect=lambda _id, cfg: saved.append(cfg),
        ),
        patch(
            "qwenpaw.app.routers.agents._initialize_agent_workspace",
        ),
        patch(
            "qwenpaw.app.routers.agents.WORKING_DIR",
            str(tmp_path),
        ),
    ):
        response = client.post(
            "/api/agents",
            json={
                "id": "biz-agent",
                "name": "Biz",
                "agent_type": BUSINESS_ANALYSIS_AGENT_TYPE,
                "workspace_dir": str(tmp_path / "biz-agent"),
            },
        )

    assert response.status_code == 201
    assert len(saved) == 1
    assert saved[0].agent_type == BUSINESS_ANALYSIS_AGENT_TYPE
    assert saved[0].id == "biz-agent"


def test_create_agent_rejects_unknown_agent_type(client):
    response = client.post(
        "/api/agents",
        json={
            "name": "Bad",
            "agent_type": "not_a_real_type",
        },
    )
    assert response.status_code == 422


def test_list_agents_includes_agent_type(client, fake_config):
    agent_cfg = AgentProfileConfig(
        id="default",
        name="Default",
        description="primary",
        workspace_dir="/tmp/ws/default",
        agent_type=BUSINESS_ANALYSIS_AGENT_TYPE,
    )

    with (
        patch(
            "qwenpaw.app.routers.agents.load_config",
            return_value=fake_config,
        ),
        patch(
            "qwenpaw.app.routers.agents.load_agent_config",
            return_value=agent_cfg,
        ),
    ):
        response = client.get("/api/agents")

    assert response.status_code == 200
    agents = response.json()["agents"]
    assert len(agents) == 1
    assert agents[0]["agent_type"] == BUSINESS_ANALYSIS_AGENT_TYPE
