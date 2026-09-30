# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
"""Plugin policy precedence, bounded execution, ownership, and audit tests."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from qwenpaw.governance.audit import AuditLog
from qwenpaw.governance.policy import (
    GovernanceAction as Action,
    GovernanceDecision,
)
from qwenpaw.governance.tool_policy import apply_tool_policy_hooks
from qwenpaw.governance.resource_governor import ResourceGovernor
from qwenpaw.plugins import PluginApi, PluginRegistry, PolicyHint, ToolCallSpec


@pytest.fixture
def registry(monkeypatch):
    monkeypatch.setattr(PluginRegistry, "_instance", None)
    return PluginRegistry()


def _register(registry, name, callback, plugin_id="risk", **kwargs):
    api = PluginApi(plugin_id, {})
    api.set_registry(registry)
    api.register_tool_policy_hook(name, callback, **kwargs)


def _spec():
    return ToolCallSpec(
        "Bash",
        "git status",
        "agent-1",
        "session-1",
        {"command": "git status", "nested": {"value": 1}},
    )


async def _apply(registry, action=Action.ALLOW):
    return await apply_tool_policy_hooks(
        _spec(),
        GovernanceDecision(action, "static rule", source="user_rules"),
        registry.get_tool_policy_hooks(),
    )


@pytest.mark.parametrize("static", list(Action))
@pytest.mark.parametrize("hint", [None, "allow", "ask", "deny"])
async def test_escalation_matrix(registry, static, hint):
    callback = AsyncMock(return_value=PolicyHint(hint, "plugin reason"))
    _register(registry, "gate", callback)
    result = await _apply(registry, static)
    expected = static
    if static is not Action.DENY:
        if hint == "deny":
            expected = Action.DENY
        elif hint == "ask" and static is not Action.ASK:
            expected = Action.ASK
    assert result.action is expected
    if static is Action.DENY:
        callback.assert_not_called()
        assert result.reason == "static rule"
    elif result.action is not static:
        assert result.reason == "plugin reason"
        assert result.source == "plugin:risk/gate"
    else:
        assert result.source == "user_rules"


async def test_priority_stable_ties_and_first_deny_wins(registry):
    calls = []

    def callback(name, action):
        async def decide(_spec):
            calls.append(name)
            return PolicyHint(action, name)

        return decide

    _register(registry, "late", callback("late", "deny"), priority=90)
    _register(registry, "first", callback("first", "ask"), priority=10)
    _register(registry, "tie", callback("tie", "ask"), priority=10)
    _register(registry, "deny", callback("deny", "deny"), priority=50)
    result = await _apply(registry)
    assert calls == ["first", "tie", "deny"]
    assert result.action is Action.DENY
    assert result.reason == "deny"
    assert len(result.extra["tool_policy"]["hooks"]) == 3


async def test_first_ask_wins_and_allow_does_not_override_it(registry):
    for name, action in [("first", "ask"), ("later", "ask"), ("ok", "allow")]:
        _register(
            registry,
            name,
            AsyncMock(return_value=PolicyHint(action, name)),
        )
    result = await _apply(registry)
    assert result.action is Action.ASK
    assert result.reason == "first"


async def test_empty_chain_preserves_decision_identity(registry):
    decision = GovernanceDecision(Action.SANDBOX_FALLBACK, "sandbox")
    result = await apply_tool_policy_hooks(_spec(), decision, [])
    assert result is decision
    assert not registry.get_tool_policy_hooks()


@pytest.mark.parametrize("fail", ["open", "closed"])
@pytest.mark.parametrize(
    "failure",
    ["exception", "timeout", "invalid", "self_cancel"],
)
async def test_callback_failures_follow_registered_mode(
    registry,
    fail,
    failure,
):
    async def decide(_spec):
        if failure == "exception":
            raise ValueError("secret must not enter the audit log")
        if failure == "timeout":
            await asyncio.sleep(60)
        if failure == "self_cancel":
            raise asyncio.CancelledError
        return {"action": "allow"}

    _register(registry, "gate", decide, fail=fail, timeout_s=0.01)
    result = await asyncio.wait_for(_apply(registry), timeout=1)
    assert result.action is (Action.DENY if fail == "closed" else Action.ALLOW)
    record = result.extra["tool_policy"]["hooks"][0]
    assert record["status"] == ("timeout" if failure == "timeout" else "error")
    assert "secret" not in record["reason"]


async def test_timeout_does_not_wait_for_callback_cancellation(registry):
    release = asyncio.Event()
    finished = asyncio.Event()

    async def decide(_spec):
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError as exc:
            await release.wait()
            raise ValueError("late failure") from exc
        finally:
            finished.set()

    _register(registry, "slow", decide, fail="closed", timeout_s=0.01)
    try:
        result = await asyncio.wait_for(_apply(registry), timeout=1)
        assert result.action is Action.DENY
    finally:
        release.set()
        await asyncio.wait_for(finished.wait(), timeout=1)


async def test_request_cancellation_propagates_and_cancels_hook(registry):
    started = asyncio.Event()
    finished = asyncio.Event()

    async def decide(_spec):
        started.set()
        try:
            await asyncio.sleep(60)
        finally:
            finished.set()

    _register(registry, "gate", decide, timeout_s=10)
    task = asyncio.create_task(_apply(registry))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.wait_for(finished.wait(), timeout=1)


@pytest.mark.parametrize(
    "hint",
    [
        PolicyHint("invalid"),  # type: ignore[arg-type]
        PolicyHint("ask", reason=1),  # type: ignore[arg-type]
        PolicyHint(metadata={"bad": object()}),
        PolicyHint(metadata={"bad": float("nan")}),
        PolicyHint(metadata=[]),  # type: ignore[arg-type]
    ],
)
async def test_invalid_hints_fail_closed(registry, hint):
    _register(registry, "gate", AsyncMock(return_value=hint), fail="closed")
    result = await _apply(registry)
    assert result.action is Action.DENY
    assert result.extra["tool_policy"]["hooks"][0]["status"] == "error"


async def test_hooks_cannot_mutate_checked_params_or_each_other(registry):
    original = _spec()

    async def mutate(spec):
        spec.raw_params["nested"]["value"] = 99
        spec.target = "different command"
        return None

    observer = AsyncMock(return_value=PolicyHint(metadata={"score": 0.2}))
    _register(registry, "mutate", mutate)
    _register(registry, "observe", observer)
    await apply_tool_policy_hooks(
        original,
        GovernanceDecision(Action.ALLOW, "ok"),
        registry.get_tool_policy_hooks(),
    )
    observed = observer.call_args.args[0]
    assert original.raw_params["nested"]["value"] == 1
    assert observed.raw_params["nested"]["value"] == 1
    assert observed.target == original.target == "git status"


async def test_audit_round_trip_includes_abstention_and_metadata(
    registry,
    tmp_path,
):
    metadata = {"verdict_id": "v-123", "risk": 0.45}
    _register(registry, "abstain", AsyncMock(return_value=None))
    _register(
        registry,
        "gate",
        AsyncMock(return_value=PolicyHint("ask", "review", metadata)),
    )
    result = await _apply(registry)
    metadata["risk"] = 1
    audit = AuditLog._create(tmp_path / "audit.db")
    try:
        audit.record(str(tmp_path), _spec(), result)
        events, total = audit.query()
        assert total == 1
        details = events[0].extra["tool_policy"]
        assert details["static_action"] == "allow"
        assert details["hooks"][0]["action"] is None
        assert details["hooks"][1]["metadata"]["risk"] == 0.45
        assert events[0].decision == "ask"
    finally:
        audit.close()


def test_ownership_replacement_and_unload(registry):
    callback = AsyncMock(return_value=None)
    _register(registry, "shared-name", callback)
    _register(registry, "shared-name", callback, priority=5)
    _register(registry, "shared-name", callback, plugin_id="other")
    hooks = registry.get_tool_policy_hooks()
    assert len(hooks) == 2
    assert hooks[0].priority == 5
    hooks.clear()
    assert len(registry.get_tool_policy_hooks()) == 2
    registry.unregister_plugin("risk")
    assert [h.plugin_id for h in registry.get_tool_policy_hooks()] == ["other"]
    registry.remove_hooks_by_name("other", ["shared-name"])
    assert not registry.get_tool_policy_hooks()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"timeout_s": 0},
        {"timeout_s": -1},
        {"timeout_s": float("inf")},
        {"timeout_s": float("nan")},
        {"timeout_s": True},
        {"fail": "ignore"},
        {"priority": "first"},
    ],
)
def test_registration_rejects_invalid_options(registry, kwargs):
    with pytest.raises(ValueError):
        _register(registry, "gate", AsyncMock(), **kwargs)
    assert not registry.get_tool_policy_hooks()


def test_registration_rejects_sync_callback(registry):
    with pytest.raises(TypeError, match="async"):
        _register(registry, "gate", lambda _spec: None)


@pytest.mark.parametrize("static", [Action.ALLOW, Action.SANDBOX_FALLBACK])
@pytest.mark.parametrize("f1_active", [False, True])
@pytest.mark.parametrize("request_level", ["auto", None])
async def test_adapter_asks_with_context_and_retains_sandbox(
    registry,
    monkeypatch,
    static,
    f1_active,
    request_level,
):
    from agentscope.permission import PermissionBehavior, PermissionDecision
    from qwenpaw.governance import tool_adapter

    sandbox = object() if static is Action.SANDBOX_FALLBACK else None
    governor = MagicMock(spec=ResourceGovernor)
    governor_level = "auto" if request_level else "smart"
    governor.policy = SimpleNamespace(execution_level=governor_level)
    governor.workspace_dir = "/tmp/workspace"
    governor.coding_project_dir = "/tmp/project"
    governor.assert_policy.return_value = GovernanceDecision(
        static,
        "static reason",
        sandbox_config=sandbox,
    )
    callback = AsyncMock(return_value=PolicyHint("ask", "cost ceiling"))
    _register(registry, "cost", callback)
    approval = AsyncMock(
        return_value=PermissionDecision(
            behavior=PermissionBehavior.ALLOW,
            message="Approved",
        ),
    )
    monkeypatch.setattr(tool_adapter, "_ask_user_approval", approval)
    monkeypatch.setattr(
        "qwenpaw.config.context.is_f1_active_for_session",
        lambda _session_id: f1_active,
    )
    if request_level is None:
        monkeypatch.setattr(
            tool_adapter,
            "_resolve_effective_approval_level",
            lambda _context: None,
        )

    async def execute_shell_command(command: str):
        """Test shell tool."""
        return command

    context = {
        "agent_id": "a",
        "session_id": "s",
        "root_session_id": "root",
        "approval_level": request_level,
    }
    tool = tool_adapter.PolicyGuardedTool(
        execute_shell_command,
        governor=governor,
        request_context=context,
    )
    result = await tool.check_permissions({"command": "git status"})
    assert result.behavior is PermissionBehavior.ALLOW
    spec = callback.call_args.args[0]
    assert (spec.tool_name, spec.agent_id, spec.session_id) == (
        "Bash",
        "a",
        "s",
    )
    assert spec.raw_params == {"command": "git status"}
    assert spec.schema_version == 1
    assert spec.approval_level == ("strict" if f1_active else governor_level)
    assert governor.policy.execution_level == governor_level
    assert approval.call_args.kwargs["request_context"] == context
    assert approval.call_args.kwargs["governance_reason"] == "cost ceiling"
    assert governor.audit.call_args.args[1].action is Action.ASK
    assert tool._qp_sandbox_mode is (sandbox is not None)
    if sandbox is not None:
        assert tool._qp_sandbox_config is sandbox


async def test_off_mode_keeps_existing_bypass(registry):
    from qwenpaw.governance.tool_adapter import PolicyGuardedTool

    callback = AsyncMock(return_value=PolicyHint("deny"))
    _register(registry, "gate", callback)
    governor = MagicMock(spec=ResourceGovernor)

    async def read_file(file_path: str):
        """Test read tool."""
        return file_path

    tool = PolicyGuardedTool(
        read_file,
        governor=governor,
        request_context={"approval_level": "off"},
    )
    result = await tool.check_permissions({"file_path": "file.txt"})
    assert result.behavior.value == "allow"
    callback.assert_not_called()
    governor.assert_policy.assert_not_called()


@pytest.mark.parametrize("approved", [True, False])
async def test_real_approval_path_does_not_persist_plugin_consent(
    registry,
    monkeypatch,
    approved,
):
    from qwenpaw.app import approvals
    from qwenpaw.governance import generalize, tool_adapter
    from qwenpaw.security.tool_guard.approval import ApprovalDecision

    callback = AsyncMock(return_value=PolicyHint("ask", "risk band"))
    _register(registry, "risk", callback)
    decision = await _apply(registry)
    service = MagicMock()
    service.cancel_stale_pending_for_tool_call = AsyncMock()
    service.create_pending = AsyncMock(
        return_value=SimpleNamespace(request_id="request-1", scope=None),
    )
    service.wait_for_approval = AsyncMock(
        return_value=ApprovalDecision.APPROVED
        if approved
        else ApprovalDecision.DENIED,
    )
    monkeypatch.setattr(approvals, "get_approval_service", lambda: service)
    generalization = AsyncMock()
    monkeypatch.setattr(
        generalize,
        "generalize_target_for_approval",
        generalization,
    )
    governor = MagicMock(spec=ResourceGovernor)
    governor.add_approved_rule = AsyncMock()
    result = await tool_adapter._ask_user_approval(
        governor,
        _spec(),
        {
            "root_session_id": "root",
            "root_agent_id": "owner",
            "tool_call_id": "tc-1",
        },
        governance_reason=decision.reason,
        source=decision.source,
        policy_extra=decision.extra,
    )
    assert result.behavior.value == ("allow" if approved else "deny")
    governor.add_approved_rule.assert_not_called()
    generalization.assert_not_called()
    assert governor.audit.call_args.args[1].extra == decision.extra
    payload = service.create_pending.call_args.kwargs
    assert payload["root_session_id"] == "root"
    assert payload["owner_agent_id"] == "owner"
    assert (
        payload["result"].findings[0].description
        == "Governance reason: risk band"
    )
    assert payload["extra"]["display"]["is_generalized"] is False
