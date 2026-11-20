"""Queued PawApp turns keep their device scope and deliver live Console events."""

import asyncio
import json
from contextlib import aclosing, asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from alembic import command
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from test_migrations import _alembic_config
from test_multi_user_identity_storage import _runtime

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.app import auth, stream_access
from qwenpaw.app.routers import frontend_plugin
from qwenpaw.app.routers.console import _admit_console_submission
from qwenpaw.app.task_tracker import TaskTracker
from qwenpaw.identity.models import PlatformRole
from qwenpaw.pawapp import deps
from qwenpaw.pawapp.console_stream import PawAppConsoleBinding
from qwenpaw.plugins.governance import (
    AppAudience,
    PluginGovernanceService,
    PluginInstallation,
    PostgresPluginGovernanceRepository,
)


@pytest.mark.asyncio
async def test_queued_kanban_turn_uses_live_device_and_plugin_grant(
    postgres_test_schema, monkeypatch
):
    await asyncio.to_thread(
        command.upgrade, _alembic_config(postgres_test_schema), "head"
    )
    schema = postgres_test_schema.name
    engine = create_async_engine(postgres_test_schema.async_url())
    factory = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def sessions():
        async with factory.begin() as db:
            yield db

    runtime = _runtime(schema, sessions)
    service = PluginGovernanceService(
        PostgresPluginGovernanceRepository(schema=schema, session_factory=sessions)
    )
    monkeypatch.setenv("QWENPAW_MULTI_USER_ENABLED", "true")
    for module in (auth, stream_access):
        monkeypatch.setattr(module, "get_identity_runtime", lambda: runtime)
    monkeypatch.setattr(deps, "_plugin_governance_service", lambda: service)
    monkeypatch.setattr(
        frontend_plugin, "get_plugin_governance_service", lambda: service
    )
    monkeypatch.setattr(deps, "_get_session", lambda _: None)

    app = FastAPI()
    app.add_middleware(stream_access.StreamAccessMiddleware)
    app.add_middleware(auth.AuthMiddleware)
    app.state.multi_agent_manager = SimpleNamespace(
        get_agent=AsyncMock(return_value=object())
    )
    contexts = {}
    finish = asyncio.Event()
    stopped = asyncio.Event()
    calls = []

    @app.post("/api/enqueue")
    async def enqueue(request: Request):
        request.state.app_id = "agent-kanban"
        request.state.authorized_agent_id = "office"
        ctx = await deps.get_ctx(request)
        contexts[ctx.user_id] = ctx
        return {"queued": True}

    @app.post("/api/console/chat")
    async def chat(request: Request):
        assert not request.headers.get("Authorization")
        assert request.headers["x-agent-id"] == "office"
        assert request.state.authorized_plugin[0] == "agent-kanban"
        user = request.state.actor.user_id
        payload = await request.json()
        assert payload["user_id"] == str(user)
        calls.append(user)

        async def body():
            try:
                yield 'data: {"object":"message","id":"first-progress"}\n\n'
                await finish.wait()
                yield 'data: {"object":"response","status":"completed"}\n\n'
            finally:
                stopped.set()

        return StreamingResponse(body(), media_type="text/event-stream")

    try:
        owner = await runtime.users.create_user(
            "owner", "owner-password", PlatformRole.ADMIN
        )
        admin = ActorContext(
            owner.id, ActorType.USER, PlatformRole.ADMIN, True, "setup"
        )
        members = [
            await runtime.users.create_user(
                name, f"{name}-password", PlatformRole.MEMBER
            )
            for name in ("alpha", "bravo")
        ]
        devices = [await runtime.sessions.issue(user, {}) for user in members]
        await service.register_installation(
            admin,
            PluginInstallation(uuid4(), "agent-kanban", "1", "app", "active"),
            source_type="path",
            source_ref="agent-kanban",
            content_hash="a" * 64,
            audience=AppAudience("all_members"),
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            for device in devices:
                response = await client.post(
                    "/api/enqueue",
                    headers={"Authorization": "Bearer " + device.access_token},
                )
                response.raise_for_status()

        first = await runtime.sessions.refresh(devices[0].refresh_token)
        assert (
            first
            and await runtime.sessions.authenticate_access(devices[0].access_token)
            is None
        )

        def run(index):
            return contexts[str(members[index].id)].chat_stream(
                "review", session_id="issue-1"
            )

        async with aclosing(run(0)) as events, asyncio.timeout(3):
            assert (await anext(events)).id == "first-progress"
            assert not finish.is_set()
        assert stopped.is_set()
        stopped.clear()
        async with aclosing(run(0)) as events, asyncio.timeout(3):
            assert (await anext(events)).id == "first-progress"
            await service.replace_audience(
                admin, "agent-kanban", AppAudience("selected_users", [members[1].id])
            )
            with pytest.raises(RuntimeError, match="without a final result"):
                await anext(events)
        assert stopped.is_set()
        with pytest.raises(RuntimeError, match="HTTP 404"):
            await anext(run(0))
        assert await runtime.sessions.revoke_current(first.refresh_token)
        with pytest.raises(RuntimeError, match="HTTP 401"):
            await anext(run(0))
        finish.set()
        assert [event.object async for event in run(1)] == ["message", "response"]
        assert calls == [members[0].id, members[0].id, members[1].id]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_consumer_backpressure_limits_internal_console_and_releases_producer():
    binding = PawAppConsoleBinding(uuid4(), uuid4(), "office", "agent-kanban")
    paused = asyncio.Event()
    closed = asyncio.Event()
    sent = []

    async def app(scope, receive, send):
        assert json.loads((await receive())["body"])["session_id"] == "issue-2"
        try:
            await send({"type": "http.response.start", "status": 200})
            for i in range(100):
                if i == 2:
                    paused.set()
                await send(
                    {
                        "type": "http.response.body",
                        "body": f'data: {{"object":"message","id":"{i}"}}\n\n'.encode(),
                    }
                )
                sent.append(i)
        finally:
            closed.set()

    async with aclosing(
        binding.events(app, "office", "review", "issue-2")
    ) as events, asyncio.timeout(3):
        assert (await anext(events)).id == "0"
        await paused.wait()
        assert sent == [0, 1]
    assert closed.is_set()


@pytest.mark.asyncio
async def test_stopping_kanban_cancels_only_the_console_run_it_started(monkeypatch):
    monkeypatch.setattr("qwenpaw.app.chats.turn_edit.capture_console_turn", AsyncMock())
    tracker = TaskTracker()
    bound_repo = SimpleNamespace(
        get_run=AsyncMock(return_value=SimpleNamespace(status="queued")),
        finish_run=AsyncMock(),
    )
    repository = SimpleNamespace(with_user=lambda user_id: bound_repo)
    workspace = SimpleNamespace(
        task_tracker=tracker,
        chat_manager=SimpleNamespace(conversation_repository=repository),
    )
    chat = SimpleNamespace(id=str(uuid4()))
    binding = PawAppConsoleBinding(uuid4(), uuid4(), "office", "agent-kanban")
    first_run = None
    model_stopped = asyncio.Event()

    async def model(_payload):
        try:
            yield 'data: {"object":"message","id":"started"}\n\n'
            await asyncio.Event().wait()
        finally:
            model_stopped.set()

    async def app(scope, receive, send):
        nonlocal first_run
        lifecycle = scope["qwenpaw.pawapp_run"]
        run_id = str(uuid4())
        queue = await _admit_console_submission(
            workspace=workspace,
            chat=chat,
            payload={"_qwenpaw_run_id": run_id},
            stream_source=model,
            access_scope="member",
            config=None,
            pawapp_run=lifecycle,
        )
        if first_run is None:
            first_run = lifecycle
        await send({"type": "http.response.start", "status": 200})
        async with aclosing(tracker.stream_from_queue(queue, chat.id)) as stream:
            async for event in stream:
                await send({"type": "http.response.body", "body": event.encode()})

    async with asyncio.timeout(3):
        async with aclosing(
            binding.events(app, "office", "run", "issue-3")
        ) as original:
            assert (await anext(original)).id == "started"
            async with aclosing(
                binding.events(app, "office", "run", "issue-3")
            ) as attached:
                assert (await anext(attached)).id == "started"
            assert not model_stopped.is_set()
        assert model_stopped.is_set() and await tracker.get_status(chat.id) == "idle"
        bound_repo.finish_run.assert_awaited_once()
        model_stopped.clear()
        async with aclosing(binding.events(app, "office", "run", "issue-3")) as later:
            assert (await anext(later)).id == "started"
            await first_run.stop()
            assert (
                not model_stopped.is_set()
                and await tracker.get_status(chat.id) == "running"
            )
        assert model_stopped.is_set()
