# -*- coding: utf-8 -*-
"""Unit tests for ``qwenpaw.app.runner.command_dispatch``.

Covers the pure helpers: ``_get_last_user_text``, ``_is_conversation_command``,
``_is_control_command`` and ``_is_command``.  The ``run_command_path``
coroutine is exercised by integration tests; we only verify here that the
short-circuit (empty input) path yields nothing.
"""

# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

from types import SimpleNamespace

import pytest

from qwenpaw.app.runner import command_dispatch as cd

# ---------------------------------------------------------------------------
# _get_last_user_text
# ---------------------------------------------------------------------------


class _MsgWithGetText:
    """Stub mimicking agentscope.message.Msg.get_text_content()."""

    def __init__(self, text: str) -> None:
        self._text = text

    def get_text_content(self) -> str:
        return self._text


@pytest.mark.parametrize("empty", [None, []])
def test_get_last_user_text_empty_returns_none(empty):
    assert cd._get_last_user_text(empty) is None


def test_get_last_user_text_uses_get_text_content_when_available():
    msgs = [_MsgWithGetText("ignored"), _MsgWithGetText("/stop")]

    assert cd._get_last_user_text(msgs) == "/stop"


def test_get_last_user_text_string_content_dict():
    msgs = [{"content": "hello world"}]

    assert cd._get_last_user_text(msgs) == "hello world"


def test_get_last_user_text_text_field_fallback():
    msgs = [{"text": "fallback text"}]

    assert cd._get_last_user_text(msgs) == "fallback text"


def test_get_last_user_text_block_list_content():
    msgs = [
        {
            "content": [
                {"type": "image", "url": "https://example.test/x.png"},
                {"type": "text", "text": "from block"},
            ],
        },
    ]

    assert cd._get_last_user_text(msgs) == "from block"


def test_get_last_user_text_block_list_without_text_returns_none():
    msgs = [{"content": [{"type": "image", "url": "https://x"}]}]

    assert cd._get_last_user_text(msgs) is None


def test_get_last_user_text_unknown_shape_returns_none():
    # Plain str inside list, no get_text_content and not a dict — should
    # fall through to ``None`` rather than crash.
    assert cd._get_last_user_text(["just a string"]) is None


# ---------------------------------------------------------------------------
# _is_conversation_command
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query",
    [
        "/compact",
        "/new",
        "/clear",
        "/history",
        "/proactive",
        # Bare /plan (no args) is a conversation command.
        "/plan",
    ],
)
def test_is_conversation_command_known_commands(query):
    assert cd._is_conversation_command(query) is True


def test_is_conversation_command_plan_with_args_is_not_command():
    # ``/plan <description>`` activates plan mode in the runner; it MUST
    # NOT be classified as a conversation command.
    assert cd._is_conversation_command("/plan implement feature X") is False


def test_is_conversation_command_plan_with_trailing_space_only_is_command():
    # Trailing whitespace alone is not arguments.
    assert cd._is_conversation_command("/plan   ") is True


@pytest.mark.parametrize(
    "query",
    [
        None,
        "",
        "hello world",
        "/unknown-command",
        # Looks like a path, not a command.
        "/usr/local/bin",
    ],
)
def test_is_conversation_command_non_command(query):
    assert cd._is_conversation_command(query) is False


# ---------------------------------------------------------------------------
# _is_control_command — thin wrapper around control_commands.is_control_command
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query",
    ["/stop", "/approval", "/approve abc", "/deny abc", "/model", "/skills"],
)
def test_is_control_command_known_handlers(query):
    assert cd._is_control_command(query) is True


def test_is_control_command_unknown_command():
    assert cd._is_control_command("/totally-unknown") is False


# ---------------------------------------------------------------------------
# _is_command — priority: daemon > control > conversation
# ---------------------------------------------------------------------------


def test_is_command_none_or_empty():
    assert cd._is_command(None) is False
    assert cd._is_command("") is False


def test_is_command_non_slash_query():
    assert cd._is_command("hello") is False


def test_is_command_recognises_conversation_command():
    assert cd._is_command("/compact") is True


def test_is_command_recognises_control_command():
    assert cd._is_command("/stop") is True


def test_is_command_recognises_daemon_command(monkeypatch):
    # parse_daemon_query is imported into command_dispatch; patch the symbol
    # actually used there.
    monkeypatch.setattr(
        cd,
        "parse_daemon_query",
        lambda q: ("status", []),
    )

    assert cd._is_command("/qwenpaw status") is True


def test_is_command_unknown_slash_query_returns_false():
    assert cd._is_command("/no-such-command") is False


# ---------------------------------------------------------------------------
# run_command_path — short-circuit on empty user text
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_command_path_no_user_text_yields_nothing():
    request = SimpleNamespace(session_id="s1", user_id="u1", channel="console")
    runner = SimpleNamespace(agent_name="agent", agent_id="aid")

    yielded = [item async for item in cd.run_command_path(request, [], runner)]

    assert yielded == []


class _FakeSession:
    """Async session stub recording the load_session_state call."""

    def __init__(self) -> None:
        self.loaded_with = None

    async def load_session_state(self, **kwargs):
        self.loaded_with = kwargs


def _make_runner(session=None):
    return SimpleNamespace(
        agent_name="agent",
        agent_id="aid",
        workspace_dir=None,
        memory_manager=None,
        context_manager=None,
        session=session,
    )


@pytest.mark.asyncio
async def test_run_command_path_dispatches_known_command(monkeypatch):
    """A known command builds an agent and bridges dispatch_command's Msg
    onto the ``(Msg, True)`` stream the query_handler expects."""
    from agentscope.message import Msg, TextBlock

    built = {}

    def _fake_build_agent(session_id, **kwargs):
        built["session_id"] = session_id
        built["kwargs"] = kwargs
        return SimpleNamespace(name="agent")

    # build_agent is imported lazily inside run_command_path.
    import qwenpaw.runtime.agent_factory as af

    monkeypatch.setattr(af, "build_agent", _fake_build_agent)

    captured = {}

    async def _fake_dispatch(query, *, agent, runner, request, msgs):
        captured["query"] = query
        captured["agent"] = agent
        return Msg(
            name="agent",
            role="assistant",
            content=[TextBlock(type="text", text="status ok")],
        )

    monkeypatch.setattr(cd, "dispatch_command", _fake_dispatch)

    session = _FakeSession()
    runner = _make_runner(session=session)
    request = SimpleNamespace(session_id="s1", user_id="u1", channel="console")
    msgs = [_MsgWithGetText("/status")]

    yielded = [
        item async for item in cd.run_command_path(request, msgs, runner)
    ]

    assert len(yielded) == 1
    msg, last = yielded[0]
    assert last is True
    assert msg.get_text_content() == "status ok"
    assert captured["query"] == "/status"
    assert captured["agent"].name == "agent"
    assert built["session_id"] == "s1"
    # Session state must be loaded so memory-touching commands work.
    assert session.loaded_with["session_id"] == "s1"


@pytest.mark.asyncio
async def test_run_command_path_passes_mcp_clients_and_context(monkeypatch):
    """The adapter must build the agent with MCP clients and request_context
    so control/skill commands see the same tools as the live query path."""
    from agentscope.message import Msg, TextBlock

    built = {}

    def _fake_build_agent(session_id, **kwargs):
        built["kwargs"] = kwargs
        return SimpleNamespace(name="agent")

    import qwenpaw.runtime.agent_factory as af

    monkeypatch.setattr(af, "build_agent", _fake_build_agent)

    async def _fake_dispatch(query, *, agent, runner, request, msgs):
        return Msg(
            name="agent",
            role="assistant",
            content=[TextBlock(type="text", text="ok")],
        )

    monkeypatch.setattr(cd, "dispatch_command", _fake_dispatch)

    sentinel_clients = [SimpleNamespace(name="mcp1")]

    class _FakeMCPManager:
        async def get_clients(self):
            return sentinel_clients

    runner = _make_runner(session=_FakeSession())
    runner._mcp_manager = _FakeMCPManager()
    request = SimpleNamespace(
        session_id="s1",
        user_id="u1",
        channel="console",
        request_context={"root_agent_id": "ra"},
    )
    msgs = [_MsgWithGetText("/skills")]

    _ = [item async for item in cd.run_command_path(request, msgs, runner)]

    assert built["kwargs"]["mcp_clients"] is sentinel_clients
    ctx = built["kwargs"]["request_context"]
    assert ctx["session_id"] == "s1"
    assert ctx["user_id"] == "u1"
    assert ctx["channel"] == "console"
    assert ctx["agent_id"] == "aid"
    # Payload request_context is merged in.
    assert ctx["root_agent_id"] == "ra"


@pytest.mark.asyncio
async def test_run_command_path_none_result_yields_nothing(monkeypatch):
    """When dispatch_command returns None (fall-through), nothing is
    yielded — the runner proceeds to the model."""
    import qwenpaw.runtime.agent_factory as af

    monkeypatch.setattr(
        af,
        "build_agent",
        lambda session_id, **kwargs: SimpleNamespace(name="agent"),
    )

    async def _fake_dispatch(query, *, agent, runner, request, msgs):
        return None

    monkeypatch.setattr(cd, "dispatch_command", _fake_dispatch)

    runner = _make_runner(session=_FakeSession())
    request = SimpleNamespace(session_id="s1", user_id="u1", channel="console")
    msgs = [_MsgWithGetText("/compact")]

    yielded = [
        item async for item in cd.run_command_path(request, msgs, runner)
    ]

    assert yielded == []


@pytest.mark.asyncio
async def test_run_command_path_restart_yields_hint_first(monkeypatch):
    """Daemon /restart yields the 'Restart in progress' hint before the
    dispatch result, preserving 1.x parity."""
    from agentscope.message import Msg, TextBlock

    import qwenpaw.runtime.agent_factory as af

    monkeypatch.setattr(
        af,
        "build_agent",
        lambda session_id, **kwargs: SimpleNamespace(name="agent"),
    )
    monkeypatch.setattr(
        cd,
        "parse_daemon_query",
        lambda q: ("restart", []),
    )

    async def _fake_dispatch(query, *, agent, runner, request, msgs):
        return Msg(
            name="agent",
            role="assistant",
            content=[TextBlock(type="text", text="restarted")],
        )

    monkeypatch.setattr(cd, "dispatch_command", _fake_dispatch)

    runner = _make_runner(session=_FakeSession())
    request = SimpleNamespace(session_id="s1", user_id="u1", channel="console")
    msgs = [_MsgWithGetText("/restart")]

    yielded = [
        item async for item in cd.run_command_path(request, msgs, runner)
    ]

    assert len(yielded) == 2
    assert "Restart in progress" in yielded[0][0].get_text_content()
    assert yielded[1][0].get_text_content() == "restarted"
