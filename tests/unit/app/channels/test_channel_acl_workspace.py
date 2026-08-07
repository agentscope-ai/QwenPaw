# -*- coding: utf-8 -*-
"""Unit tests for BaseChannel._get_acl_store workspace resolution.

Regression test for:
https://github.com/agentscope-ai/QwenPaw/issues/6786

When multica starts a new task via ACP, the channel's current workspace
points to a fresh per-task directory whose access_control.json is empty.
The ACL store must therefore resolve to the agent's *root profile* workspace
directory (shared across all task instances), not the per-task directory.
"""

from __future__ import annotations

# pylint: disable=protected-access,redefined-outer-name,unused-argument

from pathlib import Path
from typing import Optional

import pytest

from qwenpaw.app.channels.access_control import (
    ACCESS_CONTROL_FILE,
    get_access_control_store,
)
from qwenpaw.app.channels.base import BaseChannel


class _DummyWorkspace:
    """Minimal stand-in for a Workspace with a per-task directory."""

    def __init__(self, agent_id: str, workspace_dir: str):
        self.agent_id = agent_id
        self.workspace_dir = workspace_dir


class _MinimalChannel(BaseChannel):
    """Concrete BaseChannel subclass for testing _get_acl_store."""

    channel = "test"

    def __init__(self, *args, **kwargs):
        # Provide a dummy ProcessHandler callable
        if "process" not in kwargs:
            kwargs["process"] = lambda _: (_ for _ in ()).throw(
                StopIteration,
            )
        super().__init__(*args, **kwargs)

    def _process(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError

    def process(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError

    def _get_agent_id(self) -> Optional[str]:
        return None


@pytest.fixture
def channel(monkeypatch):
    """A channel wired to a per-task workspace."""
    ch = _MinimalChannel()
    ch._workspace = _DummyWorkspace("default", "/tmp/per-task-ws")
    return ch


def test_uses_root_profile_workspace_dir_when_agent_config_loads(
    channel,
    monkeypatch,
    tmp_path,
):
    """ACL store must point at the root profile workspace, not per-task."""
    root_ws = tmp_path / "root-ws"
    root_ws.mkdir()

    class _FakeProfile:
        workspace_dir = str(root_ws)

    imported = {}

    def fake_load_agent_config(agent_id):
        imported["agent_id"] = agent_id
        return _FakeProfile()

    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        fake_load_agent_config,
    )

    store = channel._get_acl_store()

    assert imported["agent_id"] == "default"
    # Store must be keyed on the root profile workspace directory.
    expected_key = str(root_ws.resolve())
    assert str(store._path.parent.resolve()) == expected_key
    assert store._path.name == ACCESS_CONTROL_FILE


def test_falls_back_to_workspace_dir_when_config_lookup_fails(
    channel,
    monkeypatch,
):
    """If agent config lookup raises, fall back to the current workspace."""
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda agent_id: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    store = channel._get_acl_store()

    expected_key = str(Path("/tmp/per-task-ws").resolve())
    assert str(store._path.parent.resolve()) == expected_key


def test_shared_store_across_multiple_task_workspaces(
    monkeypatch,
    tmp_path,
):
    """Two channels with different per-task dirs share one ACL store."""
    root_ws = tmp_path / "root-ws"
    root_ws.mkdir()

    class _FakeProfile:
        workspace_dir = str(root_ws)

    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda agent_id: _FakeProfile(),
    )

    ch1 = _MinimalChannel()
    ch1._workspace = _DummyWorkspace("default", "/tmp/task-1")
    ch2 = _MinimalChannel()
    ch2._workspace = _DummyWorkspace("default", "/tmp/task-2")

    store1 = ch1._get_acl_store()
    store2 = ch2._get_acl_store()

    assert store1 is store2
    # Approving a user on one task workspace is visible on the other.
    store1.add_to_whitelist("test", "u1")
    assert store2.is_whitelisted("test", "u1")
