# -*- coding: utf-8 -*-
"""Task 5.3-A legacy ChatSpec backfill contract."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from qwenpaw.app.chats.backfill import backfill_agent_chats, register_chat_metadata
from qwenpaw.app.chats.models import ChatSpec


@pytest.mark.asyncio
async def test_backfill_maps_default_only_to_known_agent_owner():
    owner_id = uuid4()
    chat = ChatSpec(
        session_id="legacy-session",
        user_id="default",
        channel="console",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    bound = SimpleNamespace(
        get_conversation=AsyncMock(return_value=None),
        create_conversation=AsyncMock(),
    )
    repository = SimpleNamespace(with_user=Mock(return_value=bound))

    report = await backfill_agent_chats(
        chats=[chat],
        agent_id=uuid4(),
        agent_owner_user_id=owner_id,
        repository=repository,
    )

    assert report.scanned == 1
    assert report.inserted == 1
    assert report.ambiguous == 0
    repository.with_user.assert_called_once_with(owner_id)
    created = bound.create_conversation.await_args.args[0]
    assert created.owner_user_id == owner_id


@pytest.mark.asyncio
async def test_backfill_reports_invalid_non_default_owner_without_writing():
    chat = ChatSpec(
        session_id="unknown-session",
        user_id="legacy-name",
        channel="console",
    )
    repository = SimpleNamespace(with_user=Mock())

    report = await backfill_agent_chats(
        chats=[chat],
        agent_id=uuid4(),
        agent_owner_user_id=None,
        repository=repository,
    )

    assert report.scanned == 1
    assert report.inserted == 0
    assert report.ambiguous == 1
    repository.with_user.assert_not_called()


@pytest.mark.asyncio
async def test_register_chat_metadata_persists_empty_chat_immediately():
    owner_id = uuid4()
    agent_id = uuid4()
    chat = ChatSpec(
        session_id="new-empty-session",
        user_id=str(owner_id),
        channel="console",
    )
    bound = SimpleNamespace(
        get_conversation=AsyncMock(return_value=None),
        create_conversation=AsyncMock(),
    )
    repository = SimpleNamespace(with_user=Mock(return_value=bound))

    await register_chat_metadata(
        chat=chat,
        agent_id=agent_id,
        repository=repository,
    )

    created = bound.create_conversation.await_args.args[0]
    assert str(created.id) == chat.id
    assert created.owner_user_id == owner_id
    assert created.agent_id == agent_id
