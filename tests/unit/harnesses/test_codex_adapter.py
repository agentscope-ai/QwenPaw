# -*- coding: utf-8 -*-
"""Tests for the Codex third-party agent adapter."""

# pylint: disable=protected-access

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from qwenpaw.harnesses.codex.adapter import CodexAdapter
from qwenpaw.harnesses.events import HarnessEventKind
from qwenpaw.security.tool_guard.approval import ApprovalDecision
from qwenpaw.utils.io_utils import write_json_atomic


class FakeCodexClient:
    """Small app-server double that preserves request ordering."""

    installed = True
    account_type = "chatgpt"

    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.queue: asyncio.Queue[dict[str, Any]] | None = None
        self.stopped = False
        self.server_request_handler = None

    def set_server_request_handler(self, handler) -> None:
        """Store the app-server request callback."""
        self.server_request_handler = handler

    async def start(self) -> None:
        """Record no state; the fake is always started."""

    async def request(  # pylint: disable=too-many-return-statements
        self,
        method: str,
        params: dict[str, Any],
    ) -> Any:
        self.requests.append((method, params))
        if method == "account/read":
            return {
                "account": {
                    "type": self.account_type,
                    "email": "person@example.com",
                    "planType": "plus",
                    "futureCredential": "must-not-leak",
                },
            }
        if method == "account/login/start":
            return {"type": "chatgpt", "authUrl": "https://example.com"}
        if method == "model/list":
            return {
                "data": [
                    {
                        "id": "catalog-id",
                        "model": "gpt-test-codex",
                        "displayName": "GPT Test Codex",
                        "description": "Test model",
                        "isDefault": True,
                        "defaultReasoningEffort": "medium",
                        "supportedReasoningEfforts": [
                            {"reasoningEffort": "low"},
                            {"reasoningEffort": "medium"},
                        ],
                    },
                ],
                "nextCursor": None,
            }
        if method == "thread/start":
            return {"thread": {"id": "thread-1"}}
        if method == "turn/start":
            assert self.queue is not None
            await self.queue.put(
                {
                    "method": "item/agentMessage/delta",
                    "params": {
                        "threadId": "thread-1",
                        "turnId": "turn-1",
                        "itemId": "item-1",
                        "delta": "done",
                    },
                },
            )
            await self.queue.put(
                {
                    "method": "turn/completed",
                    "params": {
                        "threadId": "thread-1",
                        "turn": {"id": "turn-1", "status": "completed"},
                    },
                },
            )
            return {"turn": {"id": "turn-1"}}
        if method == "thread/read":
            return {
                "thread": {
                    "turns": [
                        {
                            "items": [
                                {
                                    "id": "user-1",
                                    "type": "userMessage",
                                    "content": [
                                        {
                                            "type": "text",
                                            "text": "Fix it",
                                        },
                                    ],
                                },
                                {
                                    "id": "reason-1",
                                    "type": "reasoning",
                                    "summary": ["Checking"],
                                    "content": ["private details"],
                                },
                                {
                                    "id": "answer-1",
                                    "type": "agentMessage",
                                    "text": "Done",
                                },
                            ],
                        },
                    ],
                },
            }
        return {}

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        self.queue = asyncio.Queue()
        return self.queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        assert queue is self.queue
        self.queue = None

    async def stop(self) -> None:
        self.stopped = True


class BlockingCodexClient(FakeCodexClient):
    """Fake a turn that remains active until the stream is cancelled."""

    def __init__(self) -> None:
        super().__init__()
        self.turn_started = asyncio.Event()

    async def request(self, method: str, params: dict[str, Any]) -> Any:
        self.requests.append((method, params))
        if method == "thread/start":
            return {"thread": {"id": "thread-1"}}
        if method == "turn/start":
            self.turn_started.set()
            return {"turn": {"id": "turn-1"}}
        return {}


def test_loads_persisted_threads_with_io_utils(tmp_path: Path) -> None:
    write_json_atomic(
        tmp_path / "codex_sessions.json",
        {"chat-1": "thread-1"},
    )

    adapter = CodexAdapter(
        tmp_path,
        client=FakeCodexClient(),  # type: ignore[arg-type]
    )

    assert adapter._threads == {"chat-1": "thread-1"}


def test_passes_manual_binary_to_app_server(tmp_path: Path) -> None:
    with patch(
        "qwenpaw.harnesses.codex.adapter.CodexAppServerClient",
    ) as client_class:
        CodexAdapter(tmp_path, binary="/custom/bin/codex")

    client_class.assert_called_once_with(binary="/custom/bin/codex")


@pytest.mark.asyncio
async def test_status_and_login_use_app_server(tmp_path: Path) -> None:
    client = FakeCodexClient()
    adapter = CodexAdapter(tmp_path, client=client)  # type: ignore[arg-type]

    status = await adapter.status()
    login = await adapter.start_login()

    assert status.authenticated is True
    assert status.account is not None
    assert status.account["email"] == "person@example.com"
    assert "futureCredential" not in status.account
    assert login["authUrl"] == "https://example.com"
    assert client.requests[1][0] == "account/login/start"


@pytest.mark.asyncio
async def test_api_key_account_is_authenticated(tmp_path: Path) -> None:
    client = FakeCodexClient()
    client.account_type = "apiKey"
    adapter = CodexAdapter(tmp_path, client=client)  # type: ignore[arg-type]

    status = await adapter.status()

    assert status.authenticated is True
    assert status.account is not None
    assert status.account["type"] == "apiKey"


@pytest.mark.asyncio
async def test_models_are_normalized_from_app_server(
    tmp_path: Path,
) -> None:
    adapter = CodexAdapter(
        tmp_path,
        client=FakeCodexClient(),  # type: ignore[arg-type]
    )

    models = await adapter.models()

    assert len(models) == 1
    assert models[0].id == "gpt-test-codex"
    assert models[0].reasoning_efforts == ["low", "medium"]
    assert models[0].default_reasoning_effort == "medium"


@pytest.mark.asyncio
async def test_history_prefers_reasoning_summary(tmp_path: Path) -> None:
    adapter = CodexAdapter(
        tmp_path,
        client=FakeCodexClient(),  # type: ignore[arg-type]
    )
    adapter._threads["chat-1"] = "thread-1"

    history = await adapter.history("chat-1")

    assert [item.kind.value for item in history] == [
        "user",
        "reasoning",
        "message",
    ]
    assert history[1].text == "Checking"


@pytest.mark.asyncio
async def test_run_turn_persists_and_reuses_thread(tmp_path: Path) -> None:
    client = FakeCodexClient()
    adapter = CodexAdapter(tmp_path, client=client)  # type: ignore[arg-type]

    events = [
        event
        async for event in adapter.run_turn(
            session_id="chat-1",
            prompt="Fix the test",
            cwd=tmp_path,
            settings={
                "model": "gpt-test-codex",
                "reasoning_effort": "high",
            },
        )
    ]

    assert [event.kind for event in events] == [
        HarnessEventKind.TEXT_DELTA,
        HarnessEventKind.COMPLETED,
    ]
    assert events[0].text == "done"
    assert (tmp_path / "codex_sessions.json").is_file()
    assert [method for method, _ in client.requests].count("thread/start") == 1
    thread_params = next(
        params
        for method, params in client.requests
        if method == "thread/start"
    )
    turn_params = next(
        params for method, params in client.requests if method == "turn/start"
    )
    assert thread_params["model"] == "gpt-test-codex"
    assert turn_params["model"] == "gpt-test-codex"
    assert turn_params["effort"] == "high"
    assert turn_params["summary"] == "auto"


@pytest.mark.asyncio
async def test_run_turn_applies_provider_approval_controls(
    tmp_path: Path,
) -> None:
    client = FakeCodexClient()
    adapter = CodexAdapter(tmp_path, client=client)  # type: ignore[arg-type]

    async for _ in adapter.run_turn(
        session_id="chat-1",
        prompt="Fix the test",
        cwd=tmp_path,
        settings={
            "sandbox": "read-only",
            "approval_policy": "on-request",
        },
    ):
        pass

    thread_params = next(
        params
        for method, params in client.requests
        if method == "thread/start"
    )
    turn_params = next(
        params for method, params in client.requests if method == "turn/start"
    )
    assert thread_params["sandbox"] == "read-only"
    assert thread_params["approvalPolicy"] == "on-request"
    assert turn_params["sandboxPolicy"] == {"type": "readOnly"}
    assert turn_params["approvalPolicy"] == "on-request"


@pytest.mark.asyncio
async def test_codex_approval_uses_qwenpaw_service(
    tmp_path: Path,
) -> None:
    adapter = CodexAdapter(
        tmp_path,
        client=FakeCodexClient(),  # type: ignore[arg-type]
    )
    adapter._thread_contexts["thread-1"] = {
        "session_id": "chat-1",
        "agent_id": "agent-1",
        "user_id": "user-1",
        "channel": "console",
    }
    pending = MagicMock(request_id="approval-1", timeout_seconds=30)
    service = MagicMock()
    service.create_pending_summary = AsyncMock(return_value=pending)
    service.wait_for_approval = AsyncMock(
        return_value=ApprovalDecision.APPROVED,
    )

    with patch(
        "qwenpaw.harnesses.codex.adapter.get_approval_service",
        return_value=service,
    ):
        result = await adapter._handle_server_request(
            {
                "method": "item/commandExecution/requestApproval",
                "params": {
                    "threadId": "thread-1",
                    "itemId": "item-1",
                    "command": "pytest -q",
                },
            },
        )

    assert result == {"decision": "accept"}
    create_call = service.create_pending_summary.await_args.kwargs
    assert create_call["session_id"] == "chat-1"
    assert create_call["agent_id"] == "agent-1"
    assert create_call["summary"].payload["command"] == "pytest -q"


@pytest.mark.asyncio
async def test_cancelled_stream_interrupts_active_turn(tmp_path: Path) -> None:
    client = BlockingCodexClient()
    adapter = CodexAdapter(tmp_path, client=client)  # type: ignore[arg-type]

    async def consume() -> None:
        async for _ in adapter.run_turn(
            session_id="chat-1",
            prompt="Keep working",
            cwd=tmp_path,
            settings={},
        ):
            pass

    task = asyncio.create_task(consume())
    await asyncio.wait_for(client.turn_started.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert client.requests[-1] == (
        "turn/interrupt",
        {"threadId": "thread-1", "turnId": "turn-1"},
    )


def test_notification_conversion_covers_reasoning_and_tools() -> None:
    reasoning = CodexAdapter._convert_notification(
        {
            "method": "item/reasoning/summaryTextDelta",
            "params": {"itemId": "reason-1", "delta": "Checking"},
        },
    )
    plan = CodexAdapter._convert_notification(
        {
            "method": "item/plan/delta",
            "params": {"itemId": "plan-1", "delta": "Run tests"},
        },
    )
    started = CodexAdapter._convert_notification(
        {
            "method": "item/started",
            "params": {
                "item": {
                    "id": "tool-1",
                    "type": "commandExecution",
                    "command": "pytest -q",
                    "cwd": "/repo",
                    "status": "inProgress",
                },
            },
        },
    )
    progress = CodexAdapter._convert_notification(
        {
            "method": "item/commandExecution/outputDelta",
            "params": {"itemId": "tool-1", "delta": "1 passed"},
        },
    )
    completed = CodexAdapter._convert_notification(
        {
            "method": "item/completed",
            "params": {
                "item": {
                    "id": "tool-1",
                    "type": "commandExecution",
                    "command": "pytest -q",
                    "cwd": "/repo",
                    "status": "completed",
                    "aggregatedOutput": "1 passed",
                    "exitCode": 0,
                },
            },
        },
    )

    assert reasoning is not None
    assert reasoning.kind == HarnessEventKind.REASONING_DELTA
    assert reasoning.data["source"] == "summary"
    assert plan is not None
    assert plan.data["source"] == "plan"
    assert started is not None
    assert started.kind == HarnessEventKind.TOOL_STARTED
    assert started.tool_name == "shell"
    assert started.data["arguments"]["command"] == "pytest -q"
    assert progress is not None
    assert progress.kind == HarnessEventKind.TOOL_PROGRESS
    assert progress.text == "1 passed"
    assert completed is not None
    assert completed.kind == HarnessEventKind.TOOL_COMPLETED
    assert completed.text == "1 passed"
    assert completed.data["exit_code"] == 0


def test_mcp_tool_uses_server_qualified_name_and_result() -> None:
    event = CodexAdapter._convert_notification(
        {
            "method": "item/completed",
            "params": {
                "item": {
                    "id": "mcp-1",
                    "type": "mcpToolCall",
                    "server": "github",
                    "tool": "search",
                    "arguments": {"query": "bug"},
                    "status": "completed",
                    "result": {"content": "found"},
                },
            },
        },
    )

    assert event is not None
    assert event.tool_name == "github.search"
    assert event.data["arguments"] == {"query": "bug"}
    assert '"content": "found"' in event.text


@pytest.mark.parametrize(
    ("item", "expected"),
    [
        ({"type": "commandExecution"}, "shell"),
        ({"type": "fileChange"}, "apply_patch"),
        (
            {"type": "mcpToolCall", "server": "git", "tool": "status"},
            "git.status",
        ),
        (
            {
                "type": "dynamicToolCall",
                "namespace": "docs",
                "tool": "search",
            },
            "docs.search",
        ),
        (
            {"type": "collabAgentToolCall", "tool": "spawnAgent"},
            "agent.spawnAgent",
        ),
        ({"type": "webSearch"}, "web_search"),
        ({"type": "imageView"}, "view_image"),
        ({"type": "imageGeneration"}, "image_generation"),
    ],
)
def test_tool_names_are_provider_neutral(
    item: dict[str, Any],
    expected: str,
) -> None:
    assert CodexAdapter._tool_name(item) == expected
