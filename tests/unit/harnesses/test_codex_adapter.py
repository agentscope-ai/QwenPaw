# -*- coding: utf-8 -*-
"""Tests for the Codex coding harness adapter."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from qwenpaw.harnesses.codex.adapter import CodexAdapter
from qwenpaw.harnesses.events import HarnessEventKind


class FakeCodexClient:
    """Small app-server double that preserves request ordering."""

    installed = True

    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.queue: asyncio.Queue[dict[str, Any]] | None = None
        self.stopped = False

    async def start(self) -> None:
        """Record no state; the fake is always started."""

    async def request(self, method: str, params: dict[str, Any]) -> Any:
        self.requests.append((method, params))
        if method == "account/read":
            return {
                "account": {
                    "type": "chatgpt",
                    "email": "person@example.com",
                    "planType": "plus",
                    "futureCredential": "must-not-leak",
                },
            }
        if method == "account/login/start":
            return {"type": "chatgpt", "authUrl": "https://example.com"}
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

    async def request(self, method: str, params: dict[str, Any]) -> Any:
        self.requests.append((method, params))
        if method == "thread/start":
            return {"thread": {"id": "thread-1"}}
        if method == "turn/start":
            return {"turn": {"id": "turn-1"}}
        return {}


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
async def test_run_turn_persists_and_reuses_thread(tmp_path: Path) -> None:
    client = FakeCodexClient()
    adapter = CodexAdapter(tmp_path, client=client)  # type: ignore[arg-type]

    events = [
        event
        async for event in adapter.run_turn(
            session_id="chat-1",
            prompt="Fix the test",
            cwd=tmp_path,
        )
    ]

    assert [event.kind for event in events] == [
        HarnessEventKind.TEXT_DELTA,
        HarnessEventKind.COMPLETED,
    ]
    assert events[0].text == "done"
    assert (tmp_path / "codex_sessions.json").is_file()
    assert [method for method, _ in client.requests].count("thread/start") == 1


@pytest.mark.asyncio
async def test_cancelled_stream_interrupts_active_turn(tmp_path: Path) -> None:
    client = BlockingCodexClient()
    adapter = CodexAdapter(tmp_path, client=client)  # type: ignore[arg-type]

    async def consume() -> None:
        async for _ in adapter.run_turn(
            session_id="chat-1",
            prompt="Keep working",
            cwd=tmp_path,
        ):
            pass

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert client.requests[-1] == (
        "turn/interrupt",
        {"threadId": "thread-1", "turnId": "turn-1"},
    )
