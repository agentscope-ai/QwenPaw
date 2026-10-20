# -*- coding: utf-8 -*-
"""Tests for the contextvars hook's per-chat approval-level reader.

``_session_approval_level`` is best-effort by design: a read problem
must yield ``None`` (fall back to carried/agent default), never raise.
"""

# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.app.chats.models import ChatSpec
from qwenpaw.hooks.request_setup import contextvars_hook as cvh


def _ctx(
    session_id: str | None = "console:u1",
    *,
    with_workspace: bool = True,
    chat_manager: object | None = None,
) -> SimpleNamespace:
    request = SimpleNamespace(channel="console", user_id="u1")
    workspace = (
        SimpleNamespace(chat_manager=chat_manager) if with_workspace else None
    )
    return SimpleNamespace(
        session_id=session_id,
        request=request,
        workspace=workspace,
    )


def _chat_manager(level: str | None = None, **extra) -> SimpleNamespace:
    meta = {"runtime_context": {"approval_level": level}} if level else {}
    chat = ChatSpec(
        id="chat-1",
        session_id="console:u1",
        user_id="u1",
        channel="console",
        meta=meta,
    )
    base: dict = {
        "get_chat_id_by_session": AsyncMock(return_value="chat-1"),
        "get_chat": AsyncMock(return_value=chat),
    }
    base.update(extra)
    return SimpleNamespace(**base)


class TestSessionApprovalLevel:
    @pytest.mark.asyncio
    async def test_no_session_id_returns_none(self):
        assert (
            await cvh._session_approval_level(
                _ctx(session_id=None),
            )
            is None
        )

    @pytest.mark.asyncio
    async def test_no_workspace_returns_none(self):
        assert (
            await cvh._session_approval_level(
                _ctx(with_workspace=False),
            )
            is None
        )

    @pytest.mark.asyncio
    async def test_no_chat_manager_returns_none(self):
        assert (
            await cvh._session_approval_level(
                _ctx(chat_manager=None),
            )
            is None
        )

    @pytest.mark.asyncio
    async def test_unknown_session_returns_none(self):
        mgr = _chat_manager(
            "STRICT",
            get_chat_id_by_session=AsyncMock(return_value=None),
        )
        assert (
            await cvh._session_approval_level(_ctx(chat_manager=mgr)) is None
        )

    @pytest.mark.asyncio
    async def test_chat_deleted_after_lookup_returns_none(self):
        mgr = _chat_manager("STRICT", get_chat=AsyncMock(return_value=None))
        assert (
            await cvh._session_approval_level(_ctx(chat_manager=mgr)) is None
        )

    @pytest.mark.asyncio
    async def test_reads_persisted_level(self):
        mgr = _chat_manager("STRICT")
        assert (
            await cvh._session_approval_level(_ctx(chat_manager=mgr))
            == "STRICT"
        )

    @pytest.mark.asyncio
    async def test_case_insensitive_value(self):
        mgr = _chat_manager("smart")
        assert (
            await cvh._session_approval_level(_ctx(chat_manager=mgr))
            == "SMART"
        )

    @pytest.mark.asyncio
    async def test_malformed_value_returns_none(self):
        mgr = _chat_manager("bogus")
        assert (
            await cvh._session_approval_level(_ctx(chat_manager=mgr)) is None
        )

    @pytest.mark.asyncio
    async def test_lookup_error_never_raises(self):
        mgr = _chat_manager(
            "STRICT",
            get_chat_id_by_session=AsyncMock(side_effect=RuntimeError("db")),
        )
        assert (
            await cvh._session_approval_level(
                _ctx(chat_manager=mgr),
            )
            is None
        )
