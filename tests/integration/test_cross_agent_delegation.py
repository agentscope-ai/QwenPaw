"""普通成员通过真实 Console 路由和 PostgreSQL 向另一智能体委托。"""

import asyncio
from datetime import UTC, datetime
from dataclasses import replace
from functools import partial
import json
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import pytest
from alembic import command
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_migrations import _alembic_config

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.access.agent_repository import (
    AgentResourceRole,
    LegacyAgentRecord,
    PostgresAgentRepository,
    agent_database_id,
)
from qwenpaw.agents.tools import agent_management as tools
from qwenpaw.app import agent_context, auth
from qwenpaw.app.channels.console.channel import ConsoleChannel
from qwenpaw.app.chats.backfill import register_chat_metadata
from qwenpaw.app.chats.manager import ChatManager
from qwenpaw.app.chats.repo.json_repo import JsonChatRepository
from qwenpaw.app.chats.repo.postgres_repo import PostgresConversationRepository
from qwenpaw.app.console_delegation import current_delegation
from qwenpaw.app.console_task_worker import (
    ConsoleTaskWorker,
    execute_console_task,
)
from qwenpaw.app.routers import auth as auth_router
from qwenpaw.app.routers import console
from qwenpaw.app.task_tracker import TaskTracker
from qwenpaw.app.stream_access import StreamAccessMiddleware
from qwenpaw.config import Config
from qwenpaw.config.config import AgentProfileConfig
from qwenpaw.identity.models import PlatformRole
from qwenpaw.identity.runtime import get_identity_runtime
from qwenpaw.persistence import database
from qwenpaw.persistence.console_tasks import ConsoleTaskRepository
from qwenpaw.runtime.builder import AgentBuilder


@pytest.mark.asyncio
@pytest.mark.integration
async def test_two_members_delegate_and_poll_only_owned_root_and_live_target(
    postgres_test_schema,
    monkeypatch,
    tmp_path,
):
    await asyncio.to_thread(
        command.upgrade, _alembic_config(postgres_test_schema), "head"
    )
    engine = create_async_engine(postgres_test_schema.async_url())
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(database, "_get_session_factory", lambda: sessions)
    monkeypatch.setenv("QWENPAW_MULTI_USER_ENABLED", "true")
    monkeypatch.setenv("QWENPAW_DATABASE_SCHEMA", postgres_test_schema.name)
    monkeypatch.setenv("QWENPAW_SESSION_COOKIE_SECURE", "false")
    roles = PostgresAgentRepository(schema=postgres_test_schema.name)
    conversations = PostgresConversationRepository(
        schema=postgres_test_schema.name
    )
    runtime = get_identity_runtime()
    config = Config.model_validate(
        {
            "agents": {
                "active_agent": "source",
                "profiles": {
                    key: {"id": key, "workspace_dir": str(tmp_path / key)}
                    for key in ("source", "target", "third")
                },
            }
        }
    )
    monkeypatch.setattr(agent_context, "load_config", lambda: config)
    monkeypatch.setattr("qwenpaw.config.load_config", lambda: config)
    monkeypatch.setattr(auth, "_auth_config_cache", (0, None, []))
    monkeypatch.setattr(
        "qwenpaw.services.workspace_files.WORKING_DIR", tmp_path
    )
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda key: SimpleNamespace(project_dir=""),
    )
    monkeypatch.setattr(
        "qwenpaw.models.runtime.prepare_console_model", AsyncMock()
    )
    monkeypatch.setattr(console, "generate_and_update_title", AsyncMock())
    monkeypatch.setattr(
        console,
        "_personal_library_service",
        lambda: SimpleNamespace(
            match_prompt_documents=AsyncMock(return_value=[]),
        ),
    )
    target_calls = []
    parents = {}
    target_waiting = asyncio.Event()
    resume_target = asyncio.Event()

    async def stream(agent, payload):
        prompt = payload["content_parts"][0].text
        context = payload["meta"]["request_context"]
        if agent == "target":
            child = current_delegation.get()
            assert child.is_subtask and child.destination == agent
            assert context["root_agent_id"] == "source"
            assert context["root_session_id"] == child.root_session_id
            sdk = await workspaces[agent].channel_manager.get_channel(
                "console"
            )
            assert (
                sdk.build_agent_request_from_native(payload).root_session_id
                == child.root_session_id
            )
            assert child.conversation_id not in context["task_output_dir"]
            assert context["conversation_id"] in context["task_output_dir"]
            profile = AgentProfileConfig(id=agent, name=agent)
            resolved = AgentBuilder._apply_request_project(profile, context)
            assert resolved.project_dir == context["task_output_dir"]
            if prompt == "hold":
                yield ": waiting\n\n"
                await resume_target.wait()
                yield "data: confidential-after-removal\n\n"
                return
            nested = await tools.submit_to_agent("third", "nested")
            assert nested.state == "error" and "再次" in nested.content[0].text
            target_calls.append(
                (
                    payload["sender_id"],
                    payload["meta"]["session_id"],
                    context["conversation_id"],
                )
            )
            answer = "target-reply-" + payload["sender_id"]
        else:
            parents[payload["sender_id"]] = current_delegation.get()
            if prompt == "foreground":
                result = await tools.chat_with_agent(
                    "target", "review", session_id="same-handle"
                )
            elif prompt == "background":
                result = await tools.submit_to_agent(
                    "target", "review", session_id="same-handle"
                )
            else:
                result = await tools.check_agent_task(prompt)
            answer = result.content[0].text
        event = {
            "object": "response",
            "status": "completed",
            "output": [
                {
                    "content": [{"type": "text", "text": answer}],
                }
            ],
        }
        yield f"data: {json.dumps(event)}\n\n"

    app = FastAPI()
    app.add_middleware(StreamAccessMiddleware)
    app.add_middleware(auth.AuthMiddleware)
    app.include_router(auth_router.router, prefix="/api")
    app.include_router(console.router, prefix="/api")
    workspaces = {}
    for key in config.agents.profiles:
        folder = tmp_path / key
        folder.mkdir()
        channel = ConsoleChannel(
            process=AsyncMock(),
            enabled=True,
            bot_prefix="",
            media_dir=str(folder),
        )
        channel.stream_one = partial(stream, key)
        workspaces[key] = SimpleNamespace(
            agent_id=key,
            workspace_dir=folder,
            task_tracker=TaskTracker(),
            channel_manager=SimpleNamespace(
                get_channel=AsyncMock(return_value=channel)
            ),
            chat_manager=ChatManager(
                repo=JsonChatRepository(folder / "chats.json"),
                conversation_repository=conversations,
                on_chat_created=partial(_record_chat, key, conversations),
            ),
        )
    app.state.multi_agent_manager = SimpleNamespace(
        get_agent=AsyncMock(side_effect=workspaces.get)
    )
    worker = ConsoleTaskWorker(
        ConsoleTaskRepository(postgres_test_schema.name),
        partial(execute_console_task, app),
    )
    app.state.console_task_worker = worker
    serve = asyncio.create_task(worker.serve())

    async def turn(client, token, prompt, session_id="shared-root-name"):
        reply = await client.post(
            "/api/console/chat",
            headers={
                "Authorization": "Bearer " + token,
                "X-Agent-Id": "source",
            },
            json={
                "session_id": session_id,
                "input": [
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": prompt}],
                    }
                ],
            },
        )
        reply.raise_for_status()
        final = tools._terminal_sse_response(reply)
        assert final is not None
        return tools.extract_agent_text_content(final)

    try:
        admin = await runtime.users.create_user(
            "owner", "owner-password", PlatformRole.ADMIN
        )
        actor = ActorContext(
            admin.id, ActorType.USER, PlatformRole.ADMIN, True, "test"
        )
        members = [
            await runtime.users.create_user(
                name, "member-password", PlatformRole.MEMBER
            )
            for name in ("first", "second")
        ]
        for key in workspaces:
            await roles.register_owner(
                agent=LegacyAgentRecord(
                    key, key, "", str(tmp_path / key), "active"
                ),
                owner_user_id=admin.id,
            )
            for member in members:
                await roles.grant_member(
                    agent_key=key,
                    user_id=member.id,
                    role=AgentResourceRole.USER,
                    actor=actor,
                )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://local"
        ) as client:
            tokens = []
            for member in members:
                login = await client.post(
                    "/api/auth/login",
                    json={
                        "username": member.username,
                        "password": "member-password",
                    },
                )
                login.raise_for_status()
                assert login.json()["user"]["platform_role"] == "member"
                tokens.append(login.json()["token"])
            replies = await asyncio.gather(
                *(turn(client, token, "foreground") for token in tokens)
            )
            for reply, member in zip(replies, members):
                assert "target-reply-" + str(member.id) in reply
            assert len(target_calls) == 2
            assert (
                len({row[1] for row in target_calls})
                == len({row[2] for row in target_calls})
                == 2
            )
            submitted = await turn(client, tokens[0], "background")
            task = re.search(r"\[TASK_ID: (task-[0-9a-f]{12})\]", submitted)
            assert task, submitted
            task_id = task.group(1)
            async with asyncio.timeout(15):
                while True:
                    result = await turn(client, tokens[0], task_id)
                    if "[STATUS: finished]" in result:
                        break
                    await asyncio.sleep(0.05)
            assert "target-reply-" + str(members[0].id) in result
            assert "[SESSION: same-handle]" in result
            assert target_calls[-1] in target_calls[:-1]  # 同一父会话能续聊。
            assert "HTTP 404" in await turn(client, tokens[1], task_id)
            assert "HTTP 404" in await turn(
                client, tokens[0], task_id, session_id="different-root"
            )
            await roles.revoke_member(
                agent_key="target", user_id=members[0].id, actor=actor
            )
            assert "HTTP 403" in await turn(client, tokens[0], task_id)
            assert "HTTP 403" in await turn(client, tokens[0], "foreground")
            assert "target-reply-" + str(members[1].id) in await turn(
                client, tokens[1], "foreground"
            )
            # 目标仍可访问时，来源成员被移出也不能读取该派发的后台结果。
            await roles.grant_member(
                agent_key="target",
                user_id=members[0].id,
                role=AgentResourceRole.USER,
                actor=actor,
            )
            delegated = parents[str(members[0].id)].for_target(
                "target", session_handle="waiting"
            )

            async def observe_connection(scope, receive, send):
                async def observe_frame(message):
                    await send(message)
                    if message.get("body") == b": waiting\n\n":
                        target_waiting.set()

                await app(scope, receive, observe_frame)

            delegated = replace(delegated, app=observe_connection)
            pending = asyncio.create_task(
                delegated.call(
                    "POST",
                    "/api/console/chat",
                    payload={
                        "session_id": "waiting",
                        "input": [
                            {
                                "role": "user",
                                "content": [{"type": "text", "text": "hold"}],
                            }
                        ],
                    },
                )
            )
            await asyncio.wait_for(target_waiting.wait(), 5)
            await roles.revoke_member(
                agent_key="source", user_id=members[0].id, actor=actor
            )
            try:
                stopped = await asyncio.wait_for(pending, 2)
                assert "confidential-after-removal" not in stopped.text
            finally:
                resume_target.set()
            direct = await client.get(
                "/api/console/chat/task/" + task_id,
                headers={
                    "Authorization": "Bearer " + tokens[0],
                    "X-Agent-Id": "target",
                },
            )
            assert direct.status_code == 403

            # 源会话与续聊目标分别绑定实际发布记录，均不能通过委托进入草稿运行空间。
            await roles.grant_member(
                agent_key="source",
                user_id=members[0].id,
                role=AgentResourceRole.USER,
                actor=actor,
            )
            root = await workspaces[
                "source"
            ].chat_manager.get_chat_id_by_session(
                "shared-root-name",
                "console",
                user_id=str(members[0].id),
            )
            await _bind_publication(
                conversations,
                postgres_test_schema.name,
                "source",
                admin.id,
                members[0].id,
                root,
            )
            await _bind_publication(
                conversations,
                postgres_test_schema.name,
                "target",
                admin.id,
                members[1].id,
                target_calls[-1][2],
            )
            count = len(target_calls)
            for token in tokens:
                assert "HTTP 403" in await turn(client, token, "foreground")
            assert len(target_calls) == count
    finally:
        serve.cancel()
        await asyncio.gather(serve, return_exceptions=True)
        await engine.dispose()


async def _record_chat(agent_key, repository, spec):
    await register_chat_metadata(
        chat=spec, agent_id=agent_database_id(agent_key), repository=repository
    )


async def _bind_publication(
    conversations, schema, agent_key, owner_id, user_id, chat_id
):
    from qwenpaw.publications.models import (
        SharedAppRecord,
        SharedAppPublicationRecord,
    )
    from qwenpaw.publications.repository import PostgresSharedAppRepository

    now = datetime.now(UTC)
    apps = PostgresSharedAppRepository(schema=schema)
    app = await apps.create_app(
        SharedAppRecord(
            id=uuid4(),
            agent_id=agent_database_id(agent_key),
            owner_user_id=owner_id,
            status="draft",
            created_at=now,
            updated_at=now,
        )
    )
    version = uuid4()
    await apps.create_submission(
        SharedAppPublicationRecord(
            id=version,
            shared_app_id=app.id,
            version="r1",
            immutable_manifest={},
            baseline_workspace_key=f"published_workspaces/{version}",
            submitted_by=owner_id,
            review_status="pending",
        )
    )
    await apps.review(
        version,
        reviewer_id=owner_id,
        decision="approved",
        note="",
        reviewed_at=now,
    )
    await apps.switch_current(
        app.id,
        publication_id=version,
        expected_current_id=None,
        actor_id=owner_id,
        changed_at=now,
    )
    bound = await conversations.with_user(user_id).bind_publication(
        UUID(chat_id),
        expected_agent_id=app.agent_id,
        shared_app_id=app.id,
        publication_id=version,
        updated_at=now,
    )
    assert bound.publication_id == version
