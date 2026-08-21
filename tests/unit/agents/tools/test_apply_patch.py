# -*- coding: utf-8 -*-
"""Tool-level contracts for apply_patch and managed terminal interaction."""

from __future__ import annotations

import sys

import pytest
from agentscope.tool import FunctionTool

from qwenpaw.agents.tools.apply_patch import apply_patch
from qwenpaw.agents.tools.shell import execute_shell_command, write_stdin
from qwenpaw.config.context import (
    current_project_dir,
    current_shell_command_executable,
    current_terminal_manager,
)
from qwenpaw.terminal import TerminalSessionManager


def test_managed_terminal_schema_accepts_provider_numeric_strings():
    execute_properties = FunctionTool(execute_shell_command).input_schema[
        "properties"
    ]
    stdin_properties = FunctionTool(write_stdin).input_schema["properties"]

    for properties, name in (
        (execute_properties, "yield_time_ms"),
        (execute_properties, "max_output_bytes"),
        (stdin_properties, "yield_time_ms"),
        (stdin_properties, "max_output_bytes"),
    ):
        types = {
            branch.get("type")
            for branch in properties[name].get("anyOf", [properties[name]])
        }
        assert "integer" in types
        assert "string" in types

    assert stdin_properties["interrupt"]["type"] == "boolean"
    assert execute_properties["input_mode"]["enum"] == ["line", "raw"]


@pytest.mark.asyncio
async def test_apply_patch_tool_returns_structured_success(tmp_path):
    (tmp_path / "value.txt").write_text("before\n", encoding="utf-8")
    token = current_project_dir.set(tmp_path)
    try:
        result = await apply_patch(
            """*** Begin Patch
*** Update File: value.txt
@@
-before
+after
*** Add File: added.txt
+new
*** End Patch""",
        )
    finally:
        current_project_dir.reset(token)

    assert result.metadata["status"] == "applied"
    assert result.metadata["hunks_applied"] == 1
    assert (tmp_path / "value.txt").read_text(encoding="utf-8") == "after\n"
    assert (tmp_path / "added.txt").read_text(encoding="utf-8") == "new\n"


@pytest.mark.asyncio
async def test_apply_patch_tool_reports_conflict_without_writing(tmp_path):
    path = tmp_path / "value.txt"
    path.write_bytes(b"actual\n")
    token = current_project_dir.set(tmp_path)
    try:
        result = await apply_patch(
            """*** Begin Patch
*** Update File: value.txt
@@
-expected
+changed
*** End Patch""",
        )
    finally:
        current_project_dir.reset(token)

    assert result.metadata["status"] == "conflict"
    assert result.metadata["conflicts"][0]["code"] == "context_mismatch"
    assert path.read_bytes() == b"actual\n"


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX PTY behavior")
async def test_shell_tools_reuse_and_terminate_managed_session(tmp_path):
    manager = TerminalSessionManager(tmp_path)
    manager_token = current_terminal_manager.set(manager)
    project_token = current_project_dir.set(tmp_path)
    shell_token = current_shell_command_executable.set("/bin/sh")
    try:
        first = await execute_shell_command(
            "export TOOL_SESSION_VALUE=retained; cd /",
            persistent=True,
            yield_time_ms="2000",
        )
        session_id = first.metadata["session_id"]
        assert session_id
        assert f"session_id={session_id}" in first.content[0].text
        assert "running=false" in first.content[0].text
        assert "tty=true" in first.content[0].text
        assert "degraded=false" in first.content[0].text
        second = await execute_shell_command(
            'printf "%s:%s" "$TOOL_SESSION_VALUE" "$PWD"',
            session_id=session_id,
            persistent=True,
            yield_time_ms="2000",
            max_output_bytes="4096",
        )
        assert second.metadata["exit_code"] == 0
        assert "retained:/" in second.content[0].text
        assert f"session_id={session_id}" in second.content[0].text

        terminated = await write_stdin(session_id, terminate=True)
        assert terminated.metadata["session_id"] is None
        assert manager.active_sessions == 0
    finally:
        await manager.shutdown()
        current_shell_command_executable.reset(shell_token)
        current_project_dir.reset(project_token)
        current_terminal_manager.reset(manager_token)


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX PTY behavior")
async def test_shell_tools_drive_interactive_program(tmp_path):
    manager = TerminalSessionManager(tmp_path)
    manager_token = current_terminal_manager.set(manager)
    project_token = current_project_dir.set(tmp_path)
    shell_token = current_shell_command_executable.set("/bin/sh")
    try:
        first = await execute_shell_command(
            'python -u -c \'value=input("name: "); '
            'print("hello " + value, flush=True)\'',
            persistent=True,
            yield_time_ms=100,
        )
        session_id = first.metadata["session_id"]
        assert first.metadata["running"] is True

        final = await write_stdin(
            session_id,
            chars="QwenPaw\n",
            yield_time_ms=2_000,
        )

        assert final.metadata["running"] is False
        assert final.metadata["exit_code"] == 0
        complete = first.content[0].text + "\n" + final.content[0].text
        assert "name: " in complete
        assert "hello QwenPaw" in complete
        assert "__qwenpaw_ec" not in complete
        assert "QWENPAW_DONE_" not in complete
        await write_stdin(session_id, terminate=True)
    finally:
        await manager.shutdown()
        current_shell_command_executable.reset(shell_token)
        current_project_dir.reset(project_token)
        current_terminal_manager.reset(manager_token)


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX PTY behavior")
@pytest.mark.parametrize(
    ("ctrl_c", "interrupt"),
    [
        ("\x03", False),
        (r"\u0003", False),
        (r"\x03", False),
        ("&#x3;", False),
        ("", True),
    ],
)
async def test_shell_tools_interrupt_and_reuse_session(
    tmp_path,
    ctrl_c,
    interrupt,
):
    manager = TerminalSessionManager(tmp_path)
    manager_token = current_terminal_manager.set(manager)
    project_token = current_project_dir.set(tmp_path)
    shell_token = current_shell_command_executable.set("/bin/sh")
    try:
        first = await execute_shell_command(
            "sleep 30",
            persistent=True,
            yield_time_ms=100,
            timeout=60,
        )
        session_id = first.metadata["session_id"]
        assert first.metadata["running"] is True

        interrupted = await write_stdin(
            session_id,
            chars=ctrl_c,
            yield_time_ms=2_000,
            interrupt=interrupt,
        )
        assert interrupted.metadata["running"] is False
        assert interrupted.metadata["exit_code"] == 130

        repeated = await write_stdin(
            session_id,
            interrupt=True,
            yield_time_ms=0,
        )
        assert repeated.metadata["running"] is False
        assert repeated.metadata["exit_code"] == 130

        follow_up = await execute_shell_command(
            "printf alive",
            session_id=session_id,
            persistent=True,
            yield_time_ms=2_000,
        )
        assert follow_up.metadata["exit_code"] == 0
        assert "alive" in follow_up.content[0].text

        terminated = await write_stdin(session_id, terminate=True)
        assert terminated.metadata["session_id"] is None
        assert manager.active_sessions == 0
    finally:
        await manager.shutdown()
        current_shell_command_executable.reset(shell_token)
        current_project_dir.reset(project_token)
        current_terminal_manager.reset(manager_token)


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX PTY behavior")
async def test_shell_tools_report_and_drain_bounded_large_output(tmp_path):
    manager = TerminalSessionManager(tmp_path)
    manager_token = current_terminal_manager.set(manager)
    project_token = current_project_dir.set(tmp_path)
    shell_token = current_shell_command_executable.set("/bin/sh")
    try:
        result = await execute_shell_command(
            "python -u -c 'import sys; "
            'sys.stdout.write("x" * 2000000); sys.stdout.flush()\'',
            persistent=True,
            yield_time_ms=100,
            max_output_bytes=4096,
        )
        session_id = result.metadata["session_id"]
        delivered = 0
        omitted = 0

        for _ in range(600):
            delivered += result.metadata["output_bytes"]
            omitted += result.metadata["omitted_bytes"]
            assert result.metadata["output_bytes"] <= 4096
            for field in (
                "original_bytes",
                "omitted_bytes",
                "output_bytes",
                "pending_bytes",
                "output_drained",
            ):
                assert f"{field}=" in result.content[0].text
            if result.metadata["output_drained"]:
                break
            result = await write_stdin(
                session_id,
                yield_time_ms=100,
                max_output_bytes=4096,
            )
        else:
            pytest.fail("large-output terminal did not drain")

        assert result.metadata["running"] is False
        assert result.metadata["exit_code"] == 0
        assert result.metadata["original_bytes"] == 2_000_000
        assert result.metadata["pending_bytes"] == 0
        assert delivered + omitted == 2_000_000

        terminated = await write_stdin(session_id, terminate=True)
        assert terminated.metadata["terminated"] is True
        assert terminated.metadata["exit_code"] is None
        assert "exit code -9" not in terminated.content[0].text
    finally:
        await manager.shutdown()
        current_shell_command_executable.reset(shell_token)
        current_project_dir.reset(project_token)
        current_terminal_manager.reset(manager_token)


@pytest.mark.asyncio
async def test_managed_shell_fails_closed_for_current_sandbox(tmp_path):
    from qwenpaw.sandbox import SandboxConfig, SandboxMode

    result = await execute_shell_command(
        "echo blocked",
        cwd=tmp_path,
        persistent=True,
        sandbox_config=SandboxConfig(
            mode=SandboxMode.NONE,
            workspace_dir=str(tmp_path),
        ),
    )

    assert result.metadata["error_code"] == "interactive_sandbox_unsupported"
