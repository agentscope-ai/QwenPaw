# -*- coding: utf-8 -*-
"""Console 丰富事件写入 PostgreSQL 的集成契约。"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from qwenpaw.app.chats.models import ChatSpec
from qwenpaw.app.chats.repo import PostgresConversationRepository
from qwenpaw.app.chats.run_persistence import PostgresChatRunPersistence
from qwenpaw.app.task_tracker import TaskTracker

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = (
    PROJECT_ROOT / "tests" / "parity" / "fixtures" / "chat_run_event_contract.json"
)


def _alembic_config(postgres_test_schema) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", postgres_test_schema.async_url())
    config.attributes["target_schema"] = postgres_test_schema.name
    return config


@pytest.fixture
async def postgres_chat_runtime(postgres_test_schema):
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
    user_id = uuid4()
    agent_id = uuid4()

    @asynccontextmanager
    async def session_factory():
        async with factory.begin() as session:
            yield session

    async with session_factory() as session:
        await session.execute(
            text(
                f'INSERT INTO "{postgres_test_schema.name}".users '
                "(id, username, password_hash, status, platform_role) "
                "VALUES (:id, 'event-user', 'x', 'active', 'member')"
            ),
            {"id": user_id},
        )
        await session.execute(
            text(
                f'INSERT INTO "{postgres_test_schema.name}".agents '
                "(id, owner_user_id, name, status, visibility, "
                "default_model_mode, draft_workspace_key) "
                "VALUES (:id, :owner, 'Event Agent', 'active', "
                "'private', 'inherit', 'workspaces/events')"
            ),
            {"id": agent_id, "owner": user_id},
        )

    repository = PostgresConversationRepository(
        schema=postgres_test_schema.name,
        session_factory=session_factory,
    )
    try:
        yield {
            "agent_id": agent_id,
            "engine": engine,
            "repository": repository,
            "schema": postgres_test_schema.name,
            "session_factory": session_factory,
            "user_id": user_id,
        }
    finally:
        await engine.dispose()


def _fixture_events() -> list[dict]:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return fixture["events"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_rich_fixture_is_persisted_without_wire_loss(
    postgres_chat_runtime,
) -> None:
    runtime = postgres_chat_runtime
    persistence = PostgresChatRunPersistence(
        repository=runtime["repository"],
        agent_id=runtime["agent_id"],
    )
    chat = ChatSpec(
        id=str(uuid4()),
        session_id="console:event-contract",
        user_id=str(runtime["user_id"]),
        name="丰富事件契约",
    )
    fixture_events = _fixture_events()
    source_lines = [
        f"data: {json.dumps(event['wire'], ensure_ascii=False)}\n\n"
        for event in fixture_events
    ]

    async def source(_payload):
        for line in source_lines:
            yield line

    persisted_source = persistence.wrap_stream(
        chat=chat,
        initiated_by=runtime["user_id"],
        stream_fn=source,
    )
    emitted = [line async for line in persisted_source({"query": "test"})]

    assert emitted == source_lines
    async with runtime["session_factory"]() as session:
        run_row = (
            (
                await session.execute(
                    text(
                        f'SELECT id, status FROM "{runtime["schema"]}".runs '
                        "WHERE conversation_id = :conversation_id"
                    ),
                    {"conversation_id": chat.id},
                )
            )
            .mappings()
            .one()
        )
    events = await runtime["repository"].list_events(run_row["id"])
    assert run_row["status"] == "completed"
    assert [event.sequence for event in events] == list(
        range(1, len(fixture_events) + 1)
    )
    assert [event.event_type for event in events] == [
        event["type"] for event in fixture_events
    ]
    assert [event.payload for event in events] == [
        event["wire"] for event in fixture_events
    ]

    async with runtime["session_factory"]() as session:
        counts = (
            (
                await session.execute(
                    text(
                        "SELECT "
                        f'(SELECT count(*) FROM "{runtime["schema"]}".messages '
                        "WHERE conversation_id=:conversation_id) AS messages, "
                        f'(SELECT count(*) FROM "{runtime["schema"]}".tool_calls '
                        "WHERE run_id=:run_id) AS tool_calls, "
                        f'(SELECT count(*) FROM "{runtime["schema"]}".attachments '
                        "WHERE conversation_id=:conversation_id) AS attachments"
                    ),
                    {
                        "conversation_id": chat.id,
                        "run_id": run_row["id"],
                    },
                )
            )
            .mappings()
            .one()
        )
    assert counts == {"messages": 11, "tool_calls": 5, "attachments": 2}


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raised", "expected_status"),
    [
        (asyncio.CancelledError(), "cancelled"),
        (RuntimeError("boom"), "failed"),
    ],
)
async def test_run_terminal_state_converges_when_source_stops(
    postgres_chat_runtime,
    raised: BaseException,
    expected_status: str,
) -> None:
    runtime = postgres_chat_runtime
    persistence = PostgresChatRunPersistence(
        repository=runtime["repository"],
        agent_id=runtime["agent_id"],
    )
    chat = ChatSpec(
        id=str(uuid4()),
        session_id=f"console:{expected_status}",
        user_id=str(runtime["user_id"]),
        name=expected_status,
    )

    async def source(_payload):
        yield 'data: {"object":"message","id":"before-stop","type":"progress",'
        raise raised

    persisted_source = persistence.wrap_stream(
        chat=chat,
        initiated_by=runtime["user_id"],
        stream_fn=source,
    )
    with pytest.raises(type(raised)):
        async for _line in persisted_source({}):
            pass

    async with runtime["session_factory"]() as session:
        status = (
            await session.execute(
                text(
                    f'SELECT status FROM "{runtime["schema"]}".runs '
                    "WHERE conversation_id=:conversation_id"
                ),
                {"conversation_id": chat.id},
            )
        ).scalar_one()
    assert status == expected_status


@pytest.mark.integration
@pytest.mark.asyncio
async def test_repeated_runs_keep_conversation_message_sequence_unique(
    postgres_chat_runtime,
) -> None:
    runtime = postgres_chat_runtime
    persistence = PostgresChatRunPersistence(
        repository=runtime["repository"],
        agent_id=runtime["agent_id"],
    )
    chat = ChatSpec(
        id=str(uuid4()),
        session_id="console:repeat",
        user_id=str(runtime["user_id"]),
        name="连续多轮",
    )

    async def source(payload):
        wire = {
            "object": "message",
            "id": payload["message_id"],
            "type": "result",
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "text", "text": payload["message_id"]}],
        }
        yield f"data: {json.dumps(wire)}\n\n"

    for message_id in ("answer-one", "answer-two"):
        wrapped = persistence.wrap_stream(
            chat=chat,
            initiated_by=runtime["user_id"],
            stream_fn=source,
        )
        _ = [line async for line in wrapped({"message_id": message_id})]

    async with runtime["session_factory"]() as session:
        sequences = (
            (
                await session.execute(
                    text(
                        f'SELECT sequence FROM "{runtime["schema"]}".messages '
                        "WHERE conversation_id=:conversation_id ORDER BY sequence"
                    ),
                    {"conversation_id": chat.id},
                )
            )
            .scalars()
            .all()
        )
    assert sequences == [1, 2]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_error_wire_without_final_finishes_run_as_failed(
    postgres_chat_runtime,
) -> None:
    runtime = postgres_chat_runtime
    persistence = PostgresChatRunPersistence(
        repository=runtime["repository"],
        agent_id=runtime["agent_id"],
    )
    chat = ChatSpec(
        id=str(uuid4()),
        session_id="console:error-wire",
        user_id=str(runtime["user_id"]),
        name="错误终态",
    )

    async def source(_payload):
        yield 'data: {"object":"error","status":"failed","data":{"message":"x"}}\n\n'

    wrapped = persistence.wrap_stream(
        chat=chat,
        initiated_by=runtime["user_id"],
        stream_fn=source,
    )
    _ = [line async for line in wrapped({})]

    async with runtime["session_factory"]() as session:
        status = (
            await session.execute(
                text(
                    f'SELECT status FROM "{runtime["schema"]}".runs '
                    "WHERE conversation_id=:conversation_id"
                ),
                {"conversation_id": chat.id},
            )
        ).scalar_one()
    assert status == "failed"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_user_input_and_assistant_result_share_ordered_history(
    postgres_chat_runtime,
) -> None:
    runtime = postgres_chat_runtime
    persistence = PostgresChatRunPersistence(
        repository=runtime["repository"],
        agent_id=runtime["agent_id"],
    )
    chat = ChatSpec(
        id=str(uuid4()),
        session_id="console:user-message",
        user_id=str(runtime["user_id"]),
        name="用户消息",
    )

    async def source(_payload):
        yield (
            'data: {"object":"message","id":"answer","type":"result",'
            '"role":"assistant","status":"completed","content":[]}\n\n'
        )

    wrapped = persistence.wrap_stream(
        chat=chat,
        initiated_by=runtime["user_id"],
        stream_fn=source,
    )
    _ = [
        line
        async for line in wrapped(
            {
                "content_parts": [{"type": "text", "text": "你好"}],
                "message_metadata": {"qwenpaw_client_message_id": "client-user-1"},
            }
        )
    ]

    messages = await runtime["repository"].list_messages(UUID(chat.id))
    assert [(message.sequence, message.role) for message in messages] == [
        (1, "user"),
        (2, "assistant"),
    ]
    assert messages[0].content["content"] == [{"type": "text", "text": "你好"}]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_client_disconnect_does_not_stop_background_persistence(
    postgres_chat_runtime,
) -> None:
    runtime = postgres_chat_runtime
    persistence = PostgresChatRunPersistence(
        repository=runtime["repository"],
        agent_id=runtime["agent_id"],
    )
    chat = ChatSpec(
        id=str(uuid4()),
        session_id="console:disconnect",
        user_id=str(runtime["user_id"]),
        name="断线继续",
    )
    release = asyncio.Event()

    async def source(_payload):
        yield 'data: {"object":"message","id":"progress","type":"progress","role":"assistant","status":"in_progress","content":[]}\n\n'
        await release.wait()
        yield 'data: {"object":"message","id":"answer","type":"result","role":"assistant","status":"completed","content":[]}\n\n'

    wrapped = persistence.wrap_stream(
        chat=chat,
        initiated_by=runtime["user_id"],
        stream_fn=source,
    )
    tracker = TaskTracker()
    queue, _ = await tracker.attach_or_start(chat.id, {}, wrapped)
    subscriber = tracker.stream_from_queue(queue, chat.id)
    first = await anext(subscriber)
    assert "progress" in first
    await subscriber.aclose()
    release.set()
    assert await tracker.wait_all_done(timeout=5)

    async with runtime["session_factory"]() as session:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT r.status, count(e.id) AS events "
                        f'FROM "{runtime["schema"]}".runs r JOIN '
                        f'"{runtime["schema"]}".run_events e ON e.run_id=r.id '
                        "WHERE r.conversation_id=:conversation_id GROUP BY r.status"
                    ),
                    {"conversation_id": chat.id},
                )
            )
            .mappings()
            .one()
        )
    assert row == {"status": "completed", "events": 2}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_oversized_wire_payload_is_stored_as_file_reference(
    postgres_chat_runtime,
    tmp_path: Path,
) -> None:
    runtime = postgres_chat_runtime
    persistence = PostgresChatRunPersistence(
        repository=runtime["repository"],
        agent_id=runtime["agent_id"],
        payload_storage_dir=tmp_path / "event-payloads",
        inline_payload_limit=256,
    )
    chat = ChatSpec(
        id=str(uuid4()),
        session_id="console:large-output",
        user_id=str(runtime["user_id"]),
        name="超大输出",
    )
    wire = {
        "object": "message",
        "id": "large-output",
        "type": "plugin_call_output",
        "role": "tool",
        "status": "completed",
        "content": [
            {
                "type": "data",
                "data": {
                    "call_id": "large-call",
                    "name": "execute_shell_command",
                    "output": "x" * 4096,
                },
            }
        ],
    }

    async def source(_payload):
        yield f"data: {json.dumps(wire)}\n\n"

    wrapped = persistence.wrap_stream(
        chat=chat,
        initiated_by=runtime["user_id"],
        stream_fn=source,
    )
    _ = [line async for line in wrapped({})]

    async with runtime["session_factory"]() as session:
        row = (
            (
                await session.execute(
                    text(
                        f"SELECT e.payload, t.output_ref, m.content AS message_content "
                        f'FROM "{runtime["schema"]}".run_events e '
                        f'JOIN "{runtime["schema"]}".tool_calls t ON t.id=e.tool_call_id '
                        f'JOIN "{runtime["schema"]}".messages m ON m.run_id=e.run_id '
                        "AND m.sequence=e.sequence "
                        "WHERE e.event_type='tool_output'"
                    )
                )
            )
            .mappings()
            .one()
        )
    payload = row["payload"]
    assert "x" * 512 not in json.dumps(payload)
    assert "x" * 512 not in json.dumps(row["message_content"])
    assert row["message_content"] == payload
    assert payload["qwenpaw_payload_ref"]["byte_size"] > 4096
    assert row["output_ref"] == payload["qwenpaw_payload_ref"]["path"]
    assert await persistence.load_event_payload(payload) == wire
