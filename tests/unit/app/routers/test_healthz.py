# -*- coding: utf-8 -*-
"""Unit tests for ``GET /api/healthz``."""
# pylint: disable=redefined-outer-name
from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.routers.healthz import router as healthz_router


@pytest.fixture
def app() -> FastAPI:
    return FastAPI()


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    app.include_router(healthz_router, prefix="/api")
    return TestClient(app)


class TestHealthzNotReady:
    """503 when background startup has not completed."""

    def test_returns_503_when_event_not_set(self, app, client):
        app.state.startup_ready = asyncio.Event()
        resp = client.get("/api/healthz")
        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == "starting"

    def test_returns_503_when_attr_missing(self, client):
        resp = client.get("/api/healthz")
        assert resp.status_code == 503


class TestHealthzReady:
    """200 when background startup completed."""

    def test_returns_200_with_agents(self, app, client):
        event = asyncio.Event()
        event.set()
        app.state.startup_ready = event
        app.state.startup_time = time.time() - 10

        mgr = MagicMock()
        mgr.list_loaded_agents.return_value = [
            "default",
            "qa",
        ]
        app.state.multi_agent_manager = mgr

        resp = client.get("/api/healthz")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["agents_loaded"] == ["default", "qa"]
        assert isinstance(body["uptime_seconds"], float)
        assert body["uptime_seconds"] >= 10

    def test_returns_200_no_manager(self, app, client):
        event = asyncio.Event()
        event.set()
        app.state.startup_ready = event
        app.state.startup_time = time.time()
        app.state.multi_agent_manager = None

        resp = client.get("/api/healthz")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["agents_loaded"] == []
