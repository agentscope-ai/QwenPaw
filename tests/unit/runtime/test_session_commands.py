# -*- coding: utf-8 -*-
"""Tests for the session management slash commands.

Covers ``/sessions``, ``/session switch``, ``/session new`` and
``/session close`` against real persistence (``JsonChatRepository`` +
``SafeJSONSession`` on tmp_path) with a minimal fake workspace.
"""

from __future__ import annotations

import asyncio

import pytest

from agentscope.message import Msg, TextBlock
from agentscope.state import AgentState

from qwenpaw.app.chats.manager import ChatManager
from qwenpaw.app.chats.models import ChatSpec
from qwenpaw.app.chats.repo.json_repo import JsonChatRepository
from qwenpaw.app.chats.session import SafeJSONSession
from qwenpaw.runtime.builtin_commands import collect_builtin_command_specs
from qwenpaw.runtime.hooks import HookContext
from qwenpaw.runtime.commands.session_commands import (
    _collect_session_specs,
)
from qwenpaw.schemas import AgentRequest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class FakeWorkspace:
    """Minimal workspace exposing the services session commands need."""

    def __init__(self, chat_manager, session):
        self.chat_manager = chat_manager
        self.session = session
        self.workspace_dir = None


@pytest.fixture
def manager(tmp_path):
    repo = JsonChatRepository(tmp_path / "chats.json")
    return ChatManager(repo=repo)


@pytest.fixture
def session_store(tmp_path):
    return SafeJSONSession(save_dir=str(tmp_path / "sessions"))


@pytest.fixture
def workspace(manager, session_store):
    return FakeWorkspace(manager, session_store)


def make_ctx(workspace, session_id, user_id, channel="console"):
    request = AgentRequest(
        session_id=session_id,
        user_id=user_id,
        channel=channel,
        input=[],
    )
    return HookContext(
        request=request,
        session_id=session_id,
        agent_id="default",
        root_session_id=session_id,
        root_agent_id="default",
        workspace_dir=None,
        workspace=workspace,
        app_services=None,
    )


def run(coro):
    return (
        asyncio.get_event_loop_policy()
        .new_event_loop()
        .run_until_complete(
            coro,
        )
    )


async def seed_chat(manager, session_store, *, sid, uid, channel, name):
    spec = ChatSpec(session_id=sid, user_id=uid, channel=channel, name=name)
    await manager.create_chat(spec)
    return spec


async def seed_state(
    session_store,
    sid,
    uid,
    channel,
    texts,
    mode_state=None,
):
    """Persist a session state with the given context texts."""
    from qwenpaw.runtime._state_utils import StateProxy

    state = AgentState(session_id=sid)
    for text in texts:
        state.context.append(
            Msg(
                name="user",
                role="user",
                content=[TextBlock(type="text", text=text)],
            ),
        )
    proxy = StateProxy()
    proxy.data = {"state": state.model_dump(mode="json")}
    if mode_state is not None:
        proxy.data["mode_state"] = mode_state
    await session_store.save_session_state(
        session_id=sid,
        user_id=uid,
        channel=channel,
        agent=proxy,
    )


def spec_by_name(specs, name):
    return next(spec for spec in specs if spec.name == name)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_session_specs_registered_with_help_text():
    specs = _collect_session_specs()
    by_name = {spec.name: spec for spec in specs}
    assert set(by_name) == {"sessions", "session"}
    assert by_name["sessions"].category == "session"
    assert by_name["sessions"].help_text  # advertisable over ACP
    assert by_name["session"].help_text


def test_collect_builtin_command_specs_includes_session_commands():
    all_specs = collect_builtin_command_specs()
    names = {spec.name for spec in all_specs}
    assert {"sessions", "session"} <= names


# ---------------------------------------------------------------------------
# /sessions
# ---------------------------------------------------------------------------


def test_sessions_lists_only_current_user_chats(
    manager,
    session_store,
    workspace,
):
    async def scenario():
        await seed_chat(
            manager,
            session_store,
            sid="console:alice",
            uid="alice",
            channel="console",
            name="Alice chat",
        )
        await seed_chat(
            manager,
            session_store,
            sid="console:bob",
            uid="bob",
            channel="console",
            name="Bob chat",
        )
        await seed_state(
            session_store,
            "console:alice",
            "alice",
            "console",
            ["hi", "again"],
        )
        ctx = make_ctx(workspace, "console:alice", "alice")
        handler = spec_by_name(
            _collect_session_specs(),
            "sessions",
        ).handler
        msg = await handler(ctx, "")
        text = msg.content[0].text
        assert "Alice chat" in text
        assert "Bob chat" not in text  # user isolation
        assert "2 msg" in text
        assert "current" in text  # current session marked

    run(scenario())


def test_sessions_empty_list():
    async def scenario():
        from qwenpaw.runtime.commands.session_commands import (
            _render_list,
        )

        text = _render_list([], current_session_id="x", counts={})
        assert "No sessions found" in text

    run(scenario())


# ---------------------------------------------------------------------------
# /session switch
# ---------------------------------------------------------------------------


def test_switch_loads_target_context(
    manager,
    session_store,
    workspace,
):
    async def scenario():
        target = await seed_chat(
            manager,
            session_store,
            sid="console:target",
            uid="alice",
            channel="console",
            name="Target",
        )
        await seed_state(
            session_store,
            "console:target",
            "alice",
            "console",
            ["old-a", "old-b"],
        )
        await seed_state(
            session_store,
            "console:current",
            "alice",
            "console",
            ["current-a"],
        )

        ctx = make_ctx(workspace, "console:current", "alice")
        handler = spec_by_name(
            _collect_session_specs(),
            "session",
        ).handler
        msg = await handler(ctx, "switch console:target")
        text = msg.content[0].text
        assert "Target" in text
        assert "2 message(s)" in text

        # Persisted state for the *current* session now holds the target
        # context.
        data = await session_store.get_session_state_dict(
            "console:current",
            "alice",
            "console",
        )
        context = data["agent"]["state"]["context"]
        texts = [m["content"][0]["text"] for m in context]
        assert texts == ["old-a", "old-b"]

    run(scenario())


def test_switch_resolves_by_chat_uuid(
    manager,
    session_store,
    workspace,
):
    async def scenario():
        target = await seed_chat(
            manager,
            session_store,
            sid="console:target",
            uid="alice",
            channel="console",
            name="Target",
        )
        await seed_state(
            session_store,
            "console:target",
            "alice",
            "console",
            ["by-uuid"],
        )
        ctx = make_ctx(workspace, "console:current", "alice")
        handler = spec_by_name(
            _collect_session_specs(),
            "session",
        ).handler
        msg = await handler(ctx, f"switch {target.id}")
        assert "Target" in msg.content[0].text

    run(scenario())


def test_switch_rejects_other_users_session(
    manager,
    session_store,
    workspace,
):
    async def scenario():
        await seed_chat(
            manager,
            session_store,
            sid="console:alice-secret",
            uid="alice",
            channel="console",
            name="Alice secret",
        )
        ctx = make_ctx(workspace, "console:bob-current", "bob")
        handler = spec_by_name(
            _collect_session_specs(),
            "session",
        ).handler
        msg = await handler(ctx, "switch console:alice-secret")
        assert "not found" in msg.content[0].text

    run(scenario())


def test_switch_missing_target_reports_usage(
    manager,
    session_store,
    workspace,
):
    async def scenario():
        ctx = make_ctx(workspace, "console:current", "alice")
        handler = spec_by_name(
            _collect_session_specs(),
            "session",
        ).handler
        msg = await handler(ctx, "switch does-not-exist")
        assert "not found" in msg.content[0].text

    run(scenario())


def test_switch_carries_target_mode_state(
    manager,
    session_store,
    workspace,
):
    async def scenario():
        await seed_chat(
            manager,
            session_store,
            sid="console:target",
            uid="alice",
            channel="console",
            name="Target",
        )
        await seed_state(
            session_store,
            "console:target",
            "alice",
            "console",
            ["old"],
            mode_state={"mission": {"active": True}},
        )
        ctx = make_ctx(workspace, "console:current", "alice")
        handler = spec_by_name(
            _collect_session_specs(),
            "session",
        ).handler
        await handler(ctx, "switch console:target")
        data = await session_store.get_session_state_dict(
            "console:current",
            "alice",
            "console",
        )
        assert data["agent"]["mode_state"] == {
            "mission": {"active": True},
        }

    run(scenario())


def test_switch_resets_mode_state_when_target_has_none(
    manager,
    session_store,
    workspace,
):
    async def scenario():
        await seed_chat(
            manager,
            session_store,
            sid="console:target",
            uid="alice",
            channel="console",
            name="Target",
        )
        await seed_state(
            session_store,
            "console:target",
            "alice",
            "console",
            ["old"],
            mode_state=None,
        )
        ctx = make_ctx(workspace, "console:current", "alice")
        handler = spec_by_name(
            _collect_session_specs(),
            "session",
        ).handler
        await handler(ctx, "switch console:target")
        data = await session_store.get_session_state_dict(
            "console:current",
            "alice",
            "console",
        )
        assert data["agent"].get("mode_state") == {}

    run(scenario())


def test_switch_missing_target_with_empty_state(
    manager,
    session_store,
    workspace,
):
    """Switch to a registered chat that has no persisted state yet."""

    async def scenario():
        await seed_chat(
            manager,
            session_store,
            sid="console:empty",
            uid="alice",
            channel="console",
            name="Empty",
        )
        await seed_state(
            session_store,
            "console:current",
            "alice",
            "console",
            ["current"],
        )
        ctx = make_ctx(workspace, "console:current", "alice")
        handler = spec_by_name(
            _collect_session_specs(),
            "session",
        ).handler
        msg = await handler(ctx, "switch console:empty")
        assert "Empty" in msg.content[0].text
        assert "0 message(s)" in msg.content[0].text

    run(scenario())


# ---------------------------------------------------------------------------
# /session new
# ---------------------------------------------------------------------------


def test_session_new_registers_chat_and_clears_context(
    manager,
    session_store,
    workspace,
):
    async def scenario():
        await seed_state(
            session_store,
            "console:current",
            "alice",
            "console",
            ["existing"],
        )
        ctx = make_ctx(workspace, "console:current", "alice")
        handler = spec_by_name(
            _collect_session_specs(),
            "session",
        ).handler
        msg = await handler(ctx, "new")
        text = msg.content[0].text
        assert "New session id" in text

        # A fresh chat was registered under the same user/channel.
        chats = await manager.list_chats(user_id="alice")
        assert len(chats) == 1
        assert chats[0].channel == "console"
        # Current context cleared (scroll checkpoint reset with it).
        data = await session_store.get_session_state_dict(
            "console:current",
            "alice",
            "console",
        )
        assert data["agent"]["state"]["context"] == []

    run(scenario())


# ---------------------------------------------------------------------------
# /session close
# ---------------------------------------------------------------------------


def test_close_deletes_chat_and_state_file(
    manager,
    session_store,
    workspace,
):
    async def scenario():
        target = await seed_chat(
            manager,
            session_store,
            sid="console:target",
            uid="alice",
            channel="console",
            name="Target",
        )
        await seed_state(
            session_store,
            "console:target",
            "alice",
            "console",
            ["x"],
        )
        ctx = make_ctx(workspace, "console:other", "alice")
        handler = spec_by_name(
            _collect_session_specs(),
            "session",
        ).handler
        msg = await handler(ctx, f"close {target.id}")
        assert "Session closed" in msg.content[0].text

        chats = await manager.list_chats(user_id="alice")
        assert chats == []
        # Session state file removed as well.
        data = await session_store.get_session_state_dict(
            "console:target",
            "alice",
            "console",
        )
        assert data == {}

    run(scenario())


def test_close_current_session_clears_context(
    manager,
    session_store,
    workspace,
):
    async def scenario():
        await seed_chat(
            manager,
            session_store,
            sid="console:current",
            uid="alice",
            channel="console",
            name="Current",
        )
        await seed_state(
            session_store,
            "console:current",
            "alice",
            "console",
            ["existing"],
        )
        ctx = make_ctx(workspace, "console:current", "alice")
        handler = spec_by_name(
            _collect_session_specs(),
            "session",
        ).handler
        msg = await handler(ctx, "close console:current")
        assert "Session closed" in msg.content[0].text
        chats = await manager.list_chats(user_id="alice")
        assert chats == []
        data = await session_store.get_session_state_dict(
            "console:current",
            "alice",
            "console",
        )
        assert data["agent"]["state"]["context"] == []

    run(scenario())


def test_close_missing_target_reports_usage(
    manager,
    session_store,
    workspace,
):
    async def scenario():
        ctx = make_ctx(workspace, "console:current", "alice")
        handler = spec_by_name(
            _collect_session_specs(),
            "session",
        ).handler
        msg = await handler(ctx, "close nope")
        assert "not found" in msg.content[0].text

    run(scenario())


def test_session_usage_message(manager, session_store, workspace):
    async def scenario():
        ctx = make_ctx(workspace, "console:current", "alice")
        handler = spec_by_name(
            _collect_session_specs(),
            "session",
        ).handler
        msg = await handler(ctx, "")
        assert "Usage" in msg.content[0].text
        msg = await handler(ctx, "bogus")
        assert "Usage" in msg.content[0].text

    run(scenario())
