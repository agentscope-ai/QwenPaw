# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from qwenpaw.app.routers import git as git_router
from qwenpaw.utils.command_runner import CommandResult


@pytest.mark.asyncio
async def test_git_helper_uses_shared_command_runner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    recorded: dict[str, Any] = {}

    async def fake_run_command_async(command, **kwargs):
        recorded["command"] = list(command)
        recorded["kwargs"] = kwargs
        return CommandResult(
            command=list(command),
            returncode=0,
            stdout="ok",
            stderr="",
        )

    monkeypatch.setattr(
        git_router,
        "run_command_async",
        fake_run_command_async,
    )

    rc, out, err = await git_router._git(tmp_path, "status")

    assert (rc, out, err) == (0, "ok", "")
    assert recorded["command"] == ["git", "status"]
    assert recorded["kwargs"] == {
        "cwd": str(tmp_path),
        "encoding": "utf-8",
        "errors": "replace",
        "check": False,
        "timeout": None,
    }
