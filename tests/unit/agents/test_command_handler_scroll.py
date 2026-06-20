# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for ``CommandHandler``'s scroll-aware ``/compact`` wiring.

The standalone command handler builds a bare AgentScope ``Agent`` whose
``compress_context`` is always *native*. Under the scroll strategy it must
instead drive a ``ScrollContextManager`` — but only then. These pin that
branch (and the native no-op) without constructing a real model/agent.
"""

from types import SimpleNamespace

from qwenpaw.agents.command_handler import CommandHandler


def _config(strategy="scroll"):
    scroll_config = SimpleNamespace(db_filename="history.db", pinned=2)
    lcc = SimpleNamespace(strategy=strategy, scroll_config=scroll_config)
    running = SimpleNamespace(light_context_config=lcc)
    return SimpleNamespace(running=running, id="ag1")


def _handler(tmp_path, *, strategy="scroll", workspace=True, monkeypatch):
    state = SimpleNamespace(context=[], session_id="sess-x")
    handler = CommandHandler(
        agent_name="QwenPaw",
        state=state,
        agent_id="ag1",
        workspace_dir=str(tmp_path) if workspace else None,
        session_id="sess-x",
    )
    monkeypatch.setattr(
        handler,
        "_get_agent_config",
        lambda: _config(strategy),
    )
    return handler


def test_builds_scroll_manager_under_scroll(tmp_path, monkeypatch):
    handler = _handler(tmp_path, strategy="scroll", monkeypatch=monkeypatch)
    mgr = handler._build_standalone_scroll_manager()
    try:
        assert mgr is not None
        # Bound to the authoritative session id, not state.session_id.
        assert mgr._session_id == "sess-x"
        assert (tmp_path / "history.db").exists()
    finally:
        if mgr is not None:
            mgr.close()


def test_native_strategy_stays_on_native(tmp_path, monkeypatch):
    handler = _handler(tmp_path, strategy="native", monkeypatch=monkeypatch)
    assert handler._build_standalone_scroll_manager() is None


def test_no_workspace_stays_on_native(tmp_path, monkeypatch):
    handler = _handler(
        tmp_path,
        strategy="scroll",
        workspace=False,
        monkeypatch=monkeypatch,
    )
    assert handler._build_standalone_scroll_manager() is None


def test_agent_backed_mode_never_builds_a_throwaway_manager():
    """When a live agent is present, /compact uses its own compress_context;
    the standalone builder is irrelevant (and updated_scroll_state stays None
    so the adapter preserves the live agent's own saved block)."""
    from unittest.mock import MagicMock

    agent = MagicMock()
    agent.state = SimpleNamespace(context=[], session_id="s")
    agent.memory_manager = None
    handler = CommandHandler(agent_name="QwenPaw", agent=agent)
    assert handler.updated_scroll_state is None
