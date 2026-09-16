# -*- coding: utf-8 -*-
"""Task 6.2-R/3 附件生命周期列表 API 契约。"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from starlette.requests import Request

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.app.chats.repo import AttachmentRecord
from qwenpaw.identity.models import PlatformRole


USER_ID = UUID("11111111-1111-4111-8111-111111111111")
AGENT_KEY = "public-agent"
NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


def _request() -> Request:
    request = Request({"type": "http", "headers": []})
    request.state.actor = ActorContext(
        user_id=USER_ID,
        actor_type=ActorType.USER,
        platform_role=PlatformRole.MEMBER,
        admin_mode=False,
        request_id="attachment-list-test",
    )
    return request


@pytest.mark.asyncio
async def test_list_returns_only_owned_current_agent_attachments_without_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qwenpaw.app.routers import attachments as router

    record = AttachmentRecord(
        id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        agent_id=router.agent_database_id(AGENT_KEY),
        conversation_id=None,
        message_id=None,
        owner_user_id=USER_ID,
        storage_key="C:/private/user-a/public-agent/media/report.pdf",
        original_name="report.pdf",
        media_type="application/pdf",
        size=128,
        content_hash="sha256:report",
        created_at=NOW,
        updated_at=NOW,
    )
    calls = []

    class Repository:
        def with_user(self, user_id):
            assert user_id == USER_ID
            return self

        async def list_owned_attachments(self, **kwargs):
            calls.append(kwargs)
            return [record]

    workspace = SimpleNamespace(
        agent_id=AGENT_KEY,
        chat_manager=SimpleNamespace(conversation_repository=Repository()),
    )
    monkeypatch.setattr(
        router,
        "get_agent_for_request",
        lambda _request: _async_value(workspace),
    )

    response = await router.list_console_attachments(
        request=_request(),
        lifecycle="temporary",
        conversation_id=None,
    )

    assert calls == [
        {
            "owner_user_id": USER_ID,
            "agent_id": router.agent_database_id(AGENT_KEY),
            "lifecycle": "temporary",
            "conversation_id": None,
        }
    ]
    payload = [item.model_dump(mode="json") for item in response]
    assert payload[0]["original_name"] == "report.pdf"
    assert payload[0]["download_url"].endswith(str(record.id))
    assert payload[0]["can_save"] is True
    assert payload[0]["can_move"] is False
    assert payload[0]["can_delete"] is True
    assert "storage_key" not in payload[0]
    assert "C:/private" not in str(payload)


async def _async_value(value):
    return value
