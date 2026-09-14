# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Verify capability delivery to the existing sandbox boundary."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from qwenpaw.sandbox.config import SandboxConfig, SandboxMode
from qwenpaw.utils.runtime_api import TOOL_ORIGIN_ENV, TOOL_TOKEN_ENV


@pytest.mark.asyncio
async def test_shell_passes_only_current_capability_to_sandbox(
    monkeypatch,
    tmp_path,
):
    from qwenpaw.agents.tools import shell
    from qwenpaw import sandbox as sandbox_module

    config = SandboxConfig(
        mode=SandboxMode.NONE,
        workspace_dir=str(tmp_path),
        env_vars={TOOL_TOKEN_ENV: "stale-config", "OTHER_POLICY": "preserved"},
    )
    current = {
        "PATH": "fixture-path",
        "QWENPAW_RUNTIME_ID": "desktop-tool",
        TOOL_TOKEN_ENV: "current-token",
        TOOL_ORIGIN_ENV: "http://127.0.0.1:8765",
    }
    captured = []

    def create(effective):
        captured.append(effective.env_vars)
        instance = MagicMock()
        instance.execute = AsyncMock(
            return_value=sandbox_module.ExecutionResult(
                exit_code=0,
                stdout="",
                stderr="",
            ),
        )
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=None)
        return instance

    monkeypatch.setattr(sandbox_module, "create_sandbox", create)
    await shell._execute_in_sandbox(
        "fixture",
        config,
        10,
        str(tmp_path),
        current,
    )
    assert captured == [{**current, "OTHER_POLICY": "preserved"}]
    assert config.env_vars[TOOL_TOKEN_ENV] == "stale-config"
