# -*- coding: utf-8 -*-
"""Regression tests for Session-scoped /model mutations."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.runtime.commands.control.model_handler import ModelCommandHandler


def _context():
    chat = SimpleNamespace(id="chat-1", meta={})
    chat_manager = SimpleNamespace(
        get_or_create_chat=AsyncMock(return_value=chat),
        set_model_slot_override=AsyncMock(return_value=chat),
    )
    return SimpleNamespace(
        workspace=SimpleNamespace(
            chat_manager=chat_manager,
            config=SimpleNamespace(active_model=None),
        ),
        payload=SimpleNamespace(channel="console"),
        channel=None,
        session_id="console:session-1",
        user_id="user-1",
        agent_id="agent-1",
        args={"_raw_args": ""},
    )


@pytest.mark.asyncio
async def test_model_switch_updates_only_current_chat(monkeypatch):
    handler = ModelCommandHandler()
    monkeypatch.setattr(
        handler,
        "_validate_model",
        AsyncMock(return_value=(True, "")),
    )
    context = _context()
    set_model_slot_override = (
        context.workspace.chat_manager.set_model_slot_override
    )
    context.args["_raw_args"] = "openai:gpt-4o"

    result = await handler.handle(context)

    set_model_slot_override.assert_awaited_once_with(
        "chat-1",
        {"provider_id": "openai", "model": "gpt-4o"},
    )
    assert "this session" in result


@pytest.mark.asyncio
async def test_model_reset_clears_only_current_chat(monkeypatch):
    handler = ModelCommandHandler()
    context = _context()
    set_model_slot_override = (
        context.workspace.chat_manager.set_model_slot_override
    )
    context.args["_raw_args"] = "reset"
    monkeypatch.setattr(
        handler,
        "_effective_model",
        AsyncMock(
            return_value=(
                SimpleNamespace(provider_id="agent", model="default"),
                "agent",
            ),
        ),
    )

    result = await handler.handle(context)

    set_model_slot_override.assert_awaited_once_with(
        "chat-1",
        None,
    )
    assert "agent default" in result
