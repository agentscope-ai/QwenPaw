# -*- coding: utf-8 -*-
"""平台安全基线与 Agent 收紧策略的隔离测试。"""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.access.capabilities import Capability
from qwenpaw.access.service import AuthorizationService
from qwenpaw.config.config import SecurityConfig, SkillScannerWhitelistEntry
from qwenpaw.platform_ops.security_policy import (
    load_effective_security_policy,
    merge_security_policy,
    platform_locked_fields,
    validate_agent_security_override,
)
from qwenpaw.identity.models import PlatformRole


def test_effective_policy_unions_protection_and_uses_stricter_modes() -> None:
    baseline = SecurityConfig()
    baseline.tool_guard.guarded_tools = ["execute_shell_command"]
    baseline.tool_guard.denied_tools = ["dangerous_platform_tool"]
    baseline.file_guard.sensitive_files = ["~/.ssh"]
    baseline.file_guard.allow_preview_outside_workspace = True
    baseline.skill_scanner.mode = "warn"

    override = baseline.model_copy(deep=True)
    override.tool_guard.guarded_tools.append("browser")
    override.tool_guard.denied_tools.append("agent_private_tool")
    override.file_guard.sensitive_files.append("workspace/private")
    override.file_guard.allow_preview_outside_workspace = False
    override.skill_scanner.mode = "block"
    override.sandbox_enabled = True

    effective = merge_security_policy(baseline, override)

    assert effective.tool_guard.guarded_tools == ["browser", "execute_shell_command"]
    assert effective.tool_guard.denied_tools == [
        "dangerous_platform_tool",
        "agent_private_tool",
    ]
    assert effective.file_guard.sensitive_files == ["~/.ssh", "workspace/private"]
    assert effective.file_guard.allow_preview_outside_workspace is False
    assert effective.skill_scanner.mode == "block"
    assert effective.sandbox_enabled is True


def test_weaker_agent_override_reports_every_locked_field() -> None:
    baseline = SecurityConfig(sandbox_enabled=True)
    baseline.tool_guard.guarded_tools = ["execute_shell_command", "write_file"]
    baseline.tool_guard.denied_tools = ["blocked"]
    baseline.file_guard.sensitive_files = ["~/.ssh"]
    baseline.file_guard.allow_preview_outside_workspace = False
    baseline.skill_scanner.mode = "block"

    override = baseline.model_copy(deep=True)
    override.tool_guard.enabled = False
    override.tool_guard.guarded_tools = ["write_file"]
    override.tool_guard.denied_tools = []
    override.file_guard.enabled = False
    override.file_guard.sensitive_files = []
    override.file_guard.allow_preview_outside_workspace = True
    override.skill_scanner.mode = "off"
    override.sandbox_enabled = False

    fields = {
        violation.field
        for violation in validate_agent_security_override(baseline, override)
    }

    assert {
        "security.tool_guard.enabled",
        "security.tool_guard.guarded_tools",
        "security.tool_guard.denied_tools",
        "security.file_guard.enabled",
        "security.file_guard.sensitive_files",
        "security.file_guard.allow_preview_outside_workspace",
        "security.skill_scanner.mode",
        "security.sandbox_enabled",
    }.issubset(fields)


def test_agent_can_only_shrink_platform_skill_whitelist() -> None:
    baseline = SecurityConfig()
    baseline.skill_scanner.whitelist = [
        SkillScannerWhitelistEntry(skill_name="approved", content_hash="abc")
    ]
    stricter = baseline.model_copy(deep=True)
    stricter.skill_scanner.whitelist = []
    weaker = baseline.model_copy(deep=True)
    weaker.skill_scanner.whitelist.append(
        SkillScannerWhitelistEntry(skill_name="extra", content_hash="def")
    )

    assert validate_agent_security_override(baseline, stricter) == []
    assert any(
        item.field == "security.skill_scanner.whitelist"
        for item in validate_agent_security_override(baseline, weaker)
    )
    assert merge_security_policy(baseline, stricter).skill_scanner.whitelist == []


def test_no_auth_hosts_default_off_and_are_platform_locked() -> None:
    baseline = SecurityConfig()
    assert baseline.allow_no_auth_hosts == []
    assert "security.allow_no_auth_hosts" in platform_locked_fields(baseline)


def test_runtime_loader_merges_current_agent_policy(monkeypatch) -> None:
    from qwenpaw.config import config as config_module
    from qwenpaw.config import utils as config_utils
    from qwenpaw.identity import runtime as identity_runtime

    baseline = SecurityConfig()
    baseline.tool_guard.denied_tools = ["platform-denied"]
    override = baseline.model_copy(deep=True)
    override.tool_guard.denied_tools.append("agent-denied")
    root_config = SimpleNamespace(security=baseline)
    profile = SimpleNamespace(security=override)

    monkeypatch.setattr(config_utils, "load_config", lambda: root_config)
    monkeypatch.setattr(config_module, "load_agent_config", lambda _agent_id: profile)
    monkeypatch.setattr(identity_runtime, "is_multi_user_enabled", lambda: True)

    effective = load_effective_security_policy("agent-a")

    assert effective.tool_guard.denied_tools == [
        "platform-denied",
        "agent-denied",
    ]


def test_compatibility_service_principal_has_no_admin_capability() -> None:
    actor = ActorContext(
        user_id=None,
        actor_type=ActorType.SERVICE,
        platform_role=None,
        admin_mode=False,
        request_id="compat-service",
    )
    service = AuthorizationService()

    assert service.is_allowed(actor, Capability.PLATFORM_USE)
    assert service.is_allowed(actor, Capability.AGENT_USE)
    assert not service.is_allowed(actor, Capability.PLATFORM_SETTINGS_MANAGE)
    assert not service.is_allowed(actor, Capability.USERS_MANAGE)


def _policy_client(monkeypatch, role: PlatformRole) -> tuple[TestClient, object]:
    from qwenpaw.access.dependencies import get_actor
    from qwenpaw.app import agent_context
    from qwenpaw.app.routers import config as config_router
    from qwenpaw.config import config as config_module

    baseline = SecurityConfig(sandbox_enabled=True)
    baseline.file_guard.allow_preview_outside_workspace = False
    profile = SimpleNamespace(security=baseline.model_copy(deep=True))
    workspace = SimpleNamespace(
        agent_id="agent-a",
        config=profile,
    )
    root_config = SimpleNamespace(security=baseline)

    async def get_agent(_request):
        return workspace

    actor = ActorContext(
        user_id=None,
        actor_type=ActorType.USER,
        platform_role=role,
        admin_mode=False,
        request_id="policy-http",
    )
    monkeypatch.setattr(config_router, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(config_router, "load_config", lambda: root_config)
    monkeypatch.setattr(agent_context, "get_agent_for_request", get_agent)
    monkeypatch.setattr(config_module, "save_agent_config", lambda *_args: None)
    monkeypatch.setattr(config_router, "schedule_agent_reload", lambda *_args: None)

    app = FastAPI()
    app.include_router(config_router.router, prefix="/api")
    app.include_router(config_router.router, prefix="/api/agents/{agentId}")
    app.dependency_overrides[get_actor] = lambda: actor
    return TestClient(app), workspace


def test_agent_weaken_request_returns_409_with_lock_reason(monkeypatch) -> None:
    client, _workspace = _policy_client(monkeypatch, PlatformRole.MEMBER)

    response = client.put(
        "/api/agents/agent-a/config/security/sandbox",
        json={"enabled": False},
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["reason_code"] == "platform_security_baseline_locked"
    assert detail["locked_fields"][0]["field"] == "security.sandbox_enabled"

    response = client.put(
        "/api/agents/agent-a/config/security/file-guard",
        json={"enabled": False},
    )
    assert response.status_code == 409
    fields = {item["field"] for item in response.json()["detail"]["locked_fields"]}
    assert "security.file_guard.enabled" in fields


def test_agent_policy_endpoint_returns_effective_and_locked_fields(monkeypatch) -> None:
    client, workspace = _policy_client(monkeypatch, PlatformRole.MEMBER)
    workspace.config.security.file_guard.sensitive_files.append("agent/private")

    response = client.get("/api/agents/agent-a/config/security/policy")

    assert response.status_code == 200
    payload = response.json()
    assert payload["scope"] == "agent"
    assert payload["effective_policy"]["sandbox_enabled"] is True
    assert payload["effective_policy"]["file_guard"]["sensitive_files"] == [
        "agent/private"
    ]
    assert "security.sandbox_enabled" in payload["platform_locked_fields"]


def test_platform_security_write_requires_admin(monkeypatch) -> None:
    client, _workspace = _policy_client(monkeypatch, PlatformRole.MEMBER)

    response = client.put(
        "/api/config/security/tool-guard",
        json=SecurityConfig().tool_guard.model_dump(),
    )

    assert response.status_code == 403
