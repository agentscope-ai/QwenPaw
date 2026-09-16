# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access
"""Main Agent task tools never inherit identity or routing from model input."""

import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from agentscope.tool import FunctionTool
from starlette.requests import Request

from qwenpaw.app.channels.console.channel import ConsoleChannel
from qwenpaw.pawapp.tasks.agent_tools import (
    TaskToolContext,
    bind_task_tools,
    make_task_tools,
)
from qwenpaw.pawapp.tasks import ExecutorEvent, ExecutorRunRef
from qwenpaw.pawapp.tasks.binding import Readiness
from qwenpaw.runtime.builder import AgentBuilder
from qwenpaw.schemas import AgentRequest
from tests.unit.pawapp.test_task_runtime import (
    host as host_fixture,
    settled,
    SCOPE,
    ACTION,
    BODY,
)

host = host_fixture


def context(host):
    return TaskToolContext(
        host.app.state.pawapp_tasks,
        host.app.state.pawapp_task_origins,
        "alice",
        "sales",
        "main",
        "main-session",
    )


def tools(host):
    return {
        tool.__name__: FunctionTool(tool)
        for tool in make_task_tools(context(host))
    }


def payload(chunk):
    return json.loads(chunk.content[0].text)


@pytest.mark.asyncio
async def test_discover_describe_delegate_and_read(host):
    bound = tools(host)
    listing = payload(await bound["list_apps"]())
    assert len(listing["actions"]) == 1
    assert "input_schema" not in listing["actions"][0]
    description = payload(
        await bound["describe_action"](
            app_id=SCOPE.app_id,
            action_id="analyze",
        ),
    )
    assert description["action"]["input_schema"]["required"] == [
        "text",
        "datasource_id",
    ]
    schema = bound["delegate"].input_schema
    assert set(schema["properties"]) == {
        "app_id",
        "action_id",
        "inputs",
        "request_id",
    }
    args = {
        "app_id": SCOPE.app_id,
        "action_id": "analyze",
        "inputs": BODY["inputs"],
        "request_id": "intent-1",
    }
    results = await asyncio.gather(
        *(bound["delegate"](**args) for _ in range(3)),
    )
    task_ids = {payload(result)["task"]["task_id"] for result in results}
    assert len(task_ids) == 1
    task_id = task_ids.pop()
    await settled(host, task_id)
    read = payload(
        await bound["get_app_task"](app_id=SCOPE.app_id, task_id=task_id),
    )
    assert read["task"]["text_result"] == "42"
    assert read["task"]["origin"]["return_session_ref"] == "main-session"
    assert read["task"]["scope"] == SCOPE.model_dump()
    opened = payload(
        await bound["open_app"](app_id=SCOPE.app_id, task_id=task_id),
    )
    assert opened["kind"] == "pawapp_open_app"
    assert opened["action"]["path"].startswith("/apps/qwenpaw-data?handoff=")
    assert len(host.runs) == 1


@pytest.mark.asyncio
async def test_answer_tool_uses_typed_pending_request_and_durable_identity(
    host,
):
    bound = tools(host)
    # Initialize the runtime binding, then construct a deterministic waiting
    # task without involving a provider model.
    await bound["list_apps"]()
    origin = await host.app.state.pawapp_task_origins.resolve(
        SCOPE,
        "delegated",
        "main",
    )
    task = await host.store.create(
        SCOPE,
        ACTION,
        request_id="waiting-tool",
        inputs=BODY["inputs"],
        origin=origin,
    )
    await host.store.begin_submission(SCOPE, task.handle.task_id)
    ref = ExecutorRunRef(
        executor_id="engine",
        session_id="session-waiting",
        run_id="run-waiting",
    )
    host.runs[task.handle.submission_id] = ref
    await host.store.record_accepted(SCOPE, task.handle.task_id, ref)
    await host.store.apply_event(
        SCOPE,
        task.handle.task_id,
        ExecutorEvent(
            run_ref=ref,
            sequence=0,
            cursor="0",
            status="waiting_for_input",
            detail={
                "input_request": {
                    "request_id": "question-1",
                    "questions": [
                        {
                            "question": "Which period?",
                            "options": [{"label": "Q1"}, {"label": "Q2"}],
                        },
                    ],
                },
            },
        ),
    )
    host.adapters[0].release.clear()
    args = {
        "app_id": SCOPE.app_id,
        "task_id": task.handle.task_id,
        "request_id": "question-1",
        "command_id": "answer-question-1",
        "answers": [
            {"question": "Which period?", "selected_options": ["Q1"]},
        ],
    }
    first = payload(await bound["answer_task"](**args))
    retry = payload(await bound["answer_task"](**args))
    assert first["command"]["state"] == "accepted"
    assert retry["command"] == first["command"]
    assert (
        host.adapters[0].command_calls.count(
            (task.handle.task_id, "answer-question-1"),
        )
        == 1
    )


@pytest.mark.asyncio
async def test_invalid_inputs_revoked_grant_and_blocked_setup(host):
    bound = tools(host)
    args = {
        "app_id": SCOPE.app_id,
        "action_id": "analyze",
        "request_id": "one",
        "inputs": {"text": "missing source"},
    }
    invalid = payload(await bound["delegate"](**args))
    assert invalid == {"state": "error", "reason": "invalid_task_request"}
    args["inputs"] = BODY["inputs"]
    host.adapters[0].ready = Readiness(
        state="blocked",
        reason="analysis_model_missing",
    )
    blocked = payload(await bound["delegate"](**args))
    assert blocked["state"] == "blocked"
    assert "task" not in blocked
    assert not host.runs
    host.policy_path.unlink()
    assert payload(await bound["list_apps"]())["actions"] == []
    assert (
        payload(await bound["delegate"](**args))["reason"]
        == "action_forbidden"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("app_id", ["", "x" * 257])
async def test_invalid_app_identity_returns_structured_error(host, app_id):
    result = await tools(host)["delegate"](
        app_id=app_id,
        action_id="analyze",
        inputs=BODY["inputs"],
        request_id="invalid-app",
    )
    assert payload(result) == {
        "state": "error",
        "reason": "invalid_task_request",
    }
    assert not host.runs


@pytest.mark.asyncio
async def test_task_identity_and_reads_are_bound_to_the_originating_chat(host):
    host.chats["second"] = host.chats["main"].model_copy(
        update={"id": "second", "session_id": "second-session"},
    )
    second = {
        fn.__name__: FunctionTool(fn)
        for fn in make_task_tools(
            TaskToolContext(
                host.app.state.pawapp_tasks,
                host.app.state.pawapp_task_origins,
                "alice",
                "sales",
                "second",
                "second-session",
            ),
        )
    }
    args = {
        "app_id": SCOPE.app_id,
        "action_id": "analyze",
        "inputs": BODY["inputs"],
        "request_id": "same-key",
    }
    first_result = payload(await tools(host)["delegate"](**args))
    second_result = payload(await second["delegate"](**args))
    first_id = first_result["task"]["task_id"]
    assert first_id != second_result["task"]["task_id"]
    assert payload(
        await second["get_app_task"](
            app_id=SCOPE.app_id,
            task_id=first_id,
        ),
    ) == {"state": "error", "reason": "task_not_found"}
    assert payload(
        await second["open_app"](
            app_id=SCOPE.app_id,
            task_id=first_id,
        ),
    ) == {"state": "error", "reason": "task_not_found"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"archived_at": datetime(2026, 9, 16, tzinfo=timezone.utc)},
        {"source": "subagent"},
        {"channel": "discord"},
        {"user_id": "bob"},
        {"meta": {"pawapp": {}}},
        {"session_id": "pawapp:qwenpaw-data:one"},
    ],
)
async def test_only_owned_active_main_chats_receive_task_tools(host, changes):
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/console/chat",
            "headers": [],
            "query_string": b"",
            "app": host.app,
        },
    )
    request.state.user = "alice"
    native = {
        "sender_id": "alice",
        "channel_id": "console",
        "_pawapp_task_context": context(host),
    }
    await bind_task_tools(
        request,
        SimpleNamespace(agent_id="sales"),
        host.chats["main"].model_copy(update=changes),
        native,
    )
    assert "_pawapp_task_context" not in native


@pytest.mark.asyncio
async def test_ingress_authority_survives_channel_but_not_json(host, tmp_path):
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/console/chat",
            "headers": [],
            "query_string": b"",
            "app": host.app,
        },
    )
    request.state.user = "alice"
    native = {
        "sender_id": "alice",
        "channel_id": "console",
        "content_parts": [],
        "meta": {
            "session_id": "main-session",
            "request_context": {
                "user_id": "bob",
                "agent_id": "other",
                "chat_id": "bob",
                "_pawapp_task_context": {"principal_id": "bob"},
            },
        },
    }
    await bind_task_tools(
        request,
        SimpleNamespace(agent_id="sales"),
        host.chats["main"],
        native,
    )
    channel = ConsoleChannel(
        process=MagicMock(),
        enabled=True,
        bot_prefix="",
        media_dir=str(tmp_path),
    )
    agent_request = channel.build_agent_request_from_native(native)
    authority = agent_request._pawapp_task_context
    assert (
        authority.principal_id == "alice" and authority.workspace_id == "sales"
    )
    assert "_pawapp_task_context" not in agent_request.model_dump()
    assert (
        AgentRequest.model_validate_json(
            agent_request.model_dump_json(),
        )._pawapp_task_context
        is None
    )
    assert (
        AgentRequest.model_validate(
            {"_pawapp_task_context": {"principal_id": "alice"}},
        )._pawapp_task_context
        is None
    )
    forged = {**native, "sender_id": "bob"}
    await bind_task_tools(
        request,
        SimpleNamespace(agent_id="sales"),
        host.chats["bob"],
        forged,
    )
    assert "_pawapp_task_context" not in forged


@pytest.mark.asyncio
async def test_builder_uses_private_context_not_payload_claims(
    host,
    monkeypatch,
):
    request = AgentRequest(session_id="main-session", user_id="alice")
    ctx = SimpleNamespace(
        request=request,
        agent_id="sales",
        session_id="main-session",
    )
    builder = AgentBuilder()
    assert not builder._pawapp_task_tools(
        ctx,
        {"_pawapp_task_context": context(host)},
        None,
    )
    request._pawapp_task_context = context(host)
    wraps = []

    def wrap(fn, agent_id, request_context, governor):
        del governor
        wraps.append((agent_id, request_context))
        return FunctionTool(fn)

    monkeypatch.setattr(builder, "_wrap_tool", wrap)
    result = builder._pawapp_task_tools(
        ctx,
        {"user_id": "bob", "agent_id": "other"},
        None,
    )
    assert {item.name for item in result} == {
        "list_apps",
        "describe_action",
        "delegate",
        "get_app_task",
        "open_app",
        "answer_task",
        "cancel_task",
    }
    assert all(
        agent == "sales" and rc["user_id"] == "alice" for agent, rc in wraps
    )
    assert not builder._pawapp_task_tools(ctx, {"_spawn_subagent": True}, None)
    ctx.session_id = "other"
    assert not builder._pawapp_task_tools(ctx, {}, None)
