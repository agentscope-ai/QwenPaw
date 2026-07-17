# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access,unused-argument
"""Agent-level resume / crash-recovery tests for the scroll strategy.

These drive the REAL ``QwenPawAgent.state_dict`` / ``load_state_dict`` wiring
(not the manager in isolation): after an agent process dies mid-session and is
rebuilt from its persisted snapshot, its restored window must NOT be
re-appended to ``history.db``. The manager-level guarantee is covered in
``test_scroll_manager``; here we pin the glue that carries the scroll
bookkeeping through the agent's own (de)serialization.

The agent is exercised through a thin shim exposing only the two attributes
the methods under test touch (``state`` + ``_context_manager``), so we avoid
constructing the full agent (model / toolkit / governor) while still running
the production ``state_dict`` / ``load_state_dict`` code paths.
"""

import json
from pathlib import Path

import pytest
from agentscope.message import Msg, TextBlock
from agentscope.state import AgentState

from qwenpaw.agents.context.scroll.history import HistoryStore
from qwenpaw.agents.context.scroll.manager import ScrollContextManager
from qwenpaw.agents.react_agent import QwenPawAgent


class AgentShim:
    """Minimal stand-in for QwenPawAgent's state (de)serialization.

    ``state_dict`` / ``load_state_dict`` only read ``self.state`` and
    ``self._context_manager``; the manager's write-through only reads
    ``agent.state.context``. So this shim is enough to run all three against
    the real code.
    """

    def __init__(self, context_manager, state=None):
        self._context_manager = context_manager
        self.state = state if state is not None else AgentState()

    def _sanitize_loaded_context(self) -> None:
        """Delegate to the production loaded-context sanitizer."""
        QwenPawAgent._sanitize_loaded_context(self)


def _user(text):
    return Msg(
        name="u",
        role="user",
        content=[TextBlock(type="text", text=text)],
    )


def _assistant(text, headline=None):
    if headline:
        text = f"{text}\n⟦ {headline} ⟧"
    return Msg(
        name="a",
        role="assistant",
        content=[TextBlock(type="text", text=text)],
    )


@pytest.fixture
def store(tmp_path: Path):
    h = HistoryStore(tmp_path / "history.db")
    yield h
    h.close()


def _seed_session(store):
    """A live session whose manager has persisted a 3-turn window."""
    state = AgentState()
    state.context.extend(
        [
            _user("do the task"),
            _assistant("step one", headline="h1"),
            _assistant("step two", headline="h2"),
        ],
    )
    mgr = ScrollContextManager(history=store, session_id="s1", agent_id="ag1")
    agent = AgentShim(mgr, state)
    mgr._persist_new(agent)
    return agent, mgr


def test_state_dict_carries_the_scroll_bookkeeping(store):
    agent, _ = _seed_session(store)
    dumped = QwenPawAgent.state_dict(agent)
    assert "state" in dumped
    assert "scroll" in dumped  # the wiring: cm.to_dict() is embedded
    assert set(dumped["scroll"]["persisted_ids"]) == {
        m.id for m in agent.state.context
    }


def test_resume_after_crash_does_not_reappend(store):
    """Full cycle: persist → snapshot → JSON round-trip (the "crash") →
    rebuild a fresh agent+manager → the restored window is recognized as
    already durable, so the next write-through appends nothing."""
    agent1, mgr1 = _seed_session(store)
    assert store.count("s1") == 3
    snapshot = json.loads(json.dumps(QwenPawAgent.state_dict(agent1)))

    # New process: a brand-new manager (empty bookkeeping) on the SAME db.
    mgr2 = ScrollContextManager(history=store, session_id="s1", agent_id="ag1")
    agent2 = AgentShim(mgr2)
    QwenPawAgent.load_state_dict(agent2, snapshot, strict=True)

    # Window + bookkeeping were restored...
    assert [m.id for m in agent2.state.context] == [
        m.id for m in agent1.state.context
    ]
    assert mgr2._persisted_ids == mgr1._persisted_ids
    assert mgr2._index.to_dict() == mgr1._index.to_dict()
    # ...so the resumed session's write-through re-appends NOTHING.
    mgr2.on_save(agent2, None)
    assert store.count("s1") == 3


def test_resume_continues_appending_new_turns(store):
    """After resume, genuinely new turns are still persisted (the dedup seed
    must not freeze the store)."""
    agent1, _ = _seed_session(store)
    snapshot = json.loads(json.dumps(QwenPawAgent.state_dict(agent1)))

    mgr2 = ScrollContextManager(history=store, session_id="s1", agent_id="ag1")
    agent2 = AgentShim(mgr2)
    QwenPawAgent.load_state_dict(agent2, snapshot, strict=True)

    agent2.state.context.append(_assistant("step three", headline="h3"))
    mgr2.on_save(agent2, None)
    assert store.count("s1") == 4  # only the new turn landed


def test_resume_without_scroll_block_is_tolerated(store):
    """A pre-scroll / native snapshot (no 'scroll' key) still loads; the
    manager starts with empty bookkeeping and the DB ux_dedup index alone
    prevents duplicate rows on the re-append."""
    agent1, _ = _seed_session(store)
    snapshot = json.loads(json.dumps(QwenPawAgent.state_dict(agent1)))
    snapshot.pop("scroll")  # simulate an older checkpoint

    mgr2 = ScrollContextManager(history=store, session_id="s1", agent_id="ag1")
    agent2 = AgentShim(mgr2)
    QwenPawAgent.load_state_dict(agent2, snapshot, strict=True)

    assert mgr2._persisted_ids == set()  # nothing seeded
    mgr2.on_save(agent2, None)
    assert store.count("s1") == 3  # DB-level idempotency still holds
