# -*- coding: utf-8 -*-
"""Tests for unified tool governance registration (issue #6114)."""

from __future__ import annotations

import threading
from unittest.mock import patch

import pytest

from qwenpaw.agents.tools.delegate_external_agent import (
    delegate_external_agent,
)
from qwenpaw.agents.tools.file_io import append_file
from qwenpaw.config.config import (
    ToolsConfig,
    _default_builtin_tools,
    _reset_builtin_tools_cache_for_tests,
)
from qwenpaw.governance.policy import (
    DEFAULT_USER_RULES,
    GovernanceAction,
    GovernancePolicy,
    ToolCallSpec,
    _DefaultUserRulesProxy,
    _auto_default_user_rules,
    get_default_user_rules,
)
from qwenpaw.governance.tool_registry import (
    DEFAULT_REGISTRY,
    GovernanceRegistrationConflict,
    ToolRegistry,
    assert_no_governance_gaps,
    register_tool_governance,
    snake_to_pascal,
    validate_default_policy,
    validate_tool_type,
    _collect_governance_gaps,
)
from qwenpaw.plugins.api import (
    _TOOL_PLUGIN_OWNERS,
    _claim_tool_ownership,
    _register_to_governance,
    release_tool_ownership_for_plugin,
)
from qwenpaw.plugins.registry import PluginRegistry
from qwenpaw.runtime.tool_registry import ToolDescriptor, ToolGovernanceSpec


def _tc(tool_name: str, target: str = "") -> ToolCallSpec:
    return ToolCallSpec(
        tool_name=tool_name,
        target=target,
        agent_id="test-agent",
        session_id="test-session",
    )


class TestRegisterToolGovernance:
    def test_idempotent_register_identical_metadata(self):
        registry = ToolRegistry()
        pname = register_tool_governance(
            registry,
            python_name="__ut_plugin_tool__",
            tool_type="network",
            policy_name="UtPluginTool",
        )
        assert pname == "UtPluginTool"
        assert registry.get_type("UtPluginTool") == "network"
        # Same python_name + identical metadata is idempotent.
        register_tool_governance(
            registry,
            python_name="__ut_plugin_tool__",
            tool_type="network",
            policy_name="UtPluginTool",
        )
        assert registry.get_type("UtPluginTool") == "network"

    def test_reject_metadata_change_on_reregister(self):
        registry = ToolRegistry()
        register_tool_governance(
            registry,
            python_name="__ut_plugin_tool_meta__",
            tool_type="network",
            policy_name="UtPluginToolMeta",
        )
        with pytest.raises(GovernanceRegistrationConflict):
            register_tool_governance(
                registry,
                python_name="__ut_plugin_tool_meta__",
                tool_type="shell",
                policy_name="UtPluginToolMeta",
            )
        assert registry.get_type("UtPluginToolMeta") == "network"

    def test_reject_name_fold_collision(self):
        """Distinct python names must not share a folded policy identity."""
        registry = ToolRegistry()
        register_tool_governance(
            registry,
            python_name="get_current_time",
            tool_type="internal",
            policy_name="GetCurrentTime",
        )
        with pytest.raises(GovernanceRegistrationConflict):
            register_tool_governance(
                registry,
                python_name="get__current_time",
                tool_type="internal",
                # snake_to_pascal("get__current_time") == "GetCurrentTime"
            )

    def test_reject_plugin_collision_with_builtin_internal(self):
        with pytest.raises(GovernanceRegistrationConflict):
            register_tool_governance(
                DEFAULT_REGISTRY,
                python_name="__collide_get_current_time__",
                tool_type="network",
                policy_name="GetCurrentTime",
            )

    def test_snake_to_pascal(self):
        assert snake_to_pascal("generate_image_qwen") == "GenerateImageQwen"


class TestBuiltinDescriptorGovernance:
    def test_no_governance_gaps(self):
        gaps = assert_no_governance_gaps()
        assert not gaps

    def test_empty_tool_type_is_governance_gap(self):
        registry = ToolRegistry()

        class _Fn:
            __name__ = "missing_gov_tool"

        fn = _Fn()
        setattr(
            fn,
            "_tool_descriptor",
            ToolDescriptor(
                name="missing_gov_tool",
                func=lambda: None,
                governance=ToolGovernanceSpec(tool_type=""),
            ),
        )
        with patch(
            "qwenpaw.runtime.tool_registry.get_builtin_tool_funcs",
            return_value=[fn],
        ):
            gaps = _collect_governance_gaps(registry)
        assert "missing_gov_tool" in gaps

    def test_ast_search_registered(self):
        assert DEFAULT_REGISTRY.get_type("AstSearch") == "file"
        assert (
            DEFAULT_REGISTRY.python_to_policy_name("ast_search") == "AstSearch"
        )

    def test_core_builtins_registered(self):
        expected = {
            "Read": "file",
            "Write": "file",
            "Bash": "shell",
            "WebSearch": "network",
            "WebFetch": "network",
            "Browser": "network",
            "GetCurrentTime": "internal",
            "SetUserTimezone": "internal",
            "RecallHistory": "internal",
            "RecallHistoryPython": "shell",
            "MemorySearch": "internal",
        }
        for name, tool_type in expected.items():
            assert DEFAULT_REGISTRY.get_type(name) == tool_type, name

    def test_python_name_mappings(self):
        assert (
            DEFAULT_REGISTRY.python_to_policy_name("execute_shell_command")
            == "Bash"
        )
        assert DEFAULT_REGISTRY.python_to_policy_name("read_file") == "Read"
        assert (
            DEFAULT_REGISTRY.python_to_policy_name("web_search") == "WebSearch"
        )

    def test_set_user_timezone_target_not_joined_to_workspace(self):
        """Timezone names must not be treated as relative file paths."""
        assert (
            DEFAULT_REGISTRY.get_target_param("SetUserTimezone")
            == "timezone_name"
        )
        assert DEFAULT_REGISTRY.get_type("SetUserTimezone") == "internal"
        target = DEFAULT_REGISTRY.extract_target(
            "SetUserTimezone",
            {"timezone_name": "Asia/Shanghai"},
            workspace_dir="/tmp/fake-workspace",
        )
        assert target == "Asia/Shanghai"


class TestPluginGovernanceIssue6114:
    """Plugin tools must pass Phase 0 after register_tool_governance."""

    def test_plugin_tools_not_denied_as_unregistered(self):
        plugin_tools = [
            "generate_image_qwen",
            "edit_image_qwen",
            "generate_image_gpt",
            "edit_image_gpt",
            "text_to_video_wan",
            "image_to_video_wan",
            "reference_to_video_wan",
        ]
        for py_name in plugin_tools:
            # Idempotent when metadata matches (may already be registered).
            register_tool_governance(
                DEFAULT_REGISTRY,
                python_name=py_name,
                tool_type="network",
            )

        policy = GovernancePolicy(execution_level="smart")
        for py_name in plugin_tools:
            pname = DEFAULT_REGISTRY.python_to_policy_name(py_name)
            assert DEFAULT_REGISTRY.get_type(pname) == "network"
            decision = policy.evaluate(_tc(pname))
            assert (
                decision.action is not GovernanceAction.DENY
            ), f"{pname} denied: {decision.reason}"
            assert "Unregistered tool" not in (decision.reason or "")

    def test_register_to_governance_bridge(self):
        """PluginApi helper must sync into the live DEFAULT_REGISTRY."""
        _register_to_governance(
            "__ut_bridge_plugin_tool__",
            tool_type="network",
        )
        assert DEFAULT_REGISTRY.get_type("UtBridgePluginTool") == "network"
        policy = GovernancePolicy(execution_level="smart")
        decision = policy.evaluate(_tc("UtBridgePluginTool"))
        assert decision.action is not GovernanceAction.DENY
        assert "Unregistered tool" not in (decision.reason or "")

    def test_unknown_still_denied(self):
        policy = GovernancePolicy(execution_level="smart")
        decision = policy.evaluate(_tc("TotallyUnknownToolXYZ"))
        assert decision.action is GovernanceAction.DENY
        assert "Unregistered tool" in decision.reason


class TestLazyRegistryConcurrency:
    def test_lazy_registry_single_instance_under_contention(self):
        """Double-checked locking must yield one shared registry instance."""
        import time

        from qwenpaw.governance import tool_registry as tr

        # pylint: disable=protected-access
        proxy = tr._LazyDefaultRegistry()
        create_count = 0

        def _slow_create() -> ToolRegistry:
            nonlocal create_count
            create_count += 1
            time.sleep(0.05)
            return ToolRegistry()

        results: list[ToolRegistry] = []

        def _worker() -> None:
            results.append(proxy._get())

        with patch.object(tr, "_create_default_registry", _slow_create):
            threads = [threading.Thread(target=_worker) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=5)
        # pylint: enable=protected-access

        assert create_count == 1
        assert len(results) == 8
        assert all(r is results[0] for r in results)


class TestAutoDefaultUserRules:
    def test_websearch_rule_generated(self):
        rules = _auto_default_user_rules()
        by_match = {r.match: r for r in rules}
        assert "WebSearch(**)" in by_match
        assert by_match["WebSearch(**)"].action is GovernanceAction.ALLOW

    def test_write_has_no_global_allow_auto_rule(self):
        """Write must not get Write(**) — path-scoped rules stay manual."""
        matches = {r.match for r in _auto_default_user_rules()}
        assert "Write(**)" not in matches
        assert "Edit(**)" not in matches
        assert "Append(**)" not in matches

    def test_default_user_rules_proxy_matches_getter(self):
        via_proxy = list(DEFAULT_USER_RULES)
        via_fn = get_default_user_rules()
        assert len(via_proxy) == len(via_fn)
        assert [r.match for r in via_proxy] == [r.match for r in via_fn]


class TestBuiltinToolConfigFromDescriptors:
    def test_delegate_external_agent_disabled_by_default(self):
        tools = _default_builtin_tools()
        assert "delegate_external_agent" in tools
        assert tools["delegate_external_agent"].enabled is False
        desc = getattr(delegate_external_agent, "_tool_descriptor")
        assert desc.enabled_by_default is False

    def test_append_file_disabled_by_default(self):
        tools = _default_builtin_tools()
        assert tools["append_file"].enabled is False
        desc = getattr(append_file, "_tool_descriptor")
        assert desc.enabled_by_default is False

    def test_web_search_ui_metadata(self):
        tools = _default_builtin_tools()
        assert tools["web_search"].icon == "🔎"
        assert tools["view_image"].display_to_user is False

    def test_late_plugin_manifest_merged_after_cache_warm(
        self,
    ) -> None:
        """Descriptor cache must not permanently omit late plugin tools."""
        plugin_id = "__ut_late_plugin_manifest__"
        tool_name = "__ut_late_plugin_tool__"
        registry = PluginRegistry()
        registry.unregister_plugin(plugin_id)
        _reset_builtin_tools_cache_for_tests()
        try:
            before = _default_builtin_tools()
            assert tool_name not in before

            registry.register_plugin_manifest(
                plugin_id,
                {
                    "name": plugin_id,
                    "meta": {
                        "tool_name": tool_name,
                        "tool_description": "late plugin tool",
                        "tool_icon": "🧪",
                    },
                },
            )
            cfg = ToolsConfig()
            assert tool_name in cfg.builtin_tools
            assert cfg.builtin_tools[tool_name].enabled is False

            registry.unregister_plugin(plugin_id)
            after = _default_builtin_tools()
            assert tool_name not in after
        finally:
            registry.unregister_plugin(plugin_id)
            _reset_builtin_tools_cache_for_tests()


class TestToolTypeAndDefaultPolicyValidation:
    def test_reject_bogus_tool_type(self):
        registry = ToolRegistry()
        with pytest.raises(GovernanceRegistrationConflict):
            register_tool_governance(
                registry,
                python_name="__ut_bogus_type__",
                tool_type="bogus",
            )

    def test_accept_known_tool_types(self):
        registry = ToolRegistry()
        for tool_type in ("file", "network", "shell", "internal"):
            register_tool_governance(
                registry,
                python_name=f"__ut_type_{tool_type}__",
                tool_type=tool_type,
            )

    def test_validate_default_policy_rejects_typo(self):
        with pytest.raises(GovernanceRegistrationConflict):
            validate_default_policy("alow")

    def test_validate_tool_type_helpers(self):
        assert validate_tool_type("network") == "network"
        with pytest.raises(GovernanceRegistrationConflict):
            validate_tool_type("")


class TestPluginToolOwnership:
    def test_different_plugin_same_tool_name_conflicts(self):
        tool_name = "__ut_owned_tool__"
        _TOOL_PLUGIN_OWNERS.pop(tool_name, None)
        try:
            _claim_tool_ownership(tool_name, "plugin-a")
            with pytest.raises(GovernanceRegistrationConflict):
                _claim_tool_ownership(tool_name, "plugin-b")
            # Same plugin is idempotent.
            _claim_tool_ownership(tool_name, "plugin-a")
        finally:
            release_tool_ownership_for_plugin("plugin-a")
            release_tool_ownership_for_plugin("plugin-b")

    def test_release_ownership_allows_other_plugin(self):
        tool_name = "__ut_owned_tool_release__"
        _TOOL_PLUGIN_OWNERS.pop(tool_name, None)
        try:
            _claim_tool_ownership(tool_name, "plugin-a")
            release_tool_ownership_for_plugin("plugin-a")
            _claim_tool_ownership(tool_name, "plugin-b")
        finally:
            release_tool_ownership_for_plugin("plugin-a")
            release_tool_ownership_for_plugin("plugin-b")


class TestDefaultUserRulesProxy:
    def test_proxy_is_not_list_subclass(self):
        assert not isinstance(DEFAULT_USER_RULES, list)
        assert isinstance(DEFAULT_USER_RULES, _DefaultUserRulesProxy)


class TestWindowsStylePathExtraction:
    def test_extract_target_joins_backslash_relative_path(self):
        """Relative targets with backslash segments still join to workspace."""
        import ntpath

        registry = ToolRegistry()
        register_tool_governance(
            registry,
            python_name="__ut_win_read__",
            tool_type="file",
            target_param="file_path",
            policy_name="UtWinRead",
        )
        # Use an absolute POSIX workspace so join works on all platforms;
        # relative path keeps Windows-style separators as segments.
        workspace = "/tmp/ut_win_workspace"
        relative = r"src\main.py"
        target = registry.extract_target(
            "UtWinRead",
            {"file_path": relative},
            workspace_dir=workspace,
        )
        assert target.startswith(workspace)
        assert "main.py" in target
        # ntpath.basename still sees the leaf under Windows separators.
        assert ntpath.basename(relative) == "main.py"
