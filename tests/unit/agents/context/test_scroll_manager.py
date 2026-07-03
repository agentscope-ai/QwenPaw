# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access,unused-argument
"""Unit tests for :class:`ScrollContextManager`.

Covers write-through dedup, the resume checkpoint (no re-append of a restored
window), the boundary-Msg double-presence fix, cap-middleware seq adoption,
degraded-durability fail-safe (no eviction when a write fails), and retention.
"""

from pathlib import Path

import pytest
from agentscope.message import (
    Msg,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
)

from qwenpaw.agents.context.scroll.history import HistoryStore
from qwenpaw.agents.context.scroll.manager import ScrollContextManager
from qwenpaw.agents.context.types import LogEntry

# -- fixtures ---------------------------------------------------------------


def user(text: str) -> Msg:
    return Msg(
        name="u",
        role="user",
        content=[TextBlock(type="text", text=text)],
    )


def assistant(text: str, headline: str | None = None) -> Msg:
    if headline:
        text = f"{text}\n⟦ {headline} ⟧"
    return Msg(
        name="a",
        role="assistant",
        content=[TextBlock(type="text", text=text)],
    )


def assistant_with_tool(tcid: str, result_text: str = "RESULT") -> Msg:
    """An AS-2.0 accumulated assistant Msg: text + tool_call + tool_result."""
    return Msg(
        name="a",
        role="assistant",
        content=[
            TextBlock(type="text", text="calling a tool"),
            ToolCallBlock(type="tool_call", id=tcid, name="grep", input="{}"),
            ToolResultBlock(
                type="tool_result",
                id=tcid,
                name="grep",
                output=[TextBlock(type="text", text=result_text)],
            ),
        ],
    )


class FakeModel:
    def __init__(self, tokens: int, context_size: int = 1000) -> None:
        self._tokens = tokens
        self.context_size = context_size

    async def count_tokens(self, *args, **kwargs) -> int:
        return self._tokens


class FakeConfig:
    trigger_ratio = 0.1
    reserve_ratio = 0.5


class FakeState:
    def __init__(self, context: list[Msg]) -> None:
        self.context = context


class FakeAgent:
    """Minimal stand-in exposing the AS-2.0 surface the manager touches."""

    def __init__(self, context: list[Msg], tokens: int = 200) -> None:
        self.state = FakeState(context)
        self.model = FakeModel(tokens)
        self.context_config = FakeConfig()
        self._split_return: tuple | None = None

    async def _prepare_model_input(self) -> dict:
        return {"tools": []}

    async def _split_context_for_compression(self, reserve, tools) -> tuple:
        if self._split_return is not None:
            return self._split_return
        # Default: compress everything but the last msg.
        return (self.state.context[:-1], self.state.context[-1:])


@pytest.fixture
def store(tmp_path: Path) -> HistoryStore:
    h = HistoryStore(tmp_path / "history.db")
    yield h
    h.close()


def make_manager(store: HistoryStore, **kw) -> ScrollContextManager:
    kw.setdefault("session_id", "s1")
    kw.setdefault("agent_id", "ag1")
    return ScrollContextManager(history=store, **kw)


# -- write-through dedup -----------------------------------------------------


def test_persist_new_writes_each_turn_once(store: HistoryStore):
    mgr = make_manager(store)
    ctx = [user("hi"), assistant("there", headline="greeted")]
    agent = FakeAgent(ctx)
    mgr._persist_new(agent)
    mgr._persist_new(agent)  # idempotent: same context again
    assert store.count("s1") == 2


def test_persist_new_records_seq_and_headline_leaf(store: HistoryStore):
    mgr = make_manager(store)
    a = assistant("did it", headline="milestone")
    agent = FakeAgent([user("go"), a])
    mgr._persist_new(agent)
    assert a.id in mgr._leaf_by_id
    assert mgr._leaf_by_id[a.id].headline == "milestone"
    assert a.id in mgr._seq_by_id


def test_tool_result_persisted_under_tool_call_id(store: HistoryStore):
    mgr = make_manager(store)
    agent = FakeAgent([assistant_with_tool("call-1", "big output")])
    mgr._persist_new(agent)
    rows = store._conn.execute(
        "SELECT content FROM conversation_history "
        "WHERE kind='tool_result' AND tool_call_id='call-1'",
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["content"] == "big output"


# -- resume: a restored window is not re-appended ---------------------------


def test_checkpoint_round_trip_prevents_reappend(store: HistoryStore):
    ctx = [
        user("hi"),
        assistant("a1", headline="h1"),
        assistant("a2", headline="h2"),
    ]
    mgr1 = make_manager(store)
    mgr1._persist_new(FakeAgent(ctx))
    assert store.count("s1") == 3
    snap = mgr1.to_dict()

    # Fresh manager (new process / reload) over the SAME restored context.
    mgr2 = make_manager(store)
    mgr2.load_state(snap)
    assert mgr2._persisted_ids == mgr1._persisted_ids
    mgr2._persist_new(FakeAgent(ctx))
    assert store.count("s1") == 3  # nothing re-appended


def test_reappend_blocked_by_db_even_without_checkpoint(store: HistoryStore):
    """Belt-and-suspenders: even a fresh manager with no checkpoint cannot
    duplicate rows, because the ux_dedup unique index drops them."""
    ctx = [user("hi"), assistant("a1", headline="h1")]
    make_manager(store)._persist_new(FakeAgent(ctx))
    make_manager(store)._persist_new(FakeAgent(ctx))  # no load_state
    assert store.count("s1") == 2


def test_load_state_tolerates_garbage(store: HistoryStore):
    mgr = make_manager(store)
    mgr.load_state(None)
    mgr.load_state({})
    assert mgr._persisted_ids == set()


# -- cap-middleware seq adoption --------------------------------------------


def test_capped_result_is_not_re_persisted(store: HistoryStore):
    """When the cap middleware already wrote a result in full, the manager
    adopts its seq and does NOT re-persist the truncated in-context stub."""
    capped = {"call-1": 999}
    mgr = make_manager(store, capped_results=capped)
    agent = FakeAgent([assistant_with_tool("call-1", "truncated stub")])
    mgr._persist_new(agent)
    # No tool_result row was written by the manager (the cap owns it).
    rows = store._conn.execute(
        "SELECT 1 FROM conversation_history "
        "WHERE kind='tool_result' AND tool_call_id='call-1'",
    ).fetchall()
    assert rows == []
    assert "call-1" in mgr._persisted_tcids


# -- compress: eviction + the boundary double-presence fix ------------------


async def test_compress_evicts_middle_into_index(store: HistoryStore):
    ctx = [
        user("task"),
        assistant("step", headline="did-step"),
        assistant("recent"),
    ]
    mgr = make_manager(store, pinned=1)
    agent = FakeAgent(ctx, tokens=200)
    agent._split_return = (
        ctx[:2],
        ctx[2:],
    )  # compress [task, step], keep last
    await mgr.compress(agent)
    # Context is rebuilt as head + placeholder + tail.
    assert len(agent.state.context) == 3
    names = [m.name for m in agent.state.context]
    assert "memory" in names  # the index placeholder
    assert "did-step" in mgr._index.render()


async def test_compress_does_not_index_boundary_msg_still_in_tail(
    store: HistoryStore,
):
    """The boundary Msg is deep-copied into BOTH split halves under the same
    id. It must NOT be folded into the eviction index while its reserve copy
    is still live in the tail."""
    pinned = user("task")
    a = assistant("middle turn", headline="MIDDLE")
    boundary = assistant("boundary turn", headline="BOUNDARY")
    ctx = [pinned, a, boundary]
    mgr = make_manager(store, pinned=1)
    agent = FakeAgent(ctx, tokens=200)
    # Mimic AgentScope: boundary id appears in BOTH halves (same id).
    compress_half = boundary
    reserve_half = Msg(
        name="a",
        role="assistant",
        content=[TextBlock(type="text", text="boundary tail blocks")],
    )
    object.__setattr__(
        reserve_half,
        "id",
        boundary.id,
    )  # same id, fewer blocks
    agent._split_return = ([pinned, a, compress_half], [reserve_half])

    await mgr.compress(agent)
    rendered = mgr._index.render()
    assert "MIDDLE" in rendered  # the genuinely evicted turn
    assert "BOUNDARY" not in rendered  # still live → must not be indexed
    # And the boundary id is still present in the live context.
    assert boundary.id in {m.id for m in agent.state.context}


# -- degraded durability: no eviction on write failure ----------------------


async def test_compress_does_not_evict_when_persist_fails(
    store: HistoryStore,
    monkeypatch,
):
    import sqlite3

    ctx = [user("task"), assistant("step", headline="s"), assistant("more")]
    mgr = make_manager(store, pinned=1)
    agent = FakeAgent(ctx, tokens=200)

    def boom(*a, **k):
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr(store, "append", boom)
    await mgr.compress(agent)
    # Persist failed → degraded, and the context was left untouched (no
    # placeholder injected, no rows pointing at nonexistent durable data).
    assert store.degraded is True
    assert [m.id for m in agent.state.context] == [m.id for m in ctx]


def test_on_save_swallows_write_failure(store: HistoryStore, monkeypatch):
    import sqlite3

    mgr = make_manager(store)
    agent = FakeAgent([user("hi")])

    def boom(*a, **k):
        raise sqlite3.OperationalError("io error")

    monkeypatch.setattr(store, "append", boom)
    mgr.on_save(agent, None)  # must not raise
    assert store.degraded is True


def test_on_save_after_close_is_quiet_noop(store: HistoryStore):
    """Teardown race: an on_save after close is skipped quietly, not reported
    as degraded durability."""
    mgr = make_manager(store)
    agent = FakeAgent([user("hi"), assistant("there", headline="h")])
    store.close()
    assert store.closed is True

    mgr.on_save(agent, None)  # must not raise "closed database"
    # Skipped, not failed: durability stays healthy and nothing was persisted.
    assert store.degraded is False
    assert store.write_failures == 0
    assert mgr._persisted_ids == set()


# -- optional dialog offload (offload_dialog opt-in) ------------------------


class _RecordingOffloader:
    def __init__(self) -> None:
        self.calls: list = []

    async def offload_context(self, session_id, msgs):
        self.calls.append((session_id, [m.id for m in msgs]))
        return "dialog/2026-06-19.jsonl"


def _compactable(store, **kw):
    ctx = [
        user("task"),
        assistant("step", headline="did-step"),
        assistant("recent"),
    ]
    mgr = make_manager(store, pinned=1, **kw)
    agent = FakeAgent(ctx, tokens=200)
    agent._split_return = (
        ctx[:2],
        ctx[2:],
    )  # evict [step]; keep task + recent
    return mgr, agent, ctx


async def test_compress_offloads_evicted_middle_when_configured(store):
    off = _RecordingOffloader()
    mgr, agent, ctx = _compactable(store, offloader=off)
    await mgr.compress(agent)
    assert len(off.calls) == 1
    session_id, ids = off.calls[0]
    assert session_id == "s1"
    assert ids == [ctx[1].id]  # exactly the evicted middle turn


async def test_compress_does_not_offload_without_offloader(store):
    mgr, agent, _ = _compactable(store)  # no offloader wired
    await mgr.compress(agent)  # must work + write nothing to dialog
    assert "memory" in [m.name for m in agent.state.context]


async def test_offload_failure_does_not_abort_eviction(store):
    class _Boom:
        async def offload_context(self, session_id, msgs):
            raise OSError("disk full")

    mgr, agent, _ = _compactable(store, offloader=_Boom())
    await mgr.compress(agent)  # best-effort archive: swallow + keep evicting
    assert "did-step" in mgr._index.render()
    assert "memory" in [m.name for m in agent.state.context]


# -- retention ---------------------------------------------------------------


def test_purge_old_zero_keeps_everything(store: HistoryStore):
    mgr = make_manager(store)
    store.append(
        session_id="s1",
        dedup_key="m1",
        entry=LogEntry(
            kind="model_turn",
            content="x",
            created_at="2000-01-01T00:00:00+00:00",
        ),
    )
    assert mgr.purge_old(0) == 0
    assert store.count("s1") == 1


def test_purge_old_drops_rows_past_window(store: HistoryStore):
    mgr = make_manager(store)
    store.append(
        session_id="s1",
        dedup_key="m1",
        entry=LogEntry(
            kind="model_turn",
            content="ancient",
            created_at="2000-01-01T00:00:00+00:00",
        ),
    )
    assert mgr.purge_old(1) == 1
    assert store.count("s1") == 0


def test_serialize_captures_tool_input():
    """A tool call's arguments land in the ``tool_input`` column (it used to be
    dropped — only ``blocks`` carried them — so ``recall_tool`` returned None).
    """
    from qwenpaw.agents.context.scroll.serialize import msg_to_entries

    msg = Msg(
        name="a",
        role="assistant",
        content=[
            TextBlock(type="text", text="reading a file"),
            ToolCallBlock(
                type="tool_call",
                id="call-1",
                name="read_file",
                input='{"file_path": "PROFILE.md"}',
            ),
        ],
    )
    entries = msg_to_entries(msg)
    turn = next(e for e in entries if e.kind == "model_turn")
    assert turn.name == "read_file"
    assert turn.tool_call_id == "call-1"
    assert turn.tool_input == '{"file_path": "PROFILE.md"}'


def test_tool_input_round_trips_to_db(store: HistoryStore):
    """End-to-end: the persisted row's ``tool_input`` column is populated."""
    from qwenpaw.agents.context.scroll.serialize import msg_to_entries

    msg = Msg(
        name="a",
        role="assistant",
        content=[
            ToolCallBlock(
                type="tool_call",
                id="call-9",
                name="grep",
                input='{"pattern": "x"}',
            ),
        ],
    )
    (turn,) = msg_to_entries(msg)
    store.append(session_id="s1", dedup_key="m1", entry=turn)
    row = store._conn.execute(
        "SELECT tool_input FROM conversation_history "
        "WHERE tool_call_id='call-9'",
    ).fetchone()
    assert row["tool_input"] == '{"pattern": "x"}'
