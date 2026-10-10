# -*- coding: utf-8 -*-
"""Supplementary tests for proactive_utils screen analysis and session
metadata helpers.

Covers _clean_message_content empty-list branch, _analyze_screen_activity
(screenshot parsing, image-block detection, agent reply, JSON failure,
exception swallow), and _read_chat_sessions_metadata, which the first
backfill pass left uncovered.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from agentscope.message import Base64Source, DataBlock, TextBlock

from qwenpaw.agents.memory.proactive import proactive_utils as pu


# ---------------------------------------------------------------------------
# _clean_message_content — remaining branches
# ---------------------------------------------------------------------------


class TestCleanMessageContentExtra:
    def test_empty_block_list_returns_none(self):
        msg = SimpleNamespace(role="user", content=[])
        assert pu._clean_message_content(msg) is None

    def test_only_non_text_blocks_returns_none(self):
        msg = SimpleNamespace(role="user", content=[{"type": "image"}])
        assert pu._clean_message_content(msg) is None

    def test_mixed_keeps_only_text(self):
        msg = SimpleNamespace(
            role="user",
            content=[
                {"type": "image"},
                {"type": "text", "text": "keep"},
                {"type": "audio"},
            ],
        )
        result = pu._clean_message_content(msg)
        assert result is not None
        assert result.content == [{"type": "text", "text": "keep"}]

    def test_object_blocks_without_type_attr_skipped(self):
        msg = SimpleNamespace(role="user", content=[object()])
        assert pu._clean_message_content(msg) is None


# ---------------------------------------------------------------------------
# _analyze_screen_activity
# ---------------------------------------------------------------------------


def _screenshot_result(result_text: str, with_image: bool = True):
    """Build a fake desktop_screenshot() return value.

    The image block must be a real DataBlock because the code under test
    wraps it in a validated agentscope Msg via deepcopy.
    """
    blocks = []
    if with_image:
        blocks.append(
            DataBlock(
                source=Base64Source(data="aGk=", media_type="image/png"),
            ),
        )
    blocks.append(TextBlock(type="text", text=result_text))
    return SimpleNamespace(content=blocks)


class TestAnalyzeScreenActivity:
    async def test_successful_analysis(self):
        agent = SimpleNamespace()
        reply_msg = SimpleNamespace(
            get_text_content=lambda: "user is editing code",
        )
        agent.reply = AsyncMock(return_value=reply_msg)

        ok_json = json.dumps({"ok": True})
        fake_shot = _screenshot_result(ok_json)
        with patch(
            "qwenpaw.agents.tools.desktop_screenshot.desktop_screenshot",
            new=AsyncMock(return_value=fake_shot),
        ):
            result = await pu._analyze_screen_activity(agent)
        assert result is not None
        assert "SCREEN ANALYSIS" in result
        assert "user is editing code" in result

    async def test_screenshot_none_returns_none(self):
        agent = SimpleNamespace(reply=AsyncMock())
        with patch(
            "qwenpaw.agents.tools.desktop_screenshot.desktop_screenshot",
            new=AsyncMock(return_value=None),
        ):
            assert await pu._analyze_screen_activity(agent) is None

    async def test_screenshot_empty_content_returns_none(self):
        agent = SimpleNamespace(reply=AsyncMock())
        fake = SimpleNamespace(content=[])
        with patch(
            "qwenpaw.agents.tools.desktop_screenshot.desktop_screenshot",
            new=AsyncMock(return_value=fake),
        ):
            assert await pu._analyze_screen_activity(agent) is None

    async def test_screenshot_error_returns_none(self):
        agent = SimpleNamespace(reply=AsyncMock())
        ok_json = json.dumps({"ok": False, "error": "no display"})
        fake = _screenshot_result(ok_json)
        with patch(
            "qwenpaw.agents.tools.desktop_screenshot.desktop_screenshot",
            new=AsyncMock(return_value=fake),
        ):
            assert await pu._analyze_screen_activity(agent) is None

    async def test_no_image_block_returns_none(self):
        agent = SimpleNamespace(reply=AsyncMock())
        ok_json = json.dumps({"ok": True})
        fake = _screenshot_result(ok_json, with_image=False)
        with patch(
            "qwenpaw.agents.tools.desktop_screenshot.desktop_screenshot",
            new=AsyncMock(return_value=fake),
        ):
            assert await pu._analyze_screen_activity(agent) is None

    async def test_invalid_json_result_text_returns_none(self):
        agent = SimpleNamespace(reply=AsyncMock())
        fake = _screenshot_result("not json at all")
        with patch(
            "qwenpaw.agents.tools.desktop_screenshot.desktop_screenshot",
            new=AsyncMock(return_value=fake),
        ):
            assert await pu._analyze_screen_activity(agent) is None

    async def test_screenshot_exception_swallowed(self):
        agent = SimpleNamespace(reply=AsyncMock())
        with patch(
            "qwenpaw.agents.tools.desktop_screenshot.desktop_screenshot",
            new=AsyncMock(side_effect=RuntimeError("display down")),
        ):
            assert await pu._analyze_screen_activity(agent) is None

    async def test_empty_analysis_returns_none(self):
        agent = SimpleNamespace()
        reply_msg = SimpleNamespace(get_text_content=lambda: "")
        agent.reply = AsyncMock(return_value=reply_msg)
        ok_json = json.dumps({"ok": True})
        fake = _screenshot_result(ok_json)
        with patch(
            "qwenpaw.agents.tools.desktop_screenshot.desktop_screenshot",
            new=AsyncMock(return_value=fake),
        ):
            assert await pu._analyze_screen_activity(agent) is None


# ---------------------------------------------------------------------------
# _read_chat_sessions_metadata
# ---------------------------------------------------------------------------


class TestReadChatSessionsMetadata:
    def _chat(self, user_id="user1", session_id="s1", channel="console"):
        return SimpleNamespace(
            user_id=user_id,
            session_id=session_id,
            channel=channel,
            updated_at=datetime.now(timezone.utc),
        )

    async def test_builds_metadata_entries(self):
        chats = [self._chat()]
        workspace = SimpleNamespace(
            chat_manager=SimpleNamespace(
                list_chats=AsyncMock(return_value=chats),
            ),
        )
        result = await pu._read_chat_sessions_metadata(workspace)
        assert len(result) == 1
        assert result[0]["filename"] == "user1_s1.json"
        assert result[0]["user_id"] == "user1"

    async def test_colon_in_ids_replaced(self):
        chats = [self._chat(user_id="console:user", session_id="console:s1")]
        workspace = SimpleNamespace(
            chat_manager=SimpleNamespace(
                list_chats=AsyncMock(return_value=chats),
            ),
        )
        result = await pu._read_chat_sessions_metadata(workspace)
        assert ":" not in result[0]["user_id"]
        assert ":" not in result[0]["session_id"]

    async def test_list_chats_failure_returns_empty(self):
        workspace = SimpleNamespace(
            chat_manager=SimpleNamespace(
                list_chats=AsyncMock(side_effect=RuntimeError("boom")),
            ),
        )
        result = await pu._read_chat_sessions_metadata(workspace)
        assert result == []

    async def test_naive_updated_at_coerced(self):
        naive_chat = SimpleNamespace(
            user_id="u",
            session_id="s",
            channel="console",
            updated_at=datetime(2026, 1, 1),  # naive
        )
        workspace = SimpleNamespace(
            chat_manager=SimpleNamespace(
                list_chats=AsyncMock(return_value=[naive_chat]),
            ),
        )
        result = await pu._read_chat_sessions_metadata(workspace)
        assert len(result) == 1
