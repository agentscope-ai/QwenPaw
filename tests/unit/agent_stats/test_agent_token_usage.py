# -*- coding: utf-8 -*-
"""Unit tests for current-agent token aggregation in AgentStatsService."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from qwenpaw.agent_stats.models import AgentStatsSummary
from qwenpaw.agent_stats.service import (
    AgentStatsService,
    _process_session_file,
)
from qwenpaw.token_usage.manager import TokenUsageStats, TokenUsageSummary
from qwenpaw.token_usage.turn_usage import TURN_USAGE_META_KEY


def _empty_daily(date_str: str) -> dict:
    return {
        "date": date_str,
        "chats": 0,
        "active_sessions": 0,
        "user_messages": 0,
        "assistant_messages": 0,
        "total_messages": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "llm_calls": 0,
        "tool_calls": 0,
        "agent_prompt_tokens": 0,
        "agent_completion_tokens": 0,
        "agent_llm_calls": 0,
    }


def _assistant_with_usage(
    *,
    created_at: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> dict:
    return {
        "role": "assistant",
        "created_at": created_at,
        "content": [{"type": "text", "text": "hi"}],
        "metadata": {
            TURN_USAGE_META_KEY: {
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                },
            },
        },
    }


class TestProcessSessionFileAgentTokens:
    """Cover agent token accumulation inside _process_session_file."""

    def test_accumulates_turn_usage_from_assistant_metadata(self):
        daily_stats = {
            "2026-07-23": _empty_daily("2026-07-23"),
            "2026-07-24": _empty_daily("2026-07-24"),
        }
        channel_stats: dict = {}
        active_sessions: dict = {}
        session_data = {
            "agent": {
                "state": {
                    "context": [
                        {
                            "role": "user",
                            "created_at": "2026-07-2aT10:00:00Z",
                            "content": [{"type": "text", "text": "bad"}],
                        },
                        {
                            "role": "user",
                            "created_at": "2026-07-23T10:00:00Z",
                            "content": [{"type": "text", "text": "q"}],
                        },
                        _assistant_with_usage(
                            created_at="2026-07-23T10:00:01Z",
                            prompt_tokens=100,
                            completion_tokens=40,
                        ),
                        {
                            "role": "user",
                            "created_at": "2026-07-23T11:00:00Z",
                            "content": [{"type": "text", "text": "q2"}],
                        },
                        _assistant_with_usage(
                            created_at="2026-07-23T11:00:01Z",
                            prompt_tokens=200,
                            completion_tokens=60,
                        ),
                    ],
                },
            },
        }

        (
            tool_calls,
            has_messages,
            agent_prompt,
            agent_completion,
            agent_llm_calls,
        ) = _process_session_file(
            session_data,
            "2026-07-01",
            "2026-07-31",
            daily_stats,
            channel_stats,
            "console",
            "sess-1",
            active_sessions,
        )

        assert has_messages is True
        assert tool_calls == 0
        assert agent_prompt == 300
        assert agent_completion == 100
        assert agent_llm_calls == 2
        # Global daily token fields must remain untouched (overlay owns them)
        assert daily_stats["2026-07-23"]["prompt_tokens"] == 0
        assert daily_stats["2026-07-23"]["completion_tokens"] == 0
        assert daily_stats["2026-07-23"]["llm_calls"] == 0
        assert daily_stats["2026-07-23"]["assistant_messages"] == 2
        # Agent daily token fields accumulate from turn metadata
        assert daily_stats["2026-07-23"]["agent_prompt_tokens"] == 300
        assert daily_stats["2026-07-23"]["agent_completion_tokens"] == 100
        assert daily_stats["2026-07-23"]["agent_llm_calls"] == 2
        assert daily_stats["2026-07-24"]["agent_prompt_tokens"] == 0
        assert daily_stats["2026-07-24"]["agent_completion_tokens"] == 0
        assert daily_stats["2026-07-24"]["agent_llm_calls"] == 0

    def test_ignores_missing_or_empty_usage(self):
        daily_stats = {"2026-07-23": _empty_daily("2026-07-23")}
        session_data = {
            "agent": {
                "state": {
                    "context": [
                        {
                            "role": "assistant",
                            "created_at": "2026-07-23T10:00:00Z",
                            "content": [{"type": "text", "text": "a"}],
                            "metadata": {},
                        },
                        {
                            "role": "assistant",
                            "created_at": "2026-07-23T10:01:00Z",
                            "content": [{"type": "text", "text": "b"}],
                            "metadata": {
                                TURN_USAGE_META_KEY: {"usage": None},
                            },
                        },
                        {
                            "role": "assistant",
                            "created_at": "2026-07-23T10:02:00Z",
                            "content": [{"type": "text", "text": "c"}],
                            "metadata": {
                                TURN_USAGE_META_KEY: {
                                    "usage": {
                                        "prompt_tokens": 0,
                                        "completion_tokens": 0,
                                    },
                                },
                            },
                        },
                    ],
                },
            },
        }

        result = _process_session_file(
            session_data,
            "2026-07-23",
            "2026-07-23",
            daily_stats,
            {},
            "console",
            "sess-2",
            {},
        )
        assert result[2:] == (0, 0, 0)

    def test_invalid_usage_tokens_do_not_wipe_session_stats(self):
        daily_stats = {"2026-07-23": _empty_daily("2026-07-23")}
        session_data = {
            "agent": {
                "state": {
                    "context": [
                        {
                            "role": "assistant",
                            "created_at": "2026-07-23T10:00:00Z",
                            "content": [{"type": "text", "text": "bad"}],
                            "metadata": {
                                TURN_USAGE_META_KEY: {
                                    "usage": {
                                        "prompt_tokens": "abc",
                                        "completion_tokens": 10,
                                    },
                                },
                            },
                        },
                        _assistant_with_usage(
                            created_at="2026-07-23T10:01:00Z",
                            prompt_tokens=20,
                            completion_tokens=5,
                        ),
                    ],
                },
            },
        }

        (
            _tool_calls,
            has_messages,
            agent_prompt,
            agent_completion,
            agent_llm_calls,
        ) = _process_session_file(
            session_data,
            "2026-07-23",
            "2026-07-23",
            daily_stats,
            {},
            "console",
            "sess-invalid",
            {},
        )

        assert has_messages is True
        assert daily_stats["2026-07-23"]["assistant_messages"] == 2
        assert agent_prompt == 20
        assert agent_completion == 5
        assert agent_llm_calls == 1
        assert daily_stats["2026-07-23"]["agent_prompt_tokens"] == 20
        assert daily_stats["2026-07-23"]["agent_completion_tokens"] == 5

    def test_accumulates_agent_tokens_per_day(self):
        daily_stats = {
            "2026-07-23": _empty_daily("2026-07-23"),
            "2026-07-24": _empty_daily("2026-07-24"),
        }
        session_data = {
            "agent": {
                "state": {
                    "context": [
                        _assistant_with_usage(
                            created_at="2026-07-23T10:00:00Z",
                            prompt_tokens=100,
                            completion_tokens=10,
                        ),
                        _assistant_with_usage(
                            created_at="2026-07-24T10:00:00Z",
                            prompt_tokens=50,
                            completion_tokens=5,
                        ),
                    ],
                },
            },
        }

        (
            _tool_calls,
            has_messages,
            agent_prompt,
            agent_completion,
            agent_llm_calls,
        ) = _process_session_file(
            session_data,
            "2026-07-23",
            "2026-07-24",
            daily_stats,
            {},
            "console",
            "sess-days",
            {},
        )

        assert has_messages is True
        assert agent_prompt == 150
        assert agent_completion == 15
        assert agent_llm_calls == 2
        assert daily_stats["2026-07-23"]["agent_prompt_tokens"] == 100
        assert daily_stats["2026-07-23"]["agent_completion_tokens"] == 10
        assert daily_stats["2026-07-23"]["agent_llm_calls"] == 1
        assert daily_stats["2026-07-24"]["agent_prompt_tokens"] == 50
        assert daily_stats["2026-07-24"]["agent_completion_tokens"] == 5
        assert daily_stats["2026-07-24"]["agent_llm_calls"] == 1
        assert daily_stats["2026-07-23"]["prompt_tokens"] == 0
        assert daily_stats["2026-07-24"]["prompt_tokens"] == 0

    def test_skips_usage_outside_date_range(self):
        daily_stats = {"2026-07-23": _empty_daily("2026-07-23")}
        session_data = {
            "agent": {
                "state": {
                    "context": [
                        _assistant_with_usage(
                            created_at="2026-07-22T10:00:00Z",
                            prompt_tokens=999,
                            completion_tokens=999,
                        ),
                        _assistant_with_usage(
                            created_at="2026-07-23T10:00:00Z",
                            prompt_tokens=10,
                            completion_tokens=5,
                        ),
                    ],
                },
            },
        }

        result = _process_session_file(
            session_data,
            "2026-07-23",
            "2026-07-23",
            daily_stats,
            {},
            "console",
            "sess-3",
            {},
        )
        assert result[2:] == (10, 5, 1)
        assert daily_stats["2026-07-23"]["agent_prompt_tokens"] == 10
        assert daily_stats["2026-07-23"]["agent_completion_tokens"] == 5
        assert daily_stats["2026-07-23"]["prompt_tokens"] == 0


@pytest.mark.asyncio
class TestAgentStatsServiceAgentTokens:
    """Cover get_summary wiring for agent_* vs global totals."""

    async def test_get_summary_keeps_global_and_fills_agent_fields(
        self,
        tmp_path: Path,
    ):
        workspace = tmp_path / "agent-a"
        sessions = workspace / "sessions" / "console"
        sessions.mkdir(parents=True)
        session_file = sessions / "s1.json"
        session_file.write_text(
            json.dumps(
                {
                    "agent": {
                        "state": {
                            "context": [
                                {
                                    "role": "user",
                                    "created_at": "2026-07-23T09:00:00Z",
                                    "content": [
                                        {"type": "text", "text": "hi"},
                                    ],
                                },
                                _assistant_with_usage(
                                    created_at="2026-07-23T09:00:01Z",
                                    prompt_tokens=111,
                                    completion_tokens=22,
                                ),
                            ],
                        },
                    },
                },
            ),
            encoding="utf-8",
        )

        global_summary = TokenUsageSummary(
            total_prompt_tokens=4_000_000,
            total_completion_tokens=284_800,
            total_calls=72,
            by_model={},
            by_date={
                "2026-07-23": TokenUsageStats(
                    prompt_tokens=4_000_000,
                    completion_tokens=284_800,
                    call_count=72,
                ),
            },
        )
        mock_manager = AsyncMock()
        mock_manager.get_summary = AsyncMock(return_value=global_summary)

        with patch(
            "qwenpaw.agent_stats.service.get_token_usage_manager",
            return_value=mock_manager,
        ):
            summary = await AgentStatsService().get_summary(
                workspace_dir=workspace,
                start_date=date(2026, 7, 23),
                end_date=date(2026, 7, 24),
            )

        assert isinstance(summary, AgentStatsSummary)
        # Global totals remain from token_usage manager
        assert summary.total_prompt_tokens == 4_000_000
        assert summary.total_completion_tokens == 284_800
        assert summary.total_llm_calls == 72
        assert summary.by_date[0].prompt_tokens == 4_000_000
        assert summary.by_date[0].completion_tokens == 284_800
        assert summary.by_date[0].llm_calls == 72
        # Agent-scoped fields come from session turn metadata
        assert summary.agent_prompt_tokens == 111
        assert summary.agent_completion_tokens == 22
        assert summary.agent_llm_calls == 1
        assert summary.total_messages == 2
        # Daily agent token fields are independent of global overlay
        assert summary.by_date[0].agent_prompt_tokens == 111
        assert summary.by_date[0].agent_completion_tokens == 22
        assert summary.by_date[0].agent_llm_calls == 1
        assert summary.by_date[1].agent_prompt_tokens == 0
        assert summary.by_date[1].agent_completion_tokens == 0
        assert summary.by_date[1].agent_llm_calls == 0

    async def test_agent_tokens_isolated_per_workspace(self, tmp_path: Path):
        def _write_workspace(name: str, prompt: int, completion: int) -> Path:
            root = tmp_path / name
            sess_dir = root / "sessions" / "console"
            sess_dir.mkdir(parents=True)
            (sess_dir / "s.json").write_text(
                json.dumps(
                    {
                        "agent": {
                            "state": {
                                "context": [
                                    _assistant_with_usage(
                                        created_at="2026-07-23T10:00:00Z",
                                        prompt_tokens=prompt,
                                        completion_tokens=completion,
                                    ),
                                ],
                            },
                        },
                    },
                ),
                encoding="utf-8",
            )
            return root

        ws_a = _write_workspace("agent-a", 100, 10)
        ws_b = _write_workspace("agent-b", 500, 50)

        empty_global = TokenUsageSummary(
            total_prompt_tokens=999,
            total_completion_tokens=99,
            total_calls=9,
            by_model={},
            by_date={},
        )
        mock_manager = AsyncMock()
        mock_manager.get_summary = AsyncMock(return_value=empty_global)

        with patch(
            "qwenpaw.agent_stats.service.get_token_usage_manager",
            return_value=mock_manager,
        ):
            summary_a = await AgentStatsService().get_summary(
                workspace_dir=ws_a,
                start_date=date(2026, 7, 23),
                end_date=date(2026, 7, 23),
            )
            summary_b = await AgentStatsService().get_summary(
                workspace_dir=ws_b,
                start_date=date(2026, 7, 23),
                end_date=date(2026, 7, 23),
            )

        assert summary_a.agent_prompt_tokens == 100
        assert summary_a.agent_completion_tokens == 10
        assert summary_a.agent_llm_calls == 1
        assert summary_b.agent_prompt_tokens == 500
        assert summary_b.agent_completion_tokens == 50
        assert summary_b.agent_llm_calls == 1
        # Global fields stay identical (same mocked manager)
        assert summary_a.total_prompt_tokens == 999
        assert summary_b.total_prompt_tokens == 999


def _write_trend_workspace(root: Path, n_turns: int, n_tools: int) -> Path:
    sess_dir = root / "sessions" / "console"
    sess_dir.mkdir(parents=True)
    (root / "agent.json").write_text("{}", encoding="utf-8")
    content: list[dict] = [{"type": "text", "text": "hi"}]
    content.extend(
        {"type": "tool_use", "id": f"t{i}", "name": "x", "input": {}}
        for i in range(n_tools)
    )
    turns = []
    for _ in range(n_turns):
        msg = _assistant_with_usage(
            created_at="2026-07-23T10:00:00Z",
            prompt_tokens=10,
            completion_tokens=1,
        )
        msg["content"] = list(content)
        turns.append(msg)
    (sess_dir / "s.json").write_text(
        json.dumps({"agent": {"state": {"context": turns}}}),
        encoding="utf-8",
    )
    return root


@pytest.mark.asyncio
async def test_get_global_llm_tool_by_date_sums_skips_and_fills(tmp_path):
    """Sum agents, skip dup, fill days; overlay must not run."""
    ws_a = _write_trend_workspace(tmp_path / "a", 2, 2)
    ws_b = _write_trend_workspace(tmp_path / "b", 1, 1)
    with (
        patch(
            "qwenpaw.agent_stats.service.get_agent_dirs",
            return_value=[ws_a, ws_a, ws_b],
        ),
        patch(
            "qwenpaw.agent_stats.service.get_token_usage_manager",
        ) as mock_overlay,
    ):
        rows = await AgentStatsService().get_global_llm_tool_by_date(
            start_date=date(2026, 7, 23),
            end_date=date(2026, 7, 24),
        )

    mock_overlay.assert_not_called()
    assert [row.date for row in rows] == ["2026-07-23", "2026-07-24"]
    assert (rows[0].agent_llm_calls, rows[0].tool_calls) == (3, 5)
    assert (rows[1].agent_llm_calls, rows[1].tool_calls) == (0, 0)


@pytest.mark.asyncio
async def test_get_global_llm_tool_by_date_clamps_to_365_days():
    with patch(
        "qwenpaw.agent_stats.service.get_agent_dirs",
        return_value=[],
    ):
        rows = await AgentStatsService().get_global_llm_tool_by_date(
            start_date=date(2025, 1, 1),
            end_date=date(2026, 8, 1),
        )
    assert len(rows) == 365
    assert rows[0].date == "2025-08-02"
    assert rows[-1].date == "2026-08-01"
