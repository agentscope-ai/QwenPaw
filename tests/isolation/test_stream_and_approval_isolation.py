# -*- coding: utf-8 -*-
"""Task 5.4 实时流、审批与后台任务隔离契约。"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.app.routers import console as console_router
from qwenpaw.app.routers.console import get_push_messages, post_console_chat
from qwenpaw.app.approvals.service import ApprovalService, PendingApproval
from qwenpaw.app.routers.approval import (
    ApprovalActionRequest,
    get_approval_list,
    post_approval_approve,
    post_approval_deny,
)
from qwenpaw.app.task_tracker import TaskTracker
from qwenpaw.identity.models import PlatformRole


def _request(user_id) -> Request:
    request = Request({"type": "http", "headers": []})
    request.state.actor = ActorContext(
        user_id=user_id,
        actor_type=ActorType.USER,
        platform_role=PlatformRole.MEMBER,
        admin_mode=False,
        request_id="stream-isolation-test",
    )
    return request


@pytest.mark.asyncio
async def test_background_task_status_is_visible_only_to_its_owner(
    monkeypatch,
) -> None:
    """泄露 task_id 也不能读取其他用户的后台执行状态或结果。"""
    owner_id = uuid4()
    other_id = uuid4()
    task_id = "task-owner-only"
    console_router._bg_tasks[task_id] = console_router._BackgroundTask(
        status="finished",
        result={"status": "completed", "output": ["private"]},
        owner_user_id=str(owner_id),
        conversation_id=str(uuid4()),
    )
    monkeypatch.setattr(console_router, "is_multi_user_enabled", lambda: True)
    try:
        owner_result = await console_router.get_console_chat_task(
            task_id,
            _request(owner_id),
        )
        assert owner_result["result"]["output"] == ["private"]

        with pytest.raises(HTTPException) as exc_info:
            await console_router.get_console_chat_task(
                task_id,
                _request(other_id),
            )
        assert exc_info.value.status_code == 404
    finally:
        console_router._bg_tasks.pop(task_id, None)


@pytest.mark.asyncio
async def test_background_task_creation_binds_actor_conversation_and_run(
    tmp_path,
    monkeypatch,
) -> None:
    """后台任务创建时即固化可信主体、实际会话与唯一 Run。"""
    owner_id = uuid4()
    conversation_id = uuid4()
    captured_payload = {}

    class Channel:
        def resolve_session_id(self, **kwargs):
            return kwargs["channel_meta"]["session_id"]

        async def stream_one(self, payload):
            captured_payload.update(payload)
            yield 'data: {"type":"message","output":[]}\n\n'

    class ChannelManager:
        async def get_channel(self, _channel):
            return Channel()

    class ChatManager:
        async def get_or_create_chat(self, *_args, **_kwargs):
            return SimpleNamespace(id=str(conversation_id), meta={})

    workspace = SimpleNamespace(
        agent_id="background-agent",
        workspace_dir=tmp_path,
        channel_manager=ChannelManager(),
        chat_manager=ChatManager(),
    )
    monkeypatch.setattr(console_router, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(
        console_router,
        "get_agent_for_request",
        lambda _request: _async_value(workspace),
    )
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda _agent_id: SimpleNamespace(project_dir=None),
    )
    monkeypatch.setattr(
        "qwenpaw.models.runtime.prepare_console_model",
        lambda *_args, **_kwargs: _async_value(None),
    )

    submitted = await console_router.post_console_chat_task(
        {
            "channel": "console",
            "user_id": "forged-user",
            "session_id": "background-session",
            "input": [],
            "request_context": {
                "user_id": "forged-user",
                "approval_user_id": "forged-approver",
            },
        },
        _request(owner_id),
    )
    task_id = submitted["task_id"]
    try:
        background = console_router._bg_tasks[task_id]
        assert background.asyncio_task is not None
        await background.asyncio_task

        context = captured_payload["meta"]["request_context"]
        assert background.owner_user_id == str(owner_id)
        assert background.conversation_id == str(conversation_id)
        assert background.run_id == context["run_id"]
        assert context["conversation_id"] == str(conversation_id)
        assert context["approval_user_id"] == str(owner_id)
        assert context["actor_context"]["user_id"] == str(owner_id)
    finally:
        console_router._bg_tasks.pop(task_id, None)


@pytest.mark.asyncio
async def test_multi_user_reconnect_requires_conversation_id(monkeypatch) -> None:
    """重连不能只凭客户端可伪造的 session_id 定位运行流。"""

    class Channel:
        def resolve_session_id(self, **kwargs):
            return kwargs["channel_meta"]["session_id"]

    class ChannelManager:
        async def get_channel(self, _channel):
            return Channel()

    class ChatManager:
        async def get_or_create_chat(self, *_args, **_kwargs):
            return SimpleNamespace(id=str(uuid4()), name="New Chat")

    workspace = SimpleNamespace(
        channel_manager=ChannelManager(),
        chat_manager=ChatManager(),
        task_tracker=TaskTracker(),
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
                "reconnect": True,
                "session_id": "another-user-session",
                "user_id": "spoofed-user",
                "channel": "console",
            },
            _request(uuid4()),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "conversation_id is required for reconnect"


@pytest.mark.asyncio
async def test_reconnect_conversation_id_must_match_resolved_chat(
    monkeypatch,
) -> None:
    """不能用会话 A 的权限校验结果订阅 session_id 指向的会话 B。"""
    requested_id = uuid4()
    resolved_id = uuid4()

    class Channel:
        def resolve_session_id(self, **kwargs):
            return kwargs["channel_meta"]["session_id"]

    class ChannelManager:
        async def get_channel(self, _channel):
            return Channel()

    class ChatManager:
        async def get_chat(self, _chat_id):
            return SimpleNamespace(
                id=str(resolved_id),
                name="New Chat",
                meta={},
                model_copy=lambda **_kwargs: SimpleNamespace(
                    id=str(resolved_id),
                    name="New Chat",
                    meta={},
                ),
            )

        async def get_or_create_chat(self, *_args, **_kwargs):
            return SimpleNamespace(id=str(resolved_id), name="New Chat")

    class Tracker:
        attach_called = False

        async def attach(self, *_args, **_kwargs):
            self.attach_called = True
            return None

    tracker = Tracker()
    workspace = SimpleNamespace(
        channel_manager=ChannelManager(),
        chat_manager=ChatManager(),
        task_tracker=tracker,
    )
    monkeypatch.setattr(
        "qwenpaw.app.routers.console.get_agent_for_request",
        lambda _request: _async_value(workspace),
    )
    monkeypatch.setattr(
        "qwenpaw.app.routers.console._require_console_conversation_write",
        lambda *_args, **_kwargs: _async_value(None),
    )
    monkeypatch.setattr(
        "qwenpaw.app.routers.console.is_multi_user_enabled",
        lambda: True,
    )

    with pytest.raises(HTTPException) as exc_info:
        await post_console_chat(
            {
                "reconnect": True,
                "conversation_id": str(requested_id),
                "session_id": "session-for-another-chat",
                "user_id": "spoofed-user",
                "channel": "console",
            },
            _request(uuid4()),
        )

    assert exc_info.value.status_code == 404
    assert tracker.attach_called is False


@pytest.mark.asyncio
async def test_task_tracker_rejects_cross_scope_reconnect() -> None:
    """同一运行键也只能由创建该运行的用户/会话作用域订阅。"""
    tracker = TaskTracker()
    release = asyncio.Event()

    async def stream(_payload):
        yield "data: owner-only\n\n"
        await release.wait()

    owner_queue, _ = await tracker.attach_or_start(
        "conversation-1",
        None,
        stream,
        access_scope="user-a:conversation-1",
    )
    await asyncio.sleep(0)

    try:
        assert (
            await tracker.attach(
                "conversation-1",
                access_scope="user-b:conversation-1",
            )
            is None
        )
        owner_reconnect = await tracker.attach(
            "conversation-1",
            access_scope="user-a:conversation-1",
        )
        assert owner_reconnect is not None
        with pytest.raises(PermissionError):
            await tracker.attach_or_start(
                "conversation-1",
                None,
                stream,
                access_scope="user-b:conversation-1",
            )
    finally:
        release.set()
        async for _ in tracker.stream_from_queue(
            owner_queue,
            "conversation-1",
        ):
            pass


def _pending(request_id: str, approval_user_id: str) -> PendingApproval:
    loop = asyncio.get_running_loop()
    return PendingApproval(
        request_id=request_id,
        session_id=f"console:{approval_user_id}",
        root_session_id=f"console:{approval_user_id}",
        owner_agent_id="agent-a",
        user_id=approval_user_id,
        channel="console",
        agent_id="agent-a",
        tool_name="execute_shell_command",
        created_at=time.time(),
        future=loop.create_future(),
        approval_user_id=approval_user_id,
    )


@pytest.mark.asyncio
async def test_approval_list_only_returns_current_approval_user(
    monkeypatch,
) -> None:
    user_a = uuid4()
    user_b = uuid4()
    service = ApprovalService()
    service._pending = {  # pylint: disable=protected-access
        "approval-a": _pending("approval-a", str(user_a)),
        "approval-b": _pending("approval-b", str(user_b)),
    }
    monkeypatch.setattr(
        "qwenpaw.app.routers.approval.get_approval_service",
        lambda: service,
    )
    monkeypatch.setattr(
        "qwenpaw.app.routers.approval.is_multi_user_enabled",
        lambda: True,
    )

    response = await get_approval_list(_request(user_a))

    assert response.count == 1
    assert [item["request_id"] for item in response.pending_approvals] == [
        "approval-a",
    ]
    other_session = await get_approval_list(
        _request(user_a),
        session_id=f"console:{user_b}",
    )
    assert other_session.count == 0


@pytest.mark.asyncio
async def test_console_push_only_returns_current_approval_user(
    monkeypatch,
) -> None:
    user_a = uuid4()
    user_b = uuid4()
    service = ApprovalService()
    service._pending = {  # pylint: disable=protected-access
        "approval-a": _pending("approval-a", str(user_a)),
        "approval-b": _pending("approval-b", str(user_b)),
    }
    monkeypatch.setattr(
        "qwenpaw.app.approvals.get_approval_service",
        lambda: service,
    )
    monkeypatch.setattr(
        "qwenpaw.app.routers.console.is_multi_user_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "qwenpaw.app.console_push_store.get_recent",
        lambda: _async_value([]),
    )

    response = await get_push_messages(request=_request(user_a))

    assert [item["request_id"] for item in response["pending_approvals"]] == [
        "approval-a",
    ]


@pytest.mark.asyncio
async def test_other_approval_user_cannot_approve_request(monkeypatch) -> None:
    approval_user_id = uuid4()
    other_user_id = uuid4()
    service = ApprovalService()
    pending = _pending("approval-a", str(approval_user_id))
    # pylint: disable-next=protected-access
    service._pending[pending.request_id] = pending
    monkeypatch.setattr(
        "qwenpaw.app.routers.approval.get_approval_service",
        lambda: service,
    )
    monkeypatch.setattr(
        "qwenpaw.app.routers.approval.is_multi_user_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "qwenpaw.app.routers.approval._require_approval_write",
        lambda *_args, **_kwargs: _async_value(None),
    )

    with pytest.raises(HTTPException) as exc_info:
        await post_approval_approve(
            _request(other_user_id),
            ApprovalActionRequest(
                request_id=pending.request_id,
                session_id=pending.root_session_id,
            ),
        )

    assert exc_info.value.status_code == 404
    assert pending.request_id in service._pending  # pylint: disable=protected-access


@pytest.mark.asyncio
async def test_other_approval_user_cannot_deny_request(monkeypatch) -> None:
    approval_user_id = uuid4()
    other_user_id = uuid4()
    service = ApprovalService()
    pending = _pending("approval-a", str(approval_user_id))
    # pylint: disable-next=protected-access
    service._pending[pending.request_id] = pending
    monkeypatch.setattr(
        "qwenpaw.app.routers.approval.get_approval_service",
        lambda: service,
    )
    monkeypatch.setattr(
        "qwenpaw.app.routers.approval.is_multi_user_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "qwenpaw.app.routers.approval._require_approval_write",
        lambda *_args, **_kwargs: _async_value(None),
    )

    with pytest.raises(HTTPException) as exc_info:
        await post_approval_deny(
            _request(other_user_id),
            ApprovalActionRequest(
                request_id=pending.request_id,
                session_id=pending.root_session_id,
            ),
        )

    assert exc_info.value.status_code == 404
    assert pending.request_id in service._pending  # pylint: disable=protected-access


async def _async_value(value):
    return value
