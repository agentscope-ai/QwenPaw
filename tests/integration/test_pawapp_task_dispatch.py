# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access
"""Authenticated Host HTTP → independent Engine process → Host task result."""

import json
import asyncio
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace, ModuleType
from unittest.mock import AsyncMock

import pytest
from fastapi import Request

from qwenpaw.app.channels.console.channel import ConsoleChannel
from qwenpaw.app.chats.session import SafeJSONSession
from qwenpaw.app.routers import console
from qwenpaw.app.task_tracker import TaskTracker
from qwenpaw.pawapp.tasks.binding import ActionRegistration
from qwenpaw.pawapp.tasks.continuation import ContinuationWorker
from qwenpaw.runtime.builder import AgentBuilder
from qwenpaw.runtime.runtime import Runtime
from qwenpaw.schemas import AgentResponse, RunStatus
from tests.integration.test_pawapp_data_tasks import (
    engine as engine_fixture,
    TOKEN,
    BRIDGE,
)
from tests.unit.pawapp.test_task_runtime import (
    host as host_fixture,
    settled,
    ACTION,
    BODY,
    PREFIX,
    SCOPE,
)

engine = engine_fixture
host = host_fixture


@pytest.mark.asyncio
@pytest.mark.parametrize("intent", ["finish", "clarify", "pause"])
async def test_native_console_uses_durable_existing_session(
    host, engine, intent
):
    package = ModuleType("native_data_under_test")
    package.__path__ = [
        str(
            Path(__file__).resolve().parents[2]
            / "plugins/apps/qwenpaw-data/backend"
        )
    ]
    sys.modules[package.__name__] = package
    direct = importlib.import_module(package.__name__ + ".direct_tasks")
    gateway_type = importlib.import_module(
        package.__name__ + ".engine_gateway"
    ).EngineGateway
    gateway = gateway_type(
        SimpleNamespace(is_external=False, base_url=engine.base), TOKEN
    )
    action = BRIDGE.data_session_action_descriptor()
    host.registrations[(action.app_id, action.action_id)] = ActionRegistration(
        action=action,
        factory=lambda: BRIDGE.DataTaskAdapter(
            engine.endpoint, executor_id="qwenpaw-data.engine"
        ),
        settings_entry="/apps/qwenpaw-data",
    )
    await host.app.state.pawapp_tasks.set_action_grant(
        SCOPE,
        action.action_id,
        enabled=True,
        input_values={},
        expected_revision=0,
    )
    workspace = await host.app.state.pawapp_task_origins.manager.get_agent(
        "sales"
    )

    async def create_chat(chat):
        host.chats[chat.id] = chat
        return chat

    workspace.chat_manager.create_chat = create_chat

    @host.app.post("/api/native-console")
    async def dispatch(request: Request):
        return await direct.dispatch_console_chat(request, gateway)

    @host.app.post("/api/native-command/{session_id}/{run_id}/{kind}")
    async def command(
        request: Request, session_id: str, run_id: str, kind: str
    ):
        return await direct.command_console_chat(
            request, gateway, session_id, run_id, kind
        )

    await gateway.start()
    try:
        session = await gateway.json(
            "POST",
            "/api/v1/sessions",
            body={"title": "March GAAP"},
            user_id=BRIDGE.DataTaskAdapter.identity_namespace(SCOPE),
        )
        session_id = session["session"]["id"]
        body = {
            "session_id": session_id,
            "datasource_id": "sales",
            "text": intent,
        }
        headers = {"X-Agent-Id": "sales", "X-Request-Id": "native-first"}
        legacy = await gateway.json(
            "POST", "/api/v1/sessions", body={"title": "Legacy"}
        )
        denied = await host.client.post(
            "/api/native-console",
            json={**body, "session_id": legacy["session"]["id"]},
            headers={**headers, "X-Request-Id": "legacy"},
        )
        assert denied.status_code == 409
        assert "start a new session" in denied.text
        assert engine.count_runs() == 0
        first = await host.client.post(
            "/api/native-console", json=body, headers=headers
        )
        assert first.status_code == 200, first.text
        assert first.json()["chat"]["session_id"] == session_id
        task_id = first.json()["task_id"]
        expected = "succeeded"
        if intent != "finish":
            async with asyncio.timeout(5):
                while True:
                    pending = await host.store.get(SCOPE, task_id)
                    if (
                        intent == "clarify"
                        and pending.handle.status == "waiting_for_input"
                    ) or (intent == "pause" and pending.handle.text_result):
                        break
                    await asyncio.sleep(0.01)
            kind = "answer" if intent == "clarify" else "cancel"
            command_body = {
                "clarification_id": "clarification-1",
                "result": {
                    "status": "answered",
                    "answers": [
                        {
                            "question": "Which period?",
                            "selected_options": ["Q1"],
                        }
                    ],
                },
            }
            response = await host.client.post(
                f"/api/native-command/{session_id}/{first.json()['chat']['id']}/{kind}",
                json=command_body,
                headers=headers,
            )
            assert response.status_code == 200, response.text
            expected = "succeeded" if intent == "clarify" else "cancelled"
        async with asyncio.timeout(5):
            while True:
                task = await host.store.get(SCOPE, task_id)
                if task.handle.status == expected:
                    break
                await asyncio.sleep(0.01)
        assert task.handle.origin.engagement == "direct"
        assert task.handle.origin.return_session_ref is None
        again = await host.client.post(
            "/api/native-console", json=body, headers=headers
        )
        assert again.json()["task_id"] == task.handle.task_id
        assert engine.count_runs() == 1
        changed = await host.client.post(
            "/api/native-console",
            json={**body, "text": "changed"},
            headers=headers,
        )
        assert changed.status_code == 409
        invalid = await host.client.post(
            "/api/native-console", content="{", headers=headers
        )
        assert invalid.status_code == 422
    finally:
        await gateway.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "engagement,chat_id",
    [("direct", "direct"), ("delegated", "main")],
)
async def test_host_dispatch_to_engine_process(
    host,
    engine,
    engagement,
    chat_id,
):
    host.registrations[(ACTION.app_id, ACTION.action_id)] = ActionRegistration(
        action=ACTION,
        factory=lambda: BRIDGE.DataTaskAdapter(
            lambda: (engine.base, TOKEN),
            executor_id="integration-engine",
        ),
        settings_entry="/apps/qwenpaw-data",
    )
    body = {**BODY, "engagement": engagement, "chat_id": chat_id}
    response = await host.client.post(
        PREFIX + "/actions/analyze/tasks",
        json=body,
    )
    assert response.status_code == 202, response.text
    task_id = response.json()["task"]["task_id"]
    result = await settled(host, task_id)
    assert result.handle.text_result == "Revenue is 42."
    again = await host.client.post(
        PREFIX + "/actions/analyze/tasks",
        json=body,
    )
    assert again.json()["task"]["task_id"] == task_id


@pytest.mark.asyncio
async def test_console_tool_to_engine_and_card_status_api(
    host,
    engine,
    tmp_path,
    monkeypatch,
):
    """Real Console ingress and Engine with a controlled tool caller."""
    host.registrations[(ACTION.app_id, ACTION.action_id)] = ActionRegistration(
        action=ACTION,
        factory=lambda: BRIDGE.DataTaskAdapter(
            lambda: (engine.base, TOKEN),
            executor_id="integration-engine",
        ),
        settings_entry="/apps/qwenpaw-data",
    )
    workspace = SimpleNamespace(
        agent_id="sales",
        workspace_dir=tmp_path,
        task_tracker=TaskTracker(),
        chat_manager=SimpleNamespace(
            get_or_create_chat=AsyncMock(return_value=host.chats["main"]),
            mark_chat_finished=AsyncMock(),
        ),
    )
    results = []

    async def controlled_agent(request):
        runtime = Runtime(workspace=workspace, app_services=None)
        ctx = runtime._build_context(runtime._normalize(request))
        bound = AgentBuilder()._pawapp_task_tools(
            ctx,
            request.request_context,
            None,
        )
        delegate = {tool.name: tool for tool in bound}["delegate"]
        chunk = await delegate(
            app_id="qwenpaw-data",
            action_id="analyze",
            inputs=BODY["inputs"],
            request_id="main-intent",
        )
        results.append(json.loads(chunk.content[0].text))
        yield AgentResponse(
            object="response",
            status=RunStatus.Completed,
            output=[],
        )

    channel = ConsoleChannel(
        process=controlled_agent,
        enabled=True,
        bot_prefix="",
        media_dir=str(tmp_path),
    )
    workspace.channel_manager = SimpleNamespace(
        get_channel=AsyncMock(return_value=channel),
    )
    monkeypatch.setattr(
        console,
        "get_agent_for_request",
        AsyncMock(return_value=workspace),
    )
    monkeypatch.setattr(console, "generate_and_update_title", AsyncMock())
    host.app.include_router(console.router, prefix="/api")
    response = await host.client.post(
        "/api/console/chat",
        headers={"X-Agent-Id": "sales"},
        json={
            "session_id": "main-session",
            "user_id": "alice",
            "channel": "console",
            "input": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": "Analyze revenue"}],
                },
            ],
            "request_context": {"user_id": "bob", "agent_id": "other"},
        },
    )
    assert response.status_code == 200
    assert len(results) == 1, response.text
    result = results[0]
    assert result["state"] == "accepted"
    assert result["task"]["scope"]["principal_id"] == "alice"
    assert result["task"]["scope"]["workspace_id"] == "sales"
    assert result["task"]["origin"]["return_session_ref"] == "main-session"
    task_id = result["task"]["task_id"]
    await settled(host, task_id)
    card = await host.client.get(PREFIX + f"/tasks/{task_id}")
    assert card.status_code == 200
    assert card.json()["task"]["text_result"] == "Revenue is 42."
    # Exercise delivery after the initiating chat turn has finished. Only
    # text generation is controlled; queue, session, tracker and receipts run.
    origins = host.app.state.pawapp_task_origins
    workspace.session = SafeJSONSession(str(tmp_path / "sessions"))
    workspace.config = SimpleNamespace(backend="qwenpaw", language="en")
    workspace.chat_manager.get_chat = AsyncMock(side_effect=host.chats.get)
    origins.manager.get_agent.return_value = workspace
    summarizer = AsyncMock(
        return_value="The Data task completed: revenue is 42.",
    )
    worker = ContinuationWorker(
        host.app.state.pawapp_tasks,
        origins,
        summarizer=summarizer,
    )
    claim = await worker.queue.claim()
    assert claim.task_id == task_id
    await worker.deliver(claim)
    saved = await workspace.session.get_session_state_dict(
        "main-session",
        "alice",
        "console",
    )
    assert saved["agent"]["state"]["context"][0]["content"][0]["text"] == (
        "The Data task completed: revenue is 42."
    )
    assert await worker.queue.claim() is None
    await worker.aclose()
