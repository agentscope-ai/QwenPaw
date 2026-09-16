"""Runtime status and structured input must remain private on shared Agents."""

import asyncio
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.identity.models import PlatformRole
from qwenpaw.runtime_status import broadcast as status
from qwenpaw.user_input import broadcast as inputs
from qwenpaw.user_input.schemas import UserInputAnswer, UserInputQuestion
from qwenpaw.user_input.service import UserInputService


def test_runtime_status_private_queue_and_cache(monkeypatch):
    monkeypatch.setenv("QWENPAW_MULTI_USER_ENABLED", "true")
    alice, bob = str(uuid4()), str(uuid4())
    a = status.register_sse_client("shared", user_id=alice)
    b = status.register_sse_client("shared", user_id=bob)
    try:
        status.broadcast_runtime_status(
            "shared", session_id="same-session", stage="tool", user_id=alice
        )
        assert a.get_nowait()["session_id"] == "same-session"
        assert b.empty()
        assert status.get_runtime_status("shared", "same-session", user_id=bob) is None
        assert status.get_runtime_status("shared", "same-session", user_id=alice)
        status.broadcast_runtime_status("shared", session_id="unbound", stage="tool")
        assert a.empty() and b.empty()
    finally:
        status.unregister_sse_client("shared", a, user_id=alice)
        status.unregister_sse_client("shared", b, user_id=bob)


def test_user_input_private_read_and_answer(monkeypatch):
    monkeypatch.setenv("QWENPAW_MULTI_USER_ENABLED", "true")
    alice, bob = str(uuid4()), str(uuid4())

    async def scenario():
        service = UserInputService()
        a = inputs.register_sse_client("shared", user_id=alice)
        b = inputs.register_sse_client("shared", user_id=bob)
        try:
            pending = await service.create_pending(
                session_id="s",
                root_session_id="s",
                user_id="untrusted",
                recipient_user_id=alice,
                channel="console",
                agent_id="shared",
                title=None,
                questions=[UserInputQuestion(id="q", question="private")],
            )
            assert a.get_nowait()["request"]["user_id"] == alice
            assert b.empty()
            assert (
                await service.get_pending(
                    agent_id="shared", session_id="s", user_id=bob
                )
                is None
            )
            assert (
                await service.answer_request(
                    pending.request_id,
                    UserInputAnswer(),
                    agent_id="shared",
                    user_id=bob,
                )
                is None
            )
            assert (
                await service.answer_request(
                    pending.request_id,
                    UserInputAnswer(),
                    agent_id="other",
                    user_id=alice,
                )
                is None
            )
            assert (
                await service.answer_request(pending.request_id, UserInputAnswer())
                is None
            )
            assert (
                await service.cancel_all_pending_by_root_session(
                    "s", agent_id="shared", user_id=bob
                )
                == 0
            )
            assert (
                await service.cancel_all_pending_by_root_session(
                    "s", agent_id="other", user_id=alice
                )
                == 0
            )
            assert await service.answer_request(
                pending.request_id, UserInputAnswer(), agent_id="shared", user_id=alice
            )
        finally:
            inputs.unregister_sse_client("shared", a, user_id=alice)
            inputs.unregister_sse_client("shared", b, user_id=bob)

    asyncio.run(scenario())


def test_unbound_user_input_fails_closed(monkeypatch):
    monkeypatch.setenv("QWENPAW_MULTI_USER_ENABLED", "true")

    async def scenario():
        with pytest.raises(ValueError, match="identity"):
            await UserInputService().create_pending(
                session_id="s",
                root_session_id="s",
                user_id=str(uuid4()),
                channel="console",
                agent_id="shared",
                title=None,
                questions=[UserInputQuestion(id="q", question="private")],
            )

    asyncio.run(scenario())


def test_routes_enforce_current_user_and_agent(monkeypatch):
    from qwenpaw.app.routers import user_input as routes
    from qwenpaw.app.routers import runtime_status as runtime_routes
    from qwenpaw.user_input import service as service_module

    monkeypatch.setenv("QWENPAW_MULTI_USER_ENABLED", "true")
    alice, bob = uuid4(), uuid4()
    service = UserInputService()
    monkeypatch.setattr(service_module, "_service", service)

    async def workspace(request):
        return SimpleNamespace(agent_id=request.headers.get("x-agent-id", "shared"))

    monkeypatch.setattr(routes, "_get_workspace", workspace)
    monkeypatch.setattr(runtime_routes, "_get_workspace", workspace)

    def request(user, agent="shared"):
        result = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/",
                "headers": [(b"x-agent-id", agent.encode())],
            }
        )
        result.state.actor = ActorContext(
            user_id=user,
            actor_type=ActorType.USER,
            platform_role=PlatformRole.ADMIN,
            admin_mode=True,
            request_id="test",
        )
        return result

    async def scenario():
        pending = await service.create_pending(
            session_id="s",
            root_session_id="s",
            user_id="fake",
            recipient_user_id=str(alice),
            channel="console",
            agent_id="shared",
            title=None,
            questions=[UserInputQuestion(id="q", question="private")],
        )
        assert await routes.get_pending_user_input(request(bob), "s") is None
        assert await routes.get_pending_user_input(request(alice), "s")
        for forbidden in (request(bob), request(alice, "other")):
            with pytest.raises(HTTPException) as exc:
                await routes.answer_user_input(
                    forbidden, pending.request_id, UserInputAnswer()
                )
            assert exc.value.status_code == 404
        status.broadcast_runtime_status(
            "shared", session_id="s", stage="tool", user_id=str(alice)
        )
        assert (
            await runtime_routes.get_current_runtime_status(request(bob), "s") is None
        )
        assert await runtime_routes.get_current_runtime_status(request(alice), "s")
        assert (
            await routes.answer_user_input(
                request(alice), pending.request_id, UserInputAnswer()
            )
        ).status == "answered"
        with pytest.raises(HTTPException) as exc:
            await routes.get_pending_user_input(request(None), "s")
        assert exc.value.status_code == 403

    asyncio.run(scenario())


def test_execution_scope_ignores_client_user_id():
    from qwenpaw.runtime_status.scope import execution_user_id

    alice, bob = str(uuid4()), str(uuid4())
    assert execution_user_id({"user_id": bob, "approval_user_id": bob}) is None
    assert (
        execution_user_id({"user_id": bob, "actor_context": {"user_id": alice}})
        == alice
    )


def test_sse_routes_bind_authenticated_user(monkeypatch):
    from qwenpaw.app.routers import user_input as input_routes
    from qwenpaw.app.routers import runtime_status as status_routes

    monkeypatch.setenv("QWENPAW_MULTI_USER_ENABLED", "true")
    alice, bob = str(uuid4()), str(uuid4())

    async def workspace(request):
        return SimpleNamespace(agent_id="sse-agent")

    async def connected():
        return False

    monkeypatch.setattr(input_routes, "_get_workspace", workspace)
    monkeypatch.setattr(status_routes, "_get_workspace", workspace)
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    request.state.actor = ActorContext(
        user_id=UUID(alice),
        actor_type=ActorType.USER,
        platform_role=PlatformRole.MEMBER,
        admin_mode=False,
        request_id="test",
    )
    request.is_disconnected = connected

    async def scenario():
        for route, publish in (
            (
                status_routes.runtime_status_stream,
                lambda user: status.broadcast_runtime_status(
                    "sse-agent", session_id=user, stage="tool", user_id=user
                ),
            ),
            (
                input_routes.user_input_stream,
                lambda user: inputs.broadcast_user_input_update(
                    "sse-agent", {"session_id": user}, user_id=user
                ),
            ),
        ):
            response = await route(request)
            stream = response.body_iterator
            assert "connected" in await anext(stream)
            publish(bob)
            publish(alice)
            event = await asyncio.wait_for(anext(stream), 1)
            assert alice in event and bob not in event
            await stream.aclose()

    asyncio.run(scenario())


def test_tool_setup_and_subagent_preserve_trusted_actor(monkeypatch, tmp_path):
    from qwenpaw.config.context import get_current_request_context
    from qwenpaw.hooks.request_setup.contextvars_hook import ContextVarsSetupHook
    from qwenpaw.agents.tools.agent_management import _build_spawn_request_context
    from qwenpaw.runtime_status.scope import execution_user_id

    user = str(uuid4())
    ctx = SimpleNamespace(
        agent_id="shared",
        session_id="s",
        root_session_id="s",
        workspace_dir=tmp_path,
        mode_state={},
        request=SimpleNamespace(
            user_id=user,
            channel="console",
            request_context={"actor_context": {"user_id": user, "actor_type": "user"}},
        ),
    )

    async def scenario():
        await ContextVarsSetupHook().run(ctx)
        assert execution_user_id(get_current_request_context()) == user
        assert execution_user_id(_build_spawn_request_context("shared")) == user

    asyncio.run(scenario())
def test_terminal_tool_stage_cannot_remain_cached_as_running(monkeypatch):
    monkeypatch.setattr(
        "qwenpaw.runtime_status.scope.is_multi_user_enabled", lambda: False
    )

    status.broadcast_runtime_status(
        "default",
        session_id="completed-tool",
        stage="tool_completed",
        status="running",
    )

    assert status.get_runtime_status("default", "completed-tool") is None
