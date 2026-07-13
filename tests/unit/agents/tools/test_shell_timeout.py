# -*- coding: utf-8 -*-
"""Tests for shell timeout propagation into Runtime 2.0 deadlines."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from qwenpaw.agents.tools.shell import execute_shell_command


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("requested_timeout", "configured_timeout", "expected_timeout"),
    [
        (60.0, 240.0, 240.0),
        (90.0, 240.0, 90.0),
    ],
)
async def test_effective_timeout_reschedules_coordinator_deadline(
    tmp_path,
    requested_timeout: float,
    configured_timeout: float,
    expected_timeout: float,
) -> None:
    sandbox_result = SimpleNamespace(
        sandbox_violation=None,
        exit_code=0,
        stdout="completed",
        stderr="",
    )

    with patch(
        "qwenpaw.agents.tools.shell.get_current_shell_command_timeout",
        return_value=configured_timeout,
    ), patch(
        "qwenpaw.agents.tools.shell.get_current_shell_command_executable",
        return_value=None,
    ), patch(
        "qwenpaw.agents.tools.shell.get_current_workspace_dir",
        return_value=tmp_path,
    ), patch(
        "qwenpaw.agents.tools.shell._execute_in_sandbox",
        AsyncMock(return_value=sandbox_result),
    ) as execute_in_sandbox, patch(
        "qwenpaw.tool_calls.reschedule_call_timeout",
    ) as reschedule:
        result = await execute_shell_command(
            "echo completed",
            timeout=requested_timeout,
            sandbox_config=SimpleNamespace(),
        )

    reschedule.assert_called_once_with(expected_timeout)
    assert execute_in_sandbox.await_args.args[2] == expected_timeout
    assert result.content[0].text == "completed"
