# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
"""Password connection persistence, replacement and owner boundaries."""

import asyncio
import json
import os
import time

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from starlette.requests import Request

from qwenpaw.app import community_credentials as credentials
from qwenpaw.app import community_store as store
from qwenpaw.app.community_connection import (
    CommunityConnectionError,
    CommunityConnectionService,
)
from qwenpaw.app.routers.community_connection import (
    password_login_allowed,
    router,
)
from qwenpaw.envs import store as env_store
from qwenpaw.security import secret_store


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_STATE_PATH", tmp_path / "community.json")
    monkeypatch.setattr(store, "_LOCK", asyncio.Lock())
    monkeypatch.setattr(
        credentials,
        "_CREDENTIAL_PATH",
        tmp_path / "secrets" / "community_credentials.json",
    )
    monkeypatch.setattr(
        env_store,
        "_BOOTSTRAP_SECRET_DIR",
        tmp_path / "secrets",
    )
    monkeypatch.setattr(env_store, "_ENVS_JSON", tmp_path / "envs.json")
    monkeypatch.setattr(env_store, "_LEGACY_ENVS_JSON_CANDIDATES", ())
    monkeypatch.setattr(
        secret_store,
        "_cached_fernet",
        Fernet(Fernet.generate_key()),
    )
    for key in (
        "QWENPAW_COMMUNITY_ACCOUNT",
        "QWENPAW_COMMUNITY_PASSWORD",
        "QWENPAW_COMMUNITY_CREDENTIAL_STATE",
        "QWENPAW_RUNTIME_INTERNAL_TOKEN",
    ):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def requests():
    return []


@pytest.fixture
def service(requests):
    def handler(request):
        requests.append(request)
        if request.url.path.endswith("/me"):
            return httpx.Response(
                200,
                json={"user_id": "alice", "username": "Alice"},
            )
        if request.url.path.endswith("/login"):
            body = json.loads(request.content)
            if body["password"] == "wrong":
                return httpx.Response(
                    401,
                    json={"detail": "unsafe upstream detail"},
                )
        if request.url.path.endswith("/revoke"):
            return httpx.Response(200, json={})
        return httpx.Response(
            200,
            json={
                "access_token": "access-secret",
                "refresh_token": "refresh-secret",
                "expires_in": 3600,
            },
        )

    return CommunityConnectionService(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_saved_once_encrypted_and_hidden_from_env_tools(service):
    await service.connect_password("alice@example.com", "password-secret")
    raw = credentials._CREDENTIAL_PATH.read_text()
    assert "password-secret" not in raw
    assert "alice@example.com" not in raw
    assert json.loads(raw)["payload"].startswith("ENC:")
    assert credentials.load()["password"] == "password-secret"
    assert "QWENPAW_COMMUNITY_PASSWORD" not in env_store.load_envs()
    assert "QWENPAW_COMMUNITY_PASSWORD" not in os.environ
    assert "QWENPAW_COMMUNITY_PASSWORD" not in env_store.update_env_vars(
        {"EXAMPLE": "value"},
    )
    env_store.save_envs({})
    assert credentials.load()["password"] == "password-secret"
    status = await service.status(local=False, password_allowed=True)
    assert status["saved_account"] == "alice@example.com"
    assert status["password_saved"]
    assert "password-secret" not in json.dumps(status)
    assert "access-secret" not in json.dumps(status)


@pytest.mark.asyncio
async def test_invalid_replacement_preserves_old_connection_and_password(
    service,
):
    await service.connect_password("alice@example.com", "first-secret")
    before = await store.get_connection()
    with pytest.raises(CommunityConnectionError, match="credentials_rejected"):
        await service.connect_password("bob@example.com", "wrong")
    assert await store.get_connection() == before
    assert credentials.load()["account"] == "alice@example.com"
    assert credentials.load()["password"] == "first-secret"
    await service.connect_password("alice@example.com", "second-secret")
    assert credentials.load()["password"] == "second-secret"


@pytest.mark.asyncio
async def test_blank_password_only_reuses_same_account(service, requests):
    await service.connect_password("alice@example.com", "first-secret")
    await service.connect_password("alice@example.com", "")
    login = [r for r in requests if r.url.path.endswith("/login")][-1]
    assert json.loads(login.content)["password"] == "first-secret"
    with pytest.raises(CommunityConnectionError, match="credentials_required"):
        await service.connect_password("bob@example.com", "")


@pytest.mark.asyncio
async def test_restart_and_disconnect_pause_survive_new_service(
    service,
    requests,
):
    credentials.save("alice@example.com", "first-secret")
    await service.ensure_password_connection()
    assert (await store.get_connection())["account_id"] == "alice"
    await service.disconnect()
    assert credentials.load()["state"] == "paused"
    restarted = CommunityConnectionService(transport=service._transport)
    count = len(requests)
    await restarted.ensure_password_connection()
    assert len(requests) == count
    assert await store.get_connection() is None
    await restarted.connect_password("alice@example.com", "")
    assert (await store.get_connection())["account_id"] == "alice"


@pytest.mark.asyncio
async def test_refresh_is_preferred_and_password_recovers_rejected_refresh(
    service,
    requests,
):
    await service.connect_password("alice@example.com", "first-secret")
    connection = await store.get_connection()
    connection["expires_at"] = time.time() - 1
    await store.save_connection(connection)
    requests.clear()
    await service._fresh_connection()
    assert not any(r.url.path.endswith("/login") for r in requests)
    previous_handler = service._transport.handler

    def reject_refresh(request):
        if request.url.path.endswith("/refresh"):
            return httpx.Response(401)
        return previous_handler(request)

    service._transport = httpx.MockTransport(reject_refresh)
    refreshed = await service._fresh_connection(force_refresh=True)
    assert refreshed["connection_id"] == connection["connection_id"]
    assert any(r.url.path.endswith("/login") for r in requests)


@pytest.mark.asyncio
async def test_bad_saved_password_stops_retries(service, requests):
    credentials.save("alice@example.com", "wrong")
    with pytest.raises(CommunityConnectionError, match="credentials_rejected"):
        await service.ensure_password_connection()
    assert credentials.load()["state"] == "rejected"
    count = len(requests)
    await service.ensure_password_connection()
    assert len(requests) == count


@pytest.mark.asyncio
async def test_deployment_credentials_are_never_used(
    service,
    monkeypatch,
    requests,
):
    monkeypatch.setenv(
        "QWENPAW_COMMUNITY_ACCOUNT",
        "alice@example.com",
    )
    monkeypatch.setenv("QWENPAW_COMMUNITY_PASSWORD", "env-password")
    assert not credentials.load()["password"]
    await service.ensure_password_connection()
    assert not requests
    await service.clear_credentials()
    assert not credentials.load()["password"]
    await service.ensure_password_connection()
    assert await store.get_connection() is None


@pytest.mark.asyncio
async def test_disconnect_wins_over_pending_password_login(service):
    entered, release = asyncio.Event(), asyncio.Event()
    previous_handler = service._transport.handler

    async def slow(request):
        if request.url.path.endswith("/login"):
            entered.set()
            await release.wait()
        return previous_handler(request)

    service._transport = httpx.MockTransport(slow)
    pending = asyncio.create_task(
        service.connect_password("alice@example.com", "secret"),
    )
    await entered.wait()
    await service.disconnect()
    release.set()
    with pytest.raises(CommunityConnectionError, match="connection_changed"):
        await pending
    assert await store.get_connection() is None
    assert not credentials.load()["password"]


def owner_request(
    *,
    scheme="https",
    authenticated=True,
    origin=None,
    headers=(),
):
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/community/connection/password",
            "scheme": scheme,
            "server": ("qwenpaw.example", 443 if scheme == "https" else 80),
            "client": ("192.0.2.5", 1234),
            "headers": [
                (b"host", b"qwenpaw.example"),
                *headers,
                *([(b"origin", origin.encode())] if origin else []),
            ],
            "state": {"user": "owner"} if authenticated else {},
        },
    )


def test_remote_login_requires_https_owner_and_same_origin(monkeypatch):
    assert password_login_allowed(
        owner_request(origin="https://qwenpaw.example"),
    )
    assert not password_login_allowed(owner_request(authenticated=False))
    assert not password_login_allowed(owner_request(scheme="http"))
    assert not password_login_allowed(
        owner_request(origin="https://evil.example"),
    )
    monkeypatch.setenv("QWENPAW_RUNTIME_INTERNAL_TOKEN", "boundary-secret")
    assert not password_login_allowed(owner_request())
    assert not password_login_allowed(
        owner_request(
            authenticated=False,
            headers=[(b"x-qwenpaw-runtime-token", b"boundary-secret")],
        ),
    )


@pytest.mark.asyncio
async def test_router_validation_never_echoes_secret(service):
    app = FastAPI()
    app.include_router(router)
    app.state.community_connection_service = service
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 123)),
        base_url="http://localhost",
    ) as client:
        bad = await client.post(
            "/community/connection/password",
            json={"password": "do-not-echo"},
        )
        assert bad.status_code == 422
        assert "do-not-echo" not in bad.text
        response = await client.post(
            "/community/connection/password",
            json={
                "account": "alice@example.com",
                "password": "valid-secret",
            },
        )
        assert response.status_code == 200
        assert response.json() == {"connected": True}
        status = await client.get("/community/connection")
        assert status.json()["password_saved"]
        assert "valid-secret" not in status.text


@pytest.mark.asyncio
async def test_network_failure_keeps_old_credentials_and_allows_later_retry(
    service,
):
    await service.connect_password("alice@example.com", "first-secret")
    previous = await store.get_connection()

    def offline(request):
        raise httpx.ConnectError("network unavailable", request=request)

    service._transport = httpx.MockTransport(offline)
    with pytest.raises(CommunityConnectionError, match="network_unavailable"):
        await service.connect_password("alice@example.com", "replacement")
    assert credentials.load()["password"] == "first-secret"
    assert credentials.load()["state"] == "active"
    assert await store.get_connection() == previous


@pytest.mark.asyncio
async def test_replacement_preserves_preferences_and_restart_reuses_tokens(
    service,
    requests,
):
    await service.connect_password("alice@example.com", "first-secret")
    await service.set_sync(False, ["comments"])
    await service.connect_password("alice@example.com", "replacement")
    current = await store.get_connection()
    assert current["sync_enabled"] is False
    assert current["message_types"] == ["comments"]
    restarted = CommunityConnectionService(transport=service._transport)
    requests.clear()
    await restarted.ensure_password_connection()
    assert not requests
    assert await store.get_connection() == current


@pytest.mark.asyncio
async def test_generic_env_api_hides_and_preserves_saved_password(service):
    from qwenpaw.app.routers.envs import router as env_router

    await service.connect_password("alice@example.com", "first-secret")
    app = FastAPI()
    app.include_router(env_router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://localhost",
    ) as client:
        for method, path, body in [
            ("GET", "/envs", None),
            ("GET", "/envs/catalog", None),
            ("PUT", "/envs", {}),
        ]:
            response = await client.request(method, path, json=body)
            assert response.status_code == 200
            assert "QWENPAW_COMMUNITY_PASSWORD" not in response.text
            assert "first-secret" not in response.text
        assert credentials.load()["password"] == "first-secret"


def test_password_with_encryption_prefix_is_still_encrypted():
    credentials.save("alice@example.com", "ENC:literal-password")
    env_store.save_envs({})
    assert (
        "ENC:literal-password" not in credentials._CREDENTIAL_PATH.read_text()
    )
    assert credentials.load()["password"] == "ENC:literal-password"


def test_lost_key_never_sends_ciphertext_and_allows_replacement(monkeypatch):
    credentials.save("alice@example.com", "first-secret")
    monkeypatch.setattr(
        secret_store,
        "_cached_fernet",
        Fernet(Fernet.generate_key()),
    )
    assert credentials.load()["state"] == "unreadable"
    assert credentials.load()["password"] == ""
    credentials.save("alice@example.com", "replacement")
    assert credentials.load()["password"] == "replacement"


@pytest.mark.asyncio
async def test_managed_runtime_can_save_pause_clear_and_stop_rejected_retries(
    service,
    monkeypatch,
    requests,
):
    monkeypatch.setenv("QWENPAW_RUNTIME_ID", "test-managed-runtime")
    await service.connect_password("alice@example.com", "password-secret")
    assert credentials.load()["password"] == "password-secret"
    await service.disconnect()
    assert credentials.load()["state"] == "paused"
    await service.clear_credentials()
    assert not credentials.load()["password"]
    credentials.save("alice@example.com", "wrong")
    with pytest.raises(CommunityConnectionError, match="credentials_rejected"):
        await service.ensure_password_connection()
    count = len(requests)
    await service.ensure_password_connection()
    assert len(requests) == count
    assert credentials.load()["state"] == "rejected"


@pytest.mark.asyncio
async def test_saved_credentials_are_not_inherited_by_tool_processes(tmp_path):
    from qwenpaw.sandbox.config import SandboxConfig, SandboxMode
    from qwenpaw.sandbox.local_sandbox import NoneSandbox

    credentials.save("test@example.invalid", "saved-password-secret")
    env_store.load_envs_into_environ()
    assert "QWENPAW_COMMUNITY_PASSWORD" not in os.environ
    assert "QWENPAW_COMMUNITY_ACCOUNT" not in os.environ
    result = await NoneSandbox(
        SandboxConfig(mode=SandboxMode.NONE, workspace_dir=str(tmp_path)),
    ).execute(
        "python -c \"import os; print('LEAK' if 'QWENPAW_COMMUNITY_PASSWORD' in os.environ else 'CLEAN')\"",
    )
    assert result.exit_code == 0
    assert result.stdout.strip() == "CLEAN"
    assert credentials.load()["password"] == "saved-password-secret"


def test_credential_and_key_files_are_guarded(monkeypatch):
    from qwenpaw.constant import SECRET_DIR
    from qwenpaw.security.tool_guard.guardians import file_guardian

    monkeypatch.setattr(file_guardian, "_is_file_guard_enabled", lambda: True)
    guardian = file_guardian.FilePathToolGuardian()
    for name in ("community_credentials.json", ".master_key"):
        path = str(SECRET_DIR / name)
        assert guardian.guard("read_file", {"file_path": path})
        assert guardian.guard(
            "execute_shell_command",
            {"command": f'cat "{path}"'},
        )


def test_private_file_permissions_and_clear_remove_saved_ciphertext():
    import stat

    credentials.save("alice@example.com", "password-secret")
    path = credentials._CREDENTIAL_PATH
    before = path.read_text()
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    credentials.clear()
    assert path.read_text() != before
    payload = json.loads(
        secret_store.decrypt(json.loads(path.read_text())["payload"]),
    )
    assert payload["password"] == ""
    assert payload["account"] == ""


@pytest.mark.skipif(
    os.name == "nt",
    reason="Symlink creation requires Windows privileges",
)
def test_credential_symlink_is_rejected(tmp_path):
    target = tmp_path / "target"
    target.write_text("untouched")
    path = credentials._CREDENTIAL_PATH
    path.parent.mkdir()
    path.symlink_to(target)
    assert credentials.load()["state"] == "unreadable"
    with pytest.raises(OSError):
        credentials.save("alice", "secret")
    assert target.read_text() == "untouched"


@pytest.mark.asyncio
async def test_standalone_proxy_uses_production_middleware(
    service,
    monkeypatch,
):
    from types import SimpleNamespace
    from qwenpaw.app import auth
    from qwenpaw.app._app import app as production_app

    monkeypatch.setattr(auth, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(auth, "has_registered_users", lambda: True)
    monkeypatch.setattr(
        auth,
        "verify_token",
        lambda token: "owner" if token == "valid" else None,
    )
    networks = auth._parse_networks(["127.0.0.1/32"])
    monkeypatch.setattr(
        auth,
        "_get_config_cached",
        lambda: (
            SimpleNamespace(security=SimpleNamespace(allow_no_auth_hosts=[])),
            networks,
        ),
    )
    app = FastAPI(middleware=production_app.user_middleware)
    app.include_router(router, prefix="/api")
    app.state.community_connection_service = service
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 12345)),
        base_url="http://public.example",
    ) as client:
        headers = {
            "Authorization": "Bearer valid",
            "Origin": "https://public.example",
            "X-Forwarded-Proto": "https",
        }
        body = {"account": "alice@example.com", "password": "valid-secret"}
        response = await client.post(
            "/api/community/connection/password",
            headers=headers,
            json=body,
        )
        assert response.status_code == 200
        networks.clear()
        denied = await client.post(
            "/api/community/connection/password",
            headers=headers,
            json=body,
        )
        assert denied.status_code == 403


def test_hub_origin_requires_boundary_and_rejects_pawapp_scope(monkeypatch):
    from qwenpaw.utils.public_origin import HUB_PUBLIC_ORIGIN_HEADER
    from qwenpaw.plugins.browser_access import PAWAPP_SCOPE_HEADER

    extra = [
        (HUB_PUBLIC_ORIGIN_HEADER.lower().encode(), b"https://public.example"),
    ]
    assert not password_login_allowed(
        owner_request(scheme="http", headers=extra),
    )
    monkeypatch.setenv("QWENPAW_RUNTIME_INTERNAL_TOKEN", "boundary")
    assert not password_login_allowed(
        owner_request(scheme="http", headers=extra),
    )
    extra.append((b"x-qwenpaw-runtime-token", b"boundary"))
    assert password_login_allowed(
        owner_request(
            scheme="http",
            authenticated=False,
            origin="https://public.example",
            headers=extra,
        ),
    )
    assert not password_login_allowed(
        owner_request(
            scheme="http",
            origin="https://evil.example",
            headers=extra,
        ),
    )
    extra.append((PAWAPP_SCOPE_HEADER.lower().encode(), b"some-app"))
    assert not password_login_allowed(
        owner_request(
            scheme="http",
            origin="https://public.example",
            headers=extra,
        ),
    )


@pytest.mark.parametrize(
    "value",
    [
        "http://public.example",
        "https://user@public.example",
        "https://public.example/path",
        "https://public.example?x=1",
        "https://public.example#x",
        "https://public.example\r\n",
        "https://[broken",
    ],
)
def test_invalid_hub_origin_is_rejected(monkeypatch, value):
    from qwenpaw.utils.public_origin import HUB_PUBLIC_ORIGIN_HEADER

    monkeypatch.setenv("QWENPAW_RUNTIME_INTERNAL_TOKEN", "boundary")
    assert not password_login_allowed(
        owner_request(
            scheme="http",
            origin="https://public.example",
            headers=[
                (b"x-qwenpaw-runtime-token", b"boundary"),
                (HUB_PUBLIC_ORIGIN_HEADER.lower().encode(), value.encode()),
            ],
        ),
    )
