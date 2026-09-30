# -*- coding: utf-8 -*-
"""Regression coverage for subagent model override transport."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from qwenpaw.agents.tools import agent_management
from qwenpaw.app.routers import console
from qwenpaw.runtime.builder import AgentBuilder
from qwenpaw.schemas import AgentRequest


def test_subagent_model_override_survives_native_payload_conversion() -> None:
    override = {
        "provider_id": "llamacpp",
        "model": "local-model",
    }
    request_data = {
        "session_id": "sub-session",
        "request_context": {"model_slot_override": override},
        "input": [
            {
                "role": "user",
                "content": [{"type": "text", "text": "reply OK"}],
            },
        ],
    }

    native_payload = console._extract_session_and_payload(request_data)

    request_context = native_payload["meta"]["request_context"]
    actual_override = request_context["model_slot_override"]
    assert actual_override == override


def test_console_channel_restores_subagent_model_override() -> None:
    from qwenpaw.app.channels.console.channel import ConsoleChannel

    channel = object.__new__(ConsoleChannel)
    channel.channel = "console"
    channel.resolve_session_id = lambda _sender_id, _meta: "sub-session"

    def build_request(**_kwargs):
        return AgentRequest()

    channel.build_agent_request_from_user_content = build_request

    override = {
        "provider_id": "llamacpp",
        "model": "local-model",
    }
    request = channel.build_agent_request_from_native(
        {
            "channel_id": "console",
            "sender_id": "default",
            "content_parts": [],
            "meta": {"request_context": {"model_slot_override": override}},
        },
    )

    context = AgentBuilder._build_request_context(
        SimpleNamespace(request=request),
    )

    assert context["model_slot_override"] == override


@pytest.mark.asyncio
async def test_subagent_model_override_load_failure_is_logged(
    monkeypatch,
    caplog,
):
    def fail_load(_agent_id):
        raise RuntimeError("config unavailable")

    monkeypatch.setattr(agent_management, "load_agent_config", fail_load)

    with caplog.at_level("WARNING", logger=agent_management.__name__):
        context = await agent_management._build_subagent_request_context("bot")

    assert "model_slot_override" not in context
    message = "Failed to load subagent model override for agent=bot"
    assert message in caplog.text
