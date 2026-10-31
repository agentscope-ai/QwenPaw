# -*- coding: utf-8 -*-
"""Validate terminal boundary, directory resolution and payload contracts."""

import os
import threading
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.routers import terminal
from qwenpaw.app.auth import (
    AuthMiddleware,
    RuntimeBoundaryMiddleware,
    runtime_token_matches,
)


@pytest.fixture(name="client")
def terminal_client(monkeypatch, tmp_path):
    monkeypatch.setattr(terminal, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(terminal, "has_registered_users", lambda: True)
    monkeypatch.setattr(
        terminal,
        "verify_token",
        lambda token: "alice" if token == "valid" else None,
    )
    workspace = SimpleNamespace(agent_id="agent-a")
    monkeypatch.setattr(
        terminal,
        "get_agent_for_request",
        AsyncMock(return_value=workspace),
    )
    monkeypatch.setattr(
        terminal,
        "get_project_dir_for_request",
        AsyncMock(return_value=tmp_path),
    )
    app = FastAPI()
    app.include_router(terminal.router, prefix="/api")
    with TestClient(app) as test_client:
        test_client.headers["Authorization"] = "Bearer valid"
        manager = MagicMock()
        manager.create.return_value = {"id": str(uuid4())}
        manager.list.return_value = []
        app.state.terminal_manager = manager
        yield test_client, manager


def test_creation_resolves_directory_and_scopes_agent(client):
    http, manager = client
    group = str(uuid4())
    response = http.post(f"/api/terminals/{group}")
    assert response.status_code == 200
    assert manager.create.call_args.args[0] == ("alice", "agent-a", group)
    terminal.get_project_dir_for_request.assert_awaited_once()


def test_missing_native_dependency_disables_only_terminal(client, monkeypatch):
    http, manager = client
    monkeypatch.setattr(
        terminal,
        "terminal_unavailable_reason",
        lambda: "dependency_missing",
    )
    assert http.get("/api/terminals/status").json() == {
        "enabled": False,
        "reason": "dependency_missing",
    }
    response = http.post(f"/api/terminals/{uuid4()}")
    assert response.status_code == 503
    assert "pywinpty" in response.json()["detail"]
    assert not manager.mock_calls


@pytest.mark.parametrize(
    "mode",
    ["disabled", "no-users", "missing", "expired"],
)
@pytest.mark.parametrize(
    "operation",
    ["list", "create", "output", "input", "resize", "rename", "close"],
)
def test_terminal_auth_gate_covers_every_operation(
    client,
    monkeypatch,
    mode,
    operation,
):
    http, manager = client
    if mode == "disabled":
        monkeypatch.setattr(terminal, "is_auth_enabled", lambda: False)
    elif mode == "no-users":
        monkeypatch.setattr(terminal, "has_registered_users", lambda: False)
    else:
        http.headers["Authorization"] = (
            "" if mode == "missing" else "Bearer expired"
        )
    base = f"/api/terminals/{uuid4()}"
    item = f"{base}/{uuid4()}"
    requests = {
        "list": ("GET", base, None),
        "create": ("POST", base, None),
        "output": ("GET", f"{item}/output", None),
        "input": ("POST", f"{item}/input", {"data": "pwd\n"}),
        "resize": ("POST", f"{item}/resize", {"rows": 24, "cols": 80}),
        "rename": ("PATCH", item, {"title": "test"}),
        "close": ("DELETE", item, None),
    }
    method, path, body = requests[operation]
    assert http.request(method, path, json=body).status_code == (
        403 if mode == "disabled" else 401
    )
    assert not manager.mock_calls
    terminal.get_agent_for_request.assert_not_awaited()


def test_hub_token_does_not_bypass_disabled_switch(client, monkeypatch):
    http, manager = client
    monkeypatch.setattr(terminal, "is_auth_enabled", lambda: False)
    monkeypatch.setenv("QWENPAW_RUNTIME_INTERNAL_TOKEN", "boundary")
    assert (
        http.post(
            f"/api/terminals/{uuid4()}",
            headers={"X-QwenPaw-Runtime-Token": "boundary"},
        ).status_code
        == 403
    )
    manager.create.assert_not_called()
    assert http.get("/api/terminals/status").json() == {"enabled": False}


def test_hub_authentication_with_enabled_switch(client, monkeypatch):
    http, manager = client
    monkeypatch.setattr(terminal, "has_registered_users", lambda: False)
    monkeypatch.setenv("QWENPAW_RUNTIME_INTERNAL_TOKEN", "boundary")
    http.headers.pop("Authorization")
    assert (
        http.post(
            f"/api/terminals/{uuid4()}",
            headers={"X-QwenPaw-Runtime-Token": "boundary"},
        ).status_code
        == 200
    )
    assert manager.create.call_args.args[0][0] == "hub-runtime"


@pytest.mark.parametrize(
    "expected,supplied,matches",
    [
        ("boundary", "boundary", True),
        ("boundary", "wrong", False),
        ("", "", False),
        ("boundary", "boundary\u00ff", False),
        ("boundary\u00ff", "boundary\u00ff", False),
    ],
)
def test_runtime_token_comparison(expected, supplied, matches):
    assert runtime_token_matches(expected, supplied) is matches


def test_non_ascii_runtime_token_is_not_trusted(client, monkeypatch):
    http, manager = client
    monkeypatch.setenv("QWENPAW_RUNTIME_INTERNAL_TOKEN", "boundary")
    http.headers.pop("Authorization")
    response = http.post(
        f"/api/terminals/{uuid4()}",
        headers=[(b"x-qwenpaw-runtime-token", b"boundary\xff")],
    )
    assert response.status_code == 401
    assert not manager.mock_calls


@pytest.mark.parametrize("protocol", ["http", "websocket"])
async def test_boundary_rejects_non_ascii_runtime_token(monkeypatch, protocol):
    monkeypatch.setenv("QWENPAW_RUNTIME_INTERNAL_TOKEN", "boundary")
    downstream = AsyncMock()
    send = AsyncMock()
    await RuntimeBoundaryMiddleware(downstream)(
        {
            "type": protocol,
            "headers": [(b"x-qwenpaw-runtime-token", b"boundary\xff")],
        },
        AsyncMock(),
        send,
    )
    downstream.assert_not_awaited()
    first = send.call_args_list[0].args[0]
    if protocol == "websocket":
        assert first == {"type": "websocket.close", "code": 4401}
    else:
        assert first["type"] == "http.response.start"
        assert first["status"] == 401


@pytest.mark.parametrize("origin", ["https://attacker.test", "null"])
def test_rejects_cross_site_shell_creation(client, origin):
    http, manager = client
    response = http.post(
        f"/api/terminals/{uuid4()}",
        headers={"Origin": origin},
    )
    assert response.status_code == 403
    manager.create.assert_not_called()


def test_managed_runtime_origin_requires_real_boundary_token(
    client,
    monkeypatch,
):
    http, manager = client
    monkeypatch.setenv("QWENPAW_RUNTIME_INTERNAL_TOKEN", "test-token")
    path = f"/api/terminals/{uuid4()}"
    headers = {
        "Origin": "https://hub.example.test",
        "X-QwenPaw-Runtime-Token": "wrong",
    }
    assert http.post(path, headers=headers).status_code == 403
    headers["X-QwenPaw-Runtime-Token"] = "test-token"
    assert http.post(path, headers=headers).status_code == 200
    manager.create.assert_called_once()


@pytest.mark.parametrize(
    "suffix,payload",
    [
        ("input", {"data": "x" * 16385}),
        ("input", {"data": ""}),
        ("resize", {"rows": 0, "cols": 80}),
        ("resize", {"rows": 24, "cols": 10000}),
    ],
)
def test_rejects_unbounded_input_and_dimensions(client, suffix, payload):
    http, manager = client
    path = f"/api/terminals/{uuid4()}/{uuid4()}/{suffix}"
    assert http.post(path, json=payload).status_code == 422
    manager.get.assert_not_called()


def test_unknown_or_foreign_terminal_is_404(client):
    http, manager = client
    manager.get.side_effect = KeyError("foreign")
    path = f"/api/terminals/{uuid4()}/{uuid4()}/output"
    assert http.get(path).status_code == 404


def test_loopback_development_origin_is_allowed(client):
    http, manager = client
    path = f"http://127.0.0.1:8001/api/terminals/{uuid4()}"
    response = http.post(path, headers={"Origin": "http://localhost:5173"})
    assert response.status_code == 200
    manager.create.assert_called_once()


def _load_persisted_cors_origin(
    monkeypatch,
    tmp_path,
    origin,
):
    """Apply QWENPAW_CORS_ORIGINS the way the Web UI / CLI store does."""
    from qwenpaw.envs import store

    @contextmanager
    def _noop_lock():
        yield

    monkeypatch.setattr(
        "qwenpaw.backup._utils.safe_swap.restore_process_lock",
        _noop_lock,
    )
    monkeypatch.setattr(
        "qwenpaw.backup._utils.safe_swap.cleanup_stale_restore_artifacts",
        lambda _base_dir: None,
    )
    path = tmp_path / "envs.json"
    monkeypatch.setattr(store, "_ENVS_JSON", path)
    monkeypatch.setattr(store, "_LEGACY_ENVS_JSON_CANDIDATES", ())
    monkeypatch.setattr(store, "_BOOTSTRAP_SECRET_DIR", tmp_path)
    monkeypatch.setattr(store, "encrypt", lambda value: f"enc:{value}")
    monkeypatch.setattr(
        store,
        "is_encrypted",
        lambda value: isinstance(value, str) and value.startswith("enc:"),
    )
    monkeypatch.setattr(
        store,
        "decrypt",
        lambda value: value.removeprefix("enc:"),
    )
    host_values = store._HOST_ENV_VALUES  # pylint: disable=protected-access
    saved_host = dict(host_values)
    host_values.clear()
    path.write_text(
        '{"QWENPAW_CORS_ORIGINS": "enc:' + origin + '"}',
        encoding="utf-8",
    )
    # setenv records an undo even when the key was absent. delenv does
    # not, so the value load_envs_into_environ() writes would leak.
    monkeypatch.setenv(
        "QWENPAW_CORS_ORIGINS",
        os.environ.get("QWENPAW_CORS_ORIGINS", ""),
    )
    try:
        store.load_envs_into_environ()
        assert os.environ["QWENPAW_CORS_ORIGINS"] == origin
    finally:
        host_values.clear()
        host_values.update(saved_host)


def _cors_origin_set(value: str) -> set[str]:
    return {item.strip() for item in value.split(",") if item.strip()}


def test_desktop_flag_keeps_tauri_origins_after_second_env_load(
    monkeypatch,
    tmp_path,
):
    """Persisted origins must not drop the desktop webview origins."""
    from qwenpaw.constant import get_cors_origins
    from qwenpaw.envs import store
    from qwenpaw.tauri.env import ensure_desktop_cors_origins

    origin = "https://console.example.test"
    monkeypatch.setenv("QWENPAW_DESKTOP_APP", "1")
    _load_persisted_cors_origin(monkeypatch, tmp_path, origin)
    ensure_desktop_cors_origins()
    store.load_envs_into_environ()
    assert os.environ["QWENPAW_CORS_ORIGINS"] == origin
    assert _cors_origin_set(get_cors_origins()) == {
        origin,
        "tauri://localhost",
        "https://tauri.localhost",
        "http://tauri.localhost",
    }


def test_desktop_flag_off_does_not_add_tauri_origins(
    monkeypatch,
    tmp_path,
):
    """With the desktop flag off, a reload does not add Tauri origins."""
    from qwenpaw.constant import get_cors_origins
    from qwenpaw.envs import store
    from qwenpaw.tauri.env import ensure_desktop_cors_origins

    origin = "https://console.example.test"
    monkeypatch.delenv("QWENPAW_DESKTOP_APP", raising=False)
    _load_persisted_cors_origin(monkeypatch, tmp_path, origin)
    ensure_desktop_cors_origins()
    store.load_envs_into_environ()
    assert os.environ["QWENPAW_CORS_ORIGINS"] == origin
    assert _cors_origin_set(get_cors_origins()) == {origin}


def test_persisted_cors_loader_restores_absent_env(tmp_path):
    """Helper teardown must drop an origin the process did not have."""
    from pytest import MonkeyPatch

    origin = "https://console.example.test"
    previous = os.environ.pop("QWENPAW_CORS_ORIGINS", None)
    patch = MonkeyPatch()
    try:
        _load_persisted_cors_origin(patch, tmp_path, origin)
        assert os.environ["QWENPAW_CORS_ORIGINS"] == origin
        patch.undo()
        assert "QWENPAW_CORS_ORIGINS" not in os.environ
    finally:
        if previous is None:
            os.environ.pop("QWENPAW_CORS_ORIGINS", None)
        else:
            os.environ["QWENPAW_CORS_ORIGINS"] = previous


def test_cors_origin_loaded_after_import_is_allowed(
    client,
    monkeypatch,
    tmp_path,
):
    """Env-store origins applied after import must allow terminal POSTs."""
    from qwenpaw.constant import CORS_ORIGINS

    origin = "https://console.example.test"
    # constant.py reads QWENPAW_CORS_ORIGINS at import, before envs load.
    assert origin not in {value.strip() for value in CORS_ORIGINS.split(",")}
    _load_persisted_cors_origin(monkeypatch, tmp_path, origin)
    http, manager = client
    response = http.post(
        f"/api/terminals/{uuid4()}",
        headers={"Origin": origin},
    )
    assert response.status_code == 200
    manager.create.assert_called_once()


def test_unset_cors_origins_keep_default_cross_site_rejection(
    client,
    monkeypatch,
):
    """With the variable unset, non-loopback cross-site posts stay rejected."""
    monkeypatch.delenv("QWENPAW_CORS_ORIGINS", raising=False)
    http, manager = client
    response = http.post(
        f"/api/terminals/{uuid4()}",
        headers={"Origin": "https://attacker.test"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == (
        "Cross-site terminal request rejected"
    )
    manager.create.assert_not_called()


def test_process_env_cors_origin_present_at_start_is_allowed(
    client,
    monkeypatch,
):
    """An origin exported before startup is still accepted."""
    origin = "https://startup.example.test"
    monkeypatch.setenv("QWENPAW_CORS_ORIGINS", origin)
    http, manager = client
    response = http.post(
        f"/api/terminals/{uuid4()}",
        headers={"Origin": origin},
    )
    assert response.status_code == 200
    manager.create.assert_called_once()


def test_terminal_routes_pass_through_authentication(monkeypatch):
    monkeypatch.setattr(
        AuthMiddleware,
        "_should_skip_auth",
        staticmethod(lambda _: False),
    )
    app = FastAPI()
    app.include_router(terminal.router, prefix="/api")
    app.add_middleware(AuthMiddleware)
    app.add_middleware(RuntimeBoundaryMiddleware)
    with TestClient(app) as http:
        assert http.post(f"/api/terminals/{uuid4()}").status_code == 401


async def test_direct_bearer_verification_runs_off_event_loop(monkeypatch):
    event_loop_thread = threading.get_ident()
    verification_threads = []
    manager = MagicMock()
    workspace = SimpleNamespace(agent_id="agent-a")
    request = SimpleNamespace(
        headers={"authorization": "Bearer valid"},
        state=SimpleNamespace(),
        app=SimpleNamespace(
            state=SimpleNamespace(terminal_manager=manager),
        ),
    )

    monkeypatch.setattr(terminal, "is_auth_enabled", lambda: True)
    monkeypatch.delenv("QWENPAW_RUNTIME_INTERNAL_TOKEN", raising=False)
    monkeypatch.setattr(
        terminal,
        "verify_bearer_user",
        lambda _token: verification_threads.append(threading.get_ident())
        or "alice",
    )
    monkeypatch.setattr(terminal, "terminal_unavailable_reason", lambda: None)
    monkeypatch.setattr(
        terminal,
        "get_agent_for_request",
        AsyncMock(return_value=workspace),
    )

    _manager, owner, _workspace = await terminal.context(
        request,
        uuid4(),
    )

    assert owner[0] == "alice"
    assert verification_threads
    assert verification_threads[0] != event_loop_thread


def test_router_lifespan_stops_owned_processes(monkeypatch):
    manager = MagicMock()
    monkeypatch.setattr(terminal, "TerminalManager", lambda: manager)
    app = FastAPI()
    app.include_router(terminal.router, prefix="/api")
    with TestClient(app):
        assert app.state.terminal_manager is manager
    manager.shutdown.assert_called_once()
