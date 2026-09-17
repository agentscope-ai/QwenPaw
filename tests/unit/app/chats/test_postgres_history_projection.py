# -*- coding: utf-8 -*-
"""PostgreSQL 消息事实到前端历史的投影测试。"""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from qwenpaw.app.chats.api import _load_postgres_history_messages
from qwenpaw.app.chats.repo import MessageRecord


class Repository:
    def __init__(self, records):
        self.records = records
        self.bound_user = None

    def with_user(self, user_id):
        self.bound_user = user_id
        return self

    async def list_messages(self, _conversation_id):
        return self.records


class PayloadLoader:
    def __init__(self, payload):
        self.payload = payload
        self.loaded = None

    async def load_event_payload(self, stored_payload):
        self.loaded = stored_payload
        return self.payload


@pytest.mark.asyncio
async def test_projects_rich_and_legacy_messages_in_database_order() -> None:
    conversation_id = uuid4()
    user_id = uuid4()
    now = datetime.now(UTC)
    records = [
        MessageRecord(
            id=uuid4(),
            conversation_id=conversation_id,
            sequence=1,
            role="user",
            message_type="legacy_snapshot",
            content={
                "id": "legacy-user",
                "name": "user",
                "role": "user",
                "content": [{"type": "text", "text": "旧消息"}],
            },
            status="completed",
            created_by=user_id,
            created_at=now,
        ),
        MessageRecord(
            id=uuid4(),
            conversation_id=conversation_id,
            sequence=2,
            role="assistant",
            message_type="reasoning",
            content={"content": [{"type": "text", "text": "推理事件"}]},
            status="completed",
            created_by=user_id,
            created_at=now,
        ),
    ]
    repository = Repository(records)
    manager = SimpleNamespace(conversation_repository=repository)

    messages = await _load_postgres_history_messages(
        manager=manager,
        conversation_id=conversation_id,
        user_id=user_id,
    )

    assert repository.bound_user == user_id
    assert [message.content[0].text for message in messages] == ["旧消息", "推理事件"]
    assert messages[1].type.value == "reasoning"


@pytest.mark.asyncio
async def test_hydrates_offloaded_tool_output_before_history_projection() -> None:
    conversation_id = uuid4()
    user_id = uuid4()
    now = datetime.now(UTC)
    reference = {
        "qwenpaw_payload_ref": {
            "path": "run-12.json",
            "byte_size": 300_000,
            "sha256": "a" * 64,
        }
    }
    payload = {
        "id": "tool-result",
        "type": "plugin_call_output",
        "role": "tool",
        "status": "completed",
        "content": [
            {
                "type": "data",
                "data": {
                    "name": "view_image",
                    "call_id": "call-image",
                    "state": "success",
                    "output": "rendered",
                },
            }
        ],
    }
    repository = Repository(
        [
            MessageRecord(
                id=uuid4(),
                conversation_id=conversation_id,
                sequence=2,
                role="tool",
                message_type="plugin_call_output",
                content=reference,
                status="completed",
                created_by=user_id,
                created_at=now,
            )
        ]
    )
    loader = PayloadLoader(payload)
    manager = SimpleNamespace(
        conversation_repository=repository,
        run_persistence=loader,
    )

    messages = await _load_postgres_history_messages(
        manager=manager,
        conversation_id=conversation_id,
        user_id=user_id,
    )

    assert loader.loaded == reference
    assert messages[0].content[0].data["call_id"] == "call-image"
    assert messages[0].content[0].data["state"] == "success"
