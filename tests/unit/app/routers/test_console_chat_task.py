# -*- coding: utf-8 -*-
"""Regression tests for background console task completion."""
# pylint: disable=protected-access,unused-argument
from __future__ import annotations

import asyncio
import json
import stat
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, AsyncGenerator

import pytest

from qwenpaw.agents import fork_project
from qwenpaw.agents.fork_project import (
    REGISTRY_REL,
    begin_fork_scope,
    register_fork,
)
from qwenpaw.app.routers import console
from qwenpaw.app.task_tracker import TaskTracker


@dataclass(frozen=True)
class _Fork:
    project: Path
    worktree: Path
    branch: str
    scope: str
    base_head: str


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _create_fork(tmp_path: Path, name: str) -> _Fork:
    project = tmp_path / "repo"
    project.mkdir()
    _git(project, "init", "-q")
    _git(project, "config", "user.name", "QwenPaw Test")
    _git(project, "config", "user.email", "test@example.invalid")
    (project / "README.md").write_text("base\n", encoding="utf-8")
    _git(project, "add", "README.md")
    _git(project, "commit", "-qm", "base")

    scope = begin_fork_scope(project)
    branch = f"fork/{name}"
    worktree = project / ".qwenpaw" / "worktrees" / name
    worktree.parent.mkdir(parents=True, exist_ok=True)
    _git(project, "worktree", "add", "-q", str(worktree), "-b", branch)
    assert register_fork(
        str(worktree),
        branch,
        workspace_dir=project,
        scope_id=scope,
    )
    base_head = _git(worktree, "rev-parse", "HEAD").stdout.strip()
    (worktree / "result.txt").write_text(
        "subagent output\n",
        encoding="utf-8",
    )
    return _Fork(project, worktree, branch, scope, base_head)


def _install_hook(fork: _Fork, tmp_path: Path, body: str) -> None:
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    hook = hooks / "pre-commit"
    hook.write_text(
        f"#!/bin/sh\n{body}",
        encoding="utf-8",
        newline="\n",
    )
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR)
    _git(fork.worktree, "config", "core.hooksPath", str(hooks))


class _ChatManager:
    async def get_or_create_chat(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> SimpleNamespace:
        return SimpleNamespace(id="test-chat", meta={})

    async def mark_chat_finished(self, chat_id: str, finish_time: Any) -> None:
        """Match the production completion callback used by TaskTracker."""


class _ConsoleChannel:
    def resolve_session_id(
        self,
        *,
        sender_id: str,
        channel_meta: dict[str, Any],
    ) -> str:
        return channel_meta["session_id"]

    async def stream_one(
        self,
        payload: dict[str, Any],
    ) -> AsyncGenerator[str, None]:
        yield 'data: {"type":"message","output":[]}\n\n'


class _ChannelManager:
    async def get_channel(self, name: str) -> _ConsoleChannel | None:
        return _ConsoleChannel() if name == "console" else None


class _Workspace:
    def __init__(self, workspace_dir: Path) -> None:
        self.agent_id = "test-agent"
        self.workspace_dir = workspace_dir
        self.chat_manager = _ChatManager()
        self.channel_manager = _ChannelManager()
        self.task_tracker = TaskTracker()


@pytest.fixture(autouse=True)
def _clear_background_tasks():
    console._bg_tasks.clear()
    yield
    console._bg_tasks.clear()


async def _submit_forked_task(
    monkeypatch: pytest.MonkeyPatch,
    *,
    worktree: str | Path,
    branch: str,
    scope: str | None = None,
    timeout: float | None = None,
) -> tuple[str, asyncio.Task]:
    async def _get_workspace(_request):
        return _Workspace(Path(worktree))

    monkeypatch.setattr(console, "get_agent_for_request", _get_workspace)
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda _agent_id: SimpleNamespace(project_dir=None),
    )
    request_context = {
        "fork_project_dir": str(worktree),
        "fork_worktree_branch": branch,
    }
    if scope is not None:
        request_context["fork_scope_id"] = scope
    payload: dict[str, Any] = {
        "channel": "console",
        "user_id": "test-user",
        "session_id": "test-session",
        "input": [
            {
                "role": "user",
                "type": "message",
                "content": [{"type": "text", "text": "run"}],
            },
        ],
        "request_context": request_context,
    }
    if timeout is not None:
        payload["timeout"] = timeout

    submitted = await console.post_console_chat_task(payload, None)
    task_id = submitted["task_id"]
    background_task = console._bg_tasks[task_id].asyncio_task
    assert background_task is not None
    return task_id, background_task


async def _wait_for_file(path: Path) -> None:
    for _ in range(100):
        if path.exists():
            return
        await asyncio.sleep(0.05)
    pytest.fail(f"file was not created: {path.name}")


async def _wait_for_task_to_finish(task_id: str) -> dict[str, Any]:
    for _ in range(200):
        task = await console.get_console_chat_task(task_id)
        if task["status"] == "finished":
            return task
        await asyncio.sleep(0.05)
    raise TimeoutError(f"background task did not finish: {task_id}")


async def _wait_for_fork_status(
    project: Path,
    branch: str,
    status: str,
) -> dict[str, Any]:
    registry_path = project / REGISTRY_REL
    for _ in range(200):
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        if registry["forks"][branch]["status"] == status:
            return registry
        await asyncio.sleep(0.05)
    raise TimeoutError(f"fork {branch} did not reach status {status}")


async def _wait_for_thread_event(event: threading.Event) -> None:
    for _ in range(200):
        if event.is_set():
            return
        await asyncio.sleep(0.05)
    raise TimeoutError("threading event was not set")


@pytest.mark.asyncio
async def test_forked_task_reports_failed_when_worktree_cannot_be_finalized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fork without a deliverable commit must be reported as failed."""
    fork = _create_fork(tmp_path, "finalize-failure")
    _install_hook(fork, tmp_path, "exit 1\n")
    task_id, background_task = await _submit_forked_task(
        monkeypatch,
        worktree=fork.worktree,
        branch=fork.branch,
        scope=fork.scope,
    )

    await asyncio.wait_for(background_task, timeout=10)
    task = await console.get_console_chat_task(task_id)
    registry = json.loads(
        (fork.project / REGISTRY_REL).read_text(encoding="utf-8"),
    )
    fork_head = _git(fork.worktree, "rev-parse", "HEAD").stdout.strip()

    assert (
        task["status"],
        task["result"]["status"],
        registry["forks"][fork.branch]["status"],
        fork_head,
        (fork.worktree / "result.txt").read_text(encoding="utf-8"),
    ) == (
        "finished",
        "failed",
        "failed",
        fork.base_head,
        "subagent output\n",
    )


@pytest.mark.asyncio
async def test_forked_task_reports_failed_when_worktree_finalization_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A finalizer exception must fail both the task and fork registry."""
    fork = _create_fork(tmp_path, "finalize-exception")

    def _raise_git_error(*args: Any, **kwargs: Any) -> bool:
        raise OSError("simulated git failure")

    monkeypatch.setattr(
        fork_project,
        "commit_dirty_worktree",
        _raise_git_error,
    )
    task_id, background_task = await _submit_forked_task(
        monkeypatch,
        worktree=fork.worktree,
        branch=fork.branch,
        scope=fork.scope,
    )

    await asyncio.wait_for(background_task, timeout=10)
    task = await console.get_console_chat_task(task_id)
    registry = json.loads(
        (fork.project / REGISTRY_REL).read_text(encoding="utf-8"),
    )

    assert (
        task["result"]["status"],
        registry["forks"][fork.branch]["status"],
        (fork.worktree / "result.txt").read_text(encoding="utf-8"),
    ) == ("failed", "failed", "subagent output\n")


@pytest.mark.asyncio
async def test_forked_task_timeout_during_finalization_stays_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Timeout during Git finalize must publish failed/timeout immediately.

    The in-flight commit may still finish as bookkeeping, but it must not
    rewrite the task API result back to completed.
    """
    fork = _create_fork(tmp_path, "finalize-timeout")
    _install_hook(
        fork,
        tmp_path,
        "touch .hook-started\n"
        "while [ ! -f .hook-release ]; do sleep 0.05; done\n",
    )
    task_id, background_task = await _submit_forked_task(
        monkeypatch,
        worktree=fork.worktree,
        branch=fork.branch,
        scope=fork.scope,
        timeout=3.0,
    )
    try:
        await _wait_for_file(fork.worktree / ".hook-started")
        timed_out = await _wait_for_task_to_finish(task_id)
        error = (timed_out.get("result") or {}).get("error") or {}
        assert timed_out["status"] == "finished"
        assert timed_out["result"]["status"] == "failed"
        assert error.get("code") == "timeout"

        (fork.worktree / ".hook-release").touch()
        await asyncio.wait_for(background_task, timeout=10)
        # Detached Git may still commit; the task result must stay timeout.
        after_release = await console.get_console_chat_task(task_id)
        after_error = (after_release.get("result") or {}).get("error") or {}
        assert after_release["status"] == "finished"
        assert after_release["result"]["status"] == "failed"
        assert after_error.get("code") == "timeout"
    finally:
        (fork.worktree / ".hook-release").touch(exist_ok=True)
        await asyncio.gather(background_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_timeout_then_detached_finalize_exception_marks_registry_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A later finalize exception must not leave the registry finalizing."""
    fork = _create_fork(tmp_path, "finalize-timeout-exc")
    started = threading.Event()
    release = threading.Event()

    def _blocked_then_raise(*_args: Any, **_kwargs: Any) -> bool:
        started.set()
        if not release.wait(timeout=10):
            raise TimeoutError("test did not release finalize")
        raise OSError("simulated git failure")

    monkeypatch.setattr(
        fork_project,
        "commit_dirty_worktree",
        _blocked_then_raise,
    )
    task_id, background_task = await _submit_forked_task(
        monkeypatch,
        worktree=fork.worktree,
        branch=fork.branch,
        scope=fork.scope,
        timeout=3.0,
    )
    try:
        await _wait_for_thread_event(started)
        timed_out = await _wait_for_task_to_finish(task_id)
        error = (timed_out.get("result") or {}).get("error") or {}
        assert timed_out["status"] == "finished"
        assert timed_out["result"]["status"] == "failed"
        assert error.get("code") == "timeout"
        mid = json.loads(
            (fork.project / REGISTRY_REL).read_text(encoding="utf-8"),
        )
        assert mid["forks"][fork.branch]["status"] == "finalizing"

        release.set()
        after_reg = await _wait_for_fork_status(
            fork.project,
            fork.branch,
            "failed",
        )
        after = await console.get_console_chat_task(task_id)
        after_error = (after.get("result") or {}).get("error") or {}
        assert after["status"] == "finished"
        assert after["result"]["status"] == "failed"
        assert after_error.get("code") == "timeout"
        assert after_reg["forks"][fork.branch]["status"] == "failed"
    finally:
        release.set()
        await asyncio.gather(background_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_forked_task_stays_running_until_worktree_is_finalized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Success is exposed only after the fork commit becomes deliverable."""
    fork = _create_fork(tmp_path, "finalize-success")
    _install_hook(
        fork,
        tmp_path,
        "touch .hook-started\n"
        "while [ ! -f .hook-release ]; do sleep 0.05; done\n",
    )
    task_id, background_task = await _submit_forked_task(
        monkeypatch,
        worktree=fork.worktree,
        branch=fork.branch,
        scope=fork.scope,
    )
    try:
        await _wait_for_file(fork.worktree / ".hook-started")
        in_progress = await console.get_console_chat_task(task_id)
        assert in_progress["status"] == "running"

        (fork.worktree / ".hook-release").touch()
        await asyncio.wait_for(background_task, timeout=10)
        completed = await console.get_console_chat_task(task_id)
        fork_head = _git(fork.worktree, "rev-parse", "HEAD").stdout.strip()

        assert (
            completed["status"],
            completed["result"]["status"],
            fork_head != fork.base_head,
        ) == ("finished", "completed", True)
    finally:
        (fork.worktree / ".hook-release").touch(exist_ok=True)
        await asyncio.gather(background_task, return_exceptions=True)
