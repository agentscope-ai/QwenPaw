# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument
"""Unit tests for ``/api/advisor-mode``."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import qwenpaw.app.routers.advisor_mode as advisor_router_module
from qwenpaw.app.routers.advisor_mode import router as advisor_router
from qwenpaw.config.config import AgentProfileConfig, ModelSlotConfig


@pytest.fixture
def stored_config():
    cfg = AgentProfileConfig(id="agent-1", name="Agent")
    cfg.active_model = ModelSlotConfig(provider_id="dash", model="qwen3-max")
    cfg.subagent_model = ModelSlotConfig(provider_id="dash", model="qwen3-8b")
    return cfg


@pytest.fixture
def client(monkeypatch, stored_config):
    async def get_agent_for_request(_request):
        return SimpleNamespace(agent_id="agent-1")

    def load_agent_config(agent_id):
        assert agent_id == "agent-1"
        return stored_config

    async def update_agent_config_async(agent_id, updater):
        assert agent_id == "agent-1"
        updater(stored_config)
        return stored_config

    monkeypatch.setattr(
        advisor_router_module,
        "get_agent_for_request",
        get_agent_for_request,
    )
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        load_agent_config,
    )
    monkeypatch.setattr(
        "qwenpaw.config.config.update_agent_config_async",
        update_agent_config_async,
    )
    app = FastAPI()
    app.include_router(advisor_router, prefix="/api")
    return TestClient(app)


def test_get_reports_state_and_models(client):
    resp = client.get("/api/advisor-mode")
    assert resp.status_code == 200
    assert resp.json() == {
        "enabled": False,
        "plan_enabled": True,
        "followup_enabled": True,
        "on_demand_enabled": True,
        "agent_id": "agent-1",
        "teacher_model": {"provider_id": "dash", "model": "qwen3-max"},
        "student_model": {"provider_id": "dash", "model": "qwen3-8b"},
    }


def test_get_without_subagent_model(client, stored_config):
    stored_config.subagent_model = None
    body = client.get("/api/advisor-mode").json()
    assert body["student_model"] is None


def test_post_enables_and_persists(client, stored_config):
    resp = client.post("/api/advisor-mode", json={"enabled": True})
    assert resp.status_code == 200
    assert resp.json()["enabled"] is True
    assert stored_config.advisor_mode.enabled is True
    # Fields left out of the body are untouched.
    assert stored_config.advisor_mode.followup_enabled is True


def test_post_can_update_followup_alone(client, stored_config):
    stored_config.advisor_mode.enabled = True
    resp = client.post("/api/advisor-mode", json={"followup_enabled": False})
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True
    assert body["followup_enabled"] is False
    assert stored_config.advisor_mode.followup_enabled is False


def test_post_rejects_wrong_types(client):
    resp = client.post("/api/advisor-mode", json={"enabled": "yes please"})
    assert resp.status_code == 422


def test_get_reports_global_active_model_as_teacher_fallback(
    client,
    stored_config,
    monkeypatch,
):
    stored_config.active_model = None
    manager = SimpleNamespace(
        get_active_model=lambda: ModelSlotConfig(
            provider_id="glob",
            model="g-max",
        ),
    )
    monkeypatch.setattr(
        "qwenpaw.providers.ProviderManager.get_instance",
        lambda: manager,
    )
    body = client.get("/api/advisor-mode").json()
    assert body["teacher_model"] == {"provider_id": "glob", "model": "g-max"}


def test_post_can_update_on_demand_alone(client, stored_config):
    resp = client.post("/api/advisor-mode", json={"on_demand_enabled": False})
    assert resp.status_code == 200
    assert resp.json()["on_demand_enabled"] is False
    assert stored_config.advisor_mode.on_demand_enabled is False
    assert stored_config.advisor_mode.enabled is False, "untouched"


def test_post_can_switch_off_the_opening_plan(client, stored_config):
    resp = client.post("/api/advisor-mode", json={"plan_enabled": False})
    assert resp.status_code == 200
    assert resp.json()["plan_enabled"] is False
    assert stored_config.advisor_mode.plan_enabled is False
