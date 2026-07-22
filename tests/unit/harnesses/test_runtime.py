# -*- coding: utf-8 -*-
"""Tests for provider-neutral coding harness routing."""

# pylint: disable=protected-access

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from qwenpaw.harnesses.base import HarnessAdapter
from qwenpaw.harnesses.events import (
    HarnessEvent,
    HarnessEventKind,
    HarnessProvider,
)
from qwenpaw.harnesses.runtime import HarnessRuntime
from qwenpaw.schemas import AgentRequest, Message, Role, TextContent


class FakeAdapter(HarnessAdapter):
    """Emit one deterministic response for envelope assertions."""

    async def status(self) -> HarnessProvider:
        return HarnessProvider(
            id="codex",
            name="Codex",
            available=True,
            installed=True,
            authenticated=True,
        )

    async def start_login(self, device_code: bool = False) -> dict:
        return {"device_code": device_code}

    async def logout(self) -> None:
        return None

    async def run_turn(  # pylint: disable=invalid-overridden-method
        self,
        *,
        session_id: str,
        prompt: str,
        cwd: Path,
    ) -> AsyncIterator[HarnessEvent]:
        assert session_id == "chat-1"
        assert prompt == "Fix it"
        assert cwd.is_absolute()
        yield HarnessEvent(
            kind=HarnessEventKind.TEXT_DELTA,
            text="Fixed",
        )
        yield HarnessEvent(kind=HarnessEventKind.COMPLETED)

    async def stop(self) -> None:
        return None


@pytest.mark.asyncio
async def test_runtime_emits_qwenpaw_envelopes(tmp_path: Path) -> None:
    runtime = HarnessRuntime(tmp_path)
    runtime._adapters["codex"] = FakeAdapter()
    request = AgentRequest(
        session_id="chat-1",
        input=[
            Message(
                role=Role.USER,
                content=[TextContent(text="Fix it")],
            ),
        ],
    )

    output = [
        item
        async for item in runtime.stream(
            backend="codex",
            request=request,
            cwd=tmp_path.resolve(),
        )
    ]

    assert [item.object for item in output] == [
        "response",
        "response",
        "message",
        "content",
        "message",
        "response",
    ]
    assert output[3].text == "Fixed"
    assert output[-1].status == "completed"
