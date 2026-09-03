# -*- coding: utf-8 -*-
"""Unit tests for turn_usage snapshot / resolve / persist paths.

Complements ``test_turn_usage.py`` (pure helpers) by covering the
context-stats snapshot builder, the turn/ctx resolver, and the
session-persistence writer.
"""
# pylint: disable=protected-access,redefined-outer-name
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.token_usage import turn_usage


def _msg_stat(role: str, total_tokens: int = 0):
    return SimpleNamespace(role=role, total_tokens=total_tokens)


# ---------------------------------------------------------------------------
# snapshot_context_usage_for_state
# ---------------------------------------------------------------------------


class TestSnapshotContextUsage:
    async def _patch_deps(
        self,
        monkeypatch,
        *,
        max_input_length: int = 1000,
        stats: dict | None = None,
    ):
        monkeypatch.setattr(
            "qwenpaw.config.config.load_agent_config",
            lambda agent_id: SimpleNamespace(),
        )
        monkeypatch.setattr(
            "qwenpaw.config.config.get_model_max_input_length",
            lambda config: max_input_length,
        )

        async def fake_estimate(state, counter, limit):
            return dict(
                stats
                or {
                    "estimated_tokens": 300,
                    "max_input_length": limit,
                    "context_usage_ratio": 0.3,
                    "messages_detail": [
                        _msg_stat("user", 100),
                        _msg_stat("assistant", 40),
                        _msg_stat("user", 60),
                        _msg_stat("assistant", 25),
                        _msg_stat("assistant", 50),
                    ],
                },
            )

        monkeypatch.setattr(
            "qwenpaw.agents.utils.context_stats.estimate_context_tokens",
            fake_estimate,
        )
        monkeypatch.setattr(
            "qwenpaw.agents.utils.estimate_token_counter."
            "EstimatedTokenCounter",
            object,
        )

    async def test_uses_preferred_max_input_length(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        await self._patch_deps(monkeypatch)
        result = await turn_usage.snapshot_context_usage_for_state(
            SimpleNamespace(),
            "agent-1",
            preferred_max_input_length=2048,
        )
        assert result is not None
        # messages_detail is popped; latest assistant tokens after the
        # last user message are summed.
        assert "messages_detail" not in result
        assert result["latest_assistant_tokens"] == 50

    async def test_falls_back_to_config_max_length(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        await self._patch_deps(monkeypatch, max_input_length=4096)
        result = await turn_usage.snapshot_context_usage_for_state(
            SimpleNamespace(),
            "agent-1",
        )
        assert result is not None
        assert result["max_input_length"] == 4096

    async def test_zero_max_length_returns_none(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        await self._patch_deps(monkeypatch, max_input_length=0)
        result = await turn_usage.snapshot_context_usage_for_state(
            SimpleNamespace(),
            "agent-1",
        )
        assert result is None

    async def test_no_assistant_after_last_user(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        stats = {
            "estimated_tokens": 10,
            "max_input_length": 100,
            "context_usage_ratio": 0.1,
            "messages_detail": [
                _msg_stat("assistant", 99),
                _msg_stat("user", 5),
            ],
        }
        await self._patch_deps(monkeypatch, stats=stats)
        result = await turn_usage.snapshot_context_usage_for_state(
            SimpleNamespace(),
            "agent-1",
            preferred_max_input_length=100,
        )
        assert result is not None
        assert result["latest_assistant_tokens"] == 0

    async def test_exception_returns_none(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        def boom(agent_id):
            raise RuntimeError("config gone")

        monkeypatch.setattr(
            "qwenpaw.config.config.load_agent_config",
            boom,
        )
        result = await turn_usage.snapshot_context_usage_for_state(
            SimpleNamespace(),
            "agent-1",
        )
        assert result is None


# ---------------------------------------------------------------------------
# resolve_turn_usage
# ---------------------------------------------------------------------------


class TestResolveTurnUsage:
    async def test_no_session_returns_turn_only(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        turn = {"prompt_tokens": 1, "completion_tokens": 2}
        monkeypatch.setattr(
            "qwenpaw.token_usage.model_wrapper."
            "TokenRecordingModelWrapper.pop_usage_for_session",
            classmethod(lambda cls, sid: turn),
        )
        got_turn, ctx, state = await turn_usage.resolve_turn_usage(
            session_id="s",
            agent_id="a",
            session=None,
            user_id="u",
            channel="console",
        )
        assert got_turn == turn
        assert ctx is None
        assert state is None

    async def test_missing_agent_state_returns_turn_and_none(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setattr(
            "qwenpaw.token_usage.model_wrapper."
            "TokenRecordingModelWrapper.pop_usage_for_session",
            classmethod(lambda cls, sid: None),
        )
        monkeypatch.setattr(
            turn_usage,
            "_load_agent_state",
            AsyncMock(return_value=None),
        )
        got_turn, ctx, state = await turn_usage.resolve_turn_usage(
            session_id="s",
            agent_id="a",
            session=SimpleNamespace(),
            user_id="u",
            channel="console",
        )
        assert got_turn is None
        assert ctx is None
        assert state is None

    async def test_stats_missing_returns_state_without_ctx(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        agent_state = SimpleNamespace()
        monkeypatch.setattr(
            "qwenpaw.token_usage.model_wrapper."
            "TokenRecordingModelWrapper.pop_usage_for_session",
            classmethod(lambda cls, sid: None),
        )
        monkeypatch.setattr(
            turn_usage,
            "_load_agent_state",
            AsyncMock(return_value=agent_state),
        )
        monkeypatch.setattr(
            turn_usage,
            "snapshot_context_usage_for_state",
            AsyncMock(return_value=None),
        )
        got_turn, ctx, state = await turn_usage.resolve_turn_usage(
            session_id="s",
            agent_id="a",
            session=SimpleNamespace(),
            user_id="u",
            channel="console",
        )
        assert got_turn is None
        assert ctx is None
        assert state is agent_state

    async def test_stats_present_builds_ctx_and_estimated_turn(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        agent_state = SimpleNamespace()
        stats = {
            "estimated_tokens": 500,
            "max_input_length": 1000,
            "context_usage_ratio": 0.5,
            "latest_assistant_tokens": 100,
        }
        monkeypatch.setattr(
            "qwenpaw.token_usage.model_wrapper."
            "TokenRecordingModelWrapper.pop_usage_for_session",
            classmethod(lambda cls, sid: None),
        )
        monkeypatch.setattr(
            turn_usage,
            "_load_agent_state",
            AsyncMock(return_value=agent_state),
        )
        monkeypatch.setattr(
            turn_usage,
            "snapshot_context_usage_for_state",
            AsyncMock(return_value=stats),
        )

        got_turn, ctx, state = await turn_usage.resolve_turn_usage(
            session_id="s",
            agent_id="a",
            session=SimpleNamespace(),
            user_id="u",
            channel="console",
        )

        assert ctx == {
            "estimated_tokens": 500,
            "max_input_length": 1000,
            "context_usage_ratio": 0.5,
        }
        assert got_turn is not None
        assert got_turn["estimated"] is True
        assert got_turn["total_tokens"] == 500
        assert got_turn["completion_tokens"] == 100
        assert state is agent_state

    async def test_existing_turn_is_reconciled(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        recorded = {
            "prompt_tokens": 80,
            "completion_tokens": 0,
            "context_size": 1000,
        }
        stats = {
            "estimated_tokens": 500,
            "max_input_length": 1000,
            "context_usage_ratio": 0.5,
            "latest_assistant_tokens": 90,
        }
        monkeypatch.setattr(
            "qwenpaw.token_usage.model_wrapper."
            "TokenRecordingModelWrapper.pop_usage_for_session",
            classmethod(lambda cls, sid: recorded),
        )
        monkeypatch.setattr(
            turn_usage,
            "_load_agent_state",
            AsyncMock(return_value=SimpleNamespace()),
        )
        monkeypatch.setattr(
            turn_usage,
            "snapshot_context_usage_for_state",
            AsyncMock(return_value=stats),
        )

        got_turn, _, _ = await turn_usage.resolve_turn_usage(
            session_id="s",
            agent_id="a",
            session=SimpleNamespace(),
            user_id="u",
            channel="console",
        )

        # Under-reported completion patched from the estimate.
        assert got_turn["completion_tokens"] == 90
        assert got_turn["total_tokens"] == 170


# ---------------------------------------------------------------------------
# persist_turn_usage
# ---------------------------------------------------------------------------


class TestPersistTurnUsage:
    async def test_no_turn_and_ctx_is_noop(self):
        session = SimpleNamespace(update_session_state=AsyncMock())
        await turn_usage.persist_turn_usage(
            session=session,
            session_id="s",
            user_id="u",
            channel="console",
            turn=None,
            ctx=None,
        )
        session.update_session_state.assert_not_awaited()

    async def test_no_agent_state_is_noop(self):
        session = SimpleNamespace(
            update_session_state=AsyncMock(),
            get_session_state_dict=AsyncMock(return_value=None),
        )
        await turn_usage.persist_turn_usage(
            session=session,
            session_id="s",
            user_id="u",
            channel="console",
            turn={"total_tokens": 1},
            ctx=None,
        )
        session.update_session_state.assert_not_awaited()

    async def test_writes_meta_and_updates_session(self):
        closing = SimpleNamespace(
            role="assistant",
            metadata={},
        )
        agent_state = SimpleNamespace(
            context=[
                SimpleNamespace(role="user"),
                closing,
            ],
            model_dump=lambda mode=None: {"agent": {}},
        )
        session = SimpleNamespace(update_session_state=AsyncMock())

        await turn_usage.persist_turn_usage(
            session=session,
            session_id="s",
            user_id="u",
            channel="console",
            turn={"total_tokens": 5},
            ctx={"estimated_tokens": 100},
            agent_state=agent_state,
        )

        meta = closing.metadata[turn_usage.TURN_USAGE_META_KEY]
        assert meta["usage"] == {"total_tokens": 5}
        assert meta["context_usage"] == {"estimated_tokens": 100}
        session.update_session_state.assert_awaited_once()
        kwargs = session.update_session_state.call_args.kwargs
        assert kwargs["key"] == "agent.state"
        assert kwargs["session_id"] == "s"

    async def test_update_failure_is_swallowed(self):
        closing = SimpleNamespace(role="assistant", metadata={})
        agent_state = SimpleNamespace(
            context=[closing],
            model_dump=lambda mode=None: {},
        )
        session = SimpleNamespace(
            update_session_state=AsyncMock(
                side_effect=RuntimeError("store down"),
            ),
        )

        # Must not raise.
        await turn_usage.persist_turn_usage(
            session=session,
            session_id="s",
            user_id="u",
            channel="console",
            turn={"total_tokens": 5},
            ctx=None,
            agent_state=agent_state,
        )

    async def test_no_closing_assistant_skips_update(self):
        agent_state = SimpleNamespace(
            context=[SimpleNamespace(role="user")],
            model_dump=lambda mode=None: {},
        )
        session = SimpleNamespace(update_session_state=AsyncMock())

        await turn_usage.persist_turn_usage(
            session=session,
            session_id="s",
            user_id="u",
            channel="console",
            turn={"total_tokens": 5},
            ctx=None,
            agent_state=agent_state,
        )

        session.update_session_state.assert_not_awaited()


# ---------------------------------------------------------------------------
# _load_agent_state
# ---------------------------------------------------------------------------


class TestLoadAgentState:
    async def test_parses_valid_state(self, monkeypatch):
        raw = {"foo": "bar"}
        sentinel = object()
        session = SimpleNamespace(
            get_session_state_dict=AsyncMock(
                return_value={"agent": {"state": raw}},
            ),
        )

        class FakeAgentState:
            @staticmethod
            def model_validate(payload):
                assert payload == raw
                return sentinel

        monkeypatch.setattr("agentscope.state.AgentState", FakeAgentState)

        result = await turn_usage._load_agent_state(
            session=session,
            session_id="s",
            user_id="u",
            channel="console",
        )
        assert result is sentinel

    async def test_empty_state_returns_none(self):
        session = SimpleNamespace(
            get_session_state_dict=AsyncMock(return_value={}),
        )
        result = await turn_usage._load_agent_state(
            session=session,
            session_id="s",
            user_id="u",
            channel="console",
        )
        assert result is None

    async def test_non_dict_agent_state_returns_none(self):
        session = SimpleNamespace(
            get_session_state_dict=AsyncMock(
                return_value={"agent": {"state": "junk"}},
            ),
        )
        result = await turn_usage._load_agent_state(
            session=session,
            session_id="s",
            user_id="u",
            channel="console",
        )
        assert result is None

    async def test_invalid_agent_state_returns_none(self, monkeypatch):
        session = SimpleNamespace(
            get_session_state_dict=AsyncMock(
                return_value={"agent": {"state": {"x": 1}}},
            ),
        )

        class FakeAgentState:
            @staticmethod
            def model_validate(payload):
                raise ValueError("bad state")

        monkeypatch.setattr("agentscope.state.AgentState", FakeAgentState)
        result = await turn_usage._load_agent_state(
            session=session,
            session_id="s",
            user_id="u",
            channel="console",
        )
        assert result is None
