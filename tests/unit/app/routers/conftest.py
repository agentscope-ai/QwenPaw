# -*- coding: utf-8 -*-
"""Shared fixtures for ``tests/unit/app/routers/``.

Each test gets a fresh FastAPI app whose ``app.state.multi_agent_manager``
points to a ``MagicMock`` so router code can call
``request.app.state.multi_agent_manager.get_agent(...)`` without booting
the real runtime.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def workspace_mock() -> Any:
    """A workspace mock with a ``channel_manager`` exposing ``send_text``."""
    workspace = MagicMock(name="Workspace")
    workspace.channel_manager = MagicMock(name="ChannelManager")
    workspace.channel_manager.send_text = AsyncMock(return_value=None)
    return workspace


@pytest.fixture
def manager_mock(workspace_mock) -> Any:
    """Default MultiAgentManager mock: ``get_agent`` returns the workspace."""
    manager = MagicMock(name="MultiAgentManager")
    manager.get_agent = AsyncMock(return_value=workspace_mock)
    return manager


@pytest.fixture
def app(manager_mock) -> FastAPI:
    """A fresh FastAPI app with the messages router mounted under /api."""
    from qwenpaw.app.routers.messages import router as messages_router

    application = FastAPI()
    application.state.multi_agent_manager = manager_mock
    application.include_router(messages_router, prefix="/api")
    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)
