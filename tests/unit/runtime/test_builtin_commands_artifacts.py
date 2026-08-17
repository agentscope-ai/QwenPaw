# -*- coding: utf-8 -*-
"""Tests for native conversation-command artifact state persistence."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from agentscope.message import Msg, TextBlock
from agentscope.state import AgentState

from qwenpaw.app.chats.session import SafeJSONSession
from qwenpaw.runtime._state_utils import StateProxy
from qwenpaw.runtime.builtin_commands import (
    _make_conversation_adapter,
    _save_agent_state,
)


class RecordingSession:
    """Capture the state payload passed to the session layer."""

    def __init__(self) -> None:
        self.saved: dict | None = None

    async def save_session_state(self, **kwargs) -> None:
        self.saved = kwargs["agent"].state_dict()


@pytest.mark.asyncio
async def test_reset_agent_state_clears_artifact_extensions() -> None:
    session = RecordingSession()
    ctx = SimpleNamespace(
        workspace=SimpleNamespace(session=session),
        request=None,
        session_id="chat-1",
        mode_state={},
    )

    await _save_agent_state(
        ctx,
        AgentState(),
        reset_artifacts=True,
    )

    assert session.saved is not None
    assert session.saved["workspace_artifact_manifests"] == []
    assert session.saved["workspace_artifact_roots"] == {}


@pytest.mark.asyncio
async def test_partial_agent_state_save_does_not_reset_artifacts() -> None:
    session = RecordingSession()
    ctx = SimpleNamespace(
        workspace=SimpleNamespace(session=session),
        request=None,
        session_id="chat-1",
        mode_state={},
    )

    await _save_agent_state(ctx, AgentState())

    assert session.saved is not None
    assert "workspace_artifact_manifests" not in session.saved
    assert "workspace_artifact_roots" not in session.saved


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["clear", "new"])
async def test_reset_command_clears_persisted_artifacts(
    command: str,
    tmp_path: Path,
) -> None:
    session = SafeJSONSession(str(tmp_path))
    proxy = StateProxy()
    proxy.data = {
        "state": AgentState().model_dump(mode="json"),
        "workspace_artifact_manifests": [
            {"version": 3, "turn_id": "turn-1"},
        ],
        "workspace_artifact_roots": {
            "root-pinned": {"root": "project", "path": str(tmp_path)},
        },
    }
    await session.save_session_state(
        session_id="chat-1",
        user_id="user-1",
        agent=proxy,
    )
    ctx = SimpleNamespace(
        workspace=SimpleNamespace(
            session=session,
            workspace_dir=tmp_path,
            memory_manager=None,
        ),
        request=SimpleNamespace(user_id="user-1", channel=""),
        session_id="chat-1",
        agent_id="agent-1",
        mode_state={},
    )

    await _make_conversation_adapter(command).handler(ctx, "")

    persisted = await session.get_session_state_dict("chat-1", "user-1")
    assert persisted["agent"]["workspace_artifact_manifests"] == []
    assert persisted["agent"]["workspace_artifact_roots"] == {}


@pytest.mark.asyncio
async def test_failed_new_command_preserves_persisted_artifacts(
    tmp_path: Path,
) -> None:
    session = SafeJSONSession(str(tmp_path))
    state = AgentState()
    state.context.append(
        Msg(
            name="user",
            role="user",
            content=[TextBlock(type="text", text="hello")],
        ),
    )
    manifests = [{"version": 3, "turn_id": "turn-1"}]
    proxy = StateProxy()
    proxy.data = {
        "state": state.model_dump(mode="json"),
        "workspace_artifact_manifests": manifests,
        "workspace_artifact_roots": {
            "root-pinned": {"root": "project", "path": str(tmp_path)},
        },
    }
    await session.save_session_state(
        session_id="chat-1",
        user_id="user-1",
        agent=proxy,
    )
    ctx = SimpleNamespace(
        workspace=SimpleNamespace(
            session=session,
            workspace_dir=tmp_path,
            memory_manager=None,
        ),
        request=SimpleNamespace(user_id="user-1", channel=""),
        session_id="chat-1",
        agent_id="agent-1",
        mode_state={},
    )

    await _make_conversation_adapter("new").handler(ctx, "")

    persisted = await session.get_session_state_dict("chat-1", "user-1")
    assert persisted["agent"]["workspace_artifact_manifests"] == manifests
    assert "root-pinned" in persisted["agent"]["workspace_artifact_roots"]
