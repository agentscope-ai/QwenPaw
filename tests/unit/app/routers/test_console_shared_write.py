# -*- coding: utf-8 -*-
"""Task 5.3-D 共享会话写入口隔离契约。"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.access.agent_repository import agent_database_id
from qwenpaw.app.chats.models import ChatSpec
from qwenpaw.app.chats.repo import ConversationAccessRecord, ConversationRecord
from qwenpaw.app.routers.console import (
    post_console_chat,
    post_console_chat_task,
)
from qwenpaw.identity.models import PlatformRole


def _request(user_id) -> Request:
    request = Request({"type": "http", "headers": []})
    request.state.actor = ActorContext(
        user_id=user_id,
        actor_type=ActorType.USER,
        platform_role=PlatformRole.MEMBER,
        admin_mode=False,
        request_id="shared-write-test",
    )
    return request


@pytest.mark.asyncio
async def test_viewer_cannot_send_by_spoofing_owner_user_id(monkeypatch) -> None:
    owner_id = uuid4()
    viewer_id = uuid4()
    conversation_id = uuid4()
    now = datetime.now(UTC)
    conversation = ConversationRecord(
        id=conversation_id,
        agent_id=agent_database_id("agent-a"),
        owner_user_id=owner_id,
        title="Shared chat",
        status="active",
        created_at=now,
        updated_at=now,
    )

    class Repository:
        def with_user(self, _user_id):
            return self

        async def get_conversation_for_user(self, **_kwargs):
            return ConversationAccessRecord(
                conversation=conversation,
                access_role="viewer",
            )

    class Channel:
        def resolve_session_id(self, **_kwargs):
            return "console:owner"

    class ChannelManager:
        async def get_channel(self, _channel):
            return Channel()

    class ChatManager:
        conversation_repository = Repository()

        async def get_or_create_chat(self, *_args, **_kwargs):
            return ChatSpec(
                id=str(conversation_id),
                session_id="console:owner",
                user_id=str(owner_id),
            )

    class Tracker:
        async def attach(self, _chat_id):
            return SimpleNamespace()

    workspace = SimpleNamespace(
        agent_id="agent-a",
        channel_manager=ChannelManager(),
        chat_manager=ChatManager(),
        task_tracker=Tracker(),
    )
    monkeypatch.setattr(
        "qwenpaw.app.routers.console.get_agent_for_request",
        lambda _request: _async_value(workspace),
    )
    monkeypatch.setattr(
        "qwenpaw.app.routers.console.is_multi_user_enabled",
        lambda: True,
    )

    with pytest.raises(HTTPException) as exc_info:
        await post_console_chat(
            {
                "input": [{"role": "user", "content": "tamper"}],
                "session_id": "console:owner",
                "user_id": str(owner_id),
                "channel": "console",
                "conversation_id": str(conversation_id),
                "reconnect": True,
            },
            _request(viewer_id),
        )

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler", "needs_tracker"),
    [
        (post_console_chat, True),
        (post_console_chat_task, False),
    ],
)
async def test_owned_legacy_chat_reuses_explicit_conversation_id(
    monkeypatch,
    handler,
    needs_tracker,
    tmp_path,
) -> None:
    """已授权历史会话不得因旧 user_id=default 被复制成新会话。"""
    owner_id = uuid4()
    conversation_id = uuid4()
    now = datetime.now(UTC)
    conversation = ConversationRecord(
        id=conversation_id,
        agent_id=agent_database_id("agent-a"),
        owner_user_id=owner_id,
        title="Legacy owned chat",
        status="active",
        created_at=now,
        updated_at=now,
    )
    legacy_chat = ChatSpec(
        id=str(conversation_id),
        session_id="legacy-session",
        user_id="default",
    )

    class Repository:
        def with_user(self, _user_id):
            return self

        async def get_conversation_for_user(self, **_kwargs):
            return ConversationAccessRecord(
                conversation=conversation,
                access_role="owner",
            )

    class Channel:
        def resolve_session_id(self, *, channel_meta, **_kwargs):
            return channel_meta["session_id"]

        async def stream_one(self, payload):
            assert payload["meta"]["session_id"] == "legacy-session"
            yield 'data: {"type":"message","output":[]}\n\n'

    class ChannelManager:
        async def get_channel(self, _channel):
            return Channel()

    class ChatManager:
        conversation_repository = Repository()

        async def get_chat(self, chat_id):
            assert chat_id == str(conversation_id)
            return legacy_chat

        async def get_or_create_chat(self, *_args, **_kwargs):
            pytest.fail("explicit conversation_id must not create a new chat")

        def persisting_stream_source(self, chat, stream_fn):
            assert chat.user_id == str(owner_id)
            return stream_fn

    class Tracker:
        async def attach_or_start(self, chat_id, payload, *_args, **_kwargs):
            assert chat_id == str(conversation_id)
            assert payload["meta"]["session_id"] == "legacy-session"
            return SimpleNamespace(), True

        async def stream_from_queue(self, *_args, **_kwargs):
            if False:
                yield ""

    workspace = SimpleNamespace(
        agent_id="agent-a",
        workspace_dir=tmp_path,
        channel_manager=ChannelManager(),
        chat_manager=ChatManager(),
        task_tracker=Tracker() if needs_tracker else None,
    )
    monkeypatch.setattr(
        "qwenpaw.app.routers.console.get_agent_for_request",
        lambda _request: _async_value(workspace),
    )
    monkeypatch.setattr(
        "qwenpaw.app.routers.console.is_multi_user_enabled",
        lambda: True,
    )
    monkeypatch.setattr("qwenpaw.services.workspace_files.WORKING_DIR", tmp_path)
    monkeypatch.setattr(
        "qwenpaw.app.routers.console._apply_session_project_dir",
        lambda _workspace, chat, _payload: _async_value(chat),
    )
    monkeypatch.setattr(
        "qwenpaw.app.routers.console._resolve_personal_library_references",
        lambda _request, _workspace, _payload: _async_value(None),
    )
    monkeypatch.setattr(
        "qwenpaw.models.runtime.prepare_console_model",
        lambda *_args, **_kwargs: _async_value(None),
    )
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda _agent_id: SimpleNamespace(project_dir=None),
    )
    monkeypatch.setattr(
        "qwenpaw.services.project_directory.resolve_effective_project_dir",
        lambda *_args, **_kwargs: (SimpleNamespace(__str__=lambda self: "tmp"), "test"),
    )
    monkeypatch.setattr(
        "qwenpaw.services.project_directory.session_project_dir",
        lambda _meta: None,
    )

    payload = {
        "input": [
            {
                "role": "user",
                "content": [{"type": "text", "text": "continue"}],
            },
        ],
        "session_id": "client-stale-session",
        "user_id": str(owner_id),
        "channel": "console",
        "conversation_id": str(conversation_id),
    }
    result = await handler(payload, _request(owner_id))

    if needs_tracker:
        assert result.media_type == "text/event-stream"
    else:
        bg = handler.__globals__["_bg_tasks"][result["task_id"]]
        assert bg.conversation_id == str(conversation_id)
        if bg.asyncio_task is not None:
            bg.asyncio_task.cancel()


async def _async_value(value):
    return value
