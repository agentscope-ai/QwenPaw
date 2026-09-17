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
    scroll_config = SimpleNamespace(db_filename="history.db")
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


class _FakeCtxConfig:
    """Minimal stand-in for AgentScope ``ContextConfig`` (pydantic-like)."""

    def __init__(self, trigger_ratio, reserve_ratio):
        self.trigger_ratio = trigger_ratio
        self.reserve_ratio = reserve_ratio

    def model_copy(self, *, update):
        merged = {
            "trigger_ratio": self.trigger_ratio,
            "reserve_ratio": self.reserve_ratio,
            **update,
        }
        return _FakeCtxConfig(**merged)


def test_forced_compact_drops_trigger_keeps_reserve(monkeypatch):
    """Under scroll, manual /compact forces the trigger but keeps the
    configured recent-tail reserve — same as auto compaction. /compact only
    means "compact now", not "shrink the tail more aggressively"; a
    conversation that already fits inside the reserve has nothing to evict."""
    from qwenpaw.agents.command_handler import _FORCE_TRIGGER_RATIO

    handler = CommandHandler(agent_name="QwenPaw")
    monkeypatch.setattr(
        handler,
        "_get_agent_config",
        lambda: _config("scroll"),
    )
    agent = SimpleNamespace(context_config=_FakeCtxConfig(0.8, 0.1))
    forced = handler._forced_context_config(agent)
    assert forced.trigger_ratio == _FORCE_TRIGGER_RATIO
    # Reserve stays at the configured base — no scroll-specific shrink.
    assert forced.reserve_ratio == 0.1
    # The original is untouched (model_copy, not in-place mutation).
    assert agent.context_config.reserve_ratio == 0.1


def test_forced_compact_under_native_keeps_reserve(monkeypatch):
    """Under native, manual /compact forces the trigger but must NOT shrink the
    reserve. Native compaction is lossy (the non-reserved middle is summarized
    away and the originals dropped), so it keeps the configured reserve to
    preserve the same recent-tail continuity as auto compaction."""
    from qwenpaw.agents.command_handler import _FORCE_TRIGGER_RATIO

    handler = CommandHandler(agent_name="QwenPaw")
    monkeypatch.setattr(
        handler,
        "_get_agent_config",
        lambda: _config("native"),
    )
    agent = SimpleNamespace(context_config=_FakeCtxConfig(0.8, 0.1))
    forced = handler._forced_context_config(agent)
    assert forced.trigger_ratio == _FORCE_TRIGGER_RATIO
    # Reserve stays at the configured base, not the scroll-only shrink.
    assert forced.reserve_ratio == 0.1


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
