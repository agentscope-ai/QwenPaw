# -*- coding: utf-8 -*-
"""Authorization tests for QwenPaw Pro control-plane APIs."""

from collections.abc import AsyncIterator, Mapping
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from qwenpaw.pro.auth import ProAuthService
from qwenpaw.pro.control_app import create_pro_app
from qwenpaw.pro.credentials import TenantCredentialVault
from qwenpaw.pro.driver import RuntimeDriver
from qwenpaw.pro.models import RuntimeRecord, RuntimeState
from qwenpaw.pro.registry import RuntimeRegistry
from qwenpaw.pro.service import RuntimeService


class _FakeDriver(RuntimeDriver):
    name = "local"
    security_level = "isolated-local"

    def start(
        self,
        record: RuntimeRecord,
        credentials: Mapping[str, str],
    ) -> RuntimeRecord:
        del credentials
        return RuntimeRecord(
            **{
                **record.__dict__,
                "state": RuntimeState.RUNNING,
                "pid": 100,
            },
        )

    def stop(self, record: RuntimeRecord) -> RuntimeRecord:
        return RuntimeRecord(
            **{
                **record.__dict__,
                "state": RuntimeState.STOPPED,
                "pid": None,
            },
        )

    def status(self, record: RuntimeRecord) -> RuntimeRecord:
        return record

    def close(self) -> None:
        return None


class _ProxyStream(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b'{"product":"QwenPaw"}'


def _client(
    tmp_path: Path,
    proxy_transport: httpx.AsyncBaseTransport | None = None,
) -> TestClient:
    database = tmp_path / "control.db"
    registry = RuntimeRegistry(database)
    vault = TenantCredentialVault(
        database,
        tmp_path / "secrets" / ".vault_key",
    )

    def runtime_environment(record: RuntimeRecord) -> dict[str, str]:
        environment = vault.resolve_environment(
            tenant_id=record.tenant_id,
            runtime_id=record.runtime_id,
        )
        environment[
            "QWENPAW_PRO_INTERNAL_TOKEN"
        ] = vault.get_or_create_runtime_secret(
            tenant_id=record.tenant_id,
            runtime_id=record.runtime_id,
            name="QWENPAW_PRO_INTERNAL_TOKEN",
        )
        return environment

    service = RuntimeService(
        root_dir=tmp_path,
        registry=registry,
        drivers={"local": _FakeDriver()},
        credential_provider=runtime_environment,
    )
    auth = ProAuthService(database, vault)
    return TestClient(
        create_pro_app(
            service,
            auth,
            proxy_transport=proxy_transport,
        ),
    )


def _register(client: TestClient, username: str) -> str:
    response = client.post(
        "/api/auth/register",
        json={"username": username, "password": "safe-password"},
    )
    assert response.status_code == 200
    return str(response.json()["token"])


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_runtime_ownership_and_admin_user_management(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        admin_token = _register(client, "owner")
        settings = client.put(
            "/api/pro/admin/settings/registration",
            json={"enabled": True},
            headers=_headers(admin_token),
        )
        assert settings.status_code == 200
        user_token = _register(client, "member")

        created = client.post(
            "/api/pro/runtimes",
            json={"runtime_id": "admin-runtime"},
            headers=_headers(admin_token),
        )
        assert created.status_code == 201

        forbidden = client.get(
            "/api/pro/runtimes/admin-runtime",
            headers=_headers(user_token),
        )
        assert forbidden.status_code == 404

        own = client.post(
            "/api/pro/runtimes",
            json={"runtime_id": "member-runtime"},
            headers=_headers(user_token),
        )
        assert own.status_code == 201
        user_list = client.get(
            "/api/pro/runtimes",
            headers=_headers(user_token),
        )
        assert [item["runtime_id"] for item in user_list.json()] == [
            "member-runtime",
        ]
        admin_list = client.get(
            "/api/pro/runtimes",
            headers=_headers(admin_token),
        )
        assert {item["runtime_id"] for item in admin_list.json()} == {
            "admin-runtime",
            "member-runtime",
        }

        denied_users = client.get(
            "/api/pro/admin/users",
            headers=_headers(user_token),
        )
        assert denied_users.status_code == 403


def test_credential_api_never_returns_plaintext(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        token = _register(client, "owner")
        response = client.put(
            "/api/pro/credentials",
            json={
                "scope": "tenant",
                "name": "OPENAI_API_KEY",
                "value": "private-value",
            },
            headers=_headers(token),
        )
        assert response.status_code == 204

        listed = client.get(
            "/api/pro/credentials",
            headers=_headers(token),
        )
        assert listed.status_code == 200
        assert listed.json()[0]["name"] == "OPENAI_API_KEY"
        assert "private-value" not in listed.text


def test_standard_api_proxies_to_personal_runtime(tmp_path: Path) -> None:
    async def proxy_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/version"
        assert request.headers["X-QwenPaw-Pro-Runtime-Token"]
        assert "authorization" not in request.headers
        return httpx.Response(
            200,
            stream=_ProxyStream(),
            headers={"Content-Type": "application/json"},
        )

    transport = httpx.MockTransport(proxy_handler)
    with _client(tmp_path, transport) as client:
        token = _register(client, "owner")
        response = client.get(
            "/api/version",
            headers=_headers(token),
        )

        assert response.status_code == 200
        assert response.json() == {"product": "QwenPaw"}
        runtimes = client.get(
            "/api/pro/runtimes",
            headers=_headers(token),
        ).json()
        assert len(runtimes) == 1
        assert runtimes[0]["state"] == "running"
        assert runtimes[0]["owner_user_id"]
        assert runtimes[0]["metadata"]["pro_default"] is True
