# -*- coding: utf-8 -*-
"""模型调用用量必须携带可信运行归属。"""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from qwenpaw.app.agent_context import (
    set_current_agent_id,
    set_current_channel,
    set_current_session_id,
    set_current_user_id,
)
from qwenpaw.config.context import set_current_request_context
from qwenpaw.token_usage.model_wrapper import TokenRecordingModelWrapper
from qwenpaw.token_usage.buffer import _UsageEvent
from qwenpaw.token_usage.postgres_buffer import PostgresUsageBuffer


def test_model_usage_event_captures_automation_context(monkeypatch) -> None:
    user_id = uuid4()
    conversation_id = uuid4()
    run_id = uuid4()
    schedule_id = uuid4()
    captured = []
    manager = MagicMock()
    manager.enqueue.side_effect = captured.append
    monkeypatch.setattr(
        "qwenpaw.token_usage.model_wrapper.get_token_usage_manager",
        lambda: manager,
    )
    set_current_agent_id("usage-agent")
    set_current_session_id("session-display-key")
    set_current_user_id(str(user_id))
    set_current_request_context(
        {
            "actor_type": "automation",
            "conversation_id": str(conversation_id),
            "run_id": str(run_id),
            "automation_authorization": {"schedule_id": str(schedule_id)},
        }
    )
    model = MagicMock()
    model.model = "test-model"
    model.context_size = 1000
    wrapper = TokenRecordingModelWrapper("test-provider", model)
    usage = MagicMock(input_tokens=12, output_tokens=3)

    wrapper._record_usage(usage)

    event = captured[0]
    assert event.user_id == str(user_id)
    assert event.actor_type == "automation"
    assert event.agent_key == "usage-agent"
    assert event.conversation_id == str(conversation_id)
    assert event.run_id == str(run_id)
    assert event.automation_schedule_id == str(schedule_id)


def test_model_usage_event_infers_external_actor_and_chat_id(monkeypatch) -> None:
    user_id = uuid4()
    conversation_id = uuid4()
    captured = []
    manager = MagicMock()
    manager.enqueue.side_effect = captured.append
    monkeypatch.setattr(
        "qwenpaw.token_usage.model_wrapper.get_token_usage_manager",
        lambda: manager,
    )
    set_current_agent_id("usage-agent")
    set_current_channel("discord")
    set_current_user_id(str(user_id))
    set_current_request_context({"chat_id": str(conversation_id)})
    model = MagicMock(model="test-model", context_size=1000)
    wrapper = TokenRecordingModelWrapper("test-provider", model)

    wrapper._record_usage(MagicMock(input_tokens=2, output_tokens=1))

    assert captured[0].actor_type == "external"
    assert captured[0].conversation_id == str(conversation_id)


@pytest.mark.asyncio
async def test_postgres_buffer_persists_rich_event_without_legacy_fallback() -> None:
    user_id = uuid4()
    persisted = []

    class Repository:
        async def append(self, event):
            persisted.append(event)
            return True

    buffer = PostgresUsageBuffer(repository=Repository())
    buffer.start()
    buffer.enqueue(
        _UsageEvent(
            provider_id="test-provider",
            model_name="test-model",
            prompt_tokens=4,
            completion_tokens=2,
            date_str="2026-09-07",
            now_iso="2026-09-07T08:00:00+00:00",
            user_id=str(user_id),
            actor_type="user",
            agent_key="usage-agent",
        )
    )
    await buffer.stop()

    assert len(persisted) == 1
    assert persisted[0].user_id == user_id
    assert persisted[0].agent_key == "usage-agent"
