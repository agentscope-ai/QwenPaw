# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Unit tests for the mail F1 exploration mode (step-by-step approval).

F1 semantics: once activated for a session, EVERY tool call — built-in
(PolicyGuardedTool path) and MCP/Driver (DriverHandler path) — is gated
to STRICT and requires user approval. When inactive, nothing changes.

F1 state lives in a module-level session registry (NOT a ContextVar):
the tool coordinator runs each tool call in its own asyncio task
(``asyncio.create_task`` copies the context), so a ContextVar written
inside the activation tool would stay isolated in that child task and
never be visible to subsequent tool calls.

The registry also carries the latest "reasoning" text the agent emitted
before each tool call (session_id → text). It is captured by
ToolCoordinatorMiddleware.on_acting from the last assistant message and
injected into approval requests as ``extra["reasoning"]``.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from qwenpaw.config.context import (
    _F1_REASONING_MAX_CHARS,
    _f1_sessions,
    activate_f1_for_session,
    current_session_id,
    deactivate_f1_for_session,
    get_f1_reasoning,
    is_f1_active_for_session,
    set_f1_reasoning,
)
from qwenpaw.drivers.handler import _resolve_driver_execution_level
from qwenpaw.governance import tool_adapter as gov_tool_adapter
from qwenpaw.governance.policy import (
    GovernanceAction,
    GovernanceDecision,
    ToolCallSpec,
)
from qwenpaw.security.tool_guard.execution_level import ToolExecutionLevel
from qwenpaw.tool_calls._middleware import (
    ToolCoordinatorMiddleware,
    _extract_last_assistant_text,
)

_SESSION = "test-session"


@pytest.fixture(autouse=True)
def _reset_f1_registry():
    """Clear the F1 session registry and session_id ContextVar."""
    _f1_sessions.clear()
    token = current_session_id.set(None)
    yield
    _f1_sessions.clear()
    current_session_id.reset(token)


# ---------- 1. Session registry semantics ----------


def test_registry_activation_roundtrip():
    """activate/is_active/deactivate round-trip per session."""
    assert is_f1_active_for_session(_SESSION) is False

    activate_f1_for_session(_SESSION)
    assert is_f1_active_for_session(_SESSION) is True
    # Other sessions are unaffected.
    assert is_f1_active_for_session("other-session") is False

    deactivate_f1_for_session(_SESSION)
    assert is_f1_active_for_session(_SESSION) is False


def test_registry_tolerates_empty_session():
    """Falsy session ids never match and never raise."""
    assert is_f1_active_for_session(None) is False
    assert is_f1_active_for_session("") is False
    deactivate_f1_for_session(None)  # no-op
    deactivate_f1_for_session("")  # no-op


def test_activation_tool_registers_session():
    """The tool must register the session from get_current_session_id."""
    from qwenpaw.agents.tools.mail_f1_tool import (
        activate_f1_exploration_mode,
    )

    async def _run() -> Any:
        current_session_id.set(_SESSION)
        return await activate_f1_exploration_mode()

    chunk = asyncio.run(_run())
    assert chunk.is_last is True
    assert is_f1_active_for_session(_SESSION) is True
    assert chunk.content[0].text.startswith("F1 Exploration Mode is active.")
    assert "The system automatically intercepts every tool call" in (
        chunk.content[0].text
    )


def test_activation_tool_without_session_id_is_safe():
    """No session_id in context → warning path, nothing registered."""
    from qwenpaw.agents.tools.mail_f1_tool import (
        activate_f1_exploration_mode,
    )

    async def _run() -> Any:
        current_session_id.set(None)
        return await activate_f1_exploration_mode()

    chunk = asyncio.run(_run())
    assert chunk.is_last is True
    assert "Failed to activate F1 Exploration Mode" in chunk.content[0].text
    assert "do not perform any action if uncertain" in chunk.content[0].text
    assert not _f1_sessions


# ---------- Helpers for the PolicyGuardedTool path ----------


class _FakePolicy:
    def __init__(self, execution_level: str = "smart") -> None:
        self.execution_level = execution_level


class _FakeGovernor:
    """Mimics ResourceGovernor: STRICT → ASK for every tool, else ALLOW."""

    def __init__(self, execution_level: str = "smart") -> None:
        self.policy = _FakePolicy(execution_level)
        self.seen_levels: list[str] = []

    def assert_policy(self, _tc_spec: ToolCallSpec) -> GovernanceDecision:
        self.seen_levels.append(self.policy.execution_level)
        if self.policy.execution_level == "strict":
            return GovernanceDecision(
                action=GovernanceAction.ASK,
                reason="STRICT mode: all tool calls require approval",
            )
        return GovernanceDecision(
            action=GovernanceAction.ALLOW,
            reason="allowed",
        )

    def audit(self, tc_spec: ToolCallSpec, decision: Any) -> None:
        pass


def _make_tool(governor, request_context=None, name="edit_file"):
    """Build a minimal stand-in for a PolicyGuardedTool instance."""
    tc_spec = ToolCallSpec(
        tool_name=name,
        target="",
        agent_id="",
        session_id="",
        raw_params={},
    )
    return SimpleNamespace(
        name=name,
        _qp_governor=governor,
        _qp_request_context=dict(request_context or {}),
        _build_tc_spec=lambda: tc_spec,
    )


@pytest.fixture()
def _stub_ask_approval(monkeypatch):
    """Replace the blocking approval flow with a recognisable sentinel."""
    from agentscope.permission import PermissionBehavior, PermissionDecision

    calls = []

    async def _fake_ask(**kwargs):
        calls.append(kwargs)
        return PermissionDecision(
            behavior=PermissionBehavior.ASK,
            message="sentinel: approval requested",
        )

    monkeypatch.setattr(gov_tool_adapter, "_ask_user_approval", _fake_ask)
    return calls


# ---------- 2. PolicyGuardedTool: F1 gates ALL tools ----------


@pytest.mark.parametrize(
    "tool_name",
    ["edit_file", "read_file", "qwenpawmail__reply_message", "browser_use"],
)
def test_policy_tool_gates_all_tools_when_f1_active(
    _stub_ask_approval,
    tool_name,
):
    """With F1 active, every tool must be evaluated under STRICT → ASK."""
    activate_f1_for_session(_SESSION)

    governor = _FakeGovernor(execution_level="smart")
    tool = _make_tool(
        governor,
        request_context={"session_id": _SESSION},
        name=tool_name,
    )

    decision = asyncio.run(
        gov_tool_adapter._policy_tool_check_permissions(tool, {}),
    )

    # Evaluation ran under STRICT and routed to the approval flow.
    assert governor.seen_levels == ["strict"]
    assert len(_stub_ask_approval) == 1
    assert "approval requested" in decision.message
    # The pre-F1 level must be restored (no leak into later requests).
    assert governor.policy.execution_level == "smart"


def test_policy_tool_session_id_fallback_to_contextvar(_stub_ask_approval):
    """Without session_id in request_context, the ContextVar is used."""
    activate_f1_for_session(_SESSION)

    governor = _FakeGovernor(execution_level="smart")
    tool = _make_tool(governor, name="edit_file")

    async def _run() -> Any:
        current_session_id.set(_SESSION)
        return await gov_tool_adapter._policy_tool_check_permissions(
            tool,
            {},
        )

    decision = asyncio.run(_run())
    assert governor.seen_levels == ["strict"]
    assert "approval requested" in decision.message


def test_policy_tool_f1_overrides_off_level(_stub_ask_approval):
    """F1 must override approval_level=off (no silent allow-all)."""
    activate_f1_for_session(_SESSION)

    governor = _FakeGovernor(execution_level="smart")
    tool = _make_tool(
        governor,
        request_context={"approval_level": "off", "session_id": _SESSION},
        name="qwenpawmail__send_message",
    )

    decision = asyncio.run(
        gov_tool_adapter._policy_tool_check_permissions(tool, {}),
    )

    assert governor.seen_levels == ["strict"]
    assert "approval requested" in decision.message


# ---------- 3. PolicyGuardedTool: unaffected when F1 inactive ----------


def test_policy_tool_normal_when_f1_inactive(_stub_ask_approval):
    """Without F1, evaluation uses the governor's own level (ALLOW here)."""
    from agentscope.permission import PermissionBehavior

    governor = _FakeGovernor(execution_level="smart")
    tool = _make_tool(
        governor,
        request_context={"session_id": _SESSION},
        name="qwenpawmail__reply_message",
    )

    decision = asyncio.run(
        gov_tool_adapter._policy_tool_check_permissions(tool, {}),
    )

    assert decision.behavior == PermissionBehavior.ALLOW
    assert governor.seen_levels == ["smart"]
    assert not _stub_ask_approval


def test_policy_tool_normal_after_deactivate(_stub_ask_approval):
    """deactivate_f1_for_session restores the normal approval flow."""
    from agentscope.permission import PermissionBehavior

    activate_f1_for_session(_SESSION)
    deactivate_f1_for_session(_SESSION)

    governor = _FakeGovernor(execution_level="smart")
    tool = _make_tool(
        governor,
        request_context={"session_id": _SESSION},
        name="edit_file",
    )

    decision = asyncio.run(
        gov_tool_adapter._policy_tool_check_permissions(tool, {}),
    )

    assert decision.behavior == PermissionBehavior.ALLOW
    assert governor.seen_levels == ["smart"]
    assert not _stub_ask_approval


# ---------- 4. Driver/MCP path: F1 forces STRICT ----------


def test_driver_level_strict_when_f1_active():
    """MCP tools resolve to STRICT while F1 is active for the session."""
    activate_f1_for_session(_SESSION)

    level = _resolve_driver_execution_level({"session_id": _SESSION})
    assert level is ToolExecutionLevel.STRICT
    assert level.requires_approval_for_all_tools() is True


def test_driver_level_session_id_fallback_to_contextvar():
    """Without session_id in request_context, the ContextVar is used."""
    activate_f1_for_session(_SESSION)

    async def _run() -> ToolExecutionLevel:
        current_session_id.set(_SESSION)
        return _resolve_driver_execution_level({})

    level = asyncio.run(_run())
    assert level is ToolExecutionLevel.STRICT


def test_driver_level_f1_overrides_off():
    """F1 overrides an explicit approval_level=off in request_context."""
    activate_f1_for_session(_SESSION)

    level = _resolve_driver_execution_level(
        {"approval_level": "off", "session_id": _SESSION},
    )
    assert level is ToolExecutionLevel.STRICT


def test_driver_level_normal_when_f1_inactive():
    """Without F1, request_context approval_level is honoured."""
    level = _resolve_driver_execution_level(
        {"approval_level": "auto", "session_id": _SESSION},
    )
    assert level is ToolExecutionLevel.AUTO

    level = _resolve_driver_execution_level(
        {"approval_level": "off", "session_id": _SESSION},
    )
    assert level is ToolExecutionLevel.OFF


def test_driver_level_normal_after_deactivate():
    """deactivate restores request_context approval_level resolution."""
    activate_f1_for_session(_SESSION)
    deactivate_f1_for_session(_SESSION)

    level = _resolve_driver_execution_level(
        {"approval_level": "auto", "session_id": _SESSION},
    )
    assert level is ToolExecutionLevel.AUTO


# ---------- 5. create_task isolation (the real production scenario) ----------


def test_activation_survives_create_task_isolation(_stub_ask_approval):
    """Activation inside a per-tool child task must be visible outside.

    Mirrors production: ToolCoordinator.execute() wraps every tool call
    in ``asyncio.create_task``, which copies the contextvars context.
    The old ContextVar mechanism passed same-coroutine tests but failed
    here — the flag never propagated back to the parent task. The
    session registry must survive this isolation.
    """
    from qwenpaw.agents.tools.mail_f1_tool import (
        activate_f1_exploration_mode,
    )

    async def _run() -> tuple[Any, ToolExecutionLevel]:
        # PRE_DISPATCH sets session_id before any tool task is spawned,
        # so child tasks inherit it via the copied context.
        current_session_id.set(_SESSION)

        # Tool call #1: activation runs in its own child task.
        await asyncio.create_task(activate_f1_exploration_mode())

        # Parent task must see the activation.
        assert is_f1_active_for_session(_SESSION) is True

        # Tool call #2 (another child task): PolicyGuardedTool path.
        governor = _FakeGovernor(execution_level="smart")
        tool = _make_tool(
            governor,
            request_context={"session_id": _SESSION},
            name="qwenpawmail__reply_message",
        )
        policy_decision = await asyncio.create_task(
            gov_tool_adapter._policy_tool_check_permissions(tool, {}),
        )
        assert governor.seen_levels == ["strict"]

        # Tool call #3 (another child task): Driver/MCP path.
        driver_level = await asyncio.create_task(_driver_level_task())
        return policy_decision, driver_level

    async def _driver_level_task() -> ToolExecutionLevel:
        return _resolve_driver_execution_level({"session_id": _SESSION})

    decision, level = asyncio.run(_run())
    assert "approval requested" in decision.message
    assert level is ToolExecutionLevel.STRICT


# ---------- 6. Reasoning registry (session_id → latest reason) ----------


def test_reasoning_empty_right_after_activation():
    """Activation seeds an empty reasoning string."""
    activate_f1_for_session(_SESSION)
    assert get_f1_reasoning(_SESSION) == ""


def test_reasoning_set_get_roundtrip():
    """set_f1_reasoning stores (stripped) text for the active session."""
    activate_f1_for_session(_SESSION)
    set_f1_reasoning(_SESSION, "  我想再仔细阅读一下这封邮件  ")
    assert get_f1_reasoning(_SESSION) == "我想再仔细阅读一下这封邮件"

    # A later reason replaces the earlier one.
    set_f1_reasoning(_SESSION, "现在需要回复发件人")
    assert get_f1_reasoning(_SESSION) == "现在需要回复发件人"


def test_reasoning_truncated_to_max_chars():
    """Overlong text is stripped first, then truncated to 200 chars."""
    activate_f1_for_session(_SESSION)
    long_text = "  " + "x" * (_F1_REASONING_MAX_CHARS + 300) + "  "
    set_f1_reasoning(_SESSION, long_text)

    stored = get_f1_reasoning(_SESSION)
    assert len(stored) == _F1_REASONING_MAX_CHARS
    assert stored == "x" * _F1_REASONING_MAX_CHARS


def test_reasoning_set_is_noop_for_inactive_session():
    """set on a session without F1 must not register anything."""
    set_f1_reasoning(_SESSION, "should be dropped")
    assert get_f1_reasoning(_SESSION) == ""
    assert _SESSION not in _f1_sessions
    # Falsy session ids never raise.
    set_f1_reasoning(None, "ignored")
    set_f1_reasoning("", "ignored")
    assert get_f1_reasoning(None) == ""
    assert get_f1_reasoning("") == ""


def test_reasoning_cleared_after_deactivate():
    """deactivate drops the session entry, so get returns ''."""
    activate_f1_for_session(_SESSION)
    set_f1_reasoning(_SESSION, "some reason")
    deactivate_f1_for_session(_SESSION)
    assert get_f1_reasoning(_SESSION) == ""


# ---------- 7. Middleware: _extract_last_assistant_text ----------


def _agent_with_context(context: Any) -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(context=context))


def test_extract_text_from_dict_blocks():
    """Plain-dict content blocks: only the trailing text run counts."""
    msg = SimpleNamespace(
        role="assistant",
        content=[
            {"type": "text", "text": " 我想先读取"},
            {"type": "tool_use", "name": "read_file"},
            {"type": "text", "text": "这封邮件 "},
        ],
    )
    agent = _agent_with_context([msg])
    assert _extract_last_assistant_text(agent) == "这封邮件"


def test_extract_text_accumulated_message_returns_last_step_reason():
    """Accumulated assistant message → only the latest step's reason."""
    msg = SimpleNamespace(
        role="assistant",
        content=[
            {"type": "text", "text": "分诊分析：" + "长文本" * 100},
            {"type": "tool_use", "name": "get_message"},
            {"type": "text", "text": "理由1"},
            {"type": "tool_use", "name": "edit_file"},
            {"type": "text", "text": "理由2"},
        ],
    )
    agent = _agent_with_context([msg])
    assert _extract_last_assistant_text(agent) == "理由2"


def test_extract_text_joins_consecutive_trailing_text_blocks():
    """Multiple text blocks of the current turn are newline-joined."""
    msg = SimpleNamespace(
        role="assistant",
        content=[
            {"type": "text", "text": "text A"},
            {"type": "tool_use", "name": "get_message"},
            {"type": "text", "text": "B1"},
            {"type": "text", "text": "B2"},
        ],
    )
    agent = _agent_with_context([msg])
    assert _extract_last_assistant_text(agent) == "B1\nB2"


def test_extract_text_skips_trailing_tool_use_block():
    """First round: text A + trailing tool_use → text A is the reason."""
    msg = SimpleNamespace(
        role="assistant",
        content=[
            {"type": "text", "text": "text A"},
            {"type": "tool_use", "name": "get_message"},
        ],
    )
    agent = _agent_with_context([msg])
    assert _extract_last_assistant_text(agent) == "text A"


def test_extract_text_handles_agentscope_tool_call_blocks():
    """agentscope ToolCallBlock uses type='tool_call' (not 'tool_use')."""
    msg = SimpleNamespace(
        role="assistant",
        content=[
            {"type": "text", "text": "分诊分析长文本"},
            {"type": "tool_call", "name": "get_message"},
            {"type": "text", "text": "当步理由"},
            {"type": "tool_call", "name": "edit_file"},
        ],
    )
    agent = _agent_with_context([msg])
    assert _extract_last_assistant_text(agent) == "当步理由"


def test_extract_text_empty_when_trailing_tool_result_has_no_text():
    """tool_result at the end with no text after it → '' (keep previous)."""
    msg = SimpleNamespace(
        role="assistant",
        content=[
            {"type": "text", "text": "旧理由"},
            {"type": "tool_result", "output": "ok"},
        ],
    )
    agent = _agent_with_context([msg])
    assert _extract_last_assistant_text(agent) == ""


def test_extract_text_from_object_blocks():
    """Pydantic-style block objects (attribute access) are supported."""
    msg = SimpleNamespace(
        role="assistant",
        content=[SimpleNamespace(type="text", text="调用理由文本")],
    )
    agent = _agent_with_context([msg])
    assert _extract_last_assistant_text(agent) == "调用理由文本"


def test_extract_text_from_plain_string_content():
    """A plain string content is returned stripped."""
    msg = SimpleNamespace(role="assistant", content="  纯字符串理由  ")
    agent = _agent_with_context([msg])
    assert _extract_last_assistant_text(agent) == "纯字符串理由"


def test_extract_text_returns_empty_when_last_is_not_assistant():
    """Only a trailing assistant message counts."""
    msg = SimpleNamespace(role="user", content="user says hi")
    agent = _agent_with_context([msg])
    assert _extract_last_assistant_text(agent) == ""


def test_extract_text_returns_empty_for_empty_context():
    """Empty context yields '' without raising."""
    agent = _agent_with_context([])
    assert _extract_last_assistant_text(agent) == ""


def test_extract_text_tolerates_missing_state():
    """An agent without .state must not raise."""
    assert _extract_last_assistant_text(object()) == ""


def test_extract_text_tolerates_none_content():
    """role=assistant with content=None yields ''."""
    msg = SimpleNamespace(role="assistant", content=None)
    agent = _agent_with_context([msg])
    assert _extract_last_assistant_text(agent) == ""


# ---------- 8. Middleware: on_acting captures reasoning ----------


class _FakeCoordinator:
    """Minimal ToolCoordinator stand-in: records kwargs, yields once."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def execute(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        yield "tool-result"


def _drive_on_acting(agent: Any) -> tuple[_FakeCoordinator, list[Any]]:
    """Run the middleware's on_acting to completion for one tool call."""
    coordinator = _FakeCoordinator()
    middleware = ToolCoordinatorMiddleware(coordinator)

    async def _run() -> list[Any]:
        items = []
        async for item in middleware.on_acting(
            agent,
            {"tool_call": {"id": "tc-1", "name": "edit_file"}},
            next_handler=None,
        ):
            items.append(item)
        return items

    return coordinator, asyncio.run(_run())


def test_on_acting_captures_reasoning_when_f1_active():
    """F1 active → last assistant text lands in the session registry."""
    activate_f1_for_session(_SESSION)

    msg = SimpleNamespace(
        role="assistant",
        content=[{"type": "text", "text": "我想先读取这封邮件的正文"}],
    )
    agent = SimpleNamespace(
        _request_context={"session_id": _SESSION},
        state=SimpleNamespace(context=[msg]),
    )

    coordinator, items = _drive_on_acting(agent)

    assert get_f1_reasoning(_SESSION) == "我想先读取这封邮件的正文"
    # The tool call itself still flows through the coordinator.
    assert items == ["tool-result"]
    assert coordinator.calls[0]["session_id"] == _SESSION


def test_on_acting_does_not_capture_when_f1_inactive():
    """Without F1, on_acting must not register the session."""
    msg = SimpleNamespace(
        role="assistant",
        content=[{"type": "text", "text": "should not be stored"}],
    )
    agent = SimpleNamespace(
        _request_context={"session_id": _SESSION},
        state=SimpleNamespace(context=[msg]),
    )

    _coordinator, items = _drive_on_acting(agent)

    assert items == ["tool-result"]
    assert _SESSION not in _f1_sessions
    assert get_f1_reasoning(_SESSION) == ""


def test_on_acting_keeps_previous_reasoning_when_no_assistant_text():
    """Empty extraction must not overwrite the previous reason."""
    activate_f1_for_session(_SESSION)
    set_f1_reasoning(_SESSION, "上一次的理由")

    # Last message is not an assistant message → extraction yields "".
    msg = SimpleNamespace(role="tool", content="tool result")
    agent = SimpleNamespace(
        _request_context={"session_id": _SESSION},
        state=SimpleNamespace(context=[msg]),
    )

    _coordinator, items = _drive_on_acting(agent)

    assert items == ["tool-result"]
    assert get_f1_reasoning(_SESSION) == "上一次的理由"


def test_on_acting_refreshes_reasoning_per_step():
    """Two on_acting calls on a growing message → two distinct reasons."""
    activate_f1_for_session(_SESSION)

    content: list[dict[str, Any]] = [
        {"type": "text", "text": "首步理由：先读取邮件"},
        {"type": "tool_use", "name": "get_message"},
    ]
    msg = SimpleNamespace(role="assistant", content=content)
    agent = SimpleNamespace(
        _request_context={"session_id": _SESSION},
        state=SimpleNamespace(context=[msg]),
    )

    _drive_on_acting(agent)
    assert get_f1_reasoning(_SESSION) == "首步理由：先读取邮件"

    # agentscope extends the same assistant message on the next turn.
    content.append({"type": "text", "text": "第二步理由：现在需要回复"})
    content.append({"type": "tool_use", "name": "reply_message"})

    _drive_on_acting(agent)
    assert get_f1_reasoning(_SESSION) == "第二步理由：现在需要回复"


def test_on_reasoning_captures_reasoning_after_stream():
    """on_reasoning refreshes the registry once the stream completes."""
    activate_f1_for_session(_SESSION)

    msg = SimpleNamespace(
        role="assistant",
        content=[
            {"type": "text", "text": "当步理由：准备写入文件"},
            {"type": "tool_call", "name": "write_file"},
        ],
    )
    agent = SimpleNamespace(
        _request_context={"session_id": _SESSION},
        state=SimpleNamespace(context=[msg]),
    )
    middleware = ToolCoordinatorMiddleware(_FakeCoordinator())

    async def next_handler():
        yield "model-event"

    async def _run() -> list[Any]:
        return [
            item
            async for item in middleware.on_reasoning(agent, {}, next_handler)
        ]

    items = asyncio.run(_run())
    assert items == ["model-event"]
    assert get_f1_reasoning(_SESSION) == "当步理由：准备写入文件"


# ---------- 9. Reasoning injected into approval requests ----------


class _FakeApprovalService:
    """Captures create_pending/create_pending_summary kwargs."""

    def __init__(self, decision: Any) -> None:
        self.pending_kwargs: list[dict[str, Any]] = []
        self._decision = decision

    async def cancel_stale_pending_for_tool_call(
        self,
        *_args: Any,
        **_kwargs: Any,
    ) -> None:
        return None

    async def create_pending(self, **kwargs: Any) -> Any:
        self.pending_kwargs.append(kwargs)
        return SimpleNamespace(request_id="req-00000001")

    async def create_pending_summary(self, **kwargs: Any) -> Any:
        self.pending_kwargs.append(kwargs)
        return SimpleNamespace(request_id="req-00000001")

    async def wait_for_approval(
        self,
        _request_id: Any,
        _timeout: Any,
    ) -> Any:
        return self._decision


def _install_fake_approval_service(monkeypatch, decision):
    """Patch get_approval_service (both call sites import it lazily)."""
    import qwenpaw.app.approvals as approvals_pkg

    svc = _FakeApprovalService(decision)
    monkeypatch.setattr(approvals_pkg, "get_approval_service", lambda: svc)
    return svc


def _patch_generalize(monkeypatch):
    """Skip the (potentially model-backed) target generalization."""
    import qwenpaw.governance.generalize as generalize_mod

    async def _identity(
        _tool_name,
        target,
        _source,
        agent_id=None,
    ):
        del agent_id
        return target

    monkeypatch.setattr(
        generalize_mod,
        "generalize_target_for_approval",
        _identity,
    )


def _run_ask_user_approval(monkeypatch) -> _FakeApprovalService:
    """Drive the real _ask_user_approval against the fake service."""
    from qwenpaw.security.tool_guard.approval import ApprovalDecision

    svc = _install_fake_approval_service(monkeypatch, ApprovalDecision.DENIED)
    _patch_generalize(monkeypatch)

    governor = _FakeGovernor(execution_level="smart")
    tc_spec = ToolCallSpec(
        tool_name="edit_file",
        target="/ws/a.txt",
        agent_id="agent",
        session_id=_SESSION,
        raw_params={"path": "/ws/a.txt"},
    )
    decision = asyncio.run(
        gov_tool_adapter._ask_user_approval(
            governor,
            tc_spec,
            {"session_id": _SESSION},
        ),
    )

    from agentscope.permission import PermissionBehavior

    assert decision.behavior == PermissionBehavior.DENY
    assert len(svc.pending_kwargs) == 1
    return svc


def test_ask_user_approval_injects_reasoning(monkeypatch):
    """PolicyGuardedTool approval carries extra['reasoning'] when set."""
    activate_f1_for_session(_SESSION)
    set_f1_reasoning(_SESSION, "我想先读取这封邮件")

    svc = _run_ask_user_approval(monkeypatch)
    extra = svc.pending_kwargs[0]["extra"]
    assert extra["reasoning"] == "我想先读取这封邮件"


def test_ask_user_approval_reasoning_empty_when_f1_inactive(monkeypatch):
    """Without F1, extra['reasoning'] is present but empty."""
    svc = _run_ask_user_approval(monkeypatch)
    extra = svc.pending_kwargs[0]["extra"]
    assert extra["reasoning"] == ""


def _run_driver_gate(monkeypatch) -> _FakeApprovalService:
    """Drive the real QwenPawDriverApprovalGate.request_approval."""
    from qwenpaw.app.approvals.driver_gate import QwenPawDriverApprovalGate
    from qwenpaw.drivers.policy import DriverInvocationContext
    from qwenpaw.security.tool_guard.approval import ApprovalDecision

    svc = _install_fake_approval_service(
        monkeypatch,
        ApprovalDecision.APPROVED,
    )

    gate = QwenPawDriverApprovalGate()
    context = DriverInvocationContext(
        subject="tool:reply_message",
        driver_name="qwenpawmail",
        protocol="mcp",
        request_context={"session_id": _SESSION},
    )
    # APPROVED → returns without raising (wait_for_approval is awaited).
    asyncio.run(gate.request_approval(context))

    assert len(svc.pending_kwargs) == 1
    return svc


def test_driver_gate_injects_reasoning(monkeypatch):
    """Driver approval summary carries extra['reasoning'] when set."""
    activate_f1_for_session(_SESSION)
    set_f1_reasoning(_SESSION, "需要通过驱动回复这封邮件")

    svc = _run_driver_gate(monkeypatch)
    extra = svc.pending_kwargs[0]["extra"]
    assert extra["reasoning"] == "需要通过驱动回复这封邮件"


def test_driver_gate_reasoning_empty_when_f1_inactive(monkeypatch):
    """Without F1, the driver gate sends an empty reasoning string."""
    svc = _run_driver_gate(monkeypatch)
    extra = svc.pending_kwargs[0]["extra"]
    assert extra["reasoning"] == ""
