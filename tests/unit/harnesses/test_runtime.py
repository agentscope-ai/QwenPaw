# -*- coding: utf-8 -*-
"""Tests for provider-neutral third-party agent routing."""

# pylint: disable=protected-access

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from qwenpaw.app.chats.session import DatabaseSession
from qwenpaw.app.chats.transcript import TranscriptStore
from qwenpaw.app.chats.transcript_catalog import TranscriptCatalog
from qwenpaw._session_signals import (
    TRANSCRIPT_RECORDING_READY_KEY,
    TRANSCRIPT_TURN_ID_CONTEXT_KEY,
)

from qwenpaw.harnesses.base import HarnessAdapter
from qwenpaw.harnesses.events import (
    HarnessAttachment,
    HarnessAttachmentKind,
    HarnessEvent,
    HarnessEventKind,
    HarnessProvider,
)
from qwenpaw.harnesses.runtime import HarnessRuntime
from qwenpaw.schemas import (
    AgentRequest,
    FileContent,
    ImageContent,
    Message,
    MessageType,
    Role,
    TextContent,
)


class FakeAdapter(HarnessAdapter):
    """Emit one deterministic response for envelope assertions."""

    def __init__(self) -> None:
        self.stopped = False
        self.prompt = ""
        self.attachments: list[HarnessAttachment] = []

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
        settings: dict,
        attachments: list[HarnessAttachment] | None = None,
    ) -> AsyncIterator[HarnessEvent]:
        assert session_id == "chat-1"
        assert cwd.is_absolute()
        self.prompt = prompt
        self.attachments = attachments or []
        yield HarnessEvent(
            kind=HarnessEventKind.TEXT_DELTA,
            text="Fixed",
        )
        yield HarnessEvent(kind=HarnessEventKind.COMPLETED)

    async def stop(self) -> None:
        self.stopped = True


class ToolAdapter(FakeAdapter):
    """Emit interleaved reasoning, tool progress, and assistant text."""

    async def run_turn(  # pylint: disable=invalid-overridden-method
        self,
        *,
        session_id: str,
        prompt: str,
        cwd: Path,
        settings: dict,
        attachments: list[HarnessAttachment] | None = None,
    ) -> AsyncIterator[HarnessEvent]:
        del attachments
        yield HarnessEvent(
            kind=HarnessEventKind.REASONING_DELTA,
            text="Checking",
            item_id="reason-1",
        )
        yield HarnessEvent(
            kind=HarnessEventKind.TOOL_STARTED,
            item_id="tool-1",
            tool_name="shell",
            data={
                "arguments": {"command": "pytest -q"},
                "provider_type": "commandExecution",
            },
        )
        yield HarnessEvent(
            kind=HarnessEventKind.TOOL_PROGRESS,
            item_id="tool-1",
            text="1 passed",
        )
        yield HarnessEvent(
            kind=HarnessEventKind.TOOL_COMPLETED,
            item_id="tool-1",
            tool_name="shell",
            text="1 passed",
            data={
                "arguments": {"command": "pytest -q"},
                "provider_type": "commandExecution",
                "exit_code": 0,
            },
        )
        yield HarnessEvent(
            kind=HarnessEventKind.TEXT_DELTA,
            text="Done",
        )
        yield HarnessEvent(kind=HarnessEventKind.COMPLETED)


class CommandAdapter(FakeAdapter):
    """Record a provider-owned command without starting a normal turn."""

    def __init__(self) -> None:
        super().__init__()
        self.command = ""
        self.reset_session_id = ""

    async def run_command(
        self,
        *,
        session_id: str,
        command: str,
        arguments: str,
        cwd: Path,
        settings: dict,
    ) -> list[HarnessEvent]:
        del session_id, arguments, cwd, settings
        self.command = command
        return [
            HarnessEvent(
                kind=HarnessEventKind.TEXT_DELTA,
                text="Compacted",
            ),
            HarnessEvent(kind=HarnessEventKind.COMPLETED),
        ]

    async def reset_session(self, session_id: str) -> None:
        self.reset_session_id = session_id


@pytest.mark.asyncio
async def test_runtime_recreates_adapter_when_binary_changes(
    tmp_path: Path,
) -> None:
    runtime = HarnessRuntime(tmp_path)

    with patch(
        "qwenpaw.harnesses.runtime.create_adapter",
        side_effect=lambda *_args, **_kwargs: FakeAdapter(),
    ):
        first = await runtime.adapter("codex", {"binary": "/first/codex"})
        reused = await runtime.adapter("codex", {"binary": "/first/codex"})
        second = await runtime.adapter("codex", {"binary": "/second/codex"})

    assert reused is first
    assert second is not first
    assert first.stopped is True


@pytest.mark.asyncio
async def test_runtime_emits_qwenpaw_envelopes(tmp_path: Path) -> None:
    runtime = HarnessRuntime(tmp_path)
    adapter = FakeAdapter()
    runtime._adapters["codex"] = adapter
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
    assert adapter.prompt == "Fix it"
    assert adapter.attachments == []


@pytest.mark.asyncio
async def test_runtime_forwards_dropped_image_and_file(
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "screenshot.png"
    file_path = tmp_path / "requirements.txt"
    adapter = FakeAdapter()
    runtime = HarnessRuntime(tmp_path)
    runtime._adapters["codex"] = adapter
    request = AgentRequest(
        session_id="chat-1",
        input=[
            Message(
                role=Role.USER,
                content=[
                    TextContent(text="Inspect these"),
                    ImageContent(image_url=str(image_path)),
                    FileContent(
                        filename="requirements.txt",
                        file_url=str(file_path),
                    ),
                ],
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

    assert output[-1].status == "completed"
    assert adapter.prompt == "Inspect these"
    assert [item.kind for item in adapter.attachments] == [
        HarnessAttachmentKind.IMAGE,
        HarnessAttachmentKind.FILE,
    ]
    assert [item.path for item in adapter.attachments] == [
        image_path,
        file_path,
    ]
    assert adapter.attachments[1].name == "requirements.txt"


@pytest.mark.asyncio
async def test_runtime_allows_attachment_only_turn(tmp_path: Path) -> None:
    image_path = tmp_path / "screenshot.png"
    adapter = FakeAdapter()
    runtime = HarnessRuntime(tmp_path)
    runtime._adapters["codex"] = adapter
    request = AgentRequest(
        session_id="chat-1",
        input=[
            Message(
                role=Role.USER,
                content=[ImageContent(image_url=str(image_path))],
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

    assert output[-1].status == "completed"
    assert adapter.prompt == ""
    assert adapter.attachments[0].path == image_path


@pytest.mark.asyncio
async def test_runtime_emits_reasoning_and_native_tool_envelopes(
    tmp_path: Path,
) -> None:
    runtime = HarnessRuntime(tmp_path)
    runtime._adapters["codex"] = ToolAdapter()
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
    final_response = output[-1]
    output_types = [message.type for message in final_response.output]

    assert output_types == [
        MessageType.REASONING,
        MessageType.PLUGIN_CALL,
        MessageType.PLUGIN_CALL_OUTPUT,
        MessageType.MESSAGE,
    ]
    tool_call = final_response.output[1].content[0].data
    tool_output = final_response.output[2].content[0].data
    assert tool_call["name"] == "shell"
    assert tool_call["arguments"] == '{"command": "pytest -q"}'
    assert tool_output["output"] == "1 passed"
    assert tool_output["exit_code"] == 0
    assert any(
        getattr(item, "type", None) == MessageType.REASONING for item in output
    )


@pytest.mark.asyncio
async def test_runtime_routes_declared_provider_command(
    tmp_path: Path,
) -> None:
    runtime = HarnessRuntime(tmp_path)
    adapter = CommandAdapter()
    runtime._adapters["codex"] = adapter
    request = AgentRequest(
        session_id="chat-1",
        input=[
            Message(
                role=Role.USER,
                content=[TextContent(text="/compact")],
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

    assert adapter.command == "compact"
    assert output[-1].status == "completed"
    assert output[-1].output[-1].content[0].text == "Compacted"


@pytest.mark.asyncio
async def test_runtime_handles_host_clear_for_every_backend(
    tmp_path: Path,
) -> None:
    runtime = HarnessRuntime(tmp_path)
    adapter = CommandAdapter()
    runtime._adapters["codex"] = adapter
    request = AgentRequest(
        session_id="chat-1",
        input=[
            Message(
                role=Role.USER,
                content=[TextContent(text="/clear")],
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

    assert adapter.reset_session_id == "chat-1"
    assert output[-1].output[-1].metadata["context_reset"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["clear", "new"])
@pytest.mark.parametrize("backend", ["codex", "qoder"])
@pytest.mark.parametrize(
    "outcome",
    ["success", "reset_error", "cancel", "write_error"],
)
async def test_native_reset_commits_binding_and_runtime_together(
    tmp_path,
    monkeypatch,
    backend,
    outcome,
    command,
):
    """Rejected native resets must not discard the durable conversation."""

    catalog = TranscriptCatalog(tmp_path)
    session = DatabaseSession(
        catalog=catalog,
        legacy_save_dir=str(tmp_path / "sessions"),
    )
    identity = dict(session_id="chat-1", user_id="user", channel="console")
    catalog.write_runtime_state(
        **identity,
        state={"agent": {"saved": True}},
        context_generation=4,
    )
    catalog.record_provider_fact(
        **identity,
        kind="session_bound",
        data={
            "provider": backend,
            "external_session_id": "old-native",
        },
    )
    catalog.start_turn(**identity, turn_id="reset")
    before = catalog.read_runtime_state(**identity)
    runtime = HarnessRuntime(
        tmp_path,
        session=session,
        workspace=SimpleNamespace(
            transcript_store=catalog,
            workspace_dir=tmp_path,
        ),
    )
    runtime._capability_resolver.resolve = AsyncMock(return_value=None)
    adapter = CommandAdapter()
    if outcome in {"reset_error", "cancel"}:
        adapter.reset_session = AsyncMock(
            side_effect=(
                asyncio.CancelledError()
                if outcome == "cancel"
                else RuntimeError("reset failed")
            ),
        )
    if outcome == "write_error":
        original = TranscriptStore._append_fact

        def fail_binding(store, **kwargs):
            if kwargs["event_type"] == "provider.session_bound":
                raise OSError("disk full")
            return original(store, **kwargs)

        monkeypatch.setattr(TranscriptStore, "_append_fact", fail_binding)
    runtime._adapters[backend] = adapter
    request = AgentRequest(
        **identity,
        request_context={
            TRANSCRIPT_RECORDING_READY_KEY: True,
            TRANSCRIPT_TURN_ID_CONTEXT_KEY: "reset",
        },
        input=[
            Message(role="user", content=[TextContent(text=f"/{command}")]),
        ],
    )
    output = []
    try:
        try:
            async for item in runtime.stream(
                backend=backend,
                request=request,
                cwd=tmp_path,
            ):
                output.append(item)
        except asyncio.CancelledError:
            assert outcome == "cancel"
        after = catalog.read_runtime_state(**identity)
        binding = catalog.read_provider_state(**identity)["binding"]
        if outcome == "success":
            assert after.context_generation == 5
            assert after.state["agent"]["state"]["context"] == []
            assert binding["external_session_id"] is None
            assert output[-1].status.value == "completed"
        else:
            assert after == before
            assert binding["external_session_id"] == "old-native"
            if outcome != "cancel":
                assert output[-1].status.value == "failed"
                assert not any(
                    (msg.metadata or {}).get("context_reset")
                    for msg in output[-1].output
                )
    finally:
        catalog.close()


@pytest.mark.asyncio
async def test_runtime_reports_persistence_failure(tmp_path):
    """Provider output is not a successful durable turn when saving fails."""
    runtime = HarnessRuntime(tmp_path)
    runtime._adapters["codex"] = FakeAdapter()
    runtime._session_bridge = SimpleNamespace(
        append_turn=AsyncMock(side_effect=OSError("disk full")),
    )
    request = AgentRequest(
        session_id="chat-1",
        input=[Message(role="user", content=[TextContent(text="hello")])],
    )
    output = [
        item
        async for item in runtime.stream(
            backend="codex",
            request=request,
            cwd=tmp_path,
        )
    ]
    assert output[-1].status.value == "failed"
    assert output[-1].error["code"] == "session_persistence_failed"
