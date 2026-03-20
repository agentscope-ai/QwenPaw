# -*- coding: utf-8 -*-
"""Unit tests for shell.py OpenSandbox integration."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from copaw.agents.tools.shell import (
    execute_shell_command,
    get_cloud_working_dir,
    get_opensandbox_instance,
    set_cloud_working_dir,
    set_opensandbox_instance,
)


def _get_text(resp) -> str:
    """Extract text from ToolResponse content (may be dict or object)."""
    item = resp.content[0]
    if isinstance(item, dict):
        return item["text"]
    return item.text


# ── global state helpers ──────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_shell_globals():
    """Reset global sandbox state before/after each test."""
    set_opensandbox_instance(None)
    set_cloud_working_dir("/workspace")
    yield
    set_opensandbox_instance(None)
    set_cloud_working_dir("/workspace")


def test_set_and_get_opensandbox_instance():
    assert get_opensandbox_instance() is None
    fake = MagicMock()
    set_opensandbox_instance(fake)
    assert get_opensandbox_instance() is fake


def test_set_and_get_cloud_working_dir():
    assert get_cloud_working_dir() == "/workspace"
    set_cloud_working_dir("/data")
    assert get_cloud_working_dir() == "/data"


# ── cloud execution success ──────────────────────────────────────────


async def test_execute_in_opensandbox_success():
    """When sandbox is set, commands execute in cloud."""
    sandbox = MagicMock()

    execution_result = SimpleNamespace(
        logs=SimpleNamespace(
            stdout=[SimpleNamespace(text="hello world\n")],
            stderr=[],
        ),
        error=None,
        result=[],
    )
    sandbox.commands = MagicMock()
    sandbox.commands.run = AsyncMock(return_value=execution_result)

    set_opensandbox_instance(sandbox)
    resp = await execute_shell_command("echo hello world", timeout=10)

    assert _get_text(resp) == "hello world\n"
    sandbox.commands.run.assert_awaited_once()


async def test_execute_in_opensandbox_with_error():
    """Cloud command that returns an error."""
    sandbox = MagicMock()

    execution_result = SimpleNamespace(
        logs=SimpleNamespace(
            stdout=[],
            stderr=[SimpleNamespace(text="permission denied")],
        ),
        error=SimpleNamespace(name="PermissionError", value="denied"),
        result=[],
    )
    sandbox.commands = MagicMock()
    sandbox.commands.run = AsyncMock(return_value=execution_result)

    set_opensandbox_instance(sandbox)
    resp = await execute_shell_command("cat /etc/shadow", timeout=10)

    text = _get_text(resp)
    assert "failed" in text.lower() or "permission denied" in text.lower()


async def test_execute_in_opensandbox_uses_cloud_cwd():
    """Cloud execution uses cloud_working_dir when cwd is not specified."""
    sandbox = MagicMock()

    execution_result = SimpleNamespace(
        logs=SimpleNamespace(
            stdout=[SimpleNamespace(text="/custom/dir\n")],
            stderr=[],
        ),
        error=None,
        result=[],
    )
    sandbox.commands = MagicMock()
    sandbox.commands.run = AsyncMock(return_value=execution_result)

    set_opensandbox_instance(sandbox)
    set_cloud_working_dir("/custom/dir")

    await execute_shell_command("pwd", timeout=10)

    call_args = sandbox.commands.run.call_args
    opts = call_args.kwargs.get("opts") or call_args[1].get("opts")
    assert opts.working_directory == "/custom/dir"


# ── fallback to local ────────────────────────────────────────────────


async def test_fallback_to_local_on_exception(tmp_path):
    """When cloud execution raises, falls back to local subprocess."""
    sandbox = MagicMock()
    sandbox.commands = MagicMock()
    sandbox.commands.run = AsyncMock(side_effect=Exception("connection lost"))

    set_opensandbox_instance(sandbox)
    resp = await execute_shell_command(
        "echo fallback", timeout=10, cwd=tmp_path,
    )

    # Should succeed via local execution
    text = _get_text(resp)
    assert "fallback" in text


async def test_local_execution_when_no_sandbox(tmp_path):
    """Without sandbox set, commands run locally."""
    assert get_opensandbox_instance() is None
    resp = await execute_shell_command(
        "echo local_test", timeout=10, cwd=tmp_path,
    )
    assert "local_test" in _get_text(resp)
