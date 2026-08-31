# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from qwenpaw.exceptions import ConfigurationException
from qwenpaw.pawapp import (
    DependencyHealth,
    DependencyProbe,
    ManagedService,
    ManagedServiceSpec,
    PawApp,
)
from qwenpaw.pawapp.app import _build_capability_router
from qwenpaw.pawapp.context import ChatReply
from qwenpaw.pawapp.deps import get_scoped_ctx
from qwenpaw.pawapp import service as service_module

# Minimal loopback HTTP responder for managed-service fixtures. It is
# deliberately raw-socket based: stdlib HTTPServer.server_bind() calls
# socket.getfqdn() (a reverse DNS lookup) between bind() and listen(),
# which hangs the whole startup window on hosts with broken localhost
# resolution (GitHub macOS runners, actions/runner-images#6383) while
# the socket sits bound but never listening.
_LOOPBACK_SERVER_SCRIPT = """
import socket
import sys

server = socket.socket()
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind((sys.argv[1], int(sys.argv[2])))
server.listen()
print("listening", flush=True)
while True:
    connection, _ = server.accept()
    connection.recv(65536)
    connection.sendall(
        b"HTTP/1.1 200 OK\\r\\nContent-Length: 2\\r\\n"
        b"Connection: close\\r\\n\\r\\nok",
    )
    connection.close()
"""


def _route_paths(router) -> set[str]:
    paths: set[str] = set()
    for route in getattr(router, "routes", ()):
        path = getattr(route, "path", None)
        if isinstance(path, str):
            paths.add(path)
        paths.update(_route_paths(route))
        original_router = getattr(route, "original_router", None)
        if original_router is not None:
            paths.update(_route_paths(original_router))
    return paths


@pytest.mark.asyncio
async def test_managed_service_allocates_port_and_stops(
    tmp_path: Path,
) -> None:
    service = ManagedService(
        ManagedServiceSpec(
            name="fixture",
            command=(
                sys.executable,
                "-c",
                _LOOPBACK_SERVER_SCRIPT,
                "{host}",
                "{port}",
            ),
            health_path="/",
            cwd=tmp_path,
            # Generous headroom: CPU-starved CI runners (notably macOS)
            # can take several seconds to spawn the child interpreter.
            startup_timeout=30,
        ),
    )

    await service.start()
    try:
        assert service.is_ready is True
        assert service.is_external is False
        assert service.base_url.startswith("http://127.0.0.1:")
        assert service.status() == {
            "name": "fixture",
            "ready": True,
            "mode": "managed",
        }
        assert service.diagnostics()["pid"] is not None
    finally:
        await service.stop()

    assert service.is_ready is False


@pytest.mark.asyncio
async def test_external_service_mode_never_starts_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FIXTURE_MODE", "external")
    monkeypatch.setenv("FIXTURE_URL", "http://127.0.0.1:9123/")
    monkeypatch.setattr(service_module, "_health_request", lambda *_: True)
    service = ManagedService(
        ManagedServiceSpec(
            name="fixture",
            command=("must-not-run",),
            external_url_env="FIXTURE_URL",
            mode_env="FIXTURE_MODE",
        ),
    )

    await service.start()
    assert service.is_external is True
    assert service.base_url == "http://127.0.0.1:9123"
    assert service.status() == {
        "name": "fixture",
        "ready": True,
        "mode": "external",
    }
    assert service.diagnostics()["pid"] is None
    await service.stop()


@pytest.mark.asyncio
async def test_managed_service_calls_on_before_start_hook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FIXTURE_MODE", "external")
    monkeypatch.setenv("FIXTURE_URL", "http://127.0.0.1:9123/")
    monkeypatch.setattr(service_module, "_health_request", lambda *_: True)

    calls: list[str] = []

    async def hook() -> None:
        calls.append("hook")
        monkeypatch.setenv("FIXTURE_FROM_HOOK", "yes")

    service = ManagedService(
        ManagedServiceSpec(
            name="fixture",
            command=("must-not-run",),
            external_url_env="FIXTURE_URL",
            mode_env="FIXTURE_MODE",
            on_before_start=hook,
        ),
    )

    await service.start()
    assert calls == ["hook"]
    assert service.spec.env.get("FIXTURE_FROM_HOOK") is None
    await service.stop()


@pytest.mark.asyncio
async def test_managed_service_preserves_non_sdk_braces(
    tmp_path: Path,
) -> None:
    script = (
        "import os, sys\n"
        'assert sys.argv[3] == \'{"kind":"fixture"}\'\n'
        "assert os.environ['FIXTURE_JSON'] == '{\"kind\":\"fixture\"}'\n"
        + _LOOPBACK_SERVER_SCRIPT
    )
    service = ManagedService(
        ManagedServiceSpec(
            name="fixture",
            command=(
                sys.executable,
                "-c",
                script,
                "{host}",
                "{port}",
                '{"kind":"fixture"}',
            ),
            health_path="/",
            cwd=tmp_path,
            env={"FIXTURE_JSON": '{"kind":"fixture"}'},
            startup_timeout=30,
        ),
    )

    await service.start()
    await service.stop()


@pytest.mark.asyncio
async def test_failed_external_health_check_clears_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FIXTURE_MODE", "external")
    monkeypatch.setenv("FIXTURE_URL", "http://127.0.0.1:9123")
    monkeypatch.setattr(service_module, "_health_request", lambda *_: False)
    service = ManagedService(
        ManagedServiceSpec(
            name="fixture",
            command=("must-not-run",),
            external_url_env="FIXTURE_URL",
            mode_env="FIXTURE_MODE",
            startup_timeout=0.01,
        ),
    )

    with pytest.raises(TimeoutError):
        await service.start()

    assert service.is_ready is False
    assert service.is_external is False


@pytest.mark.parametrize(
    "url",
    [
        "ftp://127.0.0.1/service",
        "http://user:secret@127.0.0.1/service",
        "http://127.0.0.1/service#internal",
    ],
)
@pytest.mark.asyncio
async def test_external_service_rejects_unsafe_urls(
    monkeypatch: pytest.MonkeyPatch,
    url: str,
) -> None:
    monkeypatch.setenv("FIXTURE_URL", url)
    service = ManagedService(
        ManagedServiceSpec(
            name="fixture",
            command=("must-not-run",),
            external_url_env="FIXTURE_URL",
        ),
    )

    with pytest.raises(ValueError):
        await service.start()

    assert service.is_ready is False
    assert service.is_external is False


@pytest.mark.parametrize(
    "app_id",
    ["../other", "UPPERCASE", "contains space", "app_name"],
)
def test_pawapp_rejects_invalid_app_ids(app_id: str) -> None:
    app = PawApp("Fixture", app_id=app_id)
    with pytest.raises(ValueError, match="lowercase kebab-case"):
        app.enable_standard_capabilities()


def test_legacy_pawapp_does_not_receive_standard_routes() -> None:
    api = MagicMock()
    app = PawApp("Legacy", app_id="legacy_app")

    app.register(api)

    assert app.app_id == "legacy_app"
    api.register_http_router.assert_not_called()


def test_managed_service_rejects_non_loopback_host() -> None:
    with pytest.raises(ValueError, match="loopback"):
        ManagedService(
            ManagedServiceSpec(
                name="fixture",
                command=("must-not-run",),
                host="0.0.0.0",
            ),
        )


@pytest.mark.asyncio
async def test_managed_start_fails_actionably_without_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FIXTURE_MODE", raising=False)
    monkeypatch.delenv("FIXTURE_URL", raising=False)
    missing = tmp_path / ".venv-fixture" / "bin" / "python"
    service = ManagedService(
        ManagedServiceSpec(
            name="fixture",
            command=(str(missing), "-m", "fixture"),
            external_url_env="FIXTURE_URL",
            mode_env="FIXTURE_MODE",
        ),
    )

    assert service.runtime_available() is False
    with pytest.raises(RuntimeError, match="FIXTURE_MODE=external"):
        await service.start()
    assert service.is_ready is False


def test_runtime_available_trusts_external_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FIXTURE_MODE", "external")
    service = ManagedService(
        ManagedServiceSpec(
            name="fixture",
            command=("/nonexistent/fixture-python",),
            external_url_env="FIXTURE_URL",
            mode_env="FIXTURE_MODE",
        ),
    )

    assert service.runtime_available() is True


@pytest.mark.asyncio
async def test_managed_service_probe_reports_missing_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FIXTURE_MODE", raising=False)
    monkeypatch.delenv("FIXTURE_URL", raising=False)
    app = PawApp("Fixture", app_id="fixture")
    app.managed_service(
        "context",
        command=(str(tmp_path / "missing-python"), "-m", "fixture"),
        health_path="/",
        external_url_env="FIXTURE_URL",
        mode_env="FIXTURE_MODE",
        runtime_remediation="Run scripts/setup-dev.sh",
    )

    payload = await app.dependencies.get("context", force=True)

    assert payload["health"] == "unavailable"
    assert payload["error_code"] == "RUNTIME_MISSING"
    assert payload["remediation"] == "Run scripts/setup-dev.sh"


def test_pawapp_delegates_extensions_through_plugin_api(
    tmp_path: Path,
) -> None:
    api = MagicMock()
    app = PawApp("Fixture", app_id="fixture")
    app.enable_standard_capabilities()
    app.skill_provider(tmp_path, channels=["console"])
    app.prompt_section("fixture-guidance", "Use fixture context", priority=75)
    service = app.managed_service(
        "context",
        command=(sys.executable, "-m", "http.server", "{port}"),
        health_path="/",
    )

    app.register(api)

    api.register_skill_provider.assert_called_once_with(
        skills_dir=tmp_path,
        enabled_by_default=True,
        channels=["console"],
    )
    section = api.register_prompt_section.call_args.kwargs
    assert section["name"] == "fixture-guidance"
    assert section["after"] == "workspace"
    assert section["priority"] == 75
    assert section["provider"](object()) == "Use fixture context"

    router = api.register_http_router.call_args_list[0].args[0]
    assert (
        api.register_http_router.call_args_list[0].kwargs["prefix"]
        == "/fixture"
    )
    assert _route_paths(router) >= {
        "/chat",
        "/chat/history",
        "/chat/sessions",
        "/chat/sessions/{chat_id}",
        "/chat/sessions/{chat_id}/archive",
        "/chat/stream",
        "/storage",
        "/storage/{key}",
        "/dependencies",
        "/dependencies/{dependency_id}",
        "/dependencies/{dependency_id}/actions/{action}",
        "/capabilities",
    }
    assert api.register_http_router.call_count == 1
    api.register_startup_hook.assert_any_call(
        hook_name="pawapp_fixture_service_context",
        callback=service.start,
        priority=70,
    )
    api.register_shutdown_hook.assert_any_call(
        hook_name="pawapp_fixture_service_context",
        callback=service.stop,
        priority=130,
    )


@pytest.mark.asyncio
async def test_pawapp_manages_agent_profile_through_host_lifecycle(
    tmp_path: Path,
) -> None:
    api = MagicMock()
    manager = MagicMock()
    registry = api._registry  # pylint: disable=protected-access
    registry.get_workspace_manager.return_value = manager
    app = PawApp("Fixture", app_id="fixture")
    profile = app.agent_profile(
        "fixture-agent",
        name="Fixture Agent",
        persona_dir=tmp_path,
    )
    profile.ensure = MagicMock(return_value=True)
    profile.detach = MagicMock(return_value=True)

    app.register(api)

    startup = next(
        call.kwargs["callback"]
        for call in api.register_startup_hook.call_args_list
        if call.kwargs["hook_name"] == "pawapp_fixture_agent_fixture-agent"
    )
    uninstall = next(
        call.kwargs["callback"]
        for call in api.register_uninstall_hook.call_args_list
        if call.kwargs["hook_name"] == "pawapp_fixture_agent_fixture-agent"
    )
    await startup()
    await uninstall(plugin_id="fixture", delete_files=True)

    profile.ensure.assert_called_once_with()
    manager.schedule_agent_startup.assert_called_once_with("fixture-agent")
    profile.detach.assert_called_once_with()


def test_dependency_agent_tools_are_explicit_and_app_scoped() -> None:
    api = MagicMock()
    app = PawApp("Fixture", app_id="fixture")
    app.dependency(
        "warehouse",
        probe=DependencyProbe(
            lambda: DependencyHealth(
                health="healthy",
                lifecycle="unmanaged",
            ),
        ),
    )
    app.enable_dependency_agent_tools()

    app.register(api)

    tool_names = {
        call.kwargs["tool_name"] for call in api.register_tool.call_args_list
    }
    assert tool_names == {
        "fixture_dependency_status",
        "fixture_dependency_action",
    }
    tool_types = {
        call.kwargs["tool_name"]: call.kwargs["tool_type"]
        for call in api.register_tool.call_args_list
    }
    assert tool_types == {
        "fixture_dependency_status": "network",
        "fixture_dependency_action": "internal",
    }


def test_chat_reports_missing_model_as_actionable_unavailable() -> None:
    class MissingModelContext:
        app_id = "fixture"

        async def chat(self, *_args, **_kwargs):
            raise ConfigurationException(
                "No active model configured; pick one in the UI",
                config_key="active_model",
                error_code="MODEL_NOT_CONFIGURED",
            )

    fixture = FastAPI()
    fixture.include_router(_build_capability_router())
    fixture.dependency_overrides[get_scoped_ctx] = MissingModelContext

    response = TestClient(fixture).post(
        "/chat",
        json={"message": "compare revenue"},
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": {
            "code": "MODEL_NOT_CONFIGURED",
            "message": "No active model configured; pick one in the UI",
            "config_key": "active_model",
            "action": {
                "label": "Configure a model",
                "path": "/models",
            },
        },
    }


def test_chat_history_reads_the_same_app_session() -> None:
    class HistoryContext:
        app_id = "fixture"

        def __init__(self):
            self.requested_session_id = None

        async def get_session_history(self, session_id):
            self.requested_session_id = session_id
            return [
                {
                    "id": "message-1",
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "text", "text": "hello"}],
                },
                {
                    "id": "reasoning-1",
                    "type": "reasoning",
                    "role": "assistant",
                    "content": [{"type": "text", "text": "hidden"}],
                },
            ]

    context = HistoryContext()
    fixture = FastAPI()
    fixture.include_router(_build_capability_router())
    fixture.dependency_overrides[get_scoped_ctx] = lambda: context

    response = TestClient(fixture).get(
        "/chat/history",
        params={"session_id": "pawapp:fixture:analysis-7"},
    )

    assert response.status_code == 200
    assert context.requested_session_id == "pawapp:fixture:analysis-7"
    assert response.json() == {
        "session_id": "pawapp:fixture:analysis-7",
        "messages": [
            {
                "id": "message-1",
                "type": "message",
                "role": "user",
                "content": [{"type": "text", "text": "hello"}],
            },
        ],
    }


def test_chat_history_defaults_to_the_app_session() -> None:
    class HistoryContext:
        app_id = "fixture"

        async def get_session_history(self, session_id):
            assert session_id == "pawapp:fixture"
            return []

    fixture = FastAPI()
    fixture.include_router(_build_capability_router())
    fixture.dependency_overrides[get_scoped_ctx] = HistoryContext

    response = TestClient(fixture).get("/chat/history")

    assert response.status_code == 200
    assert response.json() == {
        "session_id": "pawapp:fixture",
        "messages": [],
    }


def test_chat_routes_reject_foreign_app_namespace_sessions() -> None:
    class ForeignSessionContext:
        app_id = "fixture"

        def is_app_session_id(self, session_id: str) -> bool:
            return session_id == "pawapp:fixture" or session_id.startswith(
                "pawapp:fixture:",
            )

        async def chat(self, *_args, **_kwargs):
            raise AssertionError("foreign session must never reach chat")

        def chat_stream(self, *_args, **_kwargs):
            raise AssertionError("foreign session must never reach stream")

        async def get_session_history(self, session_id):
            raise AssertionError("foreign session must never be read")

    fixture = FastAPI()
    fixture.include_router(_build_capability_router())
    fixture.dependency_overrides[get_scoped_ctx] = ForeignSessionContext
    client = TestClient(fixture)

    chat = client.post(
        "/chat",
        json={"message": "read it", "session_id": "pawapp:other"},
    )
    stream = client.post(
        "/chat/stream",
        json={"message": "read it", "session_id": "pawapp:other:x"},
    )
    history = client.get(
        "/chat/history",
        params={"session_id": "pawapp:other:dialogue:1"},
    )

    assert chat.status_code == 404
    assert stream.status_code == 404
    assert history.status_code == 404


def test_session_guard_falls_back_to_prefix_scoping() -> None:
    # Contexts without is_app_session_id (e.g. older stubs) still may not
    # cross into a sibling namespace, including prefix collisions without
    # the ':' separator.
    class BareContext:
        app_id = "fixture"

        async def get_session_history(self, session_id):
            raise AssertionError("foreign session must never be read")

    fixture = FastAPI()
    fixture.include_router(_build_capability_router())
    fixture.dependency_overrides[get_scoped_ctx] = BareContext

    response = TestClient(fixture).get(
        "/chat/history",
        params={"session_id": "pawapp:fixture-extra"},
    )

    assert response.status_code == 404


def test_chat_history_rejects_non_namespaced_session_ids() -> None:
    # Arbitrary host session keys (the legacy custom-ID escape hatch) are
    # not readable through the standard scoped routes; legacy PawApps keep
    # that behavior on their own routes via the Python context API.
    class LegacyContext:
        app_id = "fixture"

        async def get_session_history(self, session_id):
            raise AssertionError("non-namespaced session must never be read")

    fixture = FastAPI()
    fixture.include_router(_build_capability_router())
    fixture.dependency_overrides[get_scoped_ctx] = LegacyContext

    response = TestClient(fixture).get(
        "/chat/history",
        params={"session_id": "issue-42"},
    )

    assert response.status_code == 404


def test_standard_routes_reject_forged_identity_claims() -> None:
    # get_scoped_ctx binds user_id to the authenticated principal and pins
    # the channel; explicit claims that disagree are refused, not trusted.
    fixture = FastAPI()
    fixture.include_router(_build_capability_router())
    client = TestClient(fixture)

    forged_user = client.get(
        "/chat/history",
        params={"user_id": "somebody-else"},
    )
    forged_user_header = client.get(
        "/chat/history",
        headers={"X-User-Id": "somebody-else"},
    )
    forged_channel = client.get(
        "/chat/history",
        params={"channel": "telegram"},
    )

    assert forged_user.status_code == 403
    assert forged_user_header.status_code == 403
    assert forged_channel.status_code == 403


def test_scoped_ctx_binds_identity_to_the_authenticated_principal() -> None:
    # AuthMiddleware populates request.state.user; the scoped dependency
    # adopts it and accepts only matching explicit claims.
    from fastapi import Request

    fixture = FastAPI()

    @fixture.middleware("http")
    async def fake_auth(request: Request, call_next):
        request.state.user = "alice"
        return await call_next(request)

    captured = {}

    @fixture.get("/probe")
    async def probe(ctx=Depends(get_scoped_ctx)):
        captured["user_id"] = ctx.user_id
        captured["channel"] = ctx.channel
        return {"ok": True}

    client = TestClient(fixture)

    bound = client.get("/probe")
    matching_claim = client.get("/probe", params={"user_id": "alice"})
    forged_claim = client.get("/probe", params={"user_id": "bob"})

    assert bound.status_code == 200
    assert matching_claim.status_code == 200
    assert forged_claim.status_code == 403
    assert captured["user_id"] == "alice"
    assert captured["channel"] == "console"


def test_chat_session_routes_delegate_to_the_app_scoped_catalog() -> None:
    class SessionContext:
        app_id = "fixture"

        async def list_chat_sessions(self):
            return [
                {
                    "id": "chat-1",
                    "session_id": "pawapp:fixture",
                    "name": "Previous analysis",
                    "created_at": "2026-08-11T00:00:00Z",
                    "updated_at": "2026-08-11T00:00:00Z",
                    "archived": False,
                },
            ]

        async def create_chat_session(self, *, name):
            return {
                "id": "chat-2",
                "session_id": "pawapp:fixture:dialogue:2",
                "name": name,
                "created_at": "2026-08-11T00:00:00Z",
                "updated_at": "2026-08-11T00:00:00Z",
                "archived": False,
            }

        async def rename_chat_session(self, chat_id, *, name):
            return {
                "id": chat_id,
                "session_id": "pawapp:fixture:dialogue:2",
                "name": name,
                "created_at": "2026-08-11T00:00:00Z",
                "updated_at": "2026-08-11T00:01:00Z",
                "archived": False,
            }

        async def archive_chat_session(self, chat_id):
            return {
                "id": chat_id,
                "session_id": "pawapp:fixture:dialogue:2",
                "name": "Quarterly GAAP",
                "created_at": "2026-08-11T00:00:00Z",
                "updated_at": "2026-08-11T00:01:00Z",
                "archived": True,
            }

        async def pin_chat_session(self, chat_id, *, pinned):
            return {
                "id": chat_id,
                "session_id": "pawapp:fixture:dialogue:2",
                "name": "Quarterly GAAP",
                "created_at": "2026-08-11T00:00:00Z",
                "updated_at": "2026-08-11T00:01:00Z",
                "archived": False,
                "pinned": pinned,
            }

        async def delete_chat_session(self, chat_id):
            return chat_id == "chat-2"

    fixture = FastAPI()
    fixture.include_router(_build_capability_router())
    fixture.dependency_overrides[get_scoped_ctx] = SessionContext
    client = TestClient(fixture)

    listed = client.get("/chat/sessions")
    created = client.post("/chat/sessions", json={"name": "New analysis"})
    renamed = client.patch(
        "/chat/sessions/chat-2",
        json={"name": "Quarterly GAAP"},
    )
    archived = client.post("/chat/sessions/chat-2/archive")
    pinned = client.post("/chat/sessions/chat-2/pin", json={"pinned": True})
    deleted = client.delete("/chat/sessions/chat-2")
    delete_missing = client.delete("/chat/sessions/chat-404")

    assert listed.json()["sessions"][0]["session_id"] == "pawapp:fixture"
    assert created.json()["session_id"] == "pawapp:fixture:dialogue:2"
    assert renamed.json()["name"] == "Quarterly GAAP"
    assert archived.json()["archived"] is True
    assert pinned.json()["pinned"] is True
    assert deleted.json() == {"ok": True}
    assert delete_missing.status_code == 404


def test_chat_reply_returns_only_the_last_assistant_message() -> None:
    def message(
        text: str,
        *,
        message_type: str = "message",
        role: str = "assistant",
    ):
        return SimpleNamespace(
            type=message_type,
            role=role,
            content=[SimpleNamespace(text=text, delta=False)],
        )

    reply = ChatReply(
        chunks=[
            SimpleNamespace(
                output=[
                    message("I will inspect the schema."),
                    message("tool details", message_type="plugin_call"),
                    message("The final answer is 42."),
                ],
                error=None,
            ),
        ],
    )

    assert reply.text == "The final answer is 42."
