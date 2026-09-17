# -*- coding: utf-8 -*-
"""Task 5.3-A 会话所有权访问契约测试。"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest

from qwenpaw.app.chats.access import require_chat_access
from qwenpaw.app.chats.repo.conversation import (
    ConversationAccessRecord,
    ConversationRecord,
)
from qwenpaw.app.chats.repo.postgres_repo import PostgresConversationRepository
from qwenpaw.app.chats.models import ChatSpec
from qwenpaw.app.chats.manager import ChatManager
from qwenpaw.app.chats.repo import JsonChatRepository
from qwenpaw.app.chats.run_persistence import PostgresChatRunPersistence


def _conversation(owner_user_id):
    now = datetime.now(UTC)
    return ConversationRecord(
        id=uuid4(),
        agent_id=uuid4(),
        owner_user_id=owner_user_id,
        title="Private chat",
        status="active",
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_owner_access_is_read_write():
    owner_id = uuid4()
    record = _conversation(owner_id)

    access = await require_chat_access(
        repository=None,
        conversation=record,
        user_id=owner_id,
        write=False,
    )

    assert isinstance(access, ConversationAccessRecord)
    assert access.access_role == "owner"
    assert access.read_only is False


@pytest.mark.asyncio
async def test_unshared_user_is_not_allowed_to_read():
    owner_id = uuid4()
    record = _conversation(owner_id)

    with pytest.raises(RuntimeError, match="chat_not_found"):
        await require_chat_access(
            repository=None,
            conversation=record,
            user_id=uuid4(),
            write=False,
        )


def test_postgres_repository_creates_user_bound_view():
    user_id = uuid4()
    repository = PostgresConversationRepository(schema="qwenpaw")

    bound = repository.with_user(user_id)

    assert bound is not repository
    assert bound.request_user_id == user_id
    assert repository.request_user_id is None


@pytest.mark.asyncio
async def test_postgres_repository_session_uses_factory_and_sets_request_user():
    user_id = uuid4()
    session = SimpleNamespace(execute=AsyncMock())

    class SessionContext:
        async def __aenter__(self):
            return session

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    factory = Mock(return_value=SessionContext())
    repository = PostgresConversationRepository(
        schema="qwenpaw",
        session_factory=factory,
        request_user_id=user_id,
    )

    async with repository._session() as resolved_session:  # pylint: disable=protected-access
        assert resolved_session is session

    factory.assert_called_once_with()
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_manager_lists_only_postgres_authorized_chat_specs(tmp_path):
    owner_id = uuid4()
    other_id = uuid4()
    owner_chat = ChatSpec(
        id=str(uuid4()),
        session_id="console:owner",
        user_id=str(owner_id),
        name="Owner chat",
    )
    other_chat = ChatSpec(
        id=str(uuid4()),
        session_id="console:other",
        user_id=str(other_id),
        name="Other chat",
    )
    bound_repository = SimpleNamespace(
        list_conversations_for_user=AsyncMock(
            return_value=[
                ConversationAccessRecord(
                    conversation=ConversationRecord(
                        id=UUID(owner_chat.id),
                        agent_id=uuid4(),
                        owner_user_id=owner_id,
                        title=owner_chat.name,
                        status="active",
                        created_at=owner_chat.created_at,
                        updated_at=owner_chat.updated_at,
                    ),
                    access_role="owner",
                )
            ]
        )
    )
    conversation_repository = SimpleNamespace(
        with_user=Mock(return_value=bound_repository)
    )
    manager = ChatManager(
        repo=JsonChatRepository(tmp_path / "chats.json"),
        conversation_repository=conversation_repository,
    )
    await manager.create_chat(owner_chat)
    await manager.create_chat(other_chat)

    rows = await manager.list_accessible_chats(
        user_id=owner_id,
        scope="owned",
        archived=False,
    )

    assert [(row.chat.id, row.access.access_role) for row in rows] == [
        (owner_chat.id, "owner")
    ]
    conversation_repository.with_user.assert_called_once_with(owner_id)
    bound_repository.list_conversations_for_user.assert_awaited_once_with(
        user_id=owner_id,
        scope="owned",
    )


@pytest.mark.asyncio
async def test_run_persistence_binds_repository_to_initiating_user():
    initiated_by = uuid4()
    bound = SimpleNamespace(
        get_conversation=AsyncMock(return_value=None),
        create_conversation=AsyncMock(),
        create_run=AsyncMock(),
        list_messages=AsyncMock(return_value=[]),
        get_run=AsyncMock(return_value=SimpleNamespace(status="completed")),
    )
    repository = SimpleNamespace(with_user=Mock(return_value=bound))
    persistence = PostgresChatRunPersistence(
        repository=repository,
        agent_id=uuid4(),
    )
    chat = ChatSpec(
        session_id="console:owner",
        user_id=str(initiated_by),
        channel="console",
    )

    async def empty_stream(_payload):
        if False:
            yield ""

    wrapped = persistence.wrap_stream(
        chat=chat,
        initiated_by=initiated_by,
        stream_fn=empty_stream,
    )
    assert [item async for item in wrapped({})] == []

    repository.with_user.assert_called_once_with(initiated_by)
    bound.get_conversation.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_persistence_uses_server_bound_run_context():
    """持久化 Run 与下游工具上下文必须共享同一个服务端 run_id。"""
    initiated_by = uuid4()
    run_id = uuid4()
    observed: dict = {}
    bound = SimpleNamespace(
        get_conversation=AsyncMock(return_value=None),
        create_conversation=AsyncMock(),
        create_run=AsyncMock(),
        list_messages=AsyncMock(return_value=[]),
        get_run=AsyncMock(return_value=SimpleNamespace(status="completed")),
    )
    persistence = PostgresChatRunPersistence(
        repository=SimpleNamespace(with_user=Mock(return_value=bound)),
        agent_id=uuid4(),
    )
    chat = ChatSpec(
        id=str(uuid4()),
        session_id="console:bound-run",
        user_id=str(initiated_by),
        channel="console",
    )

    async def empty_stream(payload):
        observed.update(payload["meta"]["request_context"])
        if False:
            yield ""

    payload = {
        "_qwenpaw_run_id": str(run_id),
        "meta": {"request_context": {"user_id": str(initiated_by)}},
    }
    wrapped = persistence.wrap_stream(
        chat=chat,
        initiated_by=initiated_by,
        stream_fn=empty_stream,
    )
    assert [item async for item in wrapped(payload)] == []

    created_run = bound.create_run.await_args.args[0]
    assert created_run.id == run_id
    assert observed["run_id"] == str(run_id)
    assert observed["conversation_id"] == chat.id
