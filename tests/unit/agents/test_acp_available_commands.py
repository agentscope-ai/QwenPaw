# -*- coding: utf-8 -*-
"""Tests for the ACP agent advertising its slash commands.

The ACP server sends an ``available_commands_update`` notification after a
session is created so clients (e.g. the paw TUI) can offer autocompletion.
"""

# pylint: disable=protected-access

from __future__ import annotations

import asyncio

from acp.schema import AllowedOutcome, RequestPermissionResponse

from qwenpaw.agents.acp.server import (
    _ACP_REDUNDANT_COMMANDS,
    _EnvelopeTracker,
    ACP_AGENT_META_KEY,
    ACP_ERROR_META_KEY,
    QwenPawACPAgent,
)


class _FakeConn:
    """Records ``session_update`` calls made by the agent."""

    def __init__(self) -> None:
        self.updates: list[tuple[str, object]] = []

    async def session_update(self, session_id: str, update: object) -> None:
        self.updates.append((session_id, update))


class _ApprovalConn(_FakeConn):
    """Records ACP permission requests and approves them."""

    def __init__(self) -> None:
        super().__init__()
        self.permission_requests: list[dict[str, object]] = []

    async def request_permission(
        self,
        *,
        session_id: str,
        tool_call: object,
        options: list[object],
    ) -> RequestPermissionResponse:
        self.permission_requests.append(
            {
                "session_id": session_id,
                "tool_call": tool_call,
                "options": options,
            },
        )
        return RequestPermissionResponse(
            outcome=AllowedOutcome(
                outcome="selected",
                option_id="approve",
            ),
        )


async def _drain() -> None:
    """Let the fire-and-forget advertise task run to completion."""
    for _ in range(5):
        await asyncio.sleep(0)


def test_build_available_commands_set():
    commands = QwenPawACPAgent._build_available_commands()
    names = {c.name for c in commands}

    # Exactly the curated user-facing subset is advertised. Everything else
    # (history, plan, /new, approval commands, etc.) is intentionally hidden
    # from autocomplete.
    assert names == {"clear", "compact", "skills", "model"}

    # Hidden from the palette: history/plan are internal; /new overlaps the
    # dedicated ACP ``new_session`` affordance (clients start a fresh session
    # natively, and /clear covers the in-session "start over" need).
    assert "history" not in names
    assert "plan" not in names
    assert "new" not in names

    # Commands with a dedicated ACP affordance are not advertised.
    assert names.isdisjoint(_ACP_REDUNDANT_COMMANDS)

    # Every advertised command carries a human-readable description.
    assert all(c.description for c in commands)


async def test_new_session_advertises_commands():
    agent = QwenPawACPAgent(agent_id="default")
    conn = _FakeConn()
    agent.on_connect(conn)

    response = await agent.new_session(cwd="/tmp")
    await _drain()

    assert conn.updates, "expected an available_commands_update notification"
    session_id, update = conn.updates[0]
    assert session_id == response.session_id
    assert update.session_update == "available_commands_update"

    names = {c.name for c in update.available_commands}
    assert "mission" not in names
    assert "clear" in names
    assert "model" in names


async def test_load_session_advertises_commands():
    agent = QwenPawACPAgent(agent_id="default")
    conn = _FakeConn()
    agent.on_connect(conn)

    await agent.load_session(cwd="/tmp", session_id="sess-123")
    await _drain()

    assert conn.updates
    session_id, update = conn.updates[0]
    assert session_id == "sess-123"
    assert update.session_update == "available_commands_update"


async def test_new_session_reports_agent_id_in_meta():
    agent = QwenPawACPAgent(agent_id="my-agent")
    conn = _FakeConn()
    agent.on_connect(conn)

    response = await agent.new_session(cwd="/tmp")
    assert response.field_meta == {ACP_AGENT_META_KEY: "my-agent"}


async def test_prompt_passes_resolved_agent_id_to_runtime(monkeypatch):
    class _FakeWorkspace:
        def __init__(self) -> None:
            self.request = None

        async def stream_query(self, request):
            self.request = request
            if self.request is None:
                yield None

    agent = QwenPawACPAgent(agent_id="my-agent")
    conn = _FakeConn()
    workspace = _FakeWorkspace()
    agent.on_connect(conn)

    async def _fake_workspace():
        return workspace

    monkeypatch.setattr(agent, "_ensure_workspace", _fake_workspace)

    await agent.prompt(
        [{"type": "text", "text": "hello"}],
        session_id="sess-123",
    )

    assert getattr(workspace.request, "agent_id", None) == "my-agent"


async def test_report_prompt_error_is_sent_to_client():
    from qwenpaw.exceptions import AppBaseException

    agent = QwenPawACPAgent(agent_id="default")
    conn = _FakeConn()
    agent.on_connect(conn)

    await agent._report_prompt_error(
        "sess-err",
        AppBaseException("Model configuration is invalid"),
    )

    assert conn.updates
    session_id, update = conn.updates[0]
    assert session_id == "sess-err"
    # Delivered as a visible assistant message chunk with the error text...
    assert update.session_update == "agent_message_chunk"
    assert update.content.text == "Error: Model configuration is invalid"
    # ...tagged via _meta so clients can render it as an error.
    assert update.field_meta == {ACP_ERROR_META_KEY: True}


async def test_report_prompt_error_hides_unexpected_exception_details():
    agent = QwenPawACPAgent(agent_id="default")
    conn = _FakeConn()
    agent.on_connect(conn)

    await agent._report_prompt_error(
        "sess-err",
        RuntimeError("boom: invalid api key secret-token"),
    )

    _, update = conn.updates[0]
    assert "invalid api key" not in update.content.text
    assert "secret-token" not in update.content.text
    assert update.content.text == (
        "Error: QwenPaw failed to process the request. "
        "Check server logs for details."
    )
    assert update.field_meta == {ACP_ERROR_META_KEY: True}


async def test_report_prompt_error_shows_details_for_local_diagnostics():
    agent = QwenPawACPAgent(agent_id="default", local_diagnostics=True)
    conn = _FakeConn()
    agent.on_connect(conn)

    await agent._report_prompt_error(
        "sess-err",
        RuntimeError("boom: invalid api key secret-token"),
    )

    _, update = conn.updates[0]
    assert update.content.text == "Error: boom: invalid api key secret-token"
    assert update.field_meta == {ACP_ERROR_META_KEY: True}


async def test_approval_bridge_resolves_pending_approval(monkeypatch):
    from qwenpaw.app.approvals.service import ApprovalService
    from qwenpaw.security.tool_guard.approval import ApprovalDecision
    from qwenpaw.security.tool_guard.models import (
        GuardFinding,
        GuardSeverity,
        GuardThreatCategory,
        ToolGuardResult,
    )

    approval_svc = ApprovalService()
    monkeypatch.setattr(
        "qwenpaw.app.approvals.service._approval_service",
        approval_svc,
    )

    agent = QwenPawACPAgent(agent_id="default")
    conn = _ApprovalConn()
    agent.on_connect(conn)

    result = ToolGuardResult(
        tool_name="execute_shell_command",
        params={"command": "ls"},
        findings=[
            GuardFinding(
                id="finding-1",
                rule_id="test",
                category=GuardThreatCategory.RESOURCE_ABUSE,
                severity=GuardSeverity.MEDIUM,
                title="Approval required",
                description="Shell command requires approval.",
                tool_name="execute_shell_command",
            ),
        ],
    )
    pending = await approval_svc.create_pending(
        session_id="sess-approval",
        root_session_id="sess-approval",
        owner_agent_id="default",
        user_id="acp_user",
        channel="console",
        agent_id="default",
        tool_name="execute_shell_command",
        result=result,
        extra={
            "tool_call": {
                "id": "tool-1",
                "name": "execute_shell_command",
                "input": {"command": "ls"},
            },
        },
    )

    bridge = asyncio.create_task(
        agent._bridge_approval_requests(
            "sess-approval",
            poll_interval=0.01,
        ),
    )
    try:
        decision = await asyncio.wait_for(pending.future, timeout=1.0)
    finally:
        await agent._stop_approval_bridge(bridge)

    assert decision == ApprovalDecision.APPROVED
    assert conn.permission_requests
    request = conn.permission_requests[0]
    tool_call = request["tool_call"]
    assert request["session_id"] == "sess-approval"
    assert tool_call.title == (
        "execute_shell_command requires approval (MEDIUM)"
    )
    assert tool_call.kind == "execute"
    assert tool_call.raw_input == {"command": "ls"}


def test_acp_bootstrap_includes_runtime_slash_commands():
    from qwenpaw.app.app_services import AppServiceManager

    kwargs = QwenPawACPAgent._build_bootstrap_kwargs(AppServiceManager())
    command_names = {
        spec.name for spec in kwargs.get("builtin_command_specs", [])
    }

    assert {"clear", "compact", "skills", "model"}.issubset(
        command_names,
    )
    assert "mission" not in command_names
    assert kwargs.get("builtin_hook_clses")


def _text_event(text: str, *, delta: bool, msg_id: str = "msg-1"):
    from qwenpaw.schemas import TextContent

    event = TextContent(text=text, delta=delta, index=0)
    event.object = "content"
    event.msg_id = msg_id
    return event


def test_envelope_tracker_forwards_command_final_text():
    tracker = _EnvelopeTracker()

    [update] = tracker.process(
        _text_event("**Current Model**", delta=False),
    )

    assert update.session_update == "agent_message_chunk"
    assert update.content.text == "**Current Model**"


def test_envelope_tracker_does_not_duplicate_streamed_final_text():
    tracker = _EnvelopeTracker()

    [delta_update] = tracker.process(_text_event("hello", delta=True))
    final_updates = tracker.process(_text_event("hello", delta=False))

    assert delta_update.content.text == "hello"
    assert not final_updates


def test_usage_meta_includes_model(monkeypatch):
    from qwenpaw.token_usage.model_wrapper import TokenRecordingModelWrapper

    monkeypatch.setattr(
        TokenRecordingModelWrapper,
        "pop_usage_for_session",
        classmethod(
            lambda cls, _session_id: {
                "model_name": "qwen-plus",
                "prompt_tokens": 12,
                "completion_tokens": 34,
                "total_tokens": 46,
            },
        ),
    )

    assert QwenPawACPAgent._pop_session_usage("sess-usage") == {
        "usage": {
            "inputTokens": 12,
            "outputTokens": 34,
            "totalTokens": 46,
            "model": "qwen-plus",
        },
    }
