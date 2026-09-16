# -*- coding: utf-8 -*-
"""Merge the platform security baseline with Agent-local restrictions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from ..config.config import (
    FileGuardConfig,
    SecurityConfig,
    SkillScannerConfig,
    SkillScannerWhitelistEntry,
    ToolGuardConfig,
    ToolGuardRuleConfig,
)

_DEFAULT_GUARDED_TOOLS = frozenset(
    {
        "execute_shell_command",
        "read_file",
        "write_file",
        "edit_file",
        "append_file",
        "send_file_to_user",
        "view_text_file",
        "write_text_file",
    }
)
_SCANNER_STRENGTH = {"off": 0, "warn": 1, "block": 2}


@dataclass(frozen=True, slots=True)
class SecurityPolicyViolation:
    """One attempted reduction of a platform-enforced protection."""

    field: str
    reason: str
    platform_value: Any

    def as_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "reason": self.reason,
            "platform_value": self.platform_value,
        }


def platform_locked_fields(baseline: SecurityConfig) -> list[str]:
    """Return fields whose effective value is constrained by the baseline."""
    fields = [
        "security.allow_no_auth_hosts",
        "security.trusted_proxies",
    ]
    if baseline.tool_guard.enabled:
        fields.append("security.tool_guard.enabled")
    fields.append("security.tool_guard.guarded_tools")
    if baseline.tool_guard.denied_tools:
        fields.append("security.tool_guard.denied_tools")
    if baseline.tool_guard.auto_denied_rules:
        fields.append("security.tool_guard.auto_denied_rules")
    if baseline.tool_guard.custom_rules:
        fields.append("security.tool_guard.custom_rules")
    if any(baseline.tool_guard.shell_evasion_checks.values()):
        fields.append("security.tool_guard.shell_evasion_checks")
    if baseline.file_guard.enabled:
        fields.append("security.file_guard.enabled")
    if baseline.file_guard.sensitive_files:
        fields.append("security.file_guard.sensitive_files")
    if not baseline.file_guard.allow_preview_outside_workspace:
        fields.append("security.file_guard.allow_preview_outside_workspace")
    if baseline.sandbox_enabled:
        fields.append("security.sandbox_enabled")
    if baseline.skill_scanner.mode != "off":
        fields.append("security.skill_scanner.mode")
    if baseline.skill_scanner.whitelist:
        fields.append("security.skill_scanner.whitelist")
    return sorted(set(fields))


def validate_agent_security_override(
    baseline: SecurityConfig,
    override: SecurityConfig,
) -> list[SecurityPolicyViolation]:
    """Describe every field in *override* that weakens *baseline*."""
    violations: list[SecurityPolicyViolation] = []

    def add(field: str, reason: str, value: Any) -> None:
        violations.append(SecurityPolicyViolation(field, reason, value))

    base_tool = baseline.tool_guard
    agent_tool = override.tool_guard
    if base_tool.enabled and not agent_tool.enabled:
        add(
            "security.tool_guard.enabled",
            "平台已启用工具防护，Agent 不能关闭",
            True,
        )
    if not _guard_scope_contains(
        agent_tool.guarded_tools,
        base_tool.guarded_tools,
    ):
        add(
            "security.tool_guard.guarded_tools",
            "Agent 保护范围必须包含平台保护范围",
            base_tool.guarded_tools,
        )
    _require_superset(
        violations,
        "security.tool_guard.denied_tools",
        agent_tool.denied_tools,
        base_tool.denied_tools,
        "Agent 不能移除平台禁止工具",
    )
    _require_superset(
        violations,
        "security.tool_guard.auto_denied_rules",
        agent_tool.auto_denied_rules,
        base_tool.auto_denied_rules,
        "Agent 不能移除平台自动拒绝规则",
    )

    base_rules = {rule.id: rule for rule in base_tool.custom_rules}
    agent_rules = {rule.id: rule for rule in agent_tool.custom_rules}
    missing_or_changed = [
        rule_id
        for rule_id, rule in base_rules.items()
        if agent_rules.get(rule_id) != rule
    ]
    if missing_or_changed:
        add(
            "security.tool_guard.custom_rules",
            "Agent 不能删除或修改平台规则",
            sorted(base_rules),
        )

    additionally_disabled = set(agent_tool.disabled_rules) - set(
        base_tool.disabled_rules
    )
    if additionally_disabled:
        add(
            "security.tool_guard.disabled_rules",
            "Agent 不能禁用平台仍启用的规则",
            sorted(base_tool.disabled_rules),
        )
    for check, required in base_tool.shell_evasion_checks.items():
        if required and not agent_tool.shell_evasion_checks.get(check, False):
            add(
                f"security.tool_guard.shell_evasion_checks.{check}",
                "Agent 不能关闭平台 Shell 逃逸检测",
                True,
            )

    base_file = baseline.file_guard
    agent_file = override.file_guard
    if base_file.enabled and not agent_file.enabled:
        add(
            "security.file_guard.enabled",
            "平台已启用文件防护，Agent 不能关闭",
            True,
        )
    _require_superset(
        violations,
        "security.file_guard.sensitive_files",
        agent_file.sensitive_files,
        base_file.sensitive_files,
        "Agent 不能移除平台敏感路径",
    )
    if (
        not base_file.allow_preview_outside_workspace
        and agent_file.allow_preview_outside_workspace
    ):
        add(
            "security.file_guard.allow_preview_outside_workspace",
            "平台禁止工作区外预览，Agent 不能允许",
            False,
        )

    if baseline.sandbox_enabled and not override.sandbox_enabled:
        add(
            "security.sandbox_enabled",
            "平台已启用沙箱，Agent 不能关闭",
            True,
        )
    if (
        _SCANNER_STRENGTH[override.skill_scanner.mode]
        < _SCANNER_STRENGTH[baseline.skill_scanner.mode]
    ):
        add(
            "security.skill_scanner.mode",
            "Agent 扫描模式不能低于平台级别",
            baseline.skill_scanner.mode,
        )

    baseline_whitelist = {
        _whitelist_key(item) for item in baseline.skill_scanner.whitelist
    }
    agent_whitelist = {
        _whitelist_key(item) for item in override.skill_scanner.whitelist
    }
    if not agent_whitelist.issubset(baseline_whitelist):
        add(
            "security.skill_scanner.whitelist",
            "Agent 不能扩大平台技能白名单",
            sorted(baseline_whitelist),
        )

    if override.allow_no_auth_hosts != baseline.allow_no_auth_hosts:
        add(
            "security.allow_no_auth_hosts",
            "免认证主机只能由平台管理员配置",
            baseline.allow_no_auth_hosts,
        )
    if override.trusted_proxies != baseline.trusted_proxies:
        add(
            "security.trusted_proxies",
            "可信代理只能由平台管理员配置",
            baseline.trusted_proxies,
        )
    return violations


def merge_security_policy(
    baseline: SecurityConfig,
    override: SecurityConfig | None,
) -> SecurityConfig:
    """Return an immutable effective view that can never weaken baseline."""
    if override is None:
        return baseline.model_copy(deep=True)

    base_tool = baseline.tool_guard
    agent_tool = override.tool_guard
    tool_guard = ToolGuardConfig(
        enabled=base_tool.enabled or agent_tool.enabled,
        guarded_tools=_merge_guard_scopes(
            base_tool.guarded_tools,
            agent_tool.guarded_tools,
        ),
        denied_tools=_ordered_union(
            base_tool.denied_tools,
            agent_tool.denied_tools,
        ),
        auto_denied_rules=_ordered_union(
            base_tool.auto_denied_rules,
            agent_tool.auto_denied_rules,
        ),
        custom_rules=_merge_rules(
            base_tool.custom_rules,
            agent_tool.custom_rules,
        ),
        disabled_rules=[
            rule_id
            for rule_id in base_tool.disabled_rules
            if rule_id in set(agent_tool.disabled_rules)
        ],
        shell_evasion_checks={
            key: base_tool.shell_evasion_checks.get(key, False)
            or agent_tool.shell_evasion_checks.get(key, False)
            for key in (
                set(base_tool.shell_evasion_checks)
                | set(agent_tool.shell_evasion_checks)
            )
        },
    )
    file_guard = FileGuardConfig(
        enabled=baseline.file_guard.enabled or override.file_guard.enabled,
        sensitive_files=_ordered_union(
            baseline.file_guard.sensitive_files,
            override.file_guard.sensitive_files,
        ),
        allow_preview_outside_workspace=(
            baseline.file_guard.allow_preview_outside_workspace
            and override.file_guard.allow_preview_outside_workspace
        ),
    )
    scanner_mode = max(
        (baseline.skill_scanner.mode, override.skill_scanner.mode),
        key=_SCANNER_STRENGTH.__getitem__,
    )
    baseline_whitelist = {
        _whitelist_key(item): item for item in baseline.skill_scanner.whitelist
    }
    agent_whitelist = {
        _whitelist_key(item) for item in override.skill_scanner.whitelist
    }
    skill_scanner = SkillScannerConfig(
        mode=scanner_mode,
        timeout=override.skill_scanner.timeout,
        whitelist=[
            item.model_copy(deep=True)
            for key, item in baseline_whitelist.items()
            if key in agent_whitelist
        ],
    )
    return SecurityConfig(
        tool_guard=tool_guard,
        file_guard=file_guard,
        skill_scanner=skill_scanner,
        sandbox_enabled=(baseline.sandbox_enabled or override.sandbox_enabled),
        allow_no_auth_hosts=list(baseline.allow_no_auth_hosts),
        trusted_proxies=list(baseline.trusted_proxies),
    )


def load_effective_security_policy(agent_id: str | None = None) -> SecurityConfig:
    """Load the effective policy for the current runtime Agent context."""
    from ..config import load_config
    from ..identity.runtime import is_multi_user_enabled

    baseline = load_config().security
    if not is_multi_user_enabled():
        return baseline
    try:
        if agent_id is None:
            from ..app.agent_context import get_current_agent_id

            agent_id = get_current_agent_id()
        from ..config.config import load_agent_config

        override = load_agent_config(agent_id).security
    except Exception:
        override = None
    return merge_security_policy(baseline, override)


def _guard_scope(value: list[str] | None) -> tuple[bool, set[str]]:
    if value is None:
        return False, set(_DEFAULT_GUARDED_TOOLS)
    normalized = {item.strip() for item in value if item.strip()}
    lowered = {item.lower() for item in normalized}
    if "*" in lowered or "all" in lowered:
        return True, set()
    return False, normalized


def _guard_scope_contains(
    candidate: list[str] | None,
    required: list[str] | None,
) -> bool:
    candidate_all, candidate_items = _guard_scope(candidate)
    required_all, required_items = _guard_scope(required)
    if candidate_all:
        return True
    if required_all:
        return False
    return candidate_items.issuperset(required_items)


def _merge_guard_scopes(
    baseline: list[str] | None,
    override: list[str] | None,
) -> list[str] | None:
    base_all, base_items = _guard_scope(baseline)
    agent_all, agent_items = _guard_scope(override)
    if base_all or agent_all:
        return ["*"]
    merged = base_items | agent_items
    if baseline is None and override is None:
        return None
    return sorted(merged)


def _ordered_union(first: Iterable[str], second: Iterable[str]) -> list[str]:
    return list(dict.fromkeys([*first, *second]))


def _merge_rules(
    baseline: list[ToolGuardRuleConfig],
    override: list[ToolGuardRuleConfig],
) -> list[ToolGuardRuleConfig]:
    merged = {rule.id: rule.model_copy(deep=True) for rule in override}
    merged.update({rule.id: rule.model_copy(deep=True) for rule in baseline})
    return list(merged.values())


def _whitelist_key(item: SkillScannerWhitelistEntry) -> tuple[str, str]:
    return item.skill_name, item.content_hash


def _require_superset(
    violations: list[SecurityPolicyViolation],
    field: str,
    candidate: Iterable[str],
    required: Iterable[str],
    reason: str,
) -> None:
    required_set = set(required)
    if not set(candidate).issuperset(required_set):
        violations.append(SecurityPolicyViolation(field, reason, sorted(required_set)))
