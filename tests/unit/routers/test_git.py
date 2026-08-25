# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from qwenpaw.app.routers import git as git_router
from qwenpaw.app.routers.git import CommitRequest
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


def _isolate_git_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Force empty-ident: no global/system identity, no GECOS derive."""
    home = tmp_path / "fakehome"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home / ".gitconfig"))
    # Use an empty temp file for GIT_CONFIG_SYSTEM instead of /dev/null:
    # git ≥ 2.39 rejects /dev/null as "bad config line 1" because it
    # expects a valid (possibly empty) config file, not a device node.
    empty_system_config = tmp_path / "empty_git_system_config"
    empty_system_config.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", str(empty_system_config))
    # Clear author/committer overrides that CI or the developer shell may set.
    for key in (
        "GIT_AUTHOR_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_NAME",
        "GIT_COMMITTER_EMAIL",
    ):
        monkeypatch.delenv(key, raising=False)

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(
        [
            "git",
            "config",
            "--global",
            "user.useConfigOnly",
            "true",
        ],
        check=True,
        env={
            **os.environ,
            "HOME": str(home),
            "GIT_CONFIG_GLOBAL": str(home / ".gitconfig"),
            "GIT_CONFIG_SYSTEM": str(empty_system_config),
        },
    )
    (repo / "a.txt").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    return repo


@pytest.mark.asyncio
async def test_commit_with_identity_succeeds_without_global_gitconfig(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Regression for bug 84580657: commit must inject product identity."""
    repo = _isolate_git_env(tmp_path, monkeypatch)

    # Control: plain commit fails under empty-ident conditions.
    plain_rc, _, plain_err = await git_router._git(
        repo,
        "commit",
        "-m",
        "plain commit",
    )
    assert plain_rc != 0
    assert (
        "identity" in plain_err.lower() or "empty ident" in plain_err.lower()
    )

    # Product path: same identity args used by commit/init/revert.
    ok_rc, _, ok_err = await git_router._git(
        repo,
        *git_router._GIT_IDENTITY_ARGS,
        "commit",
        "-m",
        "injected",
    )
    assert ok_rc == 0, ok_err


@pytest.mark.asyncio
async def test_commit_endpoint_passes_identity_args(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    recorded: dict[str, Any] = {}

    async def fake_run_command_async(command, **_kwargs):
        recorded["command"] = list(command)
        return CommandResult(
            command=list(command),
            returncode=0,
            stdout="[main abc1234] msg",
            stderr="",
        )

    async def fake_get_agent(_request):
        return MagicMock()

    monkeypatch.setattr(
        git_router,
        "run_command_async",
        fake_run_command_async,
    )
    monkeypatch.setattr(git_router, "get_agent_for_request", fake_get_agent)

    async def fake_get_project_dir(_request, _workspace):
        return tmp_path

    monkeypatch.setattr(
        git_router,
        "get_project_dir_for_request",
        fake_get_project_dir,
    )

    result = await git_router.commit_changes(
        CommitRequest(message="fix identity"),
        MagicMock(),
    )

    assert result["committed"] is True
    assert recorded["command"] == [
        "git",
        "-c",
        "user.email=qwenpaw@localhost",
        "-c",
        "user.name=QwenPaw",
        "commit",
        "-m",
        "fix identity",
    ]
