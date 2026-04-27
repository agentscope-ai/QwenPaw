# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument,protected-access
"""Unit tests for CopilotOAuthService — device flow, polling, refresh.

Network is fully mocked via a fake ``httpx.AsyncClient`` factory so the
tests are deterministic and offline.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Callable, Dict, List

import httpx
import pytest

import qwenpaw.constant as constant_module
from qwenpaw.providers.oauth.copilot_oauth_service import (
    COPILOT_TOKEN_URL,
    CopilotOAuthError,
    CopilotOAuthService,
    GITHUB_DEVICE_CODE_URL,
    GITHUB_TOKEN_URL,
    GITHUB_USER_URL,
)
from qwenpaw.providers.oauth.copilot_token_store import CopilotTokenStore


@pytest.fixture
def secret_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    monkeypatch.setattr(constant_module, "SECRET_DIR", tmp_path)
    return tmp_path


def _make_mock_transport(
    handlers: Dict[tuple[str, str], Callable[[httpx.Request], httpx.Response]],
) -> httpx.MockTransport:
    """Build an httpx MockTransport that dispatches by (METHOD, URL)."""

    def handler(request: httpx.Request) -> httpx.Response:
        key = (request.method, str(request.url).split("?", 1)[0])
        if key in handlers:
            return handlers[key](request)
        return httpx.Response(404, json={"error": "no handler"})

    return httpx.MockTransport(handler)


def _service_with_handlers(
    handlers: Dict[tuple[str, str], Callable[[httpx.Request], httpx.Response]],
    *,
    provider_id: str = "github-copilot",
    token_refresh_buffer: int = 30,
) -> CopilotOAuthService:
    transport = _make_mock_transport(handlers)
    return CopilotOAuthService(
        provider_id=provider_id,
        token_store=CopilotTokenStore(provider_id),
        http_client_factory=lambda: httpx.AsyncClient(transport=transport),
        token_refresh_buffer=token_refresh_buffer,
    )


async def test_start_device_flow_returns_user_code(secret_dir: Path) -> None:
    handlers = {
        ("POST", GITHUB_DEVICE_CODE_URL): lambda req: httpx.Response(
            200,
            json={
                "device_code": "dev-abc",
                "user_code": "ABCD-1234",
                "verification_uri": "https://github.com/login/device",
                "expires_in": 900,
                "interval": 5,
            },
        ),
        # Loop will poll once after starting; respond pending to avoid
        # finishing the flow during the test.
        ("POST", GITHUB_TOKEN_URL): lambda req: httpx.Response(
            200,
            json={"error": "authorization_pending"},
        ),
    }
    service = _service_with_handlers(handlers)
    try:
        result = await service.start_device_flow()
        assert result.user_code == "ABCD-1234"
        assert result.verification_uri.startswith("https://github.com/")
        assert result.interval == 5
        assert result.expires_in == 900
        status = await service.get_status()
        assert status.status == "pending"
        assert status.is_authenticated is False
    finally:
        await service.logout()


async def test_full_device_flow_to_authorized(secret_dir: Path) -> None:
    """Simulate: device code → one pending → access_token → copilot token."""
    state = {"poll_count": 0}

    def device_code_handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "device_code": "dev-xyz",
                "user_code": "WXYZ-0000",
                "verification_uri": "https://github.com/login/device",
                "expires_in": 60,
                "interval": 1,
            },
        )

    def token_handler(req: httpx.Request) -> httpx.Response:
        state["poll_count"] += 1
        if state["poll_count"] == 1:
            return httpx.Response(
                200,
                json={"error": "authorization_pending"},
            )
        return httpx.Response(
            200,
            json={
                "access_token": "gho_test_oauth_token",
                "token_type": "bearer",
                "scope": "read:user",
            },
        )

    def user_handler(req: httpx.Request) -> httpx.Response:
        # Verify the OAuth header uses lowercase "token", not "Bearer".
        auth = req.headers.get("authorization", "")
        assert auth.startswith("token "), auth
        return httpx.Response(200, json={"login": "octocat"})

    def copilot_token_handler(req: httpx.Request) -> httpx.Response:
        # CRITICAL: token-exchange auth header MUST be "token <oauth>".
        auth = req.headers.get("authorization", "")
        assert auth.startswith("token "), auth
        # And editor headers MUST be present.
        assert req.headers.get("editor-version")
        assert req.headers.get("editor-plugin-version")
        return httpx.Response(
            200,
            json={
                "token": "tid=abc;exp=99999",
                "expires_at": int(time.time()) + 1800,
                "refresh_in": 1500,
                "endpoints": {"api": "https://api.githubcopilot.com"},
                "chat_enabled": True,
                "sku": "free",
            },
        )

    handlers = {
        ("POST", GITHUB_DEVICE_CODE_URL): device_code_handler,
        ("POST", GITHUB_TOKEN_URL): token_handler,
        ("GET", GITHUB_USER_URL): user_handler,
        ("GET", COPILOT_TOKEN_URL): copilot_token_handler,
    }
    service = _service_with_handlers(handlers)
    try:
        await service.start_device_flow()
        # Wait for the polling loop to reach "authorized".
        for _ in range(100):
            status = await service.get_status()
            if status.is_authenticated:
                break
            await asyncio.sleep(0.05)
        assert status.is_authenticated
        assert status.login == "octocat"
        assert service.oauth_access_token == "gho_test_oauth_token"
        token = await service.get_copilot_token()
        assert token == "tid=abc;exp=99999"
        # Token persisted to disk.
        assert service.token_store.load() is not None
    finally:
        await service.logout()


async def test_get_copilot_token_raises_when_not_authenticated(
    secret_dir: Path,
) -> None:
    service = _service_with_handlers({})
    with pytest.raises(CopilotOAuthError):
        await service.get_copilot_token()


async def test_logout_clears_state_and_disk(secret_dir: Path) -> None:
    service = _service_with_handlers({})
    # Manually plant a session
    service._oauth_access_token = "gho_x"  # noqa: SLF001
    service._github_login = "alice"  # noqa: SLF001
    service.token_store.save("gho_x", "alice")
    assert service.is_authenticated
    assert service.token_store.load() is not None

    await service.logout()
    assert not service.is_authenticated
    assert service.token_store.load() is None
    status = await service.get_status()
    assert status.status == "not_started"
    assert not status.is_authenticated


async def test_chat_headers_contain_required_copilot_keys() -> None:
    service = CopilotOAuthService(
        provider_id="github-copilot",
        editor_version="vscode/1.95.0",
        plugin_version="qwenpaw/1.1.4",
        user_agent="QwenPaw/1.1.4",
    )
    headers = service.chat_headers()
    # These exact header keys are required by Copilot's chat endpoints —
    # absence/typo causes 400/401.
    assert headers["Editor-Version"] == "vscode/1.95.0"
    assert headers["Editor-Plugin-Version"] == "qwenpaw/1.1.4"
    assert headers["Copilot-Integration-Id"] == "vscode-chat"
    assert headers["Openai-Intent"] == "conversation-panel"
    assert headers["X-Github-Api-Version"] == "2025-04-01"
    assert headers["User-Agent"] == "QwenPaw/1.1.4"


async def test_restore_from_disk_restores_session(secret_dir: Path) -> None:
    handlers = {
        ("GET", COPILOT_TOKEN_URL): lambda req: httpx.Response(
            200,
            json={
                "token": "restored-token",
                "expires_at": int(time.time()) + 1800,
                "refresh_in": 1500,
                "endpoints": {"api": "https://api.githubcopilot.com"},
                "chat_enabled": True,
            },
        ),
    }
    service = _service_with_handlers(handlers)
    service.token_store.save("gho_persisted", github_login="dev")

    restored = await service.restore_from_disk()
    assert restored
    assert service.is_authenticated
    assert service.github_login == "dev"
    # Background refresh should be scheduled; give it a moment.
    await asyncio.sleep(0.05)
    token = await service.get_copilot_token()
    assert token == "restored-token"


async def test_polling_handles_slow_down(secret_dir: Path) -> None:
    seq: List[Dict[str, Any]] = [
        {"error": "slow_down"},
        {
            "access_token": "gho_after_slow",
            "token_type": "bearer",
        },
    ]
    state = {"i": 0}

    def device_code_handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "device_code": "dev",
                "user_code": "U-0000",
                "verification_uri": "https://github.com/login/device",
                "expires_in": 60,
                "interval": 1,
            },
        )

    def token_handler(req: httpx.Request) -> httpx.Response:
        i = state["i"]
        state["i"] += 1
        return httpx.Response(200, json=seq[min(i, len(seq) - 1)])

    handlers = {
        ("POST", GITHUB_DEVICE_CODE_URL): device_code_handler,
        ("POST", GITHUB_TOKEN_URL): token_handler,
        ("GET", GITHUB_USER_URL): lambda req: httpx.Response(
            200,
            json={"login": "u"},
        ),
        ("GET", COPILOT_TOKEN_URL): lambda req: httpx.Response(
            200,
            json={
                "token": "ok",
                "expires_at": int(time.time()) + 1800,
                "refresh_in": 1500,
                "endpoints": {"api": "https://api.githubcopilot.com"},
            },
        ),
    }
    service = _service_with_handlers(handlers)
    try:
        await service.start_device_flow()
        # Wait long enough to traverse slow_down + success
        for _ in range(200):
            if service.is_authenticated:
                break
            await asyncio.sleep(0.05)
        assert service.is_authenticated
        assert state["i"] >= 2
    finally:
        await service.logout()


# ---------------------------------------------------------------------------
# Regression tests for PR review fixes
# ---------------------------------------------------------------------------


async def test_oauth_posts_use_form_encoded_body(secret_dir: Path) -> None:
    """RFC 8628 / GitHub OAuth device-code endpoints expect
    ``application/x-www-form-urlencoded`` request bodies.  This test
    pins the wire format so a future refactor cannot regress to JSON.
    """
    captured: Dict[str, httpx.Request] = {}

    def device_code_handler(req: httpx.Request) -> httpx.Response:
        captured["device_code"] = req
        return httpx.Response(
            200,
            json={
                "device_code": "dev",
                "user_code": "U-0000",
                "verification_uri": "https://github.com/login/device",
                "expires_in": 60,
                "interval": 1,
            },
        )

    def token_handler(req: httpx.Request) -> httpx.Response:
        captured.setdefault("token", req)
        return httpx.Response(200, json={"error": "authorization_pending"})

    handlers = {
        ("POST", GITHUB_DEVICE_CODE_URL): device_code_handler,
        ("POST", GITHUB_TOKEN_URL): token_handler,
    }
    service = _service_with_handlers(handlers)
    try:
        await service.start_device_flow()
        # Give the poll loop a chance to send one request.
        for _ in range(40):
            if "token" in captured:
                break
            await asyncio.sleep(0.05)
    finally:
        await service.logout()

    dc_req = captured["device_code"]
    assert dc_req.headers["content-type"].startswith(
        "application/x-www-form-urlencoded",
    )
    assert b"client_id=" in dc_req.content
    assert b"scope=read" in dc_req.content

    if "token" in captured:
        tok_req = captured["token"]
        assert tok_req.headers["content-type"].startswith(
            "application/x-www-form-urlencoded",
        )
        assert b"grant_type=" in tok_req.content
        assert b"device_code=" in tok_req.content


def test_seed_session_sets_state_synchronously() -> None:
    """``seed_session`` is the supported way for the provider factory
    to rehydrate a *not-yet-published* service from on-disk state.
    """
    service = CopilotOAuthService(provider_id="github-copilot-seed")
    assert not service.is_authenticated

    service.seed_session("gho_seed_token", "octocat")

    assert service.is_authenticated
    assert service.oauth_access_token == "gho_seed_token"
    assert service.github_login == "octocat"
    # Empty token is a no-op (avoids overwriting valid state with "").
    service.seed_session("", "anyone")
    assert service.oauth_access_token == "gho_seed_token"


async def test_get_or_create_http_client_returns_shared_instance() -> None:
    """The shared httpx.AsyncClient must be reused across calls so
    repeated check_connection / fetch_models / chat invocations do
    not leak sockets or file descriptors."""
    service = CopilotOAuthService(provider_id="github-copilot-shared")
    try:
        client_a = service.get_or_create_http_client()
        client_b = service.get_or_create_http_client()
        assert client_a is client_b
        # The shared client carries the Copilot chat headers.
        assert client_a.headers.get("editor-version")
    finally:
        await service.aclose_http_client()


async def test_aclose_http_client_clears_and_recreates() -> None:
    service = CopilotOAuthService(provider_id="github-copilot-recycle")
    client_a = service.get_or_create_http_client()
    await service.aclose_http_client()
    assert client_a.is_closed
    # A subsequent get returns a fresh, open client.
    client_b = service.get_or_create_http_client()
    try:
        assert client_b is not client_a
        assert not client_b.is_closed
    finally:
        await service.aclose_http_client()


async def test_logout_closes_shared_http_client(secret_dir: Path) -> None:
    service = _service_with_handlers({})
    client = service.get_or_create_http_client()
    assert not client.is_closed
    await service.logout()
    assert client.is_closed


async def test_restore_from_disk_takes_lock(secret_dir: Path) -> None:
    """``restore_from_disk`` mutates protected state under ``_lock`` so
    it cannot interleave with concurrent ``get_status`` reads.
    """
    handlers = {
        ("GET", COPILOT_TOKEN_URL): lambda req: httpx.Response(
            200,
            json={
                "token": "ok",
                "expires_at": int(time.time()) + 1800,
                "refresh_in": 1500,
                "endpoints": {"api": "https://api.githubcopilot.com"},
            },
        ),
    }
    service = _service_with_handlers(handlers)
    service.token_store.save("gho_persisted", github_login="dev")

    # Hold the lock from another coroutine so restore_from_disk must
    # actually wait for it.  If the implementation forgot to take the
    # lock, restore would complete immediately and the assertion below
    # would fire before we release.
    holder_released = asyncio.Event()
    holder_acquired = asyncio.Event()

    async def _holder() -> None:
        async with service._lock:
            holder_acquired.set()
            await holder_released.wait()

    holder_task = asyncio.create_task(_holder())
    await holder_acquired.wait()

    restore_task = asyncio.create_task(service.restore_from_disk())
    # Give restore a window to (incorrectly) bypass the lock.
    await asyncio.sleep(0.05)
    assert (
        not restore_task.done()
    ), "restore_from_disk must wait on the service lock"
    holder_released.set()
    await holder_task
    restored = await restore_task
    assert restored
    assert service.is_authenticated
