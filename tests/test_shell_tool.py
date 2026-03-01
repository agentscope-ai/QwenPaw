# -*- coding: utf-8 -*-
import sys

import pytest

from copaw.agents.tools.shell import execute_shell_command


def _first_text(resp) -> str:
    assert resp.content, "Expected ToolResponse.content to be non-empty"
    block = resp.content[0]

    if isinstance(block, dict):
        assert "text" in block, (
            "Expected 'text' key in dict content block, "
            f"got keys={list(block.keys())}"
        )
        return block["text"]

    assert hasattr(block, "text"), (
        "Expected TextBlock-like content block, " f"got {type(block)}"
    )
    return block.text


@pytest.mark.asyncio
async def test_execute_shell_command_large_stdout_does_not_timeout():
    code = "".join(
        [
            "import sys; ",
            "sys.stdout.write('x'*200000); ",
            "sys.stdout.flush()",
        ],
    )
    cmd = f'"{sys.executable}" -c "{code}"'

    resp = await execute_shell_command(cmd, timeout=5)
    text = _first_text(resp)

    assert "TimeoutError" not in text
    assert "Command failed" not in text
    assert len(text) > 1000


@pytest.mark.asyncio
async def test_execute_shell_command_empty_command_is_handled():
    resp = await execute_shell_command("   ")
    text = _first_text(resp).strip()
    assert text == "No command provided."
