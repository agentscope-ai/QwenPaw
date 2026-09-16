# -*- coding: utf-8 -*-
"""Task 6.2-R/1 对话运行目录与上传目录隔离契约。"""

from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID
from unittest.mock import AsyncMock

import pytest
from fastapi import UploadFile
from starlette.requests import Request

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.access.agent_repository import AgentResourceRole
from qwenpaw.app.chats.models import ChatSpec
from qwenpaw.app.routers import console as console_router
from qwenpaw.identity.models import PlatformRole
from qwenpaw.services import workspace_files
from qwenpaw.app.chats.repo import AttachmentRecord


USER_ID = UUID("33333333-3333-4333-8333-333333333333")


def _request() -> Request:
    request = Request({"type": "http", "headers": []})
    request.state.actor = ActorContext(
        user_id=USER_ID,
        actor_type=ActorType.USER,
        platform_role=PlatformRole.MEMBER,
        admin_mode=False,
        request_id="task-6-2-r-runtime",
    )
    request.state.agent_access = SimpleNamespace(
        role=AgentResourceRole.USER,
        historical_read_only=False,
    )
    return request


def _install_private_workspace_repository(monkeypatch) -> None:
    class Repository:
        def __init__(self, **_kwargs) -> None:
            pass

        async def ensure_private(self, **_kwargs) -> None:
            return None

    module = __import__(
        "qwenpaw.persistence.agent_user_workspaces",
        fromlist=["AgentUserWorkspaceRepository"],
    )
    monkeypatch.setattr(module, "AgentUserWorkspaceRepository", Repository)


@pytest.mark.asyncio
async def test_use_only_chat_runs_in_current_users_personal_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """把 request_context.project_dir 指回共享项目时，本测试必须失败。"""
    # 本用例只验证运行目录；模型授权已由独立治理测试覆盖。
    monkeypatch.setattr(
        "qwenpaw.models.runtime.prepare_console_model", AsyncMock(),
    )
    shared = tmp_path / "workspaces" / "shared-agent"
    shared_project = shared / "project"
    shared_project.mkdir(parents=True)
    captured: dict = {}

    class Channel:
        def resolve_session_id(self, **_kwargs) -> str:
            return "console:user"

        async def stream_one(self, _payload):
            if False:
                yield ""

    class ChannelManager:
        async def get_channel(self, _channel):
            return Channel()

    class ChatManager:
        async def get_or_create_chat(self, *_args, **_kwargs):
            return ChatSpec(
                id="22222222-2222-4222-8222-222222222222",
                session_id="console:user",
                user_id=str(USER_ID),
                created_at=datetime.now(UTC),
            )

        def persisting_stream_source(self, _chat, stream_fn):
            return stream_fn

    class Tracker:
        async def attach_or_start(self, _chat_id, payload, *_args, **_kwargs):
            captured.update(payload["meta"]["request_context"])
            return SimpleNamespace(), True

        async def stream_from_queue(self, *_args, **_kwargs):
            if False:
                yield ""

    workspace = SimpleNamespace(
        agent_id="shared-agent",
        workspace_dir=shared,
        workspace_kind="draft",
        channel_manager=ChannelManager(),
        chat_manager=ChatManager(),
        task_tracker=Tracker(),
    )
    monkeypatch.setattr(
        console_router,
        "get_agent_for_request",
        lambda _request: _async_value(workspace),
    )
    monkeypatch.setattr(console_router, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(workspace_files, "WORKING_DIR", tmp_path)
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda _agent_id: SimpleNamespace(project_dir=str(shared_project)),
    )
    _install_private_workspace_repository(monkeypatch)

    response = await console_router.post_console_chat(
        {
            "input": [{"role": "user", "content": "create a file"}],
            "session_id": "console:user",
            "user_id": str(USER_ID),
            "channel": "console",
        },
        _request(),
    )

    expected = tmp_path / "user_workspaces" / str(USER_ID) / "shared-agent"
    expected = expected / "artifacts" / "22222222-2222-4222-8222-222222222222"
    assert response.media_type == "text/event-stream"
    assert Path(captured["project_dir"]) == expected
    assert captured["project_dir_source"] == "user_task"
    assert Path(captured["task_output_dir"]) == expected
    assert expected.is_dir()


@pytest.mark.asyncio
async def test_use_only_chat_upload_is_saved_in_personal_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """把聊天附件写入共享 Agent media 目录时，本测试必须失败。"""
    shared = tmp_path / "workspaces" / "shared-agent"
    shared.mkdir(parents=True)
    shared_media = shared / "media"
    captured: list[AttachmentRecord] = []

    class Repository:
        def with_user(self, _user_id):
            return self

        async def add_attachment(self, record):
            captured.append(record)
            return record

    class Channel:
        media_dir = shared_media

    class ChannelManager:
        async def get_channel(self, _channel):
            return Channel()

    workspace = SimpleNamespace(
        agent_id="shared-agent",
        workspace_dir=shared,
        workspace_kind="draft",
        channel_manager=ChannelManager(),
        chat_manager=SimpleNamespace(conversation_repository=Repository()),
    )
    monkeypatch.setattr(
        console_router,
        "get_agent_for_request",
        lambda _request: _async_value(workspace),
    )
    monkeypatch.setattr(console_router, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(workspace_files, "WORKING_DIR", tmp_path)
    _install_private_workspace_repository(monkeypatch)

    result = await console_router.post_console_upload(
        request=_request(),
        file=UploadFile(
            filename="reference.txt",
            file=BytesIO(b"private-reference"),
        ),
        conversation_id=None,
    )

    uploaded = Path(captured[0].storage_key)
    expected_parent = (
        tmp_path
        / "user_workspaces"
        / str(USER_ID)
        / "shared-agent"
        / "media"
    )
    assert uploaded.parent == expected_parent
    assert uploaded.read_bytes() == b"private-reference"
    assert not shared_media.exists()
    assert result["url"].startswith("/api/console/attachments/")


@pytest.mark.asyncio
async def test_multi_user_upload_registers_scoped_metadata_without_leaking_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """返回本机绝对路径或漏写附件元数据时，本测试必须失败。"""
    shared = tmp_path / "workspaces" / "shared-agent"
    shared.mkdir(parents=True)
    captured: list[AttachmentRecord] = []

    class Repository:
        def with_user(self, _user_id):
            return self

        async def add_attachment(self, record):
            captured.append(record)
            return record

    class Channel:
        media_dir = shared / "media"

    class ChannelManager:
        async def get_channel(self, _channel):
            return Channel()

    workspace = SimpleNamespace(
        agent_id="shared-agent",
        workspace_dir=shared,
        workspace_kind="draft",
        channel_manager=ChannelManager(),
        chat_manager=SimpleNamespace(conversation_repository=Repository()),
    )
    monkeypatch.setattr(
        console_router,
        "get_agent_for_request",
        lambda _request: _async_value(workspace),
    )
    monkeypatch.setattr(console_router, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(workspace_files, "WORKING_DIR", tmp_path)
    _install_private_workspace_repository(monkeypatch)

    result = await console_router.post_console_upload(
        request=_request(),
        file=UploadFile(
            filename="reference.txt",
            file=BytesIO(b"private-reference"),
        ),
        conversation_id=None,
    )

    assert result["url"].startswith("/api/console/attachments/")
    assert str(tmp_path) not in result["url"]
    assert len(captured) == 1
    assert captured[0].owner_user_id == USER_ID
    assert captured[0].agent_id == console_router.agent_database_id("shared-agent")
    assert captured[0].conversation_id is None
    assert captured[0].message_id is None
    assert captured[0].original_name == "reference.txt"
    assert Path(captured[0].storage_key).read_bytes() == b"private-reference"


@pytest.mark.asyncio
async def test_attachment_download_returns_not_found_for_another_user(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """按路径直接下载或忽略 owner_user_id 时，本测试必须失败。"""
    attachment_id = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    target = tmp_path / "private.txt"
    target.write_text("private", encoding="utf-8")
    now = datetime.now(UTC)
    record = AttachmentRecord(
        id=attachment_id,
        agent_id=console_router.agent_database_id("shared-agent"),
        conversation_id=None,
        message_id=None,
        owner_user_id=USER_ID,
        storage_key=str(target),
        original_name="private.txt",
        media_type="text/plain",
        size=7,
        content_hash="sha256:private",
        created_at=now,
        updated_at=now,
    )

    class Repository:
        def __init__(self, **_kwargs):
            pass

        def with_user(self, _user_id):
            return self

        async def get_attachment(self, *, attachment_id, owner_user_id):
            if attachment_id == record.id and owner_user_id == USER_ID:
                return record
            return None

    monkeypatch.setattr(console_router, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(
        "qwenpaw.app.chats.repo.PostgresConversationRepository",
        Repository,
    )

    own_response = await console_router.get_console_attachment(
        attachment_id=attachment_id,
        request=_request(),
    )
    assert Path(own_response.path) == target

    other_request = _request()
    other_request.state.actor = other_request.state.actor.__class__(
        user_id=UUID("44444444-4444-4444-8444-444444444444"),
        actor_type=ActorType.USER,
        platform_role=PlatformRole.MEMBER,
        admin_mode=False,
        request_id="task-6-2-r-other-user",
    )
    with pytest.raises(console_router.HTTPException) as denied:
        await console_router.get_console_attachment(
            attachment_id=attachment_id,
            request=other_request,
        )
    assert denied.value.status_code == 404


@pytest.mark.asyncio
async def test_single_user_keeps_configured_runtime_and_upload_directories(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """单用户部署保留原有目录兼容。"""
    monkeypatch.setattr(console_router, "is_multi_user_enabled", lambda: False)
    request = _request()
    request.state.agent_access = SimpleNamespace(
        role=AgentResourceRole.OWNER,
        historical_read_only=False,
    )
    configured_project = tmp_path / "configured-project"
    configured_media = tmp_path / "configured-media"
    workspace = SimpleNamespace(agent_id="owned-agent")

    project, source = await console_router._resolve_console_runtime_project(
        request,
        workspace,
        project_dir=configured_project,
        project_source="agent_config",
        conversation_id="22222222-2222-4222-8222-222222222222",
    )
    media = await console_router._resolve_console_upload_dir(
        request,
        workspace,
        legacy_media_dir=configured_media,
    )

    assert project == configured_project
    assert source == "agent_config"
    assert media == configured_media


async def _async_value(value):
    return value
