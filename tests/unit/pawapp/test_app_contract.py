from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
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
from qwenpaw.pawapp.deps import get_ctx
from qwenpaw.pawapp import service as service_module


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
async def test_managed_service_allocates_port_and_stops(tmp_path: Path) -> None:
    service = ManagedService(
        ManagedServiceSpec(
            name="fixture",
            command=(
                sys.executable,
                "-m",
                "http.server",
                "{port}",
                "--bind",
                "{host}",
            ),
            health_path="/",
            cwd=tmp_path,
            startup_timeout=8,
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
async def test_managed_service_preserves_non_sdk_braces(tmp_path: Path) -> None:
    script = (
        "import http.server, os, sys; "
        'assert sys.argv[3] == \'{"kind":"fixture"}\'; '
        "assert os.environ['FIXTURE_JSON'] == '{\"kind\":\"fixture\"}'; "
        "http.server.ThreadingHTTPServer((sys.argv[1], int(sys.argv[2])), "
        "http.server.SimpleHTTPRequestHandler).serve_forever()"
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
            startup_timeout=8,
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


def test_pawapp_delegates_extensions_through_plugin_api(tmp_path: Path) -> None:
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
    assert api.register_http_router.call_args_list[0].kwargs["prefix"] == "/fixture"
    assert _route_paths(router) >= {
        "/chat",
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
    api._registry.get_workspace_manager.return_value = manager
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

    tool_names = {call.kwargs["tool_name"] for call in api.register_tool.call_args_list}
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
        async def chat(self, *_args, **_kwargs):
            raise ConfigurationException(
                "No active model configured; pick one in the UI",
                config_key="active_model",
                error_code="MODEL_NOT_CONFIGURED",
            )

    fixture = FastAPI()
    fixture.include_router(_build_capability_router())
    fixture.dependency_overrides[get_ctx] = MissingModelContext

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
        }
    }


def test_chat_reply_returns_only_the_last_assistant_message() -> None:
    def message(text: str, *, message_type: str = "message", role: str = "assistant"):
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
