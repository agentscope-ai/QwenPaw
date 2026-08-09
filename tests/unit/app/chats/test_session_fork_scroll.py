# -*- coding: utf-8 -*-
# pylint: disable=protected-access,too-many-statements
"""Production-path regression coverage for Scroll-aware session forks."""

from __future__ import annotations

from pathlib import Path

import pytest
from agentscope.message import Msg, TextBlock
from agentscope.state import AgentState

from qwenpaw.agents.context.scroll.continuation_summary import (
    ContinuationSummary,
    SummaryItem,
    SummarySource,
)
from qwenpaw.agents.context.scroll.history import HistoryStore
from qwenpaw.agents.context.scroll.manager import ScrollContextManager
from qwenpaw.agents.context.scroll.memoryspace import MemorySpace
from qwenpaw.agents.middlewares import MemoryMiddleware
from qwenpaw.agents.react_agent import QwenPawAgent
from qwenpaw.app.chats.session import SafeJSONSession


class _AgentShim:
    """Run the production Agent state serialization without model wiring."""

    def __init__(self, manager: ScrollContextManager, state=None) -> None:
        self._context_manager = manager
        self.state = state if state is not None else AgentState()

    def state_dict(self) -> dict:
        return QwenPawAgent.state_dict(self)

    def load_state_dict(self, data: dict, strict: bool = True) -> None:
        QwenPawAgent.load_state_dict(self, data, strict=strict)

    def _sanitize_loaded_context(self) -> None:
        QwenPawAgent._sanitize_loaded_context(self)


def _message(role: str, text: str) -> Msg:
    return Msg(
        name="user" if role == "user" else "assistant",
        role=role,
        content=[TextBlock(type="text", text=text)],
    )


@pytest.mark.asyncio
async def test_fork_rebases_identity_and_owns_full_scroll_history(
    tmp_path: Path,
):
    """Evicted and live rows survive under an independent fork identity."""
    source_session_id = "console:user"
    fork_session_id = "console:user:fork-12345678"
    history_path = tmp_path / "history.db"
    history = HistoryStore(history_path)
    sessions = SafeJSONSession(save_dir=str(tmp_path / "sessions"))

    old = _message("assistant", "old context already evicted")
    recent = _message("user", "recent context still live")
    source_state = AgentState(
        session_id=source_session_id,
        context=[old, recent],
    )
    source_manager = ScrollContextManager(
        history=history,
        session_id=source_session_id,
        agent_id="agent-1",
    )
    source_agent = _AgentShim(source_manager, source_state)
    source_manager._persist_new(source_agent)
    old_source_seq = source_manager._seq_by_id[old.id][0]
    recent_source_seq = source_manager._seq_by_id[recent.id][0]

    # Model a real compression boundary: the old turn is durable and indexed,
    # but no longer present in AgentState.context.
    source_manager._index_evicted([old])
    source_agent.state.context = [recent]
    source_manager._prune_bookkeeping_to_live_context(source_agent)
    source_manager._continuation_summary = ContinuationSummary(
        covered_seq=(old_source_seq, old_source_seq),
        active_task="Continue the forked task",
        status="in_progress",
        current_state=(
            SummaryItem(
                text="The old turn established the task.",
                sources=(
                    SummarySource(
                        type="seq",
                        lo=old_source_seq,
                        hi=old_source_seq,
                    ),
                ),
            ),
        ),
    )
    await sessions.save_session_state(
        session_id=source_session_id,
        agent=source_agent,
    )

    seq_map = history.clone_session_rows(
        source_session_id=source_session_id,
        destination_session_id=fork_session_id,
    )
    await sessions.clone_session_state(
        src_session_id=source_session_id,
        dst_session_id=fork_session_id,
        scroll_seq_map=seq_map,
    )

    fork_manager = ScrollContextManager(
        history=history,
        session_id=fork_session_id,
        agent_id="agent-1",
    )
    fork_agent = _AgentShim(fork_manager)
    await sessions.load_session_state(
        session_id=fork_session_id,
        agent=fork_agent,
    )

    # AgentScope/ReMe routing uses the fork identity, never the source.
    assert fork_agent.state.session_id == fork_session_id
    assert MemoryMiddleware._agent_session_id(fork_agent) == fork_session_id

    # Both the evicted turn and the restored live turn have fork-owned rows.
    old_fork_seq = seq_map[old_source_seq]
    recent_fork_seq = seq_map[recent_source_seq]
    memory = MemorySpace(
        history_db_path=history_path,
        session_id=fork_session_id,
        agent_id="agent-1",
    )
    try:
        assert memory.expand(old_fork_seq, old_fork_seq)[0]["content"] == (
            "old context already evicted"
        )
        assert (
            memory.expand(recent_fork_seq, recent_fork_seq)[0]["content"]
            == "recent context still live"
        )
        hits = memory.search(
            "already evicted",
            session_id=fork_session_id,
        )
        assert [(hit["session_id"], hit["content"]) for hit in hits] == [
            (fork_session_id, "old context already evicted"),
        ]
    finally:
        memory.close()

    index = fork_manager._index.to_dict()
    assert index["session_id"] == fork_session_id
    assert index["tiers"][0][0]["seq_lo"] == old_fork_seq
    assert index["tiers"][0][0]["seq_hi"] == old_fork_seq
    assert fork_manager._model_turn_seq[recent.id] == recent_fork_seq
    assert fork_manager._seq_by_id[recent.id] == (
        recent_fork_seq,
        recent_fork_seq,
    )
    assert fork_manager._continuation_summary is not None
    assert fork_manager._continuation_summary.covered_seq == (
        old_fork_seq,
        old_fork_seq,
    )
    assert fork_manager._continuation_summary.seq_spans() == (
        (old_fork_seq, old_fork_seq),
    )

    # First resume write-through recognizes the copied live row. A new fork
    # turn then changes only the fork's durable scope.
    fork_manager.on_save(fork_agent, None)
    assert history.count(source_session_id) == 2
    assert history.count(fork_session_id) == 2

    fork_agent.state.context.append(_message("user", "fork-only follow-up"))
    fork_manager.on_save(fork_agent, None)
    assert history.count(source_session_id) == 2
    assert history.count(fork_session_id) == 3

    history.close()
