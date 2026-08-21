# -*- coding: utf-8 -*-
"""Authorization tests for QwenPaw Hub control-plane APIs."""

from collections.abc import AsyncIterator, Iterator, Mapping
import asyncio
from dataclasses import replace
import gzip
from pathlib import Path
import sqlite3
import threading
from urllib.parse import urlsplit
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.requests import ClientDisconnect
from starlette.websockets import WebSocketDisconnect
from websockets.sync.server import ServerConnection, serve

from qwenpaw.__version__ import __version__
from qwenpaw.hub.auth import HubAuthService, HubUser
from qwenpaw.hub.config import (
    AccessSecurityConfig,
    ControlPlaneConfig,
    HubConfig,
    RateLimitConfig,
    RuntimeProxyConfig,
)
from qwenpaw.hub.control_app import create_hub_app, run_hub_app
from qwenpaw.hub.credentials import TenantCredentialVault
from qwenpaw.hub.provisioner import (
    RuntimeProvisioner,
    RuntimeProvisionerAvailability,
)
from qwenpaw.hub.models import RuntimeRecord, RuntimeState
from qwenpaw.hub.registry import RuntimeRegistry
from qwenpaw.hub.service import RuntimeService


class _FakeProvisioner(RuntimeProvisioner):
    name = "local"
    security_level = "isolated-local"

    def __init__(self, available: bool = True, port: int = 0) -> None:
        self.available = available
        self.port = port

    def preflight(self, root_dir: Path) -> RuntimeProvisionerAvailability:
        del root_dir
        return RuntimeProvisionerAvailability(
            available=self.available,
            reason=None if self.available else "sandbox unavailable",
        )

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
                "port": self.port or record.port,
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
    hub_config: HubConfig | None = None,
    provisioner_available: bool = True,
    runtime_port: int = 0,
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
            "QWENPAW_RUNTIME_INTERNAL_TOKEN"
        ] = vault.get_or_create_runtime_secret(
            tenant_id=record.tenant_id,
            runtime_id=record.runtime_id,
            name="QWENPAW_RUNTIME_INTERNAL_TOKEN",
        )
        return environment

    service = RuntimeService(
        root_dir=tmp_path,
        registry=registry,
        provisioners={
            "local": _FakeProvisioner(
                provisioner_available,
                runtime_port,
            ),
        },
        credential_provider=runtime_environment,
        hub_config=hub_config,
    )
    auth = HubAuthService(database, vault)
    return TestClient(
        create_hub_app(
            service,
            auth,
            proxy_transport=proxy_transport,
            hub_config=hub_config,
        ),
    )


def _register(client: TestClient, username: str) -> str:
    response = client.post(
        "/api/auth/register",
        json={"username": username, "password": "safe-password"},
    )
    assert response.status_code == 200
    return str(response.json()["token"])


def _create_user(client: TestClient, username: str) -> tuple[HubUser, str]:
    auth = client.app.state.auth_service
    user = auth.create_user(
        username=username,
        password="safe-password",
    )
    _, token = auth.authenticate(username, "safe-password")
    return user, token


@pytest.fixture(name="hub_client")
def _hub_client(tmp_path: Path) -> Iterator[TestClient]:
    with _client(tmp_path) as client:
        yield client


@pytest.fixture(name="admin_client")
def _admin_client(hub_client: TestClient) -> tuple[TestClient, str]:
    return hub_client, _register(hub_client, "owner")


def test_login_rate_limit_returns_retry_after(tmp_path: Path) -> None:
    config = HubConfig(
        control_plane=ControlPlaneConfig(
            security=AccessSecurityConfig(
                login_rate_limit=RateLimitConfig(
                    max_attempts=2,
                    window_seconds=60,
                    block_seconds=30,
                ),
            ),
        ),
    )
    with _client(tmp_path, hub_config=config) as client:
        _register(client, "owner")
        for _ in range(2):
            response = client.post(
                "/api/auth/login",
                json={"username": "owner", "password": "wrong-pass"},
            )
            assert response.status_code == 401

        blocked = client.post(
            "/api/auth/login",
            json={"username": "owner", "password": "wrong-pass"},
        )

        assert blocked.status_code == 429
        assert blocked.headers["Retry-After"] == "30"


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_websocket_proxy_requires_hub_authentication(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        with pytest.raises(WebSocketDisconnect) as caught:
            with client.websocket_connect("/api/ws/chrome"):
                pass

    assert caught.value.code == 4401


def test_websocket_proxy_relays_real_text_and_binary_frames(
    tmp_path: Path,
) -> None:
    upstream_path = ""
    upstream_headers: dict[str, str] = {}

    def echo(connection: ServerConnection) -> None:
        nonlocal upstream_path
        upstream_path = connection.request.path
        upstream_headers.update(connection.request.headers)
        for message in connection:
            connection.send(message)

    with serve(echo, "127.0.0.1", 0) as server:
        port = int(server.socket.getsockname()[1])
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            with _client(tmp_path, runtime_port=port) as client:
                token = _register(client, "owner")
                with client.websocket_connect(
                    "/api/ws/echo?mode=test",
                    headers=_headers(token),
                ) as websocket:
                    websocket.send_text("hello")
                    assert websocket.receive_text() == "hello"
                    websocket.send_bytes(b"binary")
                    assert websocket.receive_bytes() == b"binary"
        finally:
            server.shutdown()
            thread.join(timeout=2)

    assert upstream_path == "/api/ws/echo?mode=test"
    assert upstream_headers["x-qwenpaw-runtime-token"]


def test_websocket_proxy_rejects_unavailable_runtime(tmp_path: Path) -> None:
    with _client(tmp_path, provisioner_available=False) as client:
        token = _register(client, "owner")
        with pytest.raises(WebSocketDisconnect) as caught:
            with client.websocket_connect(
                "/api/ws/chrome",
                headers=_headers(token),
            ):
                pass

    assert caught.value.code == 1013


def test_public_version_does_not_create_runtime(
    hub_client: TestClient,
) -> None:
    response = hub_client.get("/api/version")

    assert response.status_code == 200
    assert response.json() == {"version": __version__}
    assert hub_client.app.state.runtime_service.registry.list() == []


@pytest.mark.asyncio
async def test_slow_auth_status_does_not_block_event_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = threading.Event()
    release = threading.Event()

    with _client(tmp_path) as client:
        auth = client.app.state.auth_service

        def slow_status() -> dict[str, object]:
            started.set()
            release.wait(timeout=2)
            return {"enabled": True}

        monkeypatch.setattr(auth, "status", slow_status)
        transport = httpx.ASGITransport(app=client.app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as async_client:
            blocked = asyncio.create_task(
                async_client.get("/api/auth/status"),
            )
            assert await asyncio.to_thread(started.wait, 1)
            responsive = await asyncio.wait_for(
                async_client.get("/api/version"),
                timeout=0.2,
            )
            release.set()
            status = await blocked

    assert responsive.status_code == 200
    assert status.json() == {"enabled": True}


def test_docker_image_management_is_admin_only(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        admin_token = _register(client, "admin")
        auth = client.app.state.auth_service
        auth.create_user(
            username="member",
            password="safe-password",
            role="user",
        )
        _, member_token = auth.authenticate("member", "safe-password")

        admin_response = client.get(
            "/api/hub/images",
            headers=_headers(admin_token),
        )
        member_response = client.get(
            "/api/hub/images",
            headers=_headers(member_token),
        )

    assert admin_response.status_code == 200
    assert admin_response.json()["available"] is False
    assert member_response.status_code == 403


def test_credential_api_rejects_runtime_control_environment(
    admin_client: tuple[TestClient, str],
) -> None:
    client, token = admin_client
    response = client.put(
        "/api/hub/credentials",
        headers=_headers(token),
        json={
            "scope": "tenant",
            "name": "PYTHONPATH",
            "value": "/",
        },
    )

    assert response.status_code == 400
    assert "reserved by the runtime" in response.json()["detail"]


def test_runtime_create_rejects_backend_overrides(
    admin_client: tuple[TestClient, str],
) -> None:
    client, token = admin_client
    top_level = client.post(
        "/api/hub/runtimes",
        json={"runtime_id": "top-level", "provisioner": "docker"},
        headers=_headers(token),
    )
    metadata = client.post(
        "/api/hub/runtimes",
        json={
            "runtime_id": "metadata",
            "metadata": {"docker": {"image": "attacker/image"}},
        },
        headers=_headers(token),
    )

    assert top_level.status_code == 422
    assert metadata.status_code == 400


def test_console_assets_use_precompression_and_immutable_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    static_dir = tmp_path / "console"
    assets_dir = static_dir / "assets"
    assets_dir.mkdir(parents=True)
    source = b"const product = 'QwenPaw';" * 100
    asset = assets_dir / "index-contenthash.js"
    small_source = b"export const ready = true;"
    small_asset = assets_dir / "small-contenthash.js"
    asset.write_bytes(source)
    small_asset.write_bytes(small_source)
    asset.with_suffix(".js.br").write_bytes(b"brotli-placeholder")
    asset.with_suffix(".js.gz").write_bytes(gzip.compress(source))
    (static_dir / "index.html").write_text(
        "<div id='root'></div>",
        encoding="utf-8",
    )
    monkeypatch.setenv("QWENPAW_CONSOLE_STATIC_DIR", str(static_dir))

    with _client(tmp_path) as client:
        compressed = client.get(
            "/assets/index-contenthash.js",
            headers={"Accept-Encoding": "br;q=0, gzip;q=1"},
        )
        identity = client.get(
            "/assets/index-contenthash.js",
            headers={"Accept-Encoding": "identity"},
        )
        small_fallback = client.get(
            "/assets/small-contenthash.js",
            headers={"Accept-Encoding": "br, gzip"},
        )

    assert compressed.status_code == 200
    assert compressed.content == source
    assert compressed.headers["content-encoding"] == "gzip"
    assert compressed.headers["vary"] == "Accept-Encoding"
    assert "immutable" in compressed.headers["cache-control"]
    assert identity.status_code == 200
    assert identity.content == source
    assert "content-encoding" not in identity.headers
    assert small_fallback.status_code == 200
    assert small_fallback.content == small_source
    assert "content-encoding" not in small_fallback.headers


def test_public_bind_requires_initialized_admin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QWENPAW_HUB_DIR", str(tmp_path))

    with pytest.raises(ValueError, match="initialized, enabled administrator"):
        run_hub_app(
            host="0.0.0.0",
            port=8088,
            log_level="info",
            force_public=True,
        )


def test_public_bind_starts_after_admin_initialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QWENPAW_HUB_DIR", str(tmp_path))
    database = tmp_path / "control.db"
    vault = TenantCredentialVault(
        database,
        tmp_path / "secrets" / ".vault_key",
    )
    HubAuthService(database, vault).register("owner", "safe-password")
    config_path = tmp_path / "hub.yaml"
    config_path.write_text(
        "version: 1\ncontrol_plane:\n"
        "  public_base_url: http://qwenpaw.example.com",
        encoding="utf-8",
    )

    with (
        patch("qwenpaw.hub.control_app.create_hub_app") as create_app,
        patch("qwenpaw.hub.control_app.uvicorn.run") as uvicorn_run,
    ):
        run_hub_app(
            host="::",
            port=8088,
            log_level="info",
            config_path=config_path,
            force_public=True,
        )

    uvicorn_run.assert_called_once()
    assert uvicorn_run.call_args.kwargs["host"] == "::"
    create_app.assert_called_once()


def test_public_bind_requires_public_base_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QWENPAW_HUB_DIR", str(tmp_path))
    database = tmp_path / "control.db"
    vault = TenantCredentialVault(
        database,
        tmp_path / "secrets" / ".vault_key",
    )
    HubAuthService(database, vault).register("owner", "safe-password")

    with pytest.raises(ValueError, match="public_base_url"):
        run_hub_app(
            host="0.0.0.0",
            port=8088,
            log_level="info",
            force_public=True,
        )


def test_unavailable_provisioner_keeps_control_plane_in_safe_mode(
    tmp_path: Path,
) -> None:
    with _client(tmp_path, provisioner_available=False) as client:
        anonymous_health = client.get("/api/hub/healthz")
        token = _register(client, "owner")
        health = client.get(
            "/api/hub/healthz",
            headers=_headers(token),
        )
        created = client.post(
            "/api/hub/runtimes",
            json={"runtime_id": "blocked-runtime"},
            headers=_headers(token),
        )
        proxied = client.get(
            "/api/runtime-probe",
            headers=_headers(token),
        )

        assert anonymous_health.status_code == 401
        assert health.status_code == 200
        assert health.json()["status"] == "degraded"
        assert health.json()["runtime_available"] is False
        assert health.json()["provisioner_statuses"]["local"] == {
            "available": False,
            "reason": "sandbox unavailable",
            "security_level": "isolated-local",
        }
        assert created.status_code == 503
        assert proxied.status_code == 503
        assert client.app.state.runtime_service.registry.list() == []


def test_runtime_ownership_and_admin_user_management(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        admin_token = _register(client, "owner")
        current_settings = client.get(
            "/api/hub/admin/settings",
            headers=_headers(admin_token),
        )
        payload = current_settings.json()
        payload["config"]["control_plane"]["registration"]["enabled"] = True
        settings = client.put(
            "/api/hub/admin/settings",
            json={
                "revision": payload["revision"],
                "config": payload["config"],
            },
            headers=_headers(admin_token),
        )
        assert settings.status_code == 200
        assert settings.json()["revision"] == payload["revision"] + 1
        user_token = _register(client, "member")

        created = client.post(
            "/api/hub/runtimes",
            json={"runtime_id": "admin-runtime"},
            headers=_headers(admin_token),
        )
        assert created.status_code == 201

        forbidden = client.get(
            "/api/hub/runtimes/admin-runtime",
            headers=_headers(user_token),
        )
        assert forbidden.status_code == 404

        own = client.post(
            "/api/hub/runtimes",
            json={"runtime_id": "member-runtime"},
            headers=_headers(user_token),
        )
        assert own.status_code == 201
        user_list = client.get(
            "/api/hub/runtimes",
            headers=_headers(user_token),
        )
        assert [item["runtime_id"] for item in user_list.json()["items"]] == [
            "member-runtime",
        ]
        admin_list = client.get(
            "/api/hub/runtimes",
            headers=_headers(admin_token),
        )
        assert {item["runtime_id"] for item in admin_list.json()["items"]} == {
            "admin-runtime",
            "member-runtime",
        }

        denied_users = client.get(
            "/api/hub/admin/users",
            headers=_headers(user_token),
        )
        assert denied_users.status_code == 403

        current = client.get(
            "/api/hub/me",
            headers=_headers(admin_token),
        )
        user_id = current.json()["user_id"]
        demoted = client.patch(
            f"/api/hub/admin/users/{user_id}",
            json={"role": "user"},
            headers=_headers(admin_token),
        )
        assert demoted.status_code == 409


def test_settings_apply_immediately_and_reject_stale_revision(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as client:
        admin_token = _register(client, "owner")
        current = client.get(
            "/api/hub/admin/settings",
            headers=_headers(admin_token),
        )
        assert current.status_code == 200
        payload = current.json()
        payload["config"]["capacity"] = {
            "max_running_runtimes": 0,
        }

        updated = client.put(
            "/api/hub/admin/settings",
            json={
                "revision": payload["revision"],
                "config": payload["config"],
            },
            headers=_headers(admin_token),
        )
        blocked = client.post(
            "/api/hub/runtimes",
            json={"runtime_id": "over-quota", "auto_start": True},
            headers=_headers(admin_token),
        )
        stale = client.put(
            "/api/hub/admin/settings",
            json={
                "revision": payload["revision"],
                "config": payload["config"],
            },
            headers=_headers(admin_token),
        )

        assert updated.status_code == 200
        assert updated.json()["revision"] == payload["revision"] + 1
        assert blocked.status_code == 409
        assert "runtime limit reached" in blocked.json()["detail"]
        assert stale.status_code == 409
        assert "changed concurrently" in stale.json()["detail"]


def test_credential_api_never_returns_plaintext(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        token = _register(client, "owner")
        response = client.put(
            "/api/hub/credentials",
            json={
                "scope": "tenant",
                "name": "OPENAI_API_KEY",
                "value": "private-value",
            },
            headers=_headers(token),
        )
        assert response.status_code == 204

        listed = client.get(
            "/api/hub/credentials",
            headers=_headers(token),
        )
        assert listed.status_code == 200
        assert listed.json()["items"][0]["name"] == "OPENAI_API_KEY"
        assert "private-value" not in listed.text


def test_standard_api_proxies_to_personal_runtime(tmp_path: Path) -> None:
    async def proxy_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/runtime-probe"
        assert request.headers["X-QwenPaw-Runtime-Token"]
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
            "/api/runtime-probe",
            headers=_headers(token),
        )

        assert response.status_code == 200
        assert response.json() == {"product": "QwenPaw"}
        runtimes = client.get(
            "/api/hub/runtimes",
            headers=_headers(token),
        ).json()
        assert runtimes["total"] == 1
        assert runtimes["items"][0]["state"] == "running"
        assert runtimes["items"][0]["owner_user_id"]
        assert runtimes["items"][0]["metadata"]["hub_default"] is True


def test_runtime_create_rejects_endpoint_overrides(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        token = _register(client, "owner")
        response = client.post(
            "/api/hub/runtimes",
            json={
                "runtime_id": "external-runtime",
                "host": "192.0.2.10",
                "port": 8088,
            },
            headers=_headers(token),
        )

    assert response.status_code == 422


def test_proxy_rejects_non_loopback_runtime_record(tmp_path: Path) -> None:
    calls = 0

    async def proxy_handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        del request
        calls += 1
        return httpx.Response(200, stream=_ProxyStream())

    transport = httpx.MockTransport(proxy_handler)
    with _client(tmp_path, transport) as client:
        token = _register(client, "owner")
        headers = _headers(token)
        assert client.get("/api/probe", headers=headers).status_code == 200
        service = client.app.state.runtime_service
        record = service.registry.list()[0]
        service.registry.save(replace(record, host="192.0.2.10"))

        response = client.get("/api/probe", headers=headers)

    assert response.status_code == 503
    assert "loopback-only" in response.json()["detail"]
    assert calls == 1


def test_proxy_rejects_declared_request_body_over_limit(
    tmp_path: Path,
) -> None:
    called = False

    async def proxy_handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        del request
        called = True
        return httpx.Response(200, stream=_ProxyStream())

    config = HubConfig(
        control_plane=ControlPlaneConfig(
            proxy=RuntimeProxyConfig(max_request_size_mb=1),
        ),
    )
    transport = httpx.MockTransport(proxy_handler)
    with _client(tmp_path, transport, hub_config=config) as client:
        token = _register(client, "owner")
        response = client.post(
            "/api/runtime-probe",
            content=b"x" * (1024 * 1024 + 1),
            headers=_headers(token),
        )

    assert response.status_code == 413
    assert called is False


def test_proxy_times_out_waiting_for_response_headers(
    tmp_path: Path,
) -> None:
    async def proxy_handler(request: httpx.Request) -> httpx.Response:
        await request.aread()
        await asyncio.sleep(0.05)
        return httpx.Response(200, stream=_ProxyStream())

    config = HubConfig(
        control_plane=ControlPlaneConfig(
            proxy=RuntimeProxyConfig(
                response_header_timeout_seconds=0.01,
            ),
        ),
    )
    transport = httpx.MockTransport(proxy_handler)
    with _client(tmp_path, transport, hub_config=config) as client:
        token = _register(client, "owner")
        response = client.post(
            "/api/runtime-probe",
            content=b"request",
            headers=_headers(token),
        )

    assert response.status_code == 504


def test_proxy_does_not_time_out_stream_after_response_headers(
    tmp_path: Path,
) -> None:
    class _SlowResponseStream(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            await asyncio.sleep(0.05)
            yield b"event: complete\n\n"

    async def proxy_handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            stream=_SlowResponseStream(),
            headers={"Content-Type": "text/event-stream"},
        )

    config = HubConfig(
        control_plane=ControlPlaneConfig(
            proxy=RuntimeProxyConfig(
                response_header_timeout_seconds=0.01,
            ),
        ),
    )
    transport = httpx.MockTransport(proxy_handler)
    with _client(tmp_path, transport, hub_config=config) as client:
        token = _register(client, "owner")
        response = client.get(
            "/api/runtime-events",
            headers=_headers(token),
        )

    assert response.status_code == 200
    assert response.text == "event: complete\n\n"


def test_deleted_personal_runtime_is_recreated_on_next_proxy(
    tmp_path: Path,
) -> None:
    async def proxy_handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, stream=_ProxyStream())

    transport = httpx.MockTransport(proxy_handler)
    with _client(tmp_path, transport) as client:
        admin_token = _register(client, "owner")
        member, member_token = _create_user(client, "member")
        member_headers = _headers(member_token)
        assert (
            client.get("/api/probe", headers=member_headers).status_code == 200
        )
        runtime_id = f"personal-{member.user_id[:24]}"
        original = client.app.state.runtime_service.get(runtime_id)
        marker = original.working_dir / "retained.txt"
        marker.write_text("retained", encoding="utf-8")

        stopped = client.post(
            f"/api/hub/runtimes/{runtime_id}/stop",
            headers=_headers(admin_token),
        )
        deleted = client.delete(
            f"/api/hub/runtimes/{runtime_id}",
            headers=_headers(admin_token),
        )
        recreated_response = client.get("/api/probe", headers=member_headers)
        recreated = client.app.state.runtime_service.get(runtime_id)

        assert stopped.status_code == 200
        assert deleted.status_code == 204
        assert recreated_response.status_code == 200
        assert recreated.runtime_id == runtime_id
        assert recreated.owner_user_id == member.user_id
        assert recreated.state is RuntimeState.RUNNING
        assert marker.read_text(encoding="utf-8") == "retained"


def test_proxy_closes_upstream_client_when_request_disconnects(
    tmp_path: Path,
) -> None:
    class _DisconnectingClient:
        closed = False

        def build_request(self, *_: object, **__: object) -> object:
            return object()

        async def send(self, *_: object, **__: object) -> None:
            raise ClientDisconnect()

        async def aclose(self) -> None:
            self.closed = True

    upstream_client = _DisconnectingClient()
    with _client(tmp_path) as client:
        token = _register(client, "owner")
        with (
            patch(
                "qwenpaw.hub.control_app.httpx.AsyncClient",
                return_value=upstream_client,
            ),
            pytest.raises(ClientDisconnect),
        ):
            client.post(
                "/api/runtime-probe",
                content=b"partial request",
                headers=_headers(token),
            )

    assert upstream_client.closed is True


def test_authenticated_user_changes_only_their_password(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as client:
        old_token = _register(client, "owner")

        changed = client.post(
            "/api/hub/me/password",
            json={"new_password": "new-safe-password"},
            headers=_headers(old_token),
        )

        assert changed.status_code == 200
        assert changed.json()["username"] == "owner"
        assert "token" not in changed.json()
        assert (
            client.get(
                "/api/hub/me",
                headers=_headers(old_token),
            ).status_code
            == 401
        )
        login = client.post(
            "/api/auth/login",
            json={
                "username": "owner",
                "password": "new-safe-password",
            },
        )
        assert login.status_code == 200
        new_token = login.json()["token"]
        assert (
            client.get(
                "/api/hub/me",
                headers=_headers(new_token),
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/auth/login",
                json={"username": "owner", "password": "safe-password"},
            ).status_code
            == 401
        )
        assert (
            client.post(
                "/api/auth/login",
                json={
                    "username": "owner",
                    "password": "new-safe-password",
                },
            ).status_code
            == 200
        )


def test_authenticated_user_restarts_only_their_personal_runtime(
    tmp_path: Path,
) -> None:
    async def proxy_handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, stream=_ProxyStream())

    with _client(tmp_path, httpx.MockTransport(proxy_handler)) as client:
        admin_token = _register(client, "owner")
        member, member_token = _create_user(client, "member")
        client.get("/api/probe", headers=_headers(admin_token))
        client.get("/api/probe", headers=_headers(member_token))

        restarted = client.post(
            "/api/hub/me/runtime/restart",
            headers=_headers(member_token),
        )
        audit = client.get(
            "/api/hub/admin/audit?action=runtime.restart",
            headers=_headers(admin_token),
        )

        assert restarted.status_code == 200
        assert restarted.json()["owner_user_id"] == member.user_id
        assert restarted.json()["runtime_id"].startswith(
            f"personal-{member.user_id[:24]}",
        )
        assert audit.status_code == 200
        assert audit.json()["total"] == 1
        assert audit.json()["items"][0]["actor_user_id"] == member.user_id


def test_admin_stop_and_disable_have_distinct_owner_recovery(
    tmp_path: Path,
) -> None:
    async def proxy_handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, stream=_ProxyStream())

    with _client(tmp_path, httpx.MockTransport(proxy_handler)) as client:
        admin_token = _register(client, "owner")
        member, member_token = _create_user(client, "member")
        member_headers = _headers(member_token)
        assert (
            client.get("/api/probe", headers=member_headers).status_code == 200
        )
        runtime_id = f"personal-{member.user_id[:24]}"

        stopped = client.post(
            f"/api/hub/runtimes/{runtime_id}/stop",
            headers=_headers(admin_token),
        )
        health = client.get("/api/hub/healthz", headers=member_headers)
        blocked_proxy = client.get("/api/probe", headers=member_headers)

        assert stopped.status_code == 200
        assert stopped.json()["desired_state"] == "stopped"
        assert stopped.json()["start_policy"] == "owner_allowed"
        assert health.json()["runtime_desired_state"] == "stopped"
        assert health.json()["runtime_start_policy"] == "owner_allowed"
        assert blocked_proxy.status_code == 423
        assert (
            client.app.state.runtime_service.get(
                runtime_id,
            ).state
            is RuntimeState.STOPPED
        )

        restarted = client.post(
            "/api/hub/me/runtime/restart",
            headers=member_headers,
        )
        assert restarted.status_code == 200
        assert restarted.json()["state"] == "running"

        disabled = client.post(
            f"/api/hub/runtimes/{runtime_id}/disable",
            headers=_headers(admin_token),
        )
        denied_delete = client.delete(
            f"/api/hub/runtimes/{runtime_id}",
            headers=member_headers,
        )
        retained = client.get(
            f"/api/hub/runtimes/{runtime_id}",
            headers=member_headers,
        )
        denied_restart = client.post(
            "/api/hub/me/runtime/restart",
            headers=member_headers,
        )
        denied_start = client.post(
            f"/api/hub/runtimes/{runtime_id}/start",
            headers=member_headers,
        )

        assert disabled.status_code == 200
        assert disabled.json()["start_policy"] == "admin_only"
        assert denied_delete.status_code == 403
        assert retained.status_code == 200
        assert retained.json()["start_policy"] == "admin_only"
        assert denied_restart.status_code == 423
        assert denied_start.status_code == 403

        enabled = client.post(
            f"/api/hub/runtimes/{runtime_id}/start",
            headers=_headers(admin_token),
        )
        assert enabled.status_code == 200
        assert enabled.json()["start_policy"] == "owner_allowed"
        assert (
            client.get("/api/probe", headers=member_headers).status_code == 200
        )
        assert (
            client.post(
                f"/api/hub/runtimes/{runtime_id}/stop",
                headers=_headers(admin_token),
            ).status_code
            == 200
        )
        assert (
            client.delete(
                f"/api/hub/runtimes/{runtime_id}",
                headers=_headers(admin_token),
            ).status_code
            == 204
        )


def test_hub_lists_use_server_side_pagination_and_filters(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as client:
        token = _register(client, "owner")
        auth = client.app.state.auth_service
        for index in range(4):
            runtime_token = token
            if index:
                username = f"member-{index}"
                auth.create_user(
                    username=username,
                    password="safe-password",
                )
                _, runtime_token = auth.authenticate(
                    username,
                    "safe-password",
                )
            created = client.post(
                "/api/hub/runtimes",
                json={"runtime_id": f"runtime-{index}"},
                headers=_headers(runtime_token),
            )
            assert created.status_code == 201
        client.post(
            "/api/hub/runtimes/runtime-3/start",
            headers=_headers(token),
        )

        page = client.get(
            "/api/hub/runtimes?page=2&page_size=2",
            headers=_headers(token),
        )
        filtered = client.get(
            "/api/hub/runtimes?q=runtime-3&state=running",
            headers=_headers(token),
        )

        assert page.status_code == 200
        assert page.json()["total"] == 4
        assert page.json()["pages"] == 2
        assert len(page.json()["items"]) == 2
        assert filtered.json()["total"] == 1
        assert filtered.json()["items"][0]["runtime_id"] == "runtime-3"
        assert filtered.json()["items"][0]["owner_username"] == "member-3"

        username_search = client.get(
            "/api/hub/runtimes?q=owner",
            headers=_headers(token),
        )
        username_filter = client.get(
            "/api/hub/runtimes?owner=owner",
            headers=_headers(token),
        )

        assert username_search.status_code == 200
        assert username_search.json()["total"] == 1
        assert username_filter.status_code == 200
        assert username_filter.json()["total"] == 1


def test_deleted_runtime_owner_returns_no_username(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        admin_token = _register(client, "owner")
        auth = client.app.state.auth_service
        member, member_token = _create_user(client, "former-member")
        created = client.post(
            "/api/hub/runtimes",
            json={"runtime_id": "orphaned-runtime"},
            headers=_headers(member_token),
        )
        with sqlite3.connect(auth.database_path) as connection:
            connection.execute(
                "UPDATE hub_users SET deleted_at = ? WHERE user_id = ?",
                ("2026-01-01T00:00:00Z", member.user_id),
            )
        runtimes = client.get(
            "/api/hub/runtimes?q=orphaned-runtime",
            headers=_headers(admin_token),
        )

    assert created.status_code == 201
    assert created.json()["owner_username"] == "former-member"
    assert runtimes.status_code == 200
    assert runtimes.json()["items"][0]["owner_username"] is None


def test_operations_overview_and_audit_are_real_and_sanitized(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as client:
        token = _register(client, "owner")
        stored = client.put(
            "/api/hub/credentials",
            json={
                "scope": "tenant",
                "name": "OPENAI_API_KEY",
                "value": "must-never-be-audited",
            },
            headers=_headers(token),
        )
        created = client.post(
            "/api/hub/runtimes",
            json={"runtime_id": "audited-runtime"},
            headers=_headers(token),
        )

        overview = client.get(
            "/api/hub/admin/overview",
            headers=_headers(token),
        )
        audit = client.get(
            "/api/hub/admin/audit?page_size=10",
            headers=_headers(token),
        )

        assert stored.status_code == 204
        assert created.status_code == 201
        assert overview.status_code == 200
        assert overview.json()["total_runtimes"] == 1
        assert overview.json()["runtime_counts"]["created"] == 1
        assert overview.json()["total_users"] == 1
        assert set(overview.json()["host"]) == {
            "cpu_percent",
            "memory_percent",
            "disk_percent",
        }
        assert audit.status_code == 200
        assert audit.json()["total"] == 3
        assert "must-never-be-audited" not in audit.text
        assert {event["action"] for event in audit.json()["items"]} == {
            "auth.register",
            "credential.store",
            "runtime.create",
        }


@pytest.mark.parametrize(
    ("start_path", "callback_path"),
    [
        (
            "/api/providers/openrouter/oauth/start",
            "/api/providers/openrouter/oauth/callback",
        ),
        (
            "/api/agents/default/mcp/oauth/start/test-client",
            "/api/mcp/oauth/callback",
        ),
    ],
)
def test_oauth_callback_route_is_stable_and_runtime_scoped(
    tmp_path: Path,
    start_path: str,
    callback_path: str,
) -> None:
    callback_urls: list[str] = []

    async def proxy_handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            callback_url = request.headers["X-QwenPaw-Hub-OAuth-Callback-Url"]
            callback_urls.append(callback_url)
            assert callback_url.startswith(
                "https://qwenpaw.example.com/base/",
            )
            assert callback_url != "https://attacker.example/callback"
            return httpx.Response(
                200,
                stream=_ProxyStream(),
                headers={"Content-Type": "application/json"},
            )
        assert request.url.path == callback_path
        assert request.url.query == b"code=code-value&state=state-value"
        assert request.headers["X-QwenPaw-Runtime-Token"]
        return httpx.Response(
            200,
            text="callback complete",
            headers={"Content-Type": "text/html"},
        )

    config = HubConfig(
        control_plane=ControlPlaneConfig(
            public_base_url="https://qwenpaw.example.com/base",
        ),
    )
    transport = httpx.MockTransport(proxy_handler)
    with _client(tmp_path, transport, hub_config=config) as client:
        token = _register(client, "owner")
        started = client.post(
            start_path,
            headers={
                **_headers(token),
                "X-QwenPaw-Hub-OAuth-Callback-Url": (
                    "https://attacker.example/callback"
                ),
            },
        )
        assert started.status_code == 200

        relay_url = urlsplit(callback_urls[0])
        relay_path = relay_url.path.removeprefix("/base")
        assert "personal-" in relay_path
        callback = client.get(
            f"{relay_path}?code=code-value&state=state-value",
        )
        repeated = client.get(
            f"{relay_path}?code=code-value&state=state-value",
        )

        assert callback.status_code == 200
        assert callback.text == "callback complete"
        assert repeated.status_code == 200


def test_regular_runtime_callback_still_requires_login(
    hub_client: TestClient,
) -> None:
    response = hub_client.get(
        "/api/providers/openrouter/oauth/callback",
        params={"code": "value"},
    )

    assert response.status_code == 401
