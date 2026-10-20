# -*- coding: utf-8 -*-
"""Unit tests for the per-chat approval level (chat meta namespace).

Covers the meta reader (``session_approval_level_from_meta``) and the
manager setter (``set_session_approval_level``) against the real
:class:`JsonChatRepository`, mirroring the sibling session-setting
tests.
"""

# pylint: disable=redefined-outer-name,unused-argument
from __future__ import annotations

from pathlib import Path

import pytest

from qwenpaw.app.chats.manager import ChatManager
from qwenpaw.app.chats.models import ChatSpec
from qwenpaw.app.chats.repo import JsonChatRepository
from qwenpaw.services.session_approval import (
    session_approval_level_from_meta,
)

# ---------------------------------------------------------------------------
# session_approval_level_from_meta
# ---------------------------------------------------------------------------


class TestSessionApprovalLevelFromMeta:
    def test_none_meta(self):
        assert session_approval_level_from_meta(None) is None

    def test_empty_meta(self):
        assert session_approval_level_from_meta({}) is None

    def test_no_runtime_context(self):
        assert session_approval_level_from_meta({"other": 1}) is None

    def test_no_key(self):
        assert (
            session_approval_level_from_meta({"runtime_context": {}}) is None
        )

    def test_valid_lowercase_normalized_to_name(self):
        meta = {"runtime_context": {"approval_level": "strict"}}
        assert session_approval_level_from_meta(meta) == "STRICT"

    def test_valid_mixed_case(self):
        meta = {"runtime_context": {"approval_level": "SmArT"}}
        assert session_approval_level_from_meta(meta) == "SMART"

    def test_off(self):
        meta = {"runtime_context": {"approval_level": "OFF"}}
        assert session_approval_level_from_meta(meta) == "OFF"

    def test_malformed_value_ignored(self):
        meta = {"runtime_context": {"approval_level": "bogus"}}
        assert session_approval_level_from_meta(meta) is None

    def test_non_string_value_ignored(self):
        meta = {"runtime_context": {"approval_level": 42}}
        assert session_approval_level_from_meta(meta) is None

    def test_blank_value_ignored(self):
        meta = {"runtime_context": {"approval_level": "  "}}
        assert session_approval_level_from_meta(meta) is None

    def test_sibling_keys_unaffected(self):
        meta = {
            "runtime_context": {
                "approval_level": "auto",
                "model": {"provider_id": "p", "model": "m"},
            },
        }
        assert session_approval_level_from_meta(meta) == "AUTO"


# ---------------------------------------------------------------------------
# ChatManager.set_session_approval_level
# ---------------------------------------------------------------------------


@pytest.fixture
def manager(tmp_path: Path) -> ChatManager:
    return ChatManager(repo=JsonChatRepository(tmp_path / "chats.json"))


def _spec() -> ChatSpec:
    return ChatSpec(session_id="console:u1", user_id="u1")


class TestSetSessionApprovalLevel:
    @pytest.mark.asyncio
    async def test_set_and_read_back(self, manager):
        chat = await manager.create_chat(_spec())
        updated = await manager.set_session_approval_level(chat.id, "STRICT")
        assert updated is not None
        fetched = await manager.get_chat(chat.id)
        assert session_approval_level_from_meta(fetched.meta) == "STRICT"

    @pytest.mark.asyncio
    async def test_clear_removes_override(self, manager):
        chat = await manager.create_chat(_spec())
        await manager.set_session_approval_level(chat.id, "OFF")
        updated = await manager.set_session_approval_level(chat.id, None)
        assert updated is not None
        fetched = await manager.get_chat(chat.id)
        assert session_approval_level_from_meta(fetched.meta) is None
        assert "approval_level" not in (
            fetched.meta.get("runtime_context") or {}
        )

    @pytest.mark.asyncio
    async def test_preserves_sibling_runtime_keys(self, manager):
        chat = await manager.create_chat(_spec())
        await manager.set_session_project_dirs(chat.id, None)
        await manager.set_session_approval_level(chat.id, "SMART")
        fetched = await manager.get_chat(chat.id)
        assert session_approval_level_from_meta(fetched.meta) == "SMART"

    @pytest.mark.asyncio
    async def test_unknown_chat_returns_none(self, manager):
        result = await manager.set_session_approval_level(
            "does-not-exist",
            "STRICT",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_runtime_context_dropped_when_cleared(self, manager):
        chat = await manager.create_chat(_spec())
        await manager.set_session_approval_level(chat.id, "AUTO")
        await manager.set_session_approval_level(chat.id, None)
        fetched = await manager.get_chat(chat.id)
        assert "runtime_context" not in fetched.meta
