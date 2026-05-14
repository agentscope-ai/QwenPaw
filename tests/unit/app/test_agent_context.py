# -*- coding: utf-8 -*-
"""Tests for request-scoped agent context handling."""
from types import SimpleNamespace

from starlette.requests import Request
from starlette.responses import Response

import pytest

from qwenpaw.app import agent_context
from qwenpaw.app.routers.agent_scoped import AgentContextMiddleware
from qwenpaw.app.runner import runner as runner_module
from qwenpaw.app.runner.runner import AgentRunner


def test_agent_context_reset_restores_previous_agent(monkeypatch):
    monkeypatch.setattr(agent_context, "get_active_agent_id", lambda: "active")

    outer_token = agent_context.set_current_agent_id("default")
    try:
        inner_token = agent_context.set_current_agent_id("worker")
        assert agent_context.get_current_agent_id() == "worker"

        agent_context.reset_current_agent_id(inner_token)
        assert agent_context.get_current_agent_id() == "default"
    finally:
        agent_context.reset_current_agent_id(outer_token)

    assert agent_context.get_current_agent_id() == "active"


def test_session_context_reset_restores_previous_values():
    outer_session = agent_context.set_current_session_id("session-a")
    outer_root = agent_context.set_current_root_session_id("root-a")
    try:
        inner_session = agent_context.set_current_session_id("session-b")
        inner_root = agent_context.set_current_root_session_id("root-b")

        assert agent_context.get_current_session_id() == "session-b"
        assert agent_context.get_current_root_session_id() == "root-b"

        agent_context.reset_current_root_session_id(inner_root)
        agent_context.reset_current_session_id(inner_session)

        assert agent_context.get_current_session_id() == "session-a"
        assert agent_context.get_current_root_session_id() == "root-a"
    finally:
        agent_context.reset_current_root_session_id(outer_root)
        agent_context.reset_current_session_id(outer_session)


@pytest.mark.asyncio
async def test_agent_context_middleware_resets_after_request(monkeypatch):
    monkeypatch.setattr(agent_context, "get_active_agent_id", lambda: "active")
    middleware = AgentContextMiddleware(
        app=lambda _scope, _receive, _send: None,
    )
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/agents/worker/chats",
        "headers": [(b"x-root-session-id", b"root-b")],
        "query_string": b"",
        "scheme": "http",
        "server": ("testserver", 80),
        "client": ("testclient", 50000),
    }
    request = Request(scope)

    outer_agent = agent_context.set_current_agent_id("default")
    outer_root = agent_context.set_current_root_session_id("root-a")
    observed = {}

    async def call_next(inner_request):
        observed["agent_id"] = agent_context.get_current_agent_id()
        observed[
            "root_session_id"
        ] = agent_context.get_current_root_session_id()
        observed["state_agent_id"] = inner_request.state.agent_id
        observed["request_root_session_id"] = inner_request.request_context[
            "root_session_id"
        ]
        return Response("ok")

    try:
        response = await middleware.dispatch(request, call_next)

        assert response.status_code == 200
        assert observed == {
            "agent_id": "worker",
            "root_session_id": "root-b",
            "state_agent_id": "worker",
            "request_root_session_id": "root-b",
        }
        assert agent_context.get_current_agent_id() == "default"
        assert agent_context.get_current_root_session_id() == "root-a"
    finally:
        agent_context.reset_current_root_session_id(outer_root)
        agent_context.reset_current_agent_id(outer_agent)

    assert agent_context.get_current_agent_id() == "active"
    assert agent_context.get_current_root_session_id() is None


@pytest.mark.asyncio
async def test_runner_sets_agent_context_for_command_path(monkeypatch):
    monkeypatch.setattr(agent_context, "get_active_agent_id", lambda: "active")
    monkeypatch.setattr(runner_module, "_is_command", lambda _query: True)

    observed = {}

    async def fake_run_command_path(_request, _msgs, _runner):
        observed["agent_id"] = agent_context.get_current_agent_id()
        observed["session_id"] = agent_context.get_current_session_id()
        observed[
            "root_session_id"
        ] = agent_context.get_current_root_session_id()
        yield object(), True

    monkeypatch.setattr(
        runner_module,
        "run_command_path",
        fake_run_command_path,
    )

    request = SimpleNamespace(
        session_id="session-b",
        user_id="user-b",
        channel="console",
    )
    outer_agent = agent_context.set_current_agent_id("default")
    outer_session = agent_context.set_current_session_id("session-a")
    outer_root = agent_context.set_current_root_session_id("root-a")
    try:
        results = []
        async for item in AgentRunner(agent_id="worker").query_handler(
            [{"content": "/clear"}],
            request=request,
        ):
            results.append(item)

        assert len(results) == 1
        assert results[0][1] is True
        assert observed == {
            "agent_id": "worker",
            "session_id": "session-b",
            "root_session_id": "session-b",
        }
        assert agent_context.get_current_agent_id() == "default"
        assert agent_context.get_current_session_id() == "session-a"
        assert agent_context.get_current_root_session_id() == "root-a"
    finally:
        agent_context.reset_current_root_session_id(outer_root)
        agent_context.reset_current_session_id(outer_session)
        agent_context.reset_current_agent_id(outer_agent)

    assert agent_context.get_current_agent_id() == "active"
    assert agent_context.get_current_session_id() is None
    assert agent_context.get_current_root_session_id() is None
