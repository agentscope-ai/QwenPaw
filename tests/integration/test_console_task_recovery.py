"""Recover submitted work across OS processes without replaying an uncertain effect."""

import asyncio
import multiprocessing
import os
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from qwenpaw.app.console_task_worker import ConsoleTaskWorker
from qwenpaw.identity.models import PlatformRole
from qwenpaw.identity.repository import PostgresUserRepository
from qwenpaw.identity.service import UserService
from qwenpaw.persistence.console_tasks import ConsoleTaskRepository
from qwenpaw.persistence.database import set_request_user
from test_migrations import _alembic_config


@asynccontextmanager
async def _connections(dsn, schema):
    engine = create_async_engine(dsn, poolclass=NullPool, hide_parameters=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def session():
        async with factory.begin() as db:
            await db.execute(text("SET LOCAL ROLE qwenpaw_runtime"))
            yield db

    try:
        yield ConsoleTaskRepository(schema, session, lease_seconds=1.2), factory
    finally:
        await engine.dispose()


def _child(dsn, schema, mode, marker, pipe, gate):
    async def run():
        async with _connections(dsn, schema) as (repo, _):
            pipe.send("ready")
            assert await asyncio.to_thread(gate.wait, 25)
            if mode in {"claim-only", "crash-running"}:
                claim = await repo.claim()
                if claim is None:
                    pipe.send(None)
                    return
                if mode == "crash-running":
                    assert await repo.begin(claim)
                    with open(marker, "a", encoding="utf-8") as stream:
                        stream.write(f"executed {claim.task_id}\n")
                pipe.send(claim)
                os._exit(0)  # Hard process loss, independent of Python finalizers.

            async def execute(claim, row):
                if claim.task_id == "owned-by-b":
                    await asyncio.sleep(repo.lease_seconds * 2)
                with open(marker, "a", encoding="utf-8") as stream:
                    stream.write(f"executed {claim.task_id}\n")
                return {"status": "completed", "output": row["envelope"]["label"]}

            worker = ConsoleTaskWorker(repo, execute, poll_seconds=0.08)
            serving = asyncio.create_task(worker.serve())
            try:
                assert await asyncio.to_thread(pipe.recv) == "stop"
            finally:
                serving.cancel()
                await asyncio.gather(serving, return_exceptions=True)

    asyncio.run(run())


@pytest.mark.integration
@pytest.mark.asyncio
async def test_crash_claims_execution_and_results_across_processes(postgres_test_schema, tmp_path):
    await asyncio.to_thread(command.upgrade, _alembic_config(postgres_test_schema), "head")
    dsn = postgres_test_schema.async_url()
    schema = postgres_test_schema.name
    multiprocessing_context = multiprocessing.get_context("spawn")
    marker = tmp_path / "dispatched.txt"
    children = []

    async def spawn(mode, gate):
        pipe, child_pipe = multiprocessing_context.Pipe()
        child = multiprocessing_context.Process(
            target=_child, args=(dsn, schema, mode, str(marker), child_pipe, gate)
        )
        child.start()
        child_pipe.close()
        children.append((child, pipe))
        assert await asyncio.to_thread(pipe.poll, 50), "child did not become ready"
        assert pipe.recv() == "ready"
        return child, pipe

    try:
        async with _connections(dsn, schema) as (repo, factory):
            async with factory.begin() as db:
                await db.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO qwenpaw_runtime'))
                await db.execute(
                    text(f'GRANT SELECT, UPDATE ON "{schema}".runs TO qwenpaw_runtime')
                )

            @asynccontextmanager
            async def identity_session():
                async with factory.begin() as db:
                    yield db

            users = UserService(
                PostgresUserRepository(schema=schema, session_factory=identity_session)
            )
            await users.create_user("root", "test-root-password", PlatformRole.ADMIN)
            a = await users.create_user("ordinary-a", "test-a-password", PlatformRole.MEMBER)
            b = await users.create_user("ordinary-b", "test-b-password", PlatformRole.MEMBER)
            assert a.platform_role == b.platform_role == PlatformRole.MEMBER

            async def enqueue(label, member):
                chat = str(uuid4())
                await repo.enqueue(
                    task_id=label,
                    owner_id=member.id,
                    agent_id="office",
                    parent_agent_id="office",
                    conversation_id=chat,
                    parent_conversation_id=chat,
                    run_id=str(uuid4()),
                    envelope={"label": member.username},
                )

            await enqueue("lost-before-execution", a)
            gate = multiprocessing_context.Event()
            first, pipe = await spawn("claim-only", gate)
            gate.set()
            assert await asyncio.to_thread(pipe.poll, 15)
            lost = pipe.recv()
            await asyncio.to_thread(first.join, 15)
            assert first.exitcode == 0 and not marker.exists()
            assert (await repo.lookup(lost.task_id, a.id))["state"] == "claimed"
            assert await repo.lookup(lost.task_id, b.id) is None
            async with repo.session() as db:
                await set_request_user(db, b.id)
                rows = await db.execute(
                    text(f"SELECT envelope FROM {repo.contents} WHERE id=:id"), {"id": lost.task_id}
                )
                assert rows.first() is None

            await enqueue("owned-by-b", b)
            second, second_pipe = await spawn("serve", gate)
            async with asyncio.timeout(15):
                while (await repo.lookup(lost.task_id, a.id))["state"] != "finished" or (
                    await repo.lookup("owned-by-b", b.id)
                )["state"] != "finished":
                    await asyncio.sleep(0.1)
            second_pipe.send("stop")
            await asyncio.to_thread(second.join, 15)
            assert second.exitcode == 0
            assert (await repo.lookup(lost.task_id, a.id))["result"]["output"] == "ordinary-a"
            assert (await repo.lookup("owned-by-b", b.id))["result"]["output"] == "ordinary-b"
            assert await repo.lookup("owned-by-b", a.id) is None
            assert await repo.begin(lost) is None

            await enqueue("lost-during-execution", a)
            race = multiprocessing_context.Event()
            participants = await asyncio.gather(
                spawn("crash-running", race), spawn("crash-running", race)
            )
            race.set()
            claims = []
            for process, endpoint in participants:
                assert await asyncio.to_thread(endpoint.poll, 15)
                claims.append(endpoint.recv())
                await asyncio.to_thread(process.join, 15)
                assert process.exitcode == 0
            (winner,) = [claim for claim in claims if claim is not None]
            await asyncio.sleep(repo.lease_seconds + 0.1)
            await repo.maintain()
            assert (await repo.lookup(winner.task_id, a.id))["state"] == "interrupted"
            assert not await repo.finish(winner, {"status": "completed"})
            assert await repo.claim() is None
            assert sorted(marker.read_text(encoding="utf-8").splitlines()) == [
                "executed lost-before-execution",
                "executed lost-during-execution",
                "executed owned-by-b",
            ]
            async with factory.begin() as db:
                await db.execute(
                    text(
                        f"""
                    UPDATE {repo.queue} SET finished_at=now()-interval '8 days'
                    WHERE id='owned-by-b'
                """
                    )
                )
            await repo.maintain()
            assert await repo.lookup("owned-by-b", b.id) is None
            assert await repo.lookup(lost.task_id, a.id)
    finally:
        for child, pipe in children:
            if child.is_alive():
                child.terminate()
            await asyncio.to_thread(child.join, 10)
            pipe.close()


@pytest.fixture
async def console_http(postgres_test_schema, tmp_path, monkeypatch):
    from datetime import datetime, timezone
    from functools import partial
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from qwenpaw.access.actor import ActorContext, ActorType
    from qwenpaw.access.agent_membership import AgentMembershipService
    from qwenpaw.access.agent_repository import (
        AgentResourceRole,
        LegacyAgentRecord,
        PostgresAgentRepository,
        agent_database_id,
    )
    from qwenpaw.app import agent_context, auth, console_task_worker
    from qwenpaw.app.chats.models import ChatSpec
    from qwenpaw.app.chats.repo import ConversationRecord, PostgresConversationRepository
    from qwenpaw.app.routers import auth as auth_router, console
    from qwenpaw.config import Config
    from test_multi_user_identity_storage import _runtime

    await asyncio.to_thread(command.upgrade, _alembic_config(postgres_test_schema), "head")
    schema = postgres_test_schema.name
    monkeypatch.setenv("QWENPAW_MULTI_USER_ENABLED", "true")
    monkeypatch.setenv("QWENPAW_SESSION_COOKIE_SECURE", "false")
    monkeypatch.setattr("qwenpaw.services.workspace_files.WORKING_DIR", tmp_path)
    config = Config.model_validate(
        {
            "agents": {
                "active_agent": "office",
                "profiles": {"office": {"id": "office", "workspace_dir": str(tmp_path)}},
            }
        }
    )
    monkeypatch.setattr(agent_context, "load_config", lambda: config)
    monkeypatch.setattr("qwenpaw.config.load_config", lambda: config)
    monkeypatch.setattr(auth, "_auth_config_cache", (0, None, []))
    # No external model or working-directory configuration is needed for the terminal frame.
    monkeypatch.setattr("qwenpaw.models.runtime.prepare_console_model", AsyncMock())
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config", lambda _: SimpleNamespace(project_dir=None)
    )

    async with _connections(postgres_test_schema.async_url(), schema) as (repo, factory):

        @asynccontextmanager
        async def identity_session():
            async with factory.begin() as db:
                yield db

        async with factory.begin() as db:
            await db.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO qwenpaw_runtime'))
            await db.execute(
                text(f'GRANT SELECT ON ALL TABLES IN SCHEMA "{schema}" TO qwenpaw_runtime')
            )
            await db.execute(text(f'GRANT INSERT ON "{schema}".conversations TO qwenpaw_runtime'))
            await db.execute(text(f'GRANT INSERT,UPDATE ON "{schema}".runs TO qwenpaw_runtime'))
        runtime = _runtime(schema, identity_session)
        for module in (auth, auth_router, console_task_worker):
            monkeypatch.setattr(module, "get_identity_runtime", lambda: runtime)
        agents = PostgresAgentRepository(schema=schema, session_factory=identity_session)
        monkeypatch.setattr(
            agent_context, "_get_agent_membership_service", lambda: AgentMembershipService(agents)
        )
        admin = await runtime.users.create_user("admin", "admin-password", PlatformRole.ADMIN)
        actor = ActorContext(admin.id, ActorType.USER, PlatformRole.ADMIN, True, "seed")
        await agents.register_owner(
            agent=LegacyAgentRecord("office", "Office", "", str(tmp_path), "active"),
            owner_user_id=admin.id,
        )
        chats = {}
        executed = []
        conversations = PostgresConversationRepository(schema=schema, session_factory=repo.session)
        for name in ("alice", "bob"):
            user = await runtime.users.create_user(name, f"{name}-password", PlatformRole.MEMBER)
            await agents.grant_member(
                actor=actor, user_id=user.id, agent_key="office", role=AgentResourceRole.USER
            )
            chat = ChatSpec(session_id=name, user_id=str(user.id))
            now = datetime.now(timezone.utc)
            await conversations.with_user(user.id).create_conversation(
                ConversationRecord(
                    id=chat.id,
                    agent_id=agent_database_id("office"),
                    owner_user_id=user.id,
                    title=name,
                    status="active",
                    created_at=now,
                    updated_at=now,
                )
            )
            chats[name] = chat

        class Channel:
            def resolve_session_id(self, *, channel_meta, **_):
                return channel_meta["session_id"]

            async def stream_one(self, payload):
                executed.append(payload["sender_id"])
                yield 'data: {"object":"response","status":"completed","output":["test-result"]}\n\n'

        chat_manager = SimpleNamespace(
            get_chat=AsyncMock(
                side_effect=lambda cid: next(c for c in chats.values() if c.id == cid)
            ),
            conversation_repository=conversations,
        )
        workspace = SimpleNamespace(
            agent_id="office",
            workspace_dir=tmp_path,
            channel_manager=SimpleNamespace(get_channel=AsyncMock(return_value=Channel())),
            chat_manager=chat_manager,
        )
        app = FastAPI()
        app.add_middleware(auth.AuthMiddleware)
        app.include_router(auth_router.router, prefix="/api")
        app.include_router(console.router, prefix="/api")
        app.state.multi_agent_manager = SimpleNamespace(get_agent=AsyncMock(return_value=workspace))
        worker = ConsoleTaskWorker(
            repo, partial(console_task_worker.execute_console_task, app), poll_seconds=0.05
        )
        app.state.console_task_worker = worker

        async with (
            AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as alice,
            AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as bob,
        ):

            async def submit(client, name, **options):
                login = await client.post(
                    "/api/auth/login", json={"username": name, "password": f"{name}-password"}
                )
                assert login.status_code == 200
                client.headers["Authorization"] = f"Bearer {login.json()['token']}"
                reply = await client.post(
                    "/api/console/chat/task",
                    json={
                        "conversation_id": str(chats[name].id),
                        "session_id": name,
                        "input": [],
                        "request_context": {"subagent_allowed_tools": []},
                        **options,
                    },
                )
                assert reply.status_code == 200, reply.text
                return reply.json()["task_id"]

            yield SimpleNamespace(
                repo=repo,
                factory=factory,
                schema=schema,
                worker=worker,
                chats=chats,
                executed=executed,
                alice=alice,
                bob=bob,
                submit=submit,
                workspace=workspace,
                channel_type=Channel,
                conversations=conversations,
            )


@pytest.mark.asyncio
async def test_console_http_rechecks_device_before_dispatch(console_http):
    from datetime import datetime, timezone
    from qwenpaw.app.chats.repo import RunRecord

    repo, factory = console_http.repo, console_http.factory
    alice, bob, submit = console_http.alice, console_http.bob, console_http.submit
    chats, worker = console_http.chats, console_http.worker
    executed, conversations = console_http.executed, console_http.conversations
    a_task, b_task = await asyncio.gather(submit(alice, "alice"), submit(bob, "bob"))
    assert (await bob.get(f"/api/console/chat/task/{a_task}")).status_code == 404
    assert (await alice.post("/api/auth/logout")).status_code == 200
    serving = asyncio.create_task(worker.serve())
    try:
        async with asyncio.timeout(15):
            while True:
                b = await bob.get(f"/api/console/chat/task/{b_task}")
                assert b.status_code == 200, b.text
                a = await repo.lookup(a_task, UUID(chats["alice"].user_id))
                if a["state"] == "finished" and b.json()["status"] == "finished":
                    break
                await asyncio.sleep(0.05)
        assert a["result"]["error"]["code"] == "task_http_401"
        assert b.json()["result"]["status"] == "completed"
        assert executed == [chats["bob"].user_id]
    finally:
        serving.cancel()
        await asyncio.gather(serving, return_exceptions=True)

    bob_id = UUID(chats["bob"].user_id)
    chat_id = chats["bob"].id
    run_id = uuid4()
    await repo.enqueue(
        task_id="lost-after-run-start",
        owner_id=bob_id,
        agent_id="office",
        parent_agent_id="office",
        conversation_id=chat_id,
        parent_conversation_id=chat_id,
        run_id=str(run_id),
        envelope={},
    )
    claim = await repo.claim()
    assert await repo.begin(claim)
    history = conversations.with_user(bob_id)
    await history.create_run(
        RunRecord(
            id=run_id,
            conversation_id=chat_id,
            initiated_by=bob_id,
            status="running",
            started_at=datetime.now(timezone.utc),
        )
    )
    async with factory.begin() as db:
        await db.execute(
            text(f"UPDATE {repo.queue} SET lease_until=now() WHERE id=:id"),
            {"id": claim.task_id},
        )
    await repo.maintain()
    reply = await bob.get(f"/api/console/chat/task/{claim.task_id}")
    assert reply.json()["result"]["error"]["code"] == "task_execution_interrupted"
    recorded_run = await history.get_run(run_id)
    assert (
        recorded_run.status == "failed"
        and recorded_run.error_summary == "task_execution_interrupted"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["admission", "execution", "execution_swallowed", "confirmed"])
async def test_durable_timeout_reason_and_no_replay(console_http, monkeypatch, tmp_path, phase):
    from types import SimpleNamespace
    from qwenpaw.access.agent_repository import agent_database_id
    from qwenpaw.app.chats.run_persistence import PostgresChatRunPersistence
    from qwenpaw.app.routers import console

    host = console_http
    marker = tmp_path / "tool-effects.txt"
    execution = asyncio.Event()

    if phase == "admission":

        def hold_admission(_function):
            async def wait_for_admission():
                await asyncio.Event().wait()

            return wait_for_admission

        monkeypatch.setattr(console, "admitted", hold_admission)

    async def slow_model(_self, _payload):
        execution.set()
        with marker.open("a", encoding="utf-8") as output:
            output.write("tool ran once\n")
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            if phase == "confirmed":
                yield 'data: {"object":"response","status":"completed","output":["saved"]}\n\n'
                return
            if phase != "execution_swallowed":
                raise
        yield 'data: {"object":"response","status":"cancelled"}\n\n'

    monkeypatch.setattr(host.channel_type, "stream_one", slow_model)
    persistence = PostgresChatRunPersistence(
        repository=host.conversations, agent_id=agent_database_id("office")
    )

    class RecordingChatManager(SimpleNamespace):
        def persisting_stream_source(self, chat, stream):
            return persistence.wrap_stream(
                chat=chat, initiated_by=UUID(chat.user_id), stream_fn=stream
            )

    host.workspace.chat_manager = RecordingChatManager(**vars(host.workspace.chat_manager))
    async with host.factory.begin() as db:
        await db.execute(text(f'GRANT UPDATE ON "{host.schema}".conversations TO qwenpaw_runtime'))
        await db.execute(
            text(f'GRANT INSERT,UPDATE ON "{host.schema}".run_events TO qwenpaw_runtime')
        )
        await db.execute(
            text(f'GRANT INSERT,UPDATE ON "{host.schema}".messages TO qwenpaw_runtime')
        )

    task_id = await host.submit(host.bob, "bob", timeout=1.5)
    claim = await host.repo.claim()
    await asyncio.wait_for(host.worker._execute_claim(claim), 8)
    response = await host.bob.get(f"/api/console/chat/task/{task_id}")
    response.raise_for_status()
    result = response.json()
    assert result["execution_state"] == "finished"
    history = host.conversations.with_user(UUID(host.chats["bob"].user_id))
    run = await history.get_run(UUID(result["run_id"]))
    if phase == "confirmed":
        assert result["result"]["status"] == "completed" and run.status == "completed"
        assert result["result"]["output"] == ["saved"]
    else:
        code = "task_admission_timeout" if phase == "admission" else "task_execution_timeout"
        assert result["result"]["status"] == "failed" and result["result"]["error"]["code"] == code
        if phase == "admission":
            assert not execution.is_set() and not marker.exists() and run is None
            assert "尚未开始" in result["result"]["error"]["message"]
        else:
            assert run.status == "failed" and run.error_summary == code
            assert "核对" in result["result"]["error"]["message"]
    if phase != "admission":
        assert execution.is_set() and marker.read_text(encoding="utf-8") == "tool ran once\n"
    await host.repo.maintain()
    assert await host.repo.claim() is None
