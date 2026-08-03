# -*- coding: utf-8 -*-
"""Tests for the Qoder third-party agent adapter."""

# pylint: disable=protected-access

from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from qoder_agent_sdk import (
    AssistantMessage,
    ModelInfo,
    QoderAgentOptions,
    ResultMessage,
    SessionMessage,
    StreamEvent,
    TextBlock,
)

from qwenpaw.harnesses.events import (
    HarnessAttachment,
    HarnessAttachmentKind,
    HarnessEventKind,
)
from qwenpaw.harnesses.base import HarnessOperationNotSupportedError
from qwenpaw.harnesses.capabilities import (
    HarnessMCPServerDefinition,
    HarnessRuntimeCapabilities,
    HarnessSkillDefinition,
)
from qwenpaw.harnesses.qoder.adapter import QoderAdapter
from qwenpaw.harnesses.qoder.projection import materialize_skill_plugin
from qwenpaw.harnesses.registry import create_adapter, get_provider
from qwenpaw.security.tool_guard.approval import ApprovalDecision
from qwenpaw.utils.io_utils import write_json_atomic


class FakeQoderClient:
    """Minimal Qoder SDK client double."""

    def __init__(self, options: QoderAgentOptions) -> None:
        self.options = options
        self.connected = False
        self.disconnected = False
        self.interrupted = False
        self.prompts: list[tuple[Any, str]] = []
        self.server_info: dict[str, Any] = {"skills": []}
        self.messages: list[Any] = [
            StreamEvent(
                uuid="stream-1",
                session_id="qoder-session",
                event={
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "Done"},
                },
            ),
            AssistantMessage(
                content=[TextBlock(text="Done")],
                model="qoder-test",
            ),
            ResultMessage(
                subtype="success",
                duration_ms=1,
                duration_api_ms=1,
                is_error=False,
                num_turns=1,
                session_id="qoder-session",
            ),
        ]

    async def connect(self) -> None:
        """Mark the client connected."""
        self.connected = True

    async def disconnect(self) -> None:
        """Mark the client disconnected."""
        self.disconnected = True

    async def query(self, prompt: Any, session_id: str = "default") -> None:
        """Capture user input."""
        if not isinstance(prompt, str):
            prompt = [message async for message in prompt]
        self.prompts.append((prompt, session_id))

    async def receive_response(self):
        """Yield one complete response."""
        for message in self.messages:
            yield message

    async def interrupt(self) -> None:
        """Capture interruption."""
        self.interrupted = True

    async def get_available_models(self) -> list[ModelInfo]:
        """Return one rich model entry."""
        return [
            {
                "value": "auto",
                "displayName": "Auto",
                "description": "Recommended",
                "isEnabled": True,
                "thinking_config": {
                    "enabled": {
                        "efforts": {
                            "low": {"is_default": False},
                            "high": {"is_default": True},
                        },
                    },
                },
            },
        ]

    async def get_server_info(self) -> dict[str, Any]:
        """Return discovered Qoder capabilities."""
        return self.server_info


def _executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    path.chmod(path.stat().st_mode | 0o111)
    return path


def test_skill_projection_uses_portable_copies_with_spaced_paths(
    tmp_path: Path,
) -> None:
    skill_dir = tmp_path / "QwenPaw Skills" / "代码审查"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: review\ndescription: Review code\n---\n",
        encoding="utf-8",
    )
    capabilities = HarnessRuntimeCapabilities(
        skills=[
            HarnessSkillDefinition(
                name="review",
                directory=skill_dir,
            ),
        ],
    )

    plugin = materialize_skill_plugin(
        tmp_path / "Harness State",
        capabilities,
    )

    assert plugin is not None
    projected = plugin / "skills" / "review" / "SKILL.md"
    assert projected.is_file()
    assert not projected.is_symlink()
    assert projected.read_text(encoding="utf-8").startswith("---")


def test_loads_persisted_qoder_sessions(tmp_path: Path) -> None:
    write_json_atomic(
        tmp_path / "qoder_sessions.json",
        {"chat-1": "550e8400-e29b-41d4-a716-446655440000"},
    )

    adapter = QoderAdapter(tmp_path)

    assert adapter._sessions == {
        "chat-1": "550e8400-e29b-41d4-a716-446655440000",
    }


def test_registry_exposes_qoder_capabilities(tmp_path: Path) -> None:
    provider = get_provider("qoder")
    adapter = create_adapter(
        "qoder",
        tmp_path,
        {"binary": "/custom/qodercli"},
    )

    assert provider.coming_soon is False
    assert provider.capabilities.model_selection is True
    assert provider.capabilities.reasoning_stream is True
    assert provider.capabilities.tool_stream is True
    assert provider.capabilities.attachments is True
    assert [command.name for command in provider.capabilities.commands] == [
        "compact",
    ]
    assert isinstance(adapter, QoderAdapter)
    assert adapter._binary == "/custom/qodercli"


@pytest.mark.asyncio
async def test_qoder_logout_reports_unsupported_operation(
    tmp_path: Path,
) -> None:
    adapter = QoderAdapter(tmp_path)

    with pytest.raises(
        HarnessOperationNotSupportedError,
        match="does not expose a non-interactive logout command",
    ):
        await adapter.logout()


@pytest.mark.asyncio
async def test_only_compact_is_forwarded_as_qoder_command(
    tmp_path: Path,
) -> None:
    binary = _executable(tmp_path / "qodercli")
    client = FakeQoderClient(QoderAgentOptions())
    adapter = QoderAdapter(
        tmp_path,
        binary=str(binary),
        client_factory=lambda _options: client,
    )

    unsupported = await adapter.run_command(
        session_id="chat-1",
        command="status",
        arguments="",
        cwd=tmp_path,
        settings={},
    )
    compact = await adapter.run_command(
        session_id="chat-1",
        command="compact",
        arguments="",
        cwd=tmp_path,
        settings={},
    )

    assert unsupported[0].kind == HarnessEventKind.ERROR
    assert client.prompts[0] == ("/compact", "default")
    assert compact[-1].kind == HarnessEventKind.COMPLETED


@pytest.mark.asyncio
async def test_status_accepts_cli_and_pat_authentication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binary = _executable(tmp_path / "qodercli")
    adapter = QoderAdapter(tmp_path, binary=str(binary))
    adapter._run_cli = AsyncMock(return_value="Account: Not logged in")

    status = await adapter.status()
    monkeypatch.setenv("QODER_PERSONAL_ACCESS_TOKEN", "secret")
    token_status = await adapter.status()

    assert status.installed is True
    assert status.authenticated is False
    assert token_status.authenticated is True
    assert token_status.account == {"type": "accessToken"}


@pytest.mark.asyncio
async def test_status_accepts_current_qoder_account_output(
    tmp_path: Path,
) -> None:
    binary = _executable(tmp_path / "qodercli")
    adapter = QoderAdapter(tmp_path, binary=str(binary))
    adapter._run_cli = AsyncMock(
        return_value=(
            "Version: 1.0.47\n"
            "Username: qoder-user\n"
            "Email: user@example.com\n"
        ),
    )

    status = await adapter.status()

    assert status.authenticated is True
    assert status.account == {
        "type": "qodercli",
        "email": "user@example.com",
        "username": "qoder-user",
    }


@pytest.mark.asyncio
async def test_models_and_turns_use_sdk_capabilities(tmp_path: Path) -> None:
    binary = _executable(tmp_path / "qodercli")
    clients: list[FakeQoderClient] = []

    def factory(options: QoderAgentOptions) -> FakeQoderClient:
        client = FakeQoderClient(options)
        clients.append(client)
        return client

    adapter = QoderAdapter(
        tmp_path,
        binary=str(binary),
        client_factory=factory,
    )

    models = await adapter.models()
    events = [
        event
        async for event in adapter.run_turn(
            session_id="chat-1",
            prompt="Fix it",
            cwd=tmp_path,
            settings={
                "model": "auto",
                "reasoning_effort": "high",
                "permission_mode": "default",
            },
        )
    ]

    assert models[0].id == "auto"
    assert models[0].default_reasoning_effort == "high"
    assert [event.kind for event in events] == [
        HarnessEventKind.TEXT_DELTA,
        HarnessEventKind.COMPLETED,
    ]
    turn_client = clients[-1]
    assert turn_client.options.cwd == tmp_path
    assert turn_client.options.model == "auto"
    assert turn_client.options.effort is None
    assert turn_client.options.thinking is None
    assert turn_client.options.extra_args == {
        "reasoning-effort": "high",
    }
    assert turn_client.options.include_partial_messages is True
    assert turn_client.prompts == [("Fix it", "default")]
    assert (tmp_path / "qoder_sessions.json").is_file()


@pytest.mark.asyncio
async def test_discovers_qoder_owned_skills_as_read_only(
    tmp_path: Path,
) -> None:
    binary = _executable(tmp_path / "qodercli")
    clients: list[FakeQoderClient] = []

    def factory(options: QoderAgentOptions) -> FakeQoderClient:
        client = FakeQoderClient(options)
        client.server_info = {
            "skills": [
                {
                    "name": "find-skills",
                    "description": "Find installable Skills",
                    "source": "user",
                },
                {
                    "name": "qwenpaw-runtime:review",
                    "description": "Projected Skill",
                    "source": "plugin",
                },
            ],
        }
        clients.append(client)
        return client

    adapter = QoderAdapter(
        tmp_path,
        binary=str(binary),
        client_factory=factory,
    )

    skills = await adapter.discover_skills(tmp_path)

    assert [skill.name for skill in skills] == ["find-skills"]
    assert skills[0].provider_id == "qoder"
    assert skills[0].source == "user"
    assert skills[0].read_only is True
    assert clients[0].options.setting_sources == [
        "user",
        "project",
        "local",
    ]
    assert clients[0].options.skills == "all"
    assert clients[0].disconnected is True


@pytest.mark.asyncio
async def test_turn_projects_qwenpaw_skills_and_mcp(
    tmp_path: Path,
) -> None:
    binary = _executable(tmp_path / "qodercli")
    skill_dir = tmp_path / "workspace-skills" / "review"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: review\ndescription: Review code\n---\n",
        encoding="utf-8",
    )
    clients: list[FakeQoderClient] = []

    def factory(options: QoderAgentOptions) -> FakeQoderClient:
        client = FakeQoderClient(options)
        clients.append(client)
        return client

    adapter = QoderAdapter(
        tmp_path / "harnesses",
        binary=str(binary),
        client_factory=factory,
    )
    capabilities = HarnessRuntimeCapabilities(
        skills=[
            HarnessSkillDefinition(
                name="review",
                description="Review code",
                directory=skill_dir,
            ),
        ],
        mcp_servers=[
            HarnessMCPServerDefinition(
                name="docs",
                display_name="Docs",
                transport="streamable_http",
                url="https://mcp.example.test",
                headers={"Authorization": "Bearer secret"},
                tools=["search"],
                tool_policies={"search": "ask"},
            ),
        ],
    )

    _ = [
        event
        async for event in adapter.run_turn(
            session_id="chat-1",
            prompt="Review it",
            cwd=tmp_path,
            settings={"_runtime_capabilities": capabilities},
        )
    ]

    options = clients[0].options
    assert options.skills == "all"
    assert options.setting_sources == ["user", "project", "local"]
    assert options.strict_mcp_config is True
    assert options.allowed_mcp_server_names == ["docs"]
    assert options.mcp_servers == {
        "docs": {
            "type": "http",
            "url": "https://mcp.example.test",
            "headers": {"Authorization": "Bearer secret"},
            "tools": [
                {
                    "name": "search",
                    "permission_policy": "always_ask",
                },
            ],
        },
    }
    plugin_path = Path(options.plugins[0]["path"])
    assert plugin_path.is_relative_to(tmp_path / "harnesses")
    assert (plugin_path / "skills" / "review" / "SKILL.md").is_file()


@pytest.mark.asyncio
async def test_turn_sends_images_and_files_through_qoder_protocol(
    tmp_path: Path,
) -> None:
    binary = _executable(tmp_path / "qodercli")
    image = tmp_path / "media" / "mockup.png"
    image.parent.mkdir()
    image.write_bytes(b"image-bytes")
    document = tmp_path / "media" / "product brief.pdf"
    document.write_bytes(b"document-bytes")
    client = FakeQoderClient(QoderAgentOptions())
    adapter = QoderAdapter(
        tmp_path,
        binary=str(binary),
        client_factory=lambda _options: client,
    )

    _ = [
        event
        async for event in adapter.run_turn(
            session_id="chat-1",
            prompt="Review both attachments",
            cwd=tmp_path,
            settings={},
            attachments=[
                HarnessAttachment(
                    kind=HarnessAttachmentKind.IMAGE,
                    path=image,
                    name=image.name,
                ),
                HarnessAttachment(
                    kind=HarnessAttachmentKind.FILE,
                    path=document,
                    name=document.name,
                ),
            ],
        )
    ]

    messages, query_session_id = client.prompts[0]
    assert query_session_id == "default"
    assert messages == [
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            '@"media/product brief.pdf"\n'
                            "Review both attachments"
                        ),
                    },
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": base64.b64encode(
                                b"image-bytes",
                            ).decode("ascii"),
                        },
                    },
                ],
            },
            "parent_tool_use_id": None,
        },
    ]


@pytest.mark.asyncio
async def test_turn_accepts_an_attachment_without_text(
    tmp_path: Path,
) -> None:
    binary = _executable(tmp_path / "qodercli")
    document = tmp_path / "notes.md"
    document.write_text("notes", encoding="utf-8")
    client = FakeQoderClient(QoderAgentOptions())
    adapter = QoderAdapter(
        tmp_path,
        binary=str(binary),
        client_factory=lambda _options: client,
    )

    _ = [
        event
        async for event in adapter.run_turn(
            session_id="chat-1",
            prompt="",
            cwd=tmp_path,
            settings={},
            attachments=[
                HarnessAttachment(
                    kind=HarnessAttachmentKind.FILE,
                    path=document,
                    name=document.name,
                ),
            ],
        )
    ]

    messages, _ = client.prompts[0]
    assert messages[0]["message"]["content"] == [
        {"type": "text", "text": "@notes.md"},
    ]


@pytest.mark.asyncio
async def test_qoder_approval_uses_qwenpaw_service(
    tmp_path: Path,
) -> None:
    adapter = QoderAdapter(tmp_path)
    adapter._contexts["chat-1"] = {
        "agent_id": "agent-1",
        "user_id": "user-1",
        "channel": "console",
    }
    pending = type(
        "Pending",
        (),
        {"request_id": "request-1", "timeout_seconds": 30},
    )()
    service = AsyncMock()
    service.create_pending_summary.return_value = pending
    service.wait_for_approval.return_value = ApprovalDecision.APPROVED
    context = type(
        "Context",
        (),
        {
            "description": "Run tests",
            "decision_reason": None,
            "display_name": "Shell",
            "title": None,
            "tool_use_id": "tool-1",
            "blocked_path": None,
        },
    )()

    with patch(
        "qwenpaw.harnesses.qoder.adapter.get_approval_service",
        return_value=service,
    ):
        result = await adapter._approve_tool(
            "chat-1",
            "Bash",
            {"command": "pytest"},
            context,
        )

    assert result.behavior == "allow"
    summary = service.create_pending_summary.call_args.kwargs["summary"]
    assert summary.source_type == "qoder"
    assert summary.payload["tool_name"] == "Bash"


@pytest.mark.asyncio
async def test_history_uses_persisted_qoder_session(tmp_path: Path) -> None:
    adapter = QoderAdapter(tmp_path)
    adapter._sessions["chat-1"] = "550e8400-e29b-41d4-a716-446655440000"
    messages = [
        SessionMessage(
            type="assistant",
            uuid="assistant-1",
            session_id=adapter._sessions["chat-1"],
            message={"content": [{"type": "text", "text": "Recovered"}]},
        ),
    ]

    with patch(
        "qwenpaw.harnesses.qoder.adapter.get_session_messages",
        return_value=messages,
    ) as get_messages:
        history = await adapter.history("chat-1")

    assert history[0].text == "Recovered"
    get_messages.assert_called_once_with(
        adapter._sessions["chat-1"],
        None,
    )


@pytest.mark.asyncio
async def test_cancelling_turn_interrupts_qoder(tmp_path: Path) -> None:
    binary = _executable(tmp_path / "qodercli")
    response_started = asyncio.Event()
    response_release = asyncio.Event()

    class BlockingQoderClient(FakeQoderClient):
        async def receive_response(self):
            response_started.set()
            await response_release.wait()
            yield self.messages[0]

    client = BlockingQoderClient(QoderAgentOptions())
    adapter = QoderAdapter(
        tmp_path,
        binary=str(binary),
        client_factory=lambda _options: client,
    )

    async def consume() -> None:
        async for _ in adapter.run_turn(
            session_id="chat-1",
            prompt="Wait",
            cwd=tmp_path,
            settings={},
        ):
            pass

    turn = asyncio.create_task(consume())
    await response_started.wait()
    turn.cancel()

    with pytest.raises(asyncio.CancelledError):
        await turn

    assert client.interrupted is True


@pytest.mark.asyncio
async def test_cli_timeout_reaps_process(tmp_path: Path) -> None:
    binary = _executable(tmp_path / "qodercli")

    class HangingProcess:
        def __init__(self) -> None:
            self.returncode = None
            self.killed = False
            self.waited = False

        async def communicate(self):
            await asyncio.Event().wait()

        def kill(self) -> None:
            self.killed = True
            self.returncode = -9

        async def wait(self) -> int:
            self.waited = True
            return -9

    process = HangingProcess()
    adapter = QoderAdapter(tmp_path, binary=str(binary))
    with (
        patch(
            "qwenpaw.harnesses.qoder.adapter."
            "asyncio.create_subprocess_exec",
            return_value=process,
        ),
        patch(
            "qwenpaw.harnesses.qoder.adapter._STATUS_TIMEOUT_SECONDS",
            0.01,
        ),
        pytest.raises(asyncio.TimeoutError),
    ):
        await adapter._run_cli("status")

    assert process.killed is True
    assert process.waited is True
