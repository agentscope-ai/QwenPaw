# -*- coding: utf-8 -*-
"""Security regressions for API auth middleware."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from copaw.app.auth import AuthMiddleware


@pytest.fixture(name="test_app")
def fixture_test_app() -> FastAPI:
    """Create a minimal app protected by the auth middleware."""
    test_app = FastAPI()
    test_app.add_middleware(AuthMiddleware)

    @test_app.get("/api/private")
    async def private_route(request: Request) -> dict[str, str]:
        return {"user": request.state.user}

    return test_app


@pytest.fixture(name="loopback_client")
def fixture_loopback_client(test_app: FastAPI) -> AsyncClient:
    """Create an ASGI client whose requests originate from loopback."""
    transport = ASGITransport(app=test_app, client=("127.0.0.1", 54321))
    return AsyncClient(transport=transport, base_url="http://127.0.0.1:8088")


def test_localhost_requests_no_longer_skip_auth() -> None:
    """Loopback requests must not bypass API auth anymore."""
    request = SimpleNamespace(
        method="GET",
        url=SimpleNamespace(path="/api/private"),
        client=SimpleNamespace(host="127.0.0.1"),
    )

    with (
        patch("copaw.app.auth.is_auth_enabled", return_value=True),
        patch(
            "copaw.app.auth.has_registered_users",
            return_value=True,
        ),
    ):
        # pylint: disable=protected-access
        assert AuthMiddleware._should_skip_auth(request) is False


async def test_private_api_requires_auth_on_loopback(
    loopback_client: AsyncClient,
) -> None:
    """Protected API routes should reject unauthenticated loopback callers."""
    with (
        patch("copaw.app.auth.is_auth_enabled", return_value=True),
        patch(
            "copaw.app.auth.has_registered_users",
            return_value=True,
        ),
    ):
        async with loopback_client:
            response = await loopback_client.get("/api/private")

    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}


async def test_private_api_accepts_valid_bearer_on_loopback(
    loopback_client: AsyncClient,
) -> None:
    """Valid bearer tokens should still work for local callers."""
    with (
        patch("copaw.app.auth.is_auth_enabled", return_value=True),
        patch(
            "copaw.app.auth.has_registered_users",
            return_value=True,
        ),
        patch("copaw.app.auth.verify_token", return_value="alice"),
    ):
        async with loopback_client:
            response = await loopback_client.get(
                "/api/private",
                headers={"Authorization": "Bearer local-token"},
            )

    assert response.status_code == 200
    assert response.json() == {"user": "alice"}
