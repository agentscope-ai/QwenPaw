# -*- coding: utf-8 -*-
"""Invalid memory model slots must fail request validation before updates."""

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.routers import workspace


@pytest.mark.parametrize("value", [123, False, [], {"model": 123}])
def test_invalid_memory_model_returns_422(monkeypatch, value):
    get_agent = AsyncMock()
    monkeypatch.setattr(workspace, "get_agent_for_request", get_agent)
    app = FastAPI()
    app.include_router(workspace.router, prefix="/api")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.put(
            "/api/workspace/running-config",
            json={"reme_light_memory_config": {"memory_model": value}},
        )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"][:3] == [
        "body",
        "reme_light_memory_config",
        "memory_model",
    ]
    get_agent.assert_not_awaited()
