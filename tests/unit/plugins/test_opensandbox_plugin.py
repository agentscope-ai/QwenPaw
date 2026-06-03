# -*- coding: utf-8 -*-
"""Tests for the OpenSandbox plugin."""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path
from typing import Any, ClassVar

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_DIR = REPO_ROOT / "plugins" / "tool" / "opensandbox"


def _load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _response_text(response) -> str:
    content = getattr(response, "content", None) or []
    if not content:
        return ""
    block = content[0]
    if isinstance(block, dict):
        return str(block.get("text", ""))
    return str(getattr(block, "text", block))


def test_manifest_declares_opensandbox_tool():
    manifest = json.loads(
        (PLUGIN_DIR / "plugin.json").read_text(encoding="utf-8"),
    )

    assert manifest["id"] == "opensandbox"
    tools = manifest["meta"]["tools"]
    tool = next(
        item for item in tools if item["name"] == "execute_opensandbox_command"
    )
    fields = {item["name"]: item for item in tool["config_fields"]}

    assert tool["requires_config"] is True
    assert fields["api_key"]["required"] is False
    assert fields["api_key_env"]["default"] == "OPEN_SANDBOX_API_KEY"


def test_plugin_registers_startup_hook_and_tool():
    plugin_module = _load_module(
        "_opensandbox_plugin_test",
        PLUGIN_DIR / "plugin.py",
    )
    calls: list[tuple] = []

    class DummyApi:
        def register_startup_hook(self, **kwargs):
            calls.append(("hook", kwargs["hook_name"]))

        def register_tool(self, **kwargs):
            calls.append(
                (
                    "tool",
                    kwargs["tool_name"],
                    callable(kwargs["tool_func"]),
                ),
            )

    plugin_module.plugin.register(DummyApi())

    assert ("hook", "opensandbox_install_skills") in calls
    assert ("tool", "execute_opensandbox_command", True) in calls


def _install_fake_opensandbox(monkeypatch: pytest.MonkeyPatch):
    opensandbox_mod = types.ModuleType("opensandbox")
    config_mod = types.ModuleType("opensandbox.config")
    models_mod = types.ModuleType("opensandbox.models")
    execd_mod = types.ModuleType("opensandbox.models.execd")
    sandbox_mod = types.ModuleType("opensandbox.sandbox")

    class FakeConnectionConfig:
        last_kwargs: ClassVar[dict[str, Any]] = {}

        def __init__(self, **kwargs: Any):
            type(self).last_kwargs = kwargs

    class FakeRunCommandOpts:
        def __init__(self, **kwargs: Any):
            self.kwargs = kwargs

    class FakeCommands:
        async def run(self, command, opts):
            FakeSandbox.last_run = (command, opts)
            return types.SimpleNamespace(
                logs=types.SimpleNamespace(
                    stdout=[types.SimpleNamespace(text="ok")],
                    stderr=[],
                ),
                exit_code=0,
                error=None,
            )

    class FakeSandbox:
        create_args: ClassVar[tuple[str, dict[str, Any]]] = ("", {})
        instance: ClassVar[Any] = None
        last_run: ClassVar[tuple[str, FakeRunCommandOpts | None]] = ("", None)

        def __init__(self):
            self.id = "fake-sandbox"
            self.commands = FakeCommands()
            self.killed = False
            self.closed = False

        @classmethod
        async def create(cls, image: str, **kwargs: Any):
            cls.create_args = (image, kwargs)
            cls.instance = cls()
            return cls.instance

        async def kill(self):
            self.killed = True

        async def close(self):
            self.closed = True

    config_mod.ConnectionConfig = FakeConnectionConfig
    execd_mod.RunCommandOpts = FakeRunCommandOpts
    sandbox_mod.Sandbox = FakeSandbox

    monkeypatch.setitem(sys.modules, "opensandbox", opensandbox_mod)
    monkeypatch.setitem(sys.modules, "opensandbox.config", config_mod)
    monkeypatch.setitem(sys.modules, "opensandbox.models", models_mod)
    monkeypatch.setitem(sys.modules, "opensandbox.models.execd", execd_mod)
    monkeypatch.setitem(sys.modules, "opensandbox.sandbox", sandbox_mod)

    return FakeConnectionConfig, FakeSandbox


@pytest.mark.asyncio
async def test_execute_command_allows_server_without_api_key(monkeypatch):
    shell_module = _load_module(
        "_opensandbox_shell_test",
        PLUGIN_DIR / "tools" / "shell.py",
    )
    fake_connection, fake_sandbox = _install_fake_opensandbox(monkeypatch)

    monkeypatch.delenv("OPEN_SANDBOX_API_KEY", raising=False)
    monkeypatch.setattr(
        shell_module,
        "get_tool_config",
        lambda _tool_name: {
            "domain": "127.0.0.1:8080",
            "api_key": "",
            "api_key_env": "OPEN_SANDBOX_API_KEY",
        },
    )

    response = await shell_module.execute_opensandbox_command("echo ok")

    assert "OpenSandbox sandbox: fake-sandbox" in _response_text(response)
    assert "STDOUT:\nok" in _response_text(response)

    connection_kwargs = fake_connection.last_kwargs
    create_args = fake_sandbox.create_args
    last_run = fake_sandbox.last_run
    sandbox_instance = fake_sandbox.instance
    assert sandbox_instance is not None

    assert "api_key" not in connection_kwargs
    assert create_args[0] == "opensandbox/code-interpreter:v1.0.2"
    assert last_run[0] == "echo ok"
    assert sandbox_instance.killed is True
    assert sandbox_instance.closed is True
