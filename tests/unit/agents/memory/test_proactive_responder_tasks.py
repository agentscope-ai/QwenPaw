# -*- coding: utf-8 -*-
"""Tests for proactive responder task extraction and interruption checks.

Covers _create_tasks_from_data (pure), _extract_tasks_from_memory
(agent reply parsing and empty/invalid paths), and _was_interrupted
(busy-agent and chat-update detection), which were previously
uncovered.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument,use-implicit-booleaness-not-comparison  # noqa: E501
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


from qwenpaw.agents.memory.proactive import proactive_responder as pr


# ---------------------------------------------------------------------------
# _create_tasks_from_data
# ---------------------------------------------------------------------------


class TestCreateTasksFromData:
    def test_valid_tasks_created(self):
        data = [
            {"task": "check email", "query": "q1", "why": "important"},
            {"task": "review doc", "query": "q2"},
        ]
        tasks = pr._create_tasks_from_data(data)
        assert len(tasks) == 2
        assert tasks[0].task == "check email"
        assert tasks[0].priority == 1
        assert tasks[0].reason == "important"
        assert tasks[1].priority == 2
        assert tasks[1].reason == ""

    def test_missing_fields_skipped(self):
        data = [
            {"task": "only task"},  # no query
            {"query": "only query"},  # no task
            {"task": "t", "query": "q"},
        ]
        tasks = pr._create_tasks_from_data(data)
        assert len(tasks) == 1
        assert tasks[0].task == "t"

    def test_empty_list(self):
        assert pr._create_tasks_from_data([]) == []


# ---------------------------------------------------------------------------
# _extract_tasks_from_memory
# ---------------------------------------------------------------------------


def _reply_with_text(text):
    msg = SimpleNamespace()
    msg.get_text_content = lambda: text
    msg.content = [SimpleNamespace(text=text)]
    return msg


class TestExtractTasksFromMemory:
    async def test_valid_json_tasks_extracted(self):
        payload = json.dumps(
            {
                "tasks": [
                    {"task": "t1", "query": "q1", "why": "w"},
                ],
            },
        )
        agent = SimpleNamespace(
            reply=AsyncMock(return_value=_reply_with_text(payload)),
        )
        tasks = await pr._extract_tasks_from_memory("context", agent)
        assert len(tasks) == 1
        assert tasks[0].task == "t1"

    async def test_no_tasks_key_returns_empty(self):
        payload = json.dumps({"other": []})
        agent = SimpleNamespace(
            reply=AsyncMock(return_value=_reply_with_text(payload)),
        )
        assert await pr._extract_tasks_from_memory("c", agent) == []

    async def test_invalid_json_returns_empty(self):
        agent = SimpleNamespace(
            reply=AsyncMock(return_value=_reply_with_text("not json")),
        )
        assert await pr._extract_tasks_from_memory("c", agent) == []

    async def test_none_response_returns_empty(self):
        agent = SimpleNamespace(reply=AsyncMock(return_value=None))
        assert await pr._extract_tasks_from_memory("c", agent) == []

    async def test_empty_content_response_returns_empty(self):
        agent = SimpleNamespace(
            reply=AsyncMock(return_value=SimpleNamespace(content=None)),
        )
        assert await pr._extract_tasks_from_memory("c", agent) == []

    async def test_json_in_code_block_extracted(self):
        payload = (
            "```json\n"
            + json.dumps(
                {"tasks": [{"task": "t", "query": "q"}]},
            )
            + "\n```"
        )
        agent = SimpleNamespace(
            reply=AsyncMock(return_value=_reply_with_text(payload)),
        )
        tasks = await pr._extract_tasks_from_memory("c", agent)
        assert len(tasks) == 1


# ---------------------------------------------------------------------------
# _was_interrupted
# ---------------------------------------------------------------------------


class TestWasInterrupted:
    async def test_no_workspace_returns_false(self):
        baseline = datetime.now(timezone.utc)
        assert await pr._was_interrupted(baseline, None) is False

    async def test_busy_agent_interrupted(self):
        workspace = SimpleNamespace()
        baseline = datetime.now(timezone.utc)
        with patch.object(pr, "is_agent_busy", AsyncMock(return_value=True)):
            assert await pr._was_interrupted(baseline, workspace) is True

    async def test_busy_check_exception_not_fatal(self):
        workspace = SimpleNamespace()
        baseline = datetime.now(timezone.utc)
        with patch.object(
            pr,
            "is_agent_busy",
            AsyncMock(side_effect=RuntimeError("boom")),
        ):
            # no chat_manager -> falls through to False
            result = await pr._was_interrupted(baseline, workspace)
        assert result is False

    async def test_recent_chat_update_interrupted(self):
        baseline = datetime.now(timezone.utc) - timedelta(minutes=10)
        chat = SimpleNamespace(
            id="c1",
            updated_at=datetime.now(timezone.utc),
        )
        workspace = SimpleNamespace(
            chat_manager=SimpleNamespace(
                list_chats=AsyncMock(return_value=[chat]),
            ),
        )
        with patch.object(pr, "is_agent_busy", AsyncMock(return_value=False)):
            assert await pr._was_interrupted(baseline, workspace) is True

    async def test_stale_chat_not_interrupted(self):
        baseline = datetime.now(timezone.utc)
        chat = SimpleNamespace(
            id="c1",
            updated_at=baseline - timedelta(minutes=5),
        )
        workspace = SimpleNamespace(
            chat_manager=SimpleNamespace(
                list_chats=AsyncMock(return_value=[chat]),
            ),
        )
        with patch.object(pr, "is_agent_busy", AsyncMock(return_value=False)):
            assert await pr._was_interrupted(baseline, workspace) is False

    async def test_naive_baseline_coerced(self):
        baseline = datetime.now(timezone.utc) - timedelta(minutes=10)
        chat = SimpleNamespace(
            id="c1",
            updated_at=datetime.now(timezone.utc),
        )
        workspace = SimpleNamespace(
            chat_manager=SimpleNamespace(
                list_chats=AsyncMock(return_value=[chat]),
            ),
        )
        with patch.object(pr, "is_agent_busy", AsyncMock(return_value=False)):
            assert await pr._was_interrupted(baseline, workspace) is True

    async def test_chat_list_exception_not_fatal(self):
        baseline = datetime.now(timezone.utc)
        workspace = SimpleNamespace(
            chat_manager=SimpleNamespace(
                list_chats=AsyncMock(side_effect=RuntimeError("db down")),
            ),
        )
        with patch.object(pr, "is_agent_busy", AsyncMock(return_value=False)):
            assert await pr._was_interrupted(baseline, workspace) is False
