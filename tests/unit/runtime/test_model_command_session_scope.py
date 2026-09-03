# -*- coding: utf-8 -*-
"""Regression tests for Session-scoped /model mutations."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.config.config import ModelSlotConfig
from qwenpaw.runtime.commands.control.model_handler import ModelCommandHandler
from qwenpaw.services.model_selection import (
    clear_current_model_context,
    ModelSelectionContext,
    set_current_model_context,
)


@pytest.fixture(autouse=True)
def _clear_model_context():
    clear_current_model_context()
    yield
    clear_current_model_context()


def _context():
    chat_manager = SimpleNamespace(
        set_model_slot_override=AsyncMock(),
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
    set_current_model_context(
        ModelSelectionContext(
            slot=ModelSlotConfig(provider_id="agent", model="default"),
            source="agent",
            chat_id="chat-1",
            agent_slot=ModelSlotConfig(provider_id="agent", model="default"),
        ),
    )
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
async def test_model_reset_clears_only_current_chat():
    handler = ModelCommandHandler()
    context = _context()
    set_current_model_context(
        ModelSelectionContext(
            slot=ModelSlotConfig(provider_id="openai", model="gpt-4o"),
            source="session",
            chat_id="chat-1",
            session_slot=ModelSlotConfig(
                provider_id="openai",
                model="gpt-4o",
            ),
            agent_slot=ModelSlotConfig(provider_id="agent", model="default"),
        ),
    )
    set_model_slot_override = (
        context.workspace.chat_manager.set_model_slot_override
    )
    context.args["_raw_args"] = "reset"
    result = await handler.handle(context)

    set_model_slot_override.assert_awaited_once_with(
        "chat-1",
        None,
    )
    assert "agent default" in result
