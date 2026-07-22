# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
"""Unit tests for the NocoBase REST client."""
from __future__ import annotations

import httpx
import pytest
from pytest_httpx import HTTPXMock

from nocobase_auth.nocobase_client import (
    NocoBaseClient,
    NocoBaseAuthError,
    NocoBaseRequestError,
)


USERS_LIST_URL = (
    "https://nocobase.test/api/users:list?paginate=false&appends=roles"
)
ROLES_LIST_URL = "https://nocobase.test/api/roles:list?paginate=false"


@pytest.fixture
def client() -> NocoBaseClient:
    return NocoBaseClient(
        base_url="https://nocobase.test",
        api_token="token-123",
    )


@pytest.mark.asyncio
async def test_list_users_success(
    client: NocoBaseClient,
    httpx_mock: HTTPXMock,
) -> None:
    httpx_mock.add_response(
        url=USERS_LIST_URL,
        json={
            "data": [
                {
                    "id": 1,
                    "email": "alice@example.com",
                    "nickname": "Alice",
                    "roles": [{"name": "admin", "title": "Admin"}],
                },
                {
                    "id": 2,
                    "email": "bob@example.com",
                    "nickname": "Bob",
                    "roles": ["viewer"],
                },
            ],
        },
    )

    users = await client.list_users("email")
    assert len(users) == 2
    assert users[0]["sender_id"] == "alice@example.com"
    assert users[0]["roles"] == ["admin"]
    assert users[1]["sender_id"] == "bob@example.com"
    assert users[1]["roles"] == ["viewer"]


@pytest.mark.asyncio
async def test_list_roles_success(
    client: NocoBaseClient,
    httpx_mock: HTTPXMock,
) -> None:
    httpx_mock.add_response(
        url=ROLES_LIST_URL,
        json={
            "data": [
                {"id": 1, "name": "admin", "title": "Admin"},
                {"id": 2, "name": "viewer", "title": "Viewer"},
            ],
        },
    )

    roles = await client.list_roles()
    assert len(roles) == 2
    assert roles[0]["name"] == "admin"


@pytest.mark.asyncio
async def test_auth_error(
    client: NocoBaseClient,
    httpx_mock: HTTPXMock,
) -> None:
    httpx_mock.add_response(
        url=USERS_LIST_URL,
        status_code=401,
        text='{"error": "Unauthorized"}',
    )

    with pytest.raises(NocoBaseAuthError):
        await client.list_users()


@pytest.mark.asyncio
async def test_request_error(
    client: NocoBaseClient,
    httpx_mock: HTTPXMock,
) -> None:
    httpx_mock.add_response(
        url=USERS_LIST_URL,
        status_code=500,
        text="Internal Server Error",
    )

    with pytest.raises(NocoBaseRequestError) as exc_info:
        await client.list_users()
    assert exc_info.value.status_code == 500


@pytest.mark.asyncio
async def test_health_check_success(
    client: NocoBaseClient,
    httpx_mock: HTTPXMock,
) -> None:
    httpx_mock.add_response(
        url="https://nocobase.test/api/users:list?pageSize=1",
        json={"data": []},
    )
    assert await client.health_check() is True


@pytest.mark.asyncio
async def test_health_check_failure(
    client: NocoBaseClient,
    httpx_mock: HTTPXMock,
) -> None:
    httpx_mock.add_response(
        url="https://nocobase.test/api/users:list?pageSize=1",
        status_code=503,
    )
    assert await client.health_check() is False


@pytest.mark.asyncio
async def test_client_ignores_ambient_proxies(
    client: NocoBaseClient,
) -> None:
    """The HTTP client must contact the configured NocoBase directly.

    System/ENV proxies (e.g. a corporate security agent) can otherwise
    silently hijack loopback/LAN requests and break the integration.
    """
    http_client = client._get_client()  # pylint: disable=protected-access
    assert http_client.trust_env is False
    await client.close()


@pytest.mark.asyncio
async def test_user_id_field_custom(
    client: NocoBaseClient,
    httpx_mock: HTTPXMock,
) -> None:
    httpx_mock.add_response(
        url=USERS_LIST_URL,
        json={
            "data": [
                {
                    "id": 1,
                    "email": "alice@example.com",
                    "phone": "+8612345678900",
                    "roles": [],
                },
            ],
        },
    )

    users = await client.list_users("phone")
    assert users[0]["sender_id"] == "+8612345678900"


@pytest.mark.asyncio
async def test_verify_user_token_success(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="http://nb.local/api/auth:check",
        json={"data": {"id": 7, "email": "eve@example.com"}},
        status_code=200,
    )
    client = NocoBaseClient(base_url="http://nb.local", api_token="admin")
    user = await client.verify_user_token("user-tok")
    assert user is not None
    assert user["email"] == "eve@example.com"
    await client.close()


@pytest.mark.asyncio
async def test_verify_user_token_invalid_returns_none(
    httpx_mock: HTTPXMock,
) -> None:
    httpx_mock.add_response(
        url="http://nb.local/api/auth:check",
        json={"errors": [{"code": "INVALID_TOKEN"}]},
        status_code=401,
    )
    client = NocoBaseClient(base_url="http://nb.local", api_token="admin")
    assert await client.verify_user_token("bad") is None
    await client.close()


@pytest.mark.asyncio
async def test_verify_user_token_network_error_raises(
    httpx_mock: HTTPXMock,
) -> None:
    httpx_mock.add_exception(httpx.ConnectError("down"))
    client = NocoBaseClient(base_url="http://nb.local", api_token="admin")
    with pytest.raises(NocoBaseRequestError):
        await client.verify_user_token("tok")
    await client.close()


@pytest.mark.asyncio
async def test_verify_user_token_uses_user_token_not_admin(
    httpx_mock: HTTPXMock,
) -> None:
    httpx_mock.add_response(
        url="http://nb.local/api/auth:check",
        json={"data": {"id": 1, "email": "a@b.com"}},
        status_code=200,
    )
    client = NocoBaseClient(base_url="http://nb.local", api_token="ADMIN-TOK")
    await client.verify_user_token("USER-TOK")
    req = httpx_mock.get_requests()[-1]
    assert req.headers["Authorization"] == "Bearer USER-TOK"
    await client.close()
