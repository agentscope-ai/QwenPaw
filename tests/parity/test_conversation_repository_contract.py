# -*- coding: utf-8 -*-
"""Legacy 与 PostgreSQL Conversation Repository 的共享行为契约。"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from qwenpaw.app.chats.repo import (
    AttachmentRecord,
    ConversationRecord,
    JsonConversationRepository,
    MessageRecord,
    RepositoryConflictError,
    RunEventRecord,
    RunRecord,
    ToolCallRecord,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)


def _alembic_config(postgres_test_schema) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", postgres_test_schema.async_url())
    config.attributes["target_schema"] = postgres_test_schema.name
    return config


async def _exercise_contract(
    repository,
    *,
    owner_user_id: UUID,
    agent_id: UUID,
) -> None:
    conversation_id = uuid4()
    run_id = uuid4()
    tool_id = uuid4()
    message_id = uuid4()
    attachment_id = uuid4()

    conversation = ConversationRecord(
        id=conversation_id,
        agent_id=agent_id,
        owner_user_id=owner_user_id,
        title="Repository contract",
        status="active",
        created_at=NOW,
        updated_at=NOW,
    )
    await repository.create_conversation(conversation)
    await repository.create_conversation(conversation)
    assert await repository.get_conversation(conversation_id) == conversation
    assert await repository.list_conversations(owner_user_id=owner_user_id) == [
        conversation
    ]

    run = RunRecord(
        id=run_id,
        conversation_id=conversation_id,
        initiated_by=owner_user_id,
        status="running",
        started_at=NOW,
    )
    await repository.create_run(run)

    message = MessageRecord(
        id=message_id,
        conversation_id=conversation_id,
        run_id=run_id,
        sequence=1,
        role="assistant",
        message_type="message",
        content={"text": "完成"},
        status="completed",
        created_by=owner_user_id,
        created_at=NOW,
    )
    await repository.save_message(message)
    await repository.save_message(message)
    assert await repository.list_messages(conversation_id) == [message]
    with pytest.raises(RepositoryConflictError, match="message_sequence_conflict"):
        await repository.save_message(
            message.model_copy(update={"content": {"text": "被篡改"}})
        )

    tool = ToolCallRecord(
        id=tool_id,
        run_id=run_id,
        call_id="call-1",
        source="builtin",
        tool_name="execute_shell_command",
        status="completed",
        redacted_arguments={"command": "echo ok"},
        output_ref="object://tool-output/1",
        started_at=NOW,
        finished_at=NOW,
    )
    await repository.upsert_tool_call(tool)
    await repository.upsert_tool_call(tool)
    assert await repository.list_tool_calls(run_id) == [tool]

    event_two = RunEventRecord(
        id=uuid4(),
        run_id=run_id,
        sequence=2,
        event_type="tool_output",
        payload={"text": "ok"},
        tool_call_id=tool_id,
        created_at=NOW,
    )
    event_one = RunEventRecord(
        id=uuid4(),
        run_id=run_id,
        sequence=1,
        event_type="tool_start",
        payload={"name": "execute_shell_command"},
        tool_call_id=tool_id,
        created_at=NOW,
    )
    await repository.append_event(event_two)
    await repository.append_event(event_one)
    await repository.append_event(event_one)
    assert await repository.list_events(run_id) == [event_one, event_two]
    with pytest.raises(RepositoryConflictError, match="run_event_sequence_conflict"):
        await repository.append_event(
            event_one.model_copy(update={"payload": {"name": "wrong"}})
        )

    attachment = AttachmentRecord(
        id=attachment_id,
        agent_id=agent_id,
        conversation_id=None,
        message_id=None,
        owner_user_id=owner_user_id,
        storage_key="attachments/contract.txt",
        original_name="contract.txt",
        media_type="text/plain",
        size=2,
        content_hash="sha256:contract",
        created_at=NOW,
        updated_at=NOW,
    )
    await repository.add_attachment(attachment)
    await repository.add_attachment(attachment)
    assert (
        await repository.get_attachment(
            attachment_id=attachment_id,
            owner_user_id=owner_user_id,
        )
        == attachment
    )
    assert (
        await repository.get_attachment(
            attachment_id=attachment_id,
            owner_user_id=uuid4(),
        )
        is None
    )
    assert await repository.list_attachments(conversation_id) == []
    bound_attachment = await repository.bind_attachment(
        attachment_id=attachment_id,
        owner_user_id=owner_user_id,
        agent_id=agent_id,
        conversation_id=conversation_id,
        message_id=message_id,
    )
    assert bound_attachment == attachment.model_copy(
        update={
            "conversation_id": conversation_id,
            "message_id": message_id,
        }
    )
    assert await repository.list_attachments(conversation_id) == [bound_attachment]

    finished_at = NOW.replace(hour=12, minute=1)
    finished = await repository.finish_run(
        run_id,
        status="completed",
        finished_at=finished_at,
    )
    assert finished == run.model_copy(
        update={"status": "completed", "finished_at": finished_at}
    )
    assert await repository.get_run(run_id) == finished

    archived = await repository.update_conversation(
        conversation_id,
        title="Archived contract",
        status="archived",
        updated_at=finished_at,
    )
    assert archived == conversation.model_copy(
        update={
            "title": "Archived contract",
            "status": "archived",
            "updated_at": finished_at,
        }
    )
    deleted = await repository.update_conversation(
        conversation_id,
        status="deleted",
        updated_at=finished_at,
    )
    assert deleted is not None and deleted.deleted_at == finished_at
    assert await repository.list_conversations(owner_user_id=owner_user_id) == []
    assert await repository.list_conversations(
        owner_user_id=owner_user_id,
        include_deleted=True,
    ) == [deleted]


@pytest.mark.asyncio
async def test_json_repository_satisfies_conversation_contract(tmp_path: Path) -> None:
    repository = JsonConversationRepository(tmp_path / "conversations.json")
    await _exercise_contract(
        repository,
        owner_user_id=uuid4(),
        agent_id=uuid4(),
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_repository_satisfies_conversation_contract(
    postgres_test_schema,
) -> None:
    from qwenpaw.app.chats.repo.postgres_repo import (
        PostgresConversationRepository,
    )

    await asyncio.to_thread(
        command.upgrade,
        _alembic_config(postgres_test_schema),
        "head",
    )
    engine = create_async_engine(
        postgres_test_schema.async_url(),
        poolclass=NullPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    owner_user_id = uuid4()
    agent_id = uuid4()

    @asynccontextmanager
    async def session_factory():
        async with factory.begin() as session:
            yield session

    try:
        async with session_factory() as session:
            await session.execute(
                text(
                    f'INSERT INTO "{postgres_test_schema.name}".users '
                    "(id, username, password_hash, status, platform_role) "
                    "VALUES (:id, 'contract-user', 'x', 'active', 'member')"
                ),
                {"id": owner_user_id},
            )
            await session.execute(
                text(
                    f'INSERT INTO "{postgres_test_schema.name}".agents '
                    "(id, owner_user_id, name, status, visibility, "
                    "default_model_mode, draft_workspace_key) "
                    "VALUES (:id, :owner, 'Contract Agent', 'active', "
                    "'private', 'inherit', 'workspaces/contract')"
                ),
                {"id": agent_id, "owner": owner_user_id},
            )
        repository = PostgresConversationRepository(
            schema=postgres_test_schema.name,
            session_factory=session_factory,
        )
        await _exercise_contract(
            repository,
            owner_user_id=owner_user_id,
            agent_id=agent_id,
        )
    finally:
        await engine.dispose()
