# -*- coding: utf-8 -*-
"""Tests for the shared deferred application entry point."""
# pylint: disable=protected-access

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.deferred_app import DeferredApp


@pytest.mark.parametrize(
    ("method", "path", "expected"),
    [
        ("GET", "/api/chats", "chat_core_ready"),
        ("POST", "/api/console/chat", "chat_core_ready"),
        ("POST", "/api/console/chat/task", "chat_core_ready"),
        ("POST", "/api/cron/jobs", "background_ready"),
        ("PUT", "/api/config", "background_ready"),
    ],
)
def test_request_readiness_boundary(
    method: str,
    path: str,
    expected: str,
) -> None:
    assert (
        DeferredApp._required_phase(
            {
                "type": "http",
                "method": method,
                "path": path,
            },
        )
        == expected
    )


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


def test_application_routes_wait_for_true_chat_readiness() -> None:
    release_chat = threading.Event()
    full_app = FastAPI()

    @full_app.get("/api/probe")
    def get_probe() -> dict[str, bool]:
        return {"chat": True}

    @asynccontextmanager
    async def full_lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.startup_ready = asyncio.Event()

        async def publish_chat_ready() -> None:
            await asyncio.to_thread(release_chat.wait)
            app.state.startup_ready.set()

        task = asyncio.create_task(publish_chat_ready())
        try:
            yield
        finally:
            release_chat.set()
            await task

    full_app.router.lifespan_context = full_lifespan
    deferred = DeferredApp(app_loader=lambda: full_app)

    with TestClient(deferred) as client:
        with ThreadPoolExecutor(max_workers=1) as executor:
            response_future = executor.submit(client.get, "/api/probe")
            assert not response_future.done()
            release_chat.set()
            response = response_future.result(timeout=2)

    assert response.status_code == 200
    assert response.json() == {"chat": True}
