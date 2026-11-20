"""Two ordinary users on real TCP streams with PostgreSQL-backed grants."""

import asyncio
import json
import socket
from time import perf_counter
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest
import uvicorn
from alembic import command
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from tests.fixtures.postgres import DockerPostgresAdmin
from test_migrations import _alembic_config
from test_multi_user_identity_storage import _runtime

from qwenpaw.access import agent_repository
from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.access.agent_governance import AgentGovernanceService
from qwenpaw.access.agent_repository import AgentResourceRole, LegacyAgentRecord
from qwenpaw.app import agent_context, auth, stream_access
from qwenpaw.app.routers import admin_users, agent_members, agent_scoped
from qwenpaw.app.routers import auth as login_routes
from qwenpaw.app.routers import (
    backup,
    console,
    plan,
    project_directory,
    runtime_status,
    skills_stream,
    tool_calls,
    user_input,
    workspace,
)
from qwenpaw.app.chats.models import ChatSpec
from qwenpaw.app.chats.repo.conversation import ConversationRecord
from qwenpaw.app.chats.repo.postgres_repo import PostgresConversationRepository
from qwenpaw.app.task_tracker import TaskTracker
from qwenpaw.config import Config
from qwenpaw.identity.governance import UserGovernanceService
from qwenpaw.identity.models import PlatformRole
from qwenpaw.identity.repository import PostgresUserRepository
from qwenpaw.plan import broadcast as plans
from qwenpaw.persistence import agent_user_workspaces
from qwenpaw.runtime_status import broadcast as statuses
from qwenpaw.services import workspace_files
from qwenpaw.tool_calls._stream import ToolStream
from qwenpaw.user_input import broadcast as inputs


@asynccontextmanager
async def serve(app):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                lifespan="off",
                access_log=False,
                log_level="error",
                timeout_graceful_shutdown=2,
            )
        )
        task = asyncio.create_task(server.serve(sockets=[sock]))
        try:
            async with asyncio.timeout(5):
                while not server.started:
                    if task.done():
                        await task
                    await asyncio.sleep(0.01)
            yield f"http://127.0.0.1:{sock.getsockname()[1]}"
        finally:
            server.should_exit = True
            await asyncio.wait_for(task, 8)


async def next_event(lines):
    async with asyncio.timeout(4):
        async for line in lines:
            if line.startswith("data: "):
                return json.loads(line[6:])
    raise AssertionError("stream ended before the expected event")


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action",
    [
        "logout",
        "disable",
        "remove",
        "logout_without_cookie",
        "logout_with_other_cookie",
        "external_remove",
    ],
)
async def test_two_members_keep_live_subscriptions_isolated(
    action,
    postgres_test_schema,
    monkeypatch,
    tmp_path,
    record_property,
):
    await asyncio.to_thread(command.upgrade, _alembic_config(postgres_test_schema), "head")
    engine = create_async_engine(postgres_test_schema.async_url())
    factory = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def sessions():
        async with factory.begin() as session:
            yield session

    schema = postgres_test_schema.name
    runtime = _runtime(schema, sessions)
    checks = AsyncMock(wraps=runtime.sessions.active_parent_session)
    monkeypatch.setattr(runtime.sessions, "active_parent_session", checks)
    agents = agent_repository.PostgresAgentRepository(schema=schema, session_factory=sessions)
    repo = PostgresUserRepository(schema=schema, session_factory=sessions)
    user_governance = UserGovernanceService(
        repository=repo, user_service=runtime.users, session_service=runtime.sessions
    )
    monkeypatch.setenv("QWENPAW_MULTI_USER_ENABLED", "true")
    monkeypatch.setenv("QWENPAW_SESSION_COOKIE_SECURE", "false")
    for module in (auth, login_routes, stream_access):
        monkeypatch.setattr(module, "get_identity_runtime", lambda: runtime)
    for module in (agent_repository, stream_access):
        monkeypatch.setattr(module, "PostgresAgentRepository", lambda **_: agents)
    config = Config.model_validate(
        {
            "agents": {
                "active_agent": "office",
                "profiles": {
                    "office": {"id": "office", "workspace_dir": str(tmp_path)},
                },
            }
        }
    )
    monkeypatch.setattr(auth, "_auth_config_cache", (0, None, []))
    monkeypatch.setattr("qwenpaw.config.load_config", lambda: config)
    monkeypatch.setattr(agent_context, "load_config", lambda: config)

    app = FastAPI()
    app.add_middleware(stream_access.StreamAccessMiddleware)
    app.add_middleware(agent_scoped.AgentContextMiddleware)
    app.add_middleware(auth.AuthMiddleware)
    for module in (
        login_routes,
        agent_members,
        admin_users,
        plan,
        runtime_status,
        user_input,
        workspace,
        console,
        skills_stream,
        tool_calls,
        backup,
        project_directory,
    ):
        app.include_router(module.router, prefix="/api")
    app.dependency_overrides[agent_members.get_governance_service] = lambda: AgentGovernanceService(
        agents
    )
    app.dependency_overrides[admin_users.get_governance_service] = lambda: user_governance
    workspaces = agent_user_workspaces.AgentUserWorkspaceRepository(
        schema=schema, session_factory=sessions
    )
    monkeypatch.setattr(
        agent_user_workspaces, "AgentUserWorkspaceRepository", lambda **_: workspaces
    )
    monkeypatch.setattr(workspace_files, "WORKING_DIR", tmp_path)
    from qwenpaw.config.config import AgentProfileConfig

    profile = AgentProfileConfig(id="office", name="Office")
    monkeypatch.setattr("qwenpaw.config.config.load_agent_config", lambda _: profile)
    monkeypatch.setattr("qwenpaw.models.runtime.prepare_console_model", AsyncMock())
    chat_repo = PostgresConversationRepository(schema=schema, session_factory=sessions)
    chats, tools, model_inputs, directories = {}, {}, {}, {}
    tracker = TaskTracker()

    async def local_model(payload):
        yield 'data: {"type":"connected"}\n\n'
        queue = model_inputs[payload["sender_id"]]
        while True:
            message = await queue.get()
            if message is None:
                return
            yield "data: " + json.dumps({"message": message}) + "\n\n"

    model_channel = SimpleNamespace(
        stream_one=local_model,
        resolve_session_id=lambda **kwargs: kwargs["channel_meta"]["session_id"],
    )
    local_workspace = SimpleNamespace(
        agent_id="office",
        workspace_dir=tmp_path,
        task_tracker=tracker,
        channel_manager=SimpleNamespace(get_channel=AsyncMock(return_value=model_channel)),
        chat_manager=SimpleNamespace(
            conversation_repository=chat_repo, get_chat=AsyncMock(side_effect=chats.get)
        ),
    )
    app.state.multi_agent_manager = SimpleNamespace(
        get_agent=AsyncMock(return_value=local_workspace)
    )
    app.state.app_services = SimpleNamespace(tool_coordinator=tools)
    channels = ("runtime-status", "plan", "user-input")
    try:
        owner = await runtime.users.create_user("owner", "owner-password", PlatformRole.ADMIN)
        admin = ActorContext(owner.id, ActorType.USER, PlatformRole.ADMIN, True, "seed")
        await agents.register_owner(
            agent=LegacyAgentRecord("office", "Office", "", str(tmp_path), "active"),
            owner_user_id=owner.id,
        )
        members = []
        for name in ("alpha", "bravo"):
            member = await runtime.users.create_user(name, f"{name}-password", PlatformRole.MEMBER)
            assert member.platform_role is PlatformRole.MEMBER
            await agents.grant_member(
                agent_key="office", user_id=member.id, role=AgentResourceRole.USER, actor=admin
            )
            members.append(member)
            uid = str(member.id)
            chat = ChatSpec(session_id=name, user_id=uid, channel="console")
            chats[chat.id] = chat
            now = datetime.now(UTC)
            await chat_repo.with_user(member.id).create_conversation(
                ConversationRecord(
                    id=UUID(chat.id),
                    agent_id=agent_repository.agent_database_id("office"),
                    owner_user_id=member.id,
                    title=name,
                    status="active",
                    created_at=now,
                    updated_at=now,
                )
            )
            model_inputs[uid] = asyncio.Queue()
            tools[name] = SimpleNamespace(
                ctx=SimpleNamespace(
                    agent_id="office",
                    session_id="same",
                    extra={"execution_context": {"user_id": uid}},
                ),
                stream=ToolStream(name, "same"),
            )
            directories[uid] = workspace_files.resolve_files_workspace_access(
                agent_id="office",
                agent_workspace=tmp_path,
                agent_project=tmp_path,
                actor_user_id=member.id,
                access_role=AgentResourceRole.USER,
            ).project.path

        async with serve(app) as url, AsyncExitStack() as stack:

            async def login(name):
                client = await stack.enter_async_context(
                    httpx.AsyncClient(base_url=url, trust_env=False)
                )
                response = await client.post(
                    "/api/auth/login", json={"username": name, "password": f"{name}-password"}
                )
                response.raise_for_status()
                data = response.json()
                client.headers.update(
                    {
                        "Authorization": f"Bearer {data['token']}",
                        "X-Agent-Id": "office",
                        "X-Session-Id": data["session"]["id"],
                    }
                )
                return client

            first, other, admin_client = await asyncio.gather(
                *(login(name) for name in ("alpha", "bravo", "owner"))
            )
            for endpoint, body in (
                ("/api/skills/ai/optimize/stream", {"content": "local"}),
                ("/api/workspace/project-directory/clone", {"url": "local-fixture"}),
                ("/api/backups/stream", {}),
            ):
                denied = await first.post(endpoint, json=body)
                assert denied.status_code == 403
            listeners = []
            for client, member, chat in zip((first, other), members, chats.values()):
                streams = []
                for channel in channels:
                    response = await stack.enter_async_context(
                        client.stream("GET", f"/api/{channel}/stream")
                    )
                    response.raise_for_status()
                    lines = response.aiter_lines()
                    assert await next_event(lines) == {"type": "connected"}
                    streams.append(lines)
                for reconnect in (False, True):
                    response = await stack.enter_async_context(
                        client.stream(
                            "POST",
                            "/api/console/chat",
                            json={
                                "conversation_id": chat.id,
                                "session_id": chat.session_id,
                                "reconnect": reconnect,
                                "channel": "console",
                                "input": [],
                            },
                        )
                    )
                    response.raise_for_status()
                    lines = response.aiter_lines()
                    assert await next_event(lines) == {"type": "connected"}
                    if reconnect:
                        assert await next_event(lines) == {"type": "replay_end"}
                    streams.append(lines)
                response = await stack.enter_async_context(
                    client.stream("GET", f"/api/tool-calls/same/{member.username}/stream")
                )
                response.raise_for_status()
                streams.append(response.aiter_lines())
                response = await stack.enter_async_context(
                    client.stream("GET", "/api/workspace/watch")
                )
                response.raise_for_status()
                lines = response.aiter_lines()
                assert await next_event(lines) == {"type": "connected"}
                streams.append(lines)
                listeners.append(streams)

            async def publish(member, marker):
                uid = str(member.id)
                statuses.broadcast_runtime_status(
                    "office", session_id="same", stage="step", message=marker, user_id=uid
                )
                plans.broadcast_plan_update(
                    "office",
                    {
                        "type": "plan_update",
                        "plan": {
                            "id": marker,
                            "name": marker,
                            "description": "",
                            "expected_outcome": "",
                        },
                    },
                    session_id="same",
                    user_id=uid,
                )
                inputs.broadcast_user_input_update("office", {"message": marker}, user_id=uid)
                model_inputs[uid].put_nowait(marker)
                await tools[member.username].stream.append(marker)
                (directories[uid] / (marker + ".txt")).write_text(marker, encoding="utf-8")

            async def expect(streams, marker):
                status, update, prompt, chat, reconnect, tool, files = await asyncio.gather(
                    *(next_event(lines) for lines in streams)
                )
                assert (status["message"], update["plan"]["id"], prompt["message"]) == (marker,) * 3
                assert chat["message"] == reconnect["message"] == tool["data"] == marker
                assert {event["path"] for event in files["events"]} == {marker + ".txt"}

            for member in members:
                await publish(member, member.username)
            await asyncio.gather(expect(listeners[0], "alpha"), expect(listeners[1], "bravo"))
            for client, member in zip((first, other), members):
                current = await client.get("/api/plan/current", params={"session_id": "same"})
                assert current.json()["name"] == member.username

            # Rotation must not interrupt a healthy device's open connections.
            refreshed = await other.post("/api/auth/refresh")
            refreshed.raise_for_status()
            other.headers["Authorization"] = f"Bearer {refreshed.json()['token']}"
            # A second device for the same account is independent of the first device.
            second_device = await login("alpha")
            response = await stack.enter_async_context(
                second_device.stream("GET", "/api/runtime-status/stream")
            )
            device_stream = response.aiter_lines()
            assert await next_event(device_stream) == {"type": "connected"}
            record_property("checks_before_revocation", checks.await_count)
            if action.startswith("logout"):
                if action == "logout_without_cookie":
                    first.cookies.clear()
                elif action == "logout_with_other_cookie":
                    first.cookies.clear()
                    first.cookies.update(other.cookies)
                change = await first.post("/api/auth/logout")
                assert change.json() == {"revoked": True}
                if action == "logout_with_other_cookie":
                    assert "set-cookie" not in change.headers
                    (await other.post("/api/auth/refresh")).raise_for_status()
            elif action == "disable":
                change = await admin_client.patch(
                    f"/api/admin/users/{members[0].id}/status", json={"status": "disabled"}
                )
            elif action == "external_remove":
                # A separate psql process commits a membership change without the in-process signal.
                await asyncio.to_thread(
                    DockerPostgresAdmin(postgres_test_schema.config).execute,
                    f"""UPDATE "{schema}".agent_members SET revoked_at=now()
                        WHERE agent_id='{agent_repository.agent_database_id("office")}' AND user_id='{members[0].id}'""",
                )
                change = None
            else:
                change = await admin_client.delete(f"/api/agents/office/members/{members[0].id}")
            if change is not None:
                change.raise_for_status()
            started = perf_counter()
            # Keep the plan stream idle. Other streams have data ready after revocation.
            uid = str(members[0].id)
            if action != "external_remove":
                statuses.broadcast_runtime_status(
                    "office", session_id="same", stage="step", message="after", user_id=uid
                )
                inputs.broadcast_user_input_update("office", {"message": "after"}, user_id=uid)
                model_inputs[uid].put_nowait("after")
                await tools["alpha"].stream.append("after")
                (directories[uid] / "after.txt").write_text("after", encoding="utf-8")
            await publish(members[1], "still-live")

            async def expect_eof(lines):
                async with asyncio.timeout(7 if action == "external_remove" else 3):
                    assert [line async for line in lines if line.startswith("data:")] == []
                    return (perf_counter() - started) * 1000

            timings = await asyncio.gather(*(expect_eof(lines) for lines in listeners[0]))
            record_property("max_close_ms", round(max(timings), 2))
            await expect(listeners[1], "still-live")
            if action.startswith("logout"):
                assert (await next_event(device_stream))["message"] == "after"
            else:
                await expect_eof(device_stream)
            denied = await first.get("/api/runtime-status/current", params={"session_id": "same"})
            assert denied.status_code == (403 if action.endswith("remove") else 401)
            for module in (plans, inputs):
                assert ("office", uid) not in module._queues
                assert ("office", str(members[1].id)) in module._queues
            assert not tools["alpha"].stream._subscribers
            assert len(tools["bravo"].stream._subscribers) == 1
    finally:
        for queue in model_inputs.values():
            queue.put_nowait(None)
        await engine.dispose()
