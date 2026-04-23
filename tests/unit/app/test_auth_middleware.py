# -*- coding: utf-8 -*-
"""Security regressions for API auth middleware."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from qwenpaw.app.auth import AuthMiddleware, LOCAL_CLI_TOKEN_HEADER


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


@pytest.fixture(name="remote_client")
def fixture_remote_client(test_app: FastAPI) -> AsyncClient:
    """Create an ASGI client whose requests originate from a remote host."""
    transport = ASGITransport(app=test_app, client=("10.20.30.40", 54321))
    return AsyncClient(transport=transport, base_url="http://10.20.30.40:8088")


def test_localhost_requests_no_longer_skip_auth() -> None:
    """Loopback requests must not bypass API auth anymore."""
    request = SimpleNamespace(
        method="GET",
        url=SimpleNamespace(path="/api/private"),
        client=SimpleNamespace(host="127.0.0.1"),
    )

    with (
        patch("qwenpaw.app.auth.is_auth_enabled", return_value=True),
        patch(
            "qwenpaw.app.auth.has_registered_users",
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
        patch("qwenpaw.app.auth.is_auth_enabled", return_value=True),
        patch(
            "qwenpaw.app.auth.has_registered_users",
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
        patch("qwenpaw.app.auth.is_auth_enabled", return_value=True),
        patch(
            "qwenpaw.app.auth.has_registered_users",
            return_value=True,
        ),
        patch("qwenpaw.app.auth.verify_token", return_value="alice"),
    ):
        async with loopback_client:
            response = await loopback_client.get(
                "/api/private",
                headers={"Authorization": "Bearer local-token"},
            )

    assert response.status_code == 200
    assert response.json() == {"user": "alice"}


async def test_private_api_accepts_local_cli_token_on_loopback(
    loopback_client: AsyncClient,
) -> None:
    """Loopback CLI requests may use the dedicated local CLI token."""
    with (
        patch("qwenpaw.app.auth.is_auth_enabled", return_value=True),
        patch(
            "qwenpaw.app.auth.has_registered_users",
            return_value=True,
        ),
        patch(
            "qwenpaw.app.auth._load_auth_data",
            return_value={
                "local_cli_token": "cli-token",
                "user": {"username": "alice"},
            },
        ),
    ):
        async with loopback_client:
            response = await loopback_client.get(
                "/api/private",
                headers={LOCAL_CLI_TOKEN_HEADER: "cli-token"},
            )

    assert response.status_code == 200
    assert response.json() == {"user": "alice"}


async def test_private_api_accepts_local_cli_token_with_header_whitespace(
    loopback_client: AsyncClient,
) -> None:
    """Whitespace around the local CLI token header should be ignored."""
    with (
        patch("qwenpaw.app.auth.is_auth_enabled", return_value=True),
        patch(
            "qwenpaw.app.auth.has_registered_users",
            return_value=True,
        ),
        patch(
            "qwenpaw.app.auth._load_auth_data",
            return_value={
                "local_cli_token": "cli-token",
                "user": {"username": "alice"},
            },
        ),
    ):
        async with loopback_client:
            response = await loopback_client.get(
                "/api/private",
                headers={LOCAL_CLI_TOKEN_HEADER: "  cli-token  "},
            )

    assert response.status_code == 200
    assert response.json() == {"user": "alice"}


async def test_private_api_rejects_local_cli_token_off_loopback(
    remote_client: AsyncClient,
) -> None:
    """The local CLI token must not authenticate non-loopback callers."""
    with (
        patch("qwenpaw.app.auth.is_auth_enabled", return_value=True),
        patch(
            "qwenpaw.app.auth.has_registered_users",
            return_value=True,
        ),
        patch(
            "qwenpaw.app.auth._load_auth_data",
            return_value={
                "local_cli_token": "cli-token",
                "user": {"username": "alice"},
            },
        ),
    ):
        async with remote_client:
            response = await remote_client.get(
                "/api/private",
                headers={LOCAL_CLI_TOKEN_HEADER: "cli-token"},
            )

    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}
