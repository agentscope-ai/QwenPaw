# -*- coding: utf-8 -*-
"""Session hook persistence behavior."""

from __future__ import annotations

import asyncio
import contextlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agentscope.message import Msg, TextBlock
from agentscope.state import AgentState

from qwenpaw.agents.acp.meta import ACP_EPHEMERAL_META_KEY
from qwenpaw.agents.react_agent import QwenPawAgent
from qwenpaw.app.chats.session import SafeJSONSession
from qwenpaw.hooks.session.session_hook import (
    SessionEarlySaveHook,
    SessionLoadHook,
    SessionSaveHook,
)
from qwenpaw.hooks.session.signals import SESSION_SAVE_SUCCEEDED_KEY
from qwenpaw.runtime.builder import AgentBuilder
from qwenpaw.runtime.hooks import HookRegistry
from qwenpaw.runtime.phases import Phase
from qwenpaw.runtime.runtime import Runtime
from qwenpaw.schemas import AgentRequest, Message, Role, TextContent

pytestmark = [pytest.mark.unit, pytest.mark.p1]


class _FakeSession:
    def __init__(self, *, save_error: Exception | None = None) -> None:
        self.loaded = False
        self.saved = False
        self.load_payload = {}
        self.saved_payload = {}
        self.save_error = save_error

    async def load_session_state(self, *args, **kwargs) -> None:
        del args
        self.loaded = True
        kwargs["agent"].load_state_dict(self.load_payload)

    async def save_session_state(self, *args, **kwargs) -> None:
        del args
        if self.save_error is not None:
            raise self.save_error
        self.saved = True
        self.saved_payload = kwargs["agent"].state_dict()


def _user_msg(text: str = "hello") -> Msg:
    """A single user message shaped like ``_request_input_to_msgs`` output."""
    return Msg(
        name="user",
        role="user",
        content=[TextBlock(type="text", text=text)],
    )


def _ctx(
    session: _FakeSession,
    *,
    ephemeral: bool,
    input_msgs: list | None = None,
):
    return SimpleNamespace(
        request=SimpleNamespace(
            request_context={ACP_EPHEMERAL_META_KEY: ephemeral},
            user_id="acp_warmup",
            channel="",
        ),
        workspace=SimpleNamespace(session=session),
        agent=SimpleNamespace(
            state_dict=lambda: {"state": {"context": []}},
        ),
        session_id="warmup-session",
        mode_state={},
        extras={},
        input_msgs=input_msgs or [],
    )


async def test_ephemeral_request_skips_session_load_and_save():
    session = _FakeSession()
    ctx = _ctx(session, ephemeral=True)

    await SessionLoadHook().run(ctx)
    await SessionSaveHook().run(ctx)

    assert session.loaded is False
    assert session.saved is False
    assert ctx.extras[SESSION_SAVE_SUCCEEDED_KEY] is False


async def test_normal_request_loads_and_saves_session_state():
    session = _FakeSession()
    session.load_payload = {
        "mode_state": {"mission": {"active": True}},
    }
    ctx = _ctx(session, ephemeral=False)

    await SessionLoadHook().run(ctx)
    await SessionSaveHook().run(ctx)

    assert session.loaded is True
    assert session.saved is True
    assert ctx.extras[SESSION_SAVE_SUCCEEDED_KEY] is True
    assert ctx.mode_state == {"mission": {"active": True}}
    assert session.saved_payload["mode_state"] == ctx.mode_state


async def test_failed_session_save_does_not_mark_turn_as_persisted():
    session = _FakeSession(save_error=RuntimeError("save failed"))
    ctx = _ctx(session, ephemeral=False)

    await SessionSaveHook().run(ctx)

    assert session.saved is False
    assert ctx.extras[SESSION_SAVE_SUCCEEDED_KEY] is False


# --- SessionEarlySaveHook (PRE_EXECUTE turn-start save) -------------------


def test_early_save_hook_runs_last_in_pre_execute():
    hook = SessionEarlySaveHook()
    assert hook.phase is Phase.PRE_EXECUTE
    assert hook.name == "session_early_save"
    # Higher priority = later within the phase; must run after the other
    # PRE_EXECUTE hooks (e.g. BootstrapHook=20) so the snapshot reflects
    # the final pre-execution state.
    assert hook.priority >= 90


async def test_early_save_hook_saves_current_input_at_turn_start():
    # A2 acceptance: the PRE_EXECUTE snapshot must already contain the
    # just-sent user message, even though execution has not committed it
    # to the live agent context yet.
    session = _FakeSession()
    ctx = _ctx(
        session,
        ephemeral=False,
        input_msgs=[_user_msg("CURRENT TURN")],
    )

    await SessionEarlySaveHook().run(ctx)

    assert session.saved is True
    context = session.saved_payload["state"]["context"]
    assert [msg["content"][0]["text"] for msg in context] == ["CURRENT TURN"]
    assert session.saved_payload["mode_state"] == ctx.mode_state


async def test_early_save_hook_projects_input_without_mutating_live_agent():
    # Execution appends ctx.input_msgs itself (via AgentScope
    # _handle_incoming_messages); the early save must not double-append.
    session = _FakeSession()
    live_context: list = []
    ctx = _ctx(
        session,
        ephemeral=False,
        input_msgs=[_user_msg("CURRENT TURN")],
    )
    ctx.agent = SimpleNamespace(
        state_dict=lambda: {"state": {"context": live_context}},
    )

    await SessionEarlySaveHook().run(ctx)

    assert session.saved is True
    context = session.saved_payload["state"]["context"]
    assert [msg["content"][0]["text"] for msg in context] == ["CURRENT TURN"]
    assert live_context == []


async def test_early_save_hook_with_no_input_persists_state_unchanged():
    session = _FakeSession()
    ctx = _ctx(session, ephemeral=False)

    await SessionEarlySaveHook().run(ctx)

    assert session.saved is True
    assert session.saved_payload["state"]["context"] == []
    assert session.saved_payload["mode_state"] == ctx.mode_state


async def test_post_response_save_does_not_project_input():
    # At POST_RESPONSE the input is already part of the live context; the
    # canonical save must persist that context verbatim, not re-append.
    session = _FakeSession()
    ctx = _ctx(
        session,
        ephemeral=False,
        input_msgs=[_user_msg("CURRENT TURN")],
    )

    await SessionSaveHook().run(ctx)

    assert session.saved is True
    assert session.saved_payload["state"]["context"] == []
    assert ctx.extras[SESSION_SAVE_SUCCEEDED_KEY] is True


async def test_early_save_hook_skips_ephemeral_request():
    session = _FakeSession()
    ctx = _ctx(session, ephemeral=True)

    await SessionEarlySaveHook().run(ctx)

    assert session.saved is False


async def test_early_save_hook_does_not_publish_success_key():
    # SESSION_SAVE_SUCCEEDED_KEY is reserved for the canonical
    # POST_RESPONSE save that CheckpointAutoSnapshotHook depends on.
    session = _FakeSession()
    ctx = _ctx(session, ephemeral=False)

    await SessionEarlySaveHook().run(ctx)

    assert session.saved is True
    assert SESSION_SAVE_SUCCEEDED_KEY not in ctx.extras


async def test_early_save_hook_swallows_save_errors():
    session = _FakeSession(save_error=RuntimeError("disk gone"))
    ctx = _ctx(session, ephemeral=False)

    # Must not raise — the turn has to proceed even when the early
    # snapshot cannot be written.
    await SessionEarlySaveHook().run(ctx)

    assert session.saved is False


# ---------------------------------------------------------------------------
# A2: mid-turn refresh persistence (production path)
# ---------------------------------------------------------------------------


def _pausing_agent(*, committed, release) -> QwenPawAgent:
    """A QwenPawAgent that uses real AgentScope input handling, then pauses.

    ``reply_stream`` commits its inputs to ``state.context`` through the
    real ``Agent._handle_incoming_messages`` — the same normalization the
    executor consumes — then blocks until *release* is set, i.e. a turn
    paused before model completion.  Built via ``object.__new__`` to skip
    the full constructor; only the attributes the session hooks touch are
    populated.
    """
    agent = object.__new__(QwenPawAgent)
    agent.state = AgentState()
    agent.name = "replay-agent"
    agent._context_manager = None
    agent._governor = None
    agent.offloader = None
    agent._agent_config = None

    async def reply_stream(inputs=None):
        if inputs:
            await agent._handle_incoming_messages(inputs)
        agent.state.reply_id = "reply-1"
        committed.set()
        # Block before emitting anything — the heartbeat wrapper shields the
        # pending ``__anext__()``, so the turn stays paused until released.
        await release.wait()
        if False:  # pragma: no cover — keep reply_stream an async generator
            yield

    agent.reply_stream = reply_stream
    return agent


def _runtime_workspace(session):
    registry = HookRegistry()
    registry.register(SessionLoadHook())
    registry.register(SessionSaveHook())
    registry.register(SessionEarlySaveHook())
    return SimpleNamespace(
        session=session,
        plugins=SimpleNamespace(
            hook_registry=registry,
            slash_command_registry=SimpleNamespace(
                dispatch=AsyncMock(return_value=None),
            ),
            modes=[],
        ),
    )


@pytest.mark.asyncio
async def test_early_save_survives_mid_turn_refresh(tmp_path, monkeypatch):
    """A turn paused before model completion is durable on reload.

    A2 regression: the PRE_EXECUTE early save used to snapshot the
    previous turn's state, because AgentScope only appends ``ctx.input_msgs``
    to the agent context inside ``reply_stream()`` — after the hook has
    returned.  This test runs the real ``Runtime`` pipeline (real hooks,
    real ``SafeJSONSession``, real AgentScope input handling), pauses the
    turn before the model completes, then reloads the persisted session as
    a mid-turn refresh would and asserts the current user message is there.
    """
    session = SafeJSONSession(save_dir=str(tmp_path))
    committed = asyncio.Event()
    release = asyncio.Event()

    agent = _pausing_agent(committed=committed, release=release)
    monkeypatch.setattr(
        AgentBuilder,
        "build",
        AsyncMock(return_value=agent),
    )
    runtime = Runtime(
        workspace=_runtime_workspace(session),
        app_services=None,
    )

    request = AgentRequest(
        session_id="mid-turn-session",
        user_id="mid-turn-user",
        input=[
            Message(
                role=Role.USER,
                content=[TextContent(text="CURRENT TURN")],
            ),
        ],
    )

    async def _drain():
        async for _ev in runtime.run(request):
            pass

    task = asyncio.create_task(_drain())
    try:
        # The input is committed to the live agent strictly after the
        # PRE_EXECUTE early save wrote the projected snapshot to the
        # session file, so once this fires the file is durable.
        await asyncio.wait_for(committed.wait(), timeout=5.0)

        # Mid-turn refresh: reload the persisted session while the model
        # is still blocked (the turn has not completed).
        states = await session.get_session_state_dict(
            session_id="mid-turn-session",
            user_id="mid-turn-user",
            channel="",
        )
        assert "agent" in states, states
        restored = _pausing_agent(committed=committed, release=release)
        restored.load_state_dict(states["agent"])

        user_texts = [
            msg.get_text_content()
            for msg in restored.state.context
            if getattr(msg, "role", "") == "user"
        ]
        assert "CURRENT TURN" in user_texts, user_texts
    finally:
        release.set()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
