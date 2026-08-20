# -*- coding: utf-8 -*-
"""Tests for Console Session thinking-level request handling."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.app.routers.console import _apply_session_thinking_level


@pytest.mark.asyncio
async def test_restores_thinking_level_without_request_context() -> None:
    """Chat Metadata supplies the level when request context is absent."""
    workspace = SimpleNamespace(
        chat_manager=SimpleNamespace(patch_chat=AsyncMock()),
    )
    chat = SimpleNamespace(
        id="chat-1",
        meta={"thinking_level": "high"},
    )
    payload = {"meta": {}}

    result = await _apply_session_thinking_level(
        workspace,
        chat,
        payload,
    )

    assert result is chat
    assert payload["meta"]["request_context"] == {
        "thinking_level": "high",
    }
    workspace.chat_manager.patch_chat.assert_not_awaited()


@pytest.mark.asyncio
async def test_request_thinking_level_updates_chat_metadata() -> None:
    """A valid UI level persists before dispatching the request."""
    updated_chat = SimpleNamespace(
        id="chat-1",
        meta={"thinking_level": "low"},
    )
    workspace = SimpleNamespace(
        chat_manager=SimpleNamespace(
            patch_chat=AsyncMock(return_value=updated_chat),
        ),
    )
    chat = SimpleNamespace(
        id="chat-1",
        meta={"project_dir": "/tmp/project"},
    )
    payload = {
        "meta": {
            "request_context": {
                "approval_level": "AUTO",
                "thinking_level": "low",
            },
        },
    }

    result = await _apply_session_thinking_level(
        workspace,
        chat,
        payload,
    )

    assert result is updated_chat
    workspace.chat_manager.patch_chat.assert_awaited_once()
    patch = workspace.chat_manager.patch_chat.await_args.args[1]
    assert patch.thinking_level == "low"
    assert payload["meta"]["request_context"] == {
        "approval_level": "AUTO",
        "thinking_level": "low",
    }
