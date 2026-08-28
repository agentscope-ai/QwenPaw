# -*- coding: utf-8 -*-
"""Tests for the shared deferred application entry point."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.deferred_app import DeferredApp


def test_healthz_is_immediately_available_during_import() -> None:
    release = threading.Event()
    full_app = FastAPI()

    @asynccontextmanager
    async def full_lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.startup_ready = asyncio.Event()
        app.state.startup_ready.set()
        yield

    full_app.router.lifespan_context = full_lifespan

    def load_app() -> FastAPI:
        release.wait(timeout=2)
        return full_app

    deferred = DeferredApp(app_loader=load_app)
    with TestClient(deferred) as client:
        response = client.get("/api/healthz")
        assert response.status_code == 503
        assert response.json()["status"] == "starting"
        assert client.get("/api/version").status_code == 200
        release.set()


def test_healthz_becomes_ready_with_default_agent() -> None:
    full_app = FastAPI()

    class Registry:
        @staticmethod
        def list_loaded_agents() -> list[str]:
            return ["default"]

    @asynccontextmanager
    async def full_lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.startup_ready = asyncio.Event()
        app.state.multi_agent_manager = Registry()
        app.state.startup_time = 1.0
        app.state.startup_ready.set()
        yield

    full_app.router.lifespan_context = full_lifespan
    deferred = DeferredApp(app_loader=lambda: full_app)

    with TestClient(deferred) as client:
        response = client.get("/api/healthz")

    assert response.status_code == 200
    assert response.json()["agents_loaded"] == ["default"]
