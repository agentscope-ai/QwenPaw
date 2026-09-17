# -*- coding: utf-8 -*-
"""Task 6.2-R/2 附件所有权与绑定契约。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from qwenpaw.app.chats.api import _protect_history_attachment_urls
from qwenpaw.app.chats.models import ChatSpec
from qwenpaw.app.chats.repo import (
    AttachmentRecord,
    JsonConversationRepository,
    RepositoryConflictError,
)
from qwenpaw.app.chats.run_persistence import PostgresChatRunPersistence
from qwenpaw.schemas import FileContent, ImageContent, Message


USER_ID = UUID("33333333-3333-4333-8333-333333333333")
OTHER_USER_ID = UUID("44444444-4444-4444-8444-444444444444")
AGENT_ID = UUID("55555555-5555-4555-8555-555555555555")
OTHER_AGENT_ID = UUID("66666666-6666-4666-8666-666666666666")
CONVERSATION_ID = UUID("77777777-7777-4777-8777-777777777777")
OTHER_CONVERSATION_ID = UUID("88888888-8888-4888-8888-888888888888")
MESSAGE_ID = UUID("99999999-9999-4999-8999-999999999999")
ATTACHMENT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
NOW = datetime(2026, 9, 2, 10, 0, tzinfo=UTC)


def _pending_attachment(tmp_path: Path) -> AttachmentRecord:
    target = tmp_path / "private.txt"
    target.write_text("private", encoding="utf-8")
    return AttachmentRecord(
        id=ATTACHMENT_ID,
        agent_id=AGENT_ID,
        conversation_id=None,
        message_id=None,
        owner_user_id=USER_ID,
        storage_key=str(target),
        original_name="private.txt",
        media_type="text/plain",
        size=7,
        content_hash="sha256:private",
        created_at=NOW,
        updated_at=NOW,
    )


def test_attachment_record_keeps_agent_and_original_name(tmp_path: Path) -> None:
    """删除 Agent 归属或文件名字段时，本测试必须失败。"""
    record = _pending_attachment(tmp_path)

    assert record.agent_id == AGENT_ID
    assert record.conversation_id is None
    assert record.original_name == "private.txt"


def test_legacy_attachment_defaults_updated_at_to_created_at() -> None:
    """旧 JSON 附件没有生命周期时间字段时仍应可读取。"""
    record = AttachmentRecord.model_validate(
        {
            "id": ATTACHMENT_ID,
            "agent_id": AGENT_ID,
            "owner_user_id": USER_ID,
            "storage_key": "attachments/legacy.txt",
            "original_name": "legacy.txt",
            "media_type": "text/plain",
            "size": 6,
            "content_hash": "sha256:legacy",
            "created_at": NOW,
        }
    )

    assert record.lifecycle == "temporary"
    assert record.updated_at == NOW
    assert record.lifecycle == "temporary"
    assert record.saved_path is None
    assert record.saved_at is None
    assert record.deleted_at is None
    assert record.updated_at == NOW


@pytest.mark.asyncio
async def test_pending_attachment_can_only_bind_to_its_owner_and_agent(
    tmp_path: Path,
) -> None:
    """放宽用户或 Agent 校验时，本测试必须失败。"""
    repository = JsonConversationRepository(tmp_path / "conversations.json")
    record = _pending_attachment(tmp_path)
    await repository.add_attachment(record)

    assert await repository.get_attachment(
        attachment_id=ATTACHMENT_ID,
        owner_user_id=USER_ID,
    ) == record
    assert (
        await repository.get_attachment(
            attachment_id=ATTACHMENT_ID,
            owner_user_id=OTHER_USER_ID,
        )
        is None
    )

    with pytest.raises(RepositoryConflictError, match="attachment_agent_mismatch"):
        await repository.bind_attachment(
            attachment_id=ATTACHMENT_ID,
            owner_user_id=USER_ID,
            agent_id=OTHER_AGENT_ID,
            conversation_id=CONVERSATION_ID,
            message_id=MESSAGE_ID,
        )

    bound = await repository.bind_attachment(
        attachment_id=ATTACHMENT_ID,
        owner_user_id=USER_ID,
        agent_id=AGENT_ID,
        conversation_id=CONVERSATION_ID,
        message_id=MESSAGE_ID,
    )
    assert bound.conversation_id == CONVERSATION_ID
    assert bound.message_id == MESSAGE_ID


@pytest.mark.asyncio
async def test_bound_attachment_cannot_be_reused_by_another_conversation(
    tmp_path: Path,
) -> None:
    """允许同一附件跨会话复用时，本测试必须失败。"""
    repository = JsonConversationRepository(tmp_path / "conversations.json")
    await repository.add_attachment(_pending_attachment(tmp_path))
    await repository.bind_attachment(
        attachment_id=ATTACHMENT_ID,
        owner_user_id=USER_ID,
        agent_id=AGENT_ID,
        conversation_id=CONVERSATION_ID,
        message_id=MESSAGE_ID,
    )

    with pytest.raises(
        RepositoryConflictError,
        match="attachment_conversation_mismatch",
    ):
        await repository.bind_attachment(
            attachment_id=ATTACHMENT_ID,
            owner_user_id=USER_ID,
            agent_id=AGENT_ID,
            conversation_id=OTHER_CONVERSATION_ID,
            message_id=MESSAGE_ID,
        )


@pytest.mark.asyncio
async def test_owned_attachment_listing_is_scoped_by_user_agent_and_lifecycle(
    tmp_path: Path,
) -> None:
    repository = JsonConversationRepository(tmp_path / "conversations.json")
    temporary = _pending_attachment(tmp_path)
    saved = temporary.model_copy(
        update={
            "id": UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
            "storage_key": str(tmp_path / "saved.txt"),
            "lifecycle": "saved",
            "saved_path": "saved.txt",
            "saved_at": NOW,
        }
    )
    other_agent = temporary.model_copy(
        update={
            "id": UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc"),
            "agent_id": OTHER_AGENT_ID,
            "storage_key": str(tmp_path / "other-agent.txt"),
        }
    )
    await repository.add_attachment(temporary)
    await repository.add_attachment(saved)
    await repository.add_attachment(other_agent)

    assert await repository.list_owned_attachments(
        owner_user_id=USER_ID,
        agent_id=AGENT_ID,
        lifecycle="temporary",
    ) == [temporary]
    assert await repository.list_owned_attachments(
        owner_user_id=OTHER_USER_ID,
        agent_id=AGENT_ID,
    ) == []


@pytest.mark.asyncio
async def test_user_message_persistence_binds_attachment_to_real_message(
    tmp_path: Path,
) -> None:
    """持久化用户消息后未绑定实际 message_id 时，本测试必须失败。"""
    repository = JsonConversationRepository(tmp_path / "conversations.json")
    repository.with_user = lambda _user_id: repository  # type: ignore[attr-defined]

    async def persist_frame(*, event, message=None, **_kwargs):
        await repository.append_event(event)
        if message is not None:
            await repository.save_message(message)

    repository.persist_frame = persist_frame  # type: ignore[attr-defined]
    await repository.add_attachment(_pending_attachment(tmp_path))
    persistence = PostgresChatRunPersistence(
        repository=repository,
        agent_id=AGENT_ID,
    )
    chat = ChatSpec(
        id=str(CONVERSATION_ID),
        session_id="console:user",
        user_id=str(USER_ID),
        name="Attachment chat",
        created_at=NOW,
        updated_at=NOW,
    )

    async def stream_fn(_payload):
        if False:
            yield ""

    wrapped = persistence.wrap_stream(
        chat=chat,
        initiated_by=USER_ID,
        stream_fn=stream_fn,
    )
    payload = {
        "content_parts": [
            {
                "type": "file",
                "file_url": f"/api/console/attachments/{ATTACHMENT_ID}",
                "attachment_id": str(ATTACHMENT_ID),
            }
        ],
        "message_metadata": {"qwenpaw_client_message_id": "client-1"},
    }
    assert [item async for item in wrapped(payload)] == []

    attachments = await repository.list_attachments(CONVERSATION_ID)
    assert len(attachments) == 1
    assert attachments[0].message_id is not None
    messages = await repository.list_messages(CONVERSATION_ID)
    assert attachments[0].message_id == messages[0].id
    assert messages[0].content["content"][0]["file_url"] == (
        f"/api/console/attachments/{ATTACHMENT_ID}"
    )


def test_history_attachment_urls_use_protected_ids_and_hide_unowned_paths(
    tmp_path: Path,
) -> None:
    """历史消息不得继续向浏览器暴露附件磁盘路径。"""
    attachment = _pending_attachment(tmp_path)
    owner_messages = [
        Message(
            content=[
                FileContent(
                    file_url=attachment.storage_key,
                    filename=attachment.original_name,
                ),
                ImageContent(image_url=attachment.storage_key),
            ]
        )
    ]

    _protect_history_attachment_urls(
        owner_messages,
        [attachment],
        hide_unowned_local_urls=False,
    )

    protected_url = f"/api/console/attachments/{attachment.id}"
    assert owner_messages[0].content[0].file_url == protected_url
    assert owner_messages[0].content[1].image_url == protected_url

    viewer_messages = [
        Message(
            content=[
                FileContent(
                    file_url=attachment.storage_key,
                    filename=attachment.original_name,
                )
            ]
        )
    ]
    _protect_history_attachment_urls(
        viewer_messages,
        [],
        hide_unowned_local_urls=True,
    )
    assert viewer_messages[0].content[0].file_url == ""
