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
    """Constant token count, or a sequence (last value sticks) to model the
    window shrinking as compress() evicts. ``calls`` counts count_tokens
    invocations (compress must not recount an unchanged context)."""

    def __init__(self, tokens, context_size: int = 1000) -> None:
        self._tokens = (
            list(tokens) if isinstance(tokens, (list, tuple)) else [tokens]
        )
        self.context_size = context_size
        self.calls = 0

    async def count_tokens(self, *args, **kwargs) -> int:
        self.calls += 1
        if len(self._tokens) > 1:
            return self._tokens.pop(0)
        return self._tokens[0]


class FakeConfig:
    trigger_ratio = 0.1
    reserve_ratio = 0.5


class FakeState:
    def __init__(self, context: list[Msg]) -> None:
        self.context = context


class FakeAgent:
    """Minimal stand-in exposing the AS-2.0 surface the manager touches."""

    def __init__(
        self,
        context: list[Msg],
        tokens: int | list[int] = 200,
    ) -> None:
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
    # A newer user turn follows the evictable middle: the active turn (last
    # user msg onward) stays live, the finished older turns are evicted.
    ctx = [
        user("task"),
        assistant("step", headline="did-step"),
        user("next question"),
        assistant("recent"),
    ]
    mgr = make_manager(store)
    agent = FakeAgent(ctx, tokens=200)
    agent._split_return = (
        ctx[:2],
        ctx[2:],
    )  # compress [task, step], keep [next, recent]
    await mgr.compress(agent)
    # Context is rebuilt as placeholder + tail.
    assert len(agent.state.context) == 3
    names = [m.name for m in agent.state.context]
    assert names[0] == "memory"  # the index placeholder leads
    assert "did-step" in mgr._index.render()
    assert mgr.last_compress["evicted"] == 2  # /compact reporting source


async def test_compress_does_not_index_boundary_msg_still_in_tail(
    store: HistoryStore,
):
    """The boundary Msg is deep-copied into BOTH split halves under the same
    id. It must NOT be folded into the eviction index while its reserve copy
    is still live in the tail."""
    old_task = user("task")
    a = assistant("middle turn", headline="MIDDLE")
    current = user("current request")
    boundary = assistant("boundary turn", headline="BOUNDARY")
    ctx = [old_task, a, current, boundary]
    mgr = make_manager(store)
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
    agent._split_return = (
        [old_task, a, current, compress_half],
        [reserve_half],
    )

    await mgr.compress(agent)
    rendered = mgr._index.render()
    assert "MIDDLE" in rendered  # the genuinely evicted turn
    assert "BOUNDARY" not in rendered  # still live → must not be indexed
    # And the boundary id is still present in the live context.
    assert boundary.id in {m.id for m in agent.state.context}


async def test_compress_keeps_active_turn_live(store: HistoryStore):
    """The token-based split may push the CURRENT user request (and its
    running assistant chain) into the compress half. The active turn must
    stay live — evicting it makes the model answer an older message
    (#5747)."""
    old_u = user("older question")
    old_a = assistant("older reply", headline="OLD")
    cur_u = user("/heartbeat")
    cur_a = assistant("running tools", headline="RUNNING")
    ctx = [old_u, old_a, cur_u, cur_a]
    mgr = make_manager(store)
    agent = FakeAgent(ctx, tokens=200)
    # A long active turn blows the reserve budget: the split reserves nothing
    # and would evict the current request along with the old turns.
    agent._split_return = (ctx, [])
    await mgr.compress(agent)
    live_ids = [m.id for m in agent.state.context]
    assert cur_u.id in live_ids and cur_a.id in live_ids
    rendered = mgr._index.render()
    assert "OLD" in rendered  # the finished old turn is evicted
    assert "RUNNING" not in rendered  # the active turn is not
    # The active turn sits after the placeholder, mirroring a normal tail.
    names = [m.name for m in agent.state.context]
    assert names.index("memory") < live_ids.index(cur_u.id)


def continuation_stub(text: str = "Continue working on the task.") -> Msg:
    """The user-role stub loop gates / stop handlers inject mid-turn."""
    from qwenpaw.constant import (
        LOOP_CONTINUATION_MESSAGE_TAG,
        QWENPAW_MESSAGE_TAG_KEY,
    )

    return Msg(
        name="user",
        role="user",
        content=[TextBlock(type="text", text=text)],
        metadata={QWENPAW_MESSAGE_TAG_KEY: LOOP_CONTINUATION_MESSAGE_TAG},
    )


async def test_active_turn_anchor_skips_continuation_stubs(
    store: HistoryStore,
):
    """A loop-continuation stub is user-role but NOT a new request: the
    active-turn anchor must stay on the real request that started the turn,
    or the real request becomes evictable middle again (#5746, loop-session
    flavor)."""
    old_u = user("older question")
    old_a = assistant("older reply", headline="OLD")
    real_u = user("write the report")
    a1 = assistant("working on it", headline="MID-TASK")
    stub = continuation_stub()
    a2 = assistant("continuing the report")
    ctx = [old_u, old_a, real_u, a1, stub, a2]
    mgr = make_manager(store)
    agent = FakeAgent(ctx, tokens=200)
    agent._split_return = (ctx, [])  # split would evict everything
    await mgr.compress(agent)
    live_ids = [m.id for m in agent.state.context]
    # The whole extended turn — real request, pre-stub reply, the stub
    # itself, and the post-stub reply — stays live.
    for m in (real_u, a1, stub, a2):
        assert m.id in live_ids
    rendered = mgr._index.render()
    assert "OLD" in rendered  # the finished old turn is evicted
    assert "MID-TASK" not in rendered  # the extended active turn is not


async def test_compress_noop_when_active_turn_fits_reserve(
    store: HistoryStore,
):
    """Single-user-msg session (e.g. a cron run): the whole context is the
    active turn and nothing is evictable. While the window still fits the
    reserve, compress leaves it untouched — no compaction, no fold."""
    ctx = [
        user("/heartbeat"),
        assistant("step one", headline="S1"),
        assistant("step two", headline="S2"),
    ]
    mgr = make_manager(store)
    agent = FakeAgent(ctx, tokens=200)  # over trigger, under reserve (500)
    agent._split_return = (ctx, [])
    await mgr.compress(agent)
    assert [m.id for m in agent.state.context] == [m.id for m in ctx]
    assert mgr._index.is_empty


def _multi_tool_turn(n: int = 3) -> Msg:
    """An accumulated assistant Msg with ``n`` completed call/result pairs."""
    blocks = []
    for i in range(n):
        blocks.append(TextBlock(type="text", text=f"step {i}"))
        blocks.append(
            ToolCallBlock(
                type="tool_call",
                id=f"c{i}",
                name="grep",
                input="{}",
            ),
        )
        blocks.append(
            ToolResultBlock(
                type="tool_result",
                id=f"c{i}",
                name="grep",
                output=[TextBlock(type="text", text=f"RESULT-{i}")],
            ),
        )
    return Msg(name="a", role="assistant", content=blocks)


async def test_fold_not_triggered_between_reserve_and_trigger(
    store: HistoryStore,
):
    """With REALISTIC ratios (trigger 0.8, reserve 0.1), an active turn that
    exceeds the reserve but leaves most of the window free must NOT be
    folded — the fold is a last resort gated on the compression trigger,
    not on the soft reserve target. (Pre-fix, a 25k active turn in a 200k
    window was stubbed on every compress round of an ordinary long chat.)"""

    class _RealisticConfig:
        trigger_ratio = 0.8  # trigger at 800 of the 1000-token window
        reserve_ratio = 0.1  # reserve target 100

    old_u = user("older question")
    old_a = assistant("older reply", headline="OLD")
    turn = _multi_tool_turn()
    ctx = [old_u, old_a, user("/heartbeat"), turn]
    mgr = make_manager(store)
    # 900 at the trigger check; 300 after eviction — over the reserve (100)
    # but far under the trigger (800).
    agent = FakeAgent(ctx, tokens=[900, 300])
    agent.context_config = _RealisticConfig()
    agent._split_return = (ctx[:2], ctx[2:])
    await mgr.compress(agent)

    rendered = mgr._index.render()
    assert "OLD" in rendered  # normal eviction happened
    # ... but every tool result of the active turn stays verbatim.
    for block in turn.content:
        if getattr(block, "type", None) == "tool_result":
            assert block.output[0].text.startswith("RESULT-")


async def test_pressure_fold_stubs_older_results_keeps_newest(
    store: HistoryStore,
):
    """Nothing evictable and the window still overflows the compression
    trigger: the active turn's completed tool results are stubbed in place
    to recall pointers. The request, tool calls, reasoning, and the NEWEST
    result stay verbatim; the durable rows keep the full outputs; the Msg
    object (and id) is untouched so the runtime keeps extending the same
    message."""
    turn = _multi_tool_turn()
    ctx = [user("/heartbeat"), turn]
    mgr = make_manager(store)
    agent = FakeAgent(ctx, tokens=600)  # > trigger (100): sustained pressure
    agent._split_return = (ctx, [])  # split would evict everything
    await mgr.compress(agent)

    # Same live objects — no rebuild happened (nothing was evicted).
    assert agent.state.context == ctx
    assert agent.state.context[-1] is turn

    def out_text(i: int) -> str:
        block = turn.content[3 * i + 2]
        return block.output[0].text

    # folded → seq-addressed stub pointing at the structured recall tool
    assert 'recall_history(op="expand"' in out_text(0)
    assert 'recall_history(op="expand"' in out_text(1)
    assert out_text(2) == "RESULT-2"  # newest result kept verbatim
    # The durable rows still hold the FULL outputs (persisted before fold).
    for i in range(3):
        row = store._conn.execute(
            "SELECT content FROM conversation_history "
            f"WHERE kind='tool_result' AND tool_call_id='c{i}'",
        ).fetchone()
        assert row["content"] == f"RESULT-{i}"

    # /compact reads this to report honestly (fold changes no msg count).
    assert mgr.last_compress["folded"] == 2

    # Idempotent: a second round neither double-folds nor rewrites rows.
    await mgr.compress(agent)
    assert out_text(0).count("[scroll folded]") == 1
    assert out_text(2) == "RESULT-2"
    assert mgr.last_compress["folded"] == 0  # nothing newly folded


async def test_steady_state_counts_once_and_warns_once(
    store: HistoryStore,
    caplog,
):
    """Over the trigger with nothing evictable, compactable, or foldable:
    each compress pays exactly ONE token count (the trigger check — the
    context never changed, so recounting it is waste), and the
    still-over-trigger warning fires once per overflow episode, not once
    per reasoning step."""
    import logging as _logging

    ctx = [
        user("/heartbeat"),
        assistant("step one"),
        assistant("step two"),
    ]
    mgr = make_manager(store)
    agent = FakeAgent(ctx, tokens=600)  # > trigger (100), nothing to shrink
    agent._split_return = (ctx, [])
    with caplog.at_level(_logging.WARNING):
        await mgr.compress(agent)
        assert agent.model.calls == 1  # trigger check only
        await mgr.compress(agent)
        assert agent.model.calls == 2
    stuck = [
        r for r in caplog.records if "compression trigger" in r.getMessage()
    ]
    assert len(stuck) == 1


async def test_empty_middle_still_compacts_index_under_pressure(
    store: HistoryStore,
):
    """Regression for the phase-1 early return: with nothing evictable but
    an index already built, sustained pressure must still roll the index up
    (and re-render the placeholder) instead of doing nothing."""
    from qwenpaw.agents.context.scroll.eviction_index import Leaf

    mgr = make_manager(store)
    for i in range(3):  # a multi-block Tier 0 from earlier evictions
        mgr._index.add_eviction(
            [Leaf(seq=i * 10 + 1, headline=f"h{i}")],
            seq_lo=i * 10,
            seq_hi=i * 10 + 9,
        )
    ctx = [user("/heartbeat"), assistant("working", headline="W")]
    mgr._persist_new(FakeAgent(ctx))
    agent = FakeAgent(ctx, tokens=600)  # > reserve: sustained pressure
    agent._split_return = (ctx, [])  # nothing evictable
    await mgr.compress(agent)
    # The index was force-compacted to a single block and re-rendered.
    names = [m.name for m in agent.state.context]
    assert names[0] == "memory"
    assert (
        len([ln for ln in mgr._index.describe().splitlines() if "[seq" in ln])
        == 1
    )
    # The active turn is still live, after the placeholder.
    assert agent.state.context[-1].id == ctx[-1].id


def test_seq_by_tcid_round_trips_through_checkpoint(store: HistoryStore):
    mgr = make_manager(store)
    mgr._persist_new(FakeAgent([assistant_with_tool("call-7", "out")]))
    assert "call-7" in mgr._seq_by_tcid
    mgr2 = make_manager(store)
    mgr2.load_state(mgr.to_dict())
    assert mgr2._seq_by_tcid == mgr._seq_by_tcid


# -- degraded durability: no eviction on write failure ----------------------


async def test_compress_does_not_evict_when_persist_fails(
    store: HistoryStore,
    monkeypatch,
):
    import sqlite3

    ctx = [user("task"), assistant("step", headline="s"), assistant("more")]
    mgr = make_manager(store)
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
        user("next question"),
        assistant("recent"),
    ]
    mgr = make_manager(store, **kw)
    agent = FakeAgent(ctx, tokens=200)
    agent._split_return = (
        ctx[:2],
        ctx[2:],
    )  # evict [step]; keep task + [next, recent]
    return mgr, agent, ctx


async def test_compress_offloads_evicted_middle_when_configured(store):
    off = _RecordingOffloader()
    mgr, agent, ctx = _compactable(store, offloader=off)
    await mgr.compress(agent)
    assert len(off.calls) == 1
    session_id, ids = off.calls[0]
    assert session_id == "s1"
    assert ids == [ctx[0].id, ctx[1].id]  # exactly the evicted middle


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


def test_serialize_persists_runtime_tag():
    """The qwenpaw_tag survives into the durable row's metadata, so the
    recall layer's SQL floor can tell continuation stubs from requests."""
    from qwenpaw.agents.context.scroll.serialize import msg_to_entries
    from qwenpaw.constant import (
        LOOP_CONTINUATION_MESSAGE_TAG,
        QWENPAW_MESSAGE_TAG_KEY,
    )

    (entry,) = msg_to_entries(continuation_stub())
    assert entry.metadata == {
        QWENPAW_MESSAGE_TAG_KEY: LOOP_CONTINUATION_MESSAGE_TAG,
    }
    (plain,) = msg_to_entries(user("hello"))
    assert not plain.metadata


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
