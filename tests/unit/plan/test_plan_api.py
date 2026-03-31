# -*- coding: utf-8 -*-
"""Tests for plan API endpoints using FastAPI TestClient."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentscope.plan import PlanNotebook

from copaw.app.routers.plan import router


def _make_app(plan_notebook=None):
    """Create a minimal FastAPI app with plan router and mock workspace."""
    app = FastAPI()
    app.include_router(router, prefix="/api")

    mock_workspace = MagicMock()
    mock_workspace.agent_id = "test-agent"

    if plan_notebook is not None:
        mock_workspace.plan_notebook = plan_notebook
    else:
        mock_workspace.plan_notebook = None

    mock_config = MagicMock()
    mock_config.plan = MagicMock()
    mock_config.plan.enabled = plan_notebook is not None
    mock_config.plan.model_dump.return_value = {
        "enabled": plan_notebook is not None,
        "max_subtasks": None,
        "storage_type": "memory",
        "storage_path": None,
        "agent_managed": True,
    }
    mock_workspace.config = mock_config

    async def _mock_get_agent(_request, **_kwargs):
        return mock_workspace

    app.state.multi_agent_manager = MagicMock()
    app.state.multi_agent_manager.get_agent = AsyncMock(
        return_value=mock_workspace,
    )

    return app, _mock_get_agent


class TestPlanCurrentEndpoint:
    """GET /plan/current."""

    def test_returns_null_when_no_notebook(self):
        app, mock_get = _make_app(plan_notebook=None)
        with patch(
            "copaw.app.routers.plan.get_agent_for_request",
            side_effect=mock_get,
        ):
            client = TestClient(app)
            r = client.get("/api/plan/current")
            assert r.status_code == 200

    def test_returns_null_when_no_plan(self):
        nb = PlanNotebook()
        app, mock_get = _make_app(plan_notebook=nb)
        with patch(
            "copaw.app.routers.plan.get_agent_for_request",
            side_effect=mock_get,
        ):
            client = TestClient(app)
            r = client.get("/api/plan/current")
            assert r.status_code == 200


class TestPlanDisabledEndpoints:
    """Endpoints return 404 when plan mode is disabled."""

    def test_create_returns_404(self):
        app, mock_get = _make_app(plan_notebook=None)
        with patch(
            "copaw.app.routers.plan.get_agent_for_request",
            side_effect=mock_get,
        ):
            client = TestClient(app)
            r = client.post(
                "/api/plan/create",
                json={
                    "name": "X",
                    "description": "X",
                    "expected_outcome": "X",
                    "subtasks": [],
                },
            )
            assert r.status_code == 404

    def test_history_returns_404(self):
        app, mock_get = _make_app(plan_notebook=None)
        with patch(
            "copaw.app.routers.plan.get_agent_for_request",
            side_effect=mock_get,
        ):
            client = TestClient(app)
            r = client.get("/api/plan/history")
            assert r.status_code == 404


class TestPlanConfigEndpoint:
    """GET/PUT /plan/config."""

    def test_get_config(self):
        app, mock_get = _make_app(plan_notebook=None)
        with patch(
            "copaw.app.routers.plan.get_agent_for_request",
            side_effect=mock_get,
        ):
            client = TestClient(app)
            r = client.get("/api/plan/config")
            assert r.status_code == 200
            data = r.json()
            assert "enabled" in data
