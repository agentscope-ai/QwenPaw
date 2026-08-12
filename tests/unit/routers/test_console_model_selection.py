# -*- coding: utf-8 -*-
"""Tests for Console Session model request handling."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from qwenpaw.app.routers.console import _apply_session_model_slot


@pytest.mark.asyncio
async def test_request_model_override_is_persisted_before_dispatch() -> None:
    updated_chat = SimpleNamespace(meta={})
    workspace = SimpleNamespace(
        chat_manager=SimpleNamespace(
            set_model_slot_override=AsyncMock(return_value=updated_chat),
        ),
    )
    chat = SimpleNamespace(id="chat-1", meta={})
    payload = {
        "model_slot_override": {
            "provider_id": "openai",
            "model": "gpt-4o",
        },
    }

    result = await _apply_session_model_slot(workspace, chat, payload)

    assert result is updated_chat
    workspace.chat_manager.set_model_slot_override.assert_awaited_once_with(
        "chat-1",
        {"provider_id": "openai", "model": "gpt-4o"},
    )


@pytest.mark.asyncio
async def test_persisted_model_override_is_restored_to_request() -> None:
    workspace = SimpleNamespace(
        chat_manager=SimpleNamespace(set_model_slot_override=AsyncMock()),
    )
    chat = SimpleNamespace(
        id="chat-1",
        meta={
            "runtime_context": {
                "model_slot_override": {
                    "provider_id": "anthropic",
                    "model": "claude-sonnet",
                },
            },
        },
    )
    payload = {}

    result = await _apply_session_model_slot(workspace, chat, payload)

    assert result is chat
    assert payload["model_slot_override"] == {
        "provider_id": "anthropic",
        "model": "claude-sonnet",
    }
    workspace.chat_manager.set_model_slot_override.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_request_model_override_is_rejected() -> None:
    workspace = SimpleNamespace(
        chat_manager=SimpleNamespace(set_model_slot_override=AsyncMock()),
    )
    chat = SimpleNamespace(id="chat-1", meta={})

    with pytest.raises(HTTPException, match="Invalid model_slot_override"):
        await _apply_session_model_slot(
            workspace,
            chat,
            {"model_slot_override": {"model": "missing-provider"}},
        )

    workspace.chat_manager.set_model_slot_override.assert_not_awaited()
