# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for unified tool governance registration (issue #6114)."""

from __future__ import annotations

import threading
from pathlib import Path
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
    PluginApi,
    _TOOL_PLUGIN_OWNERS,
    _bridge_to_runtime,
    _claim_tool_ownership,
    _register_to_governance,
    _unbridge_from_runtime,
    release_tool_ownership_for_plugin,
)
from qwenpaw.runtime.tool_registry import ToolRegistry as RuntimeToolRegistry
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

    def test_proxy_equals_materialized_and_plus_preserves_rules(self):
        rules = get_default_user_rules()
        assert DEFAULT_USER_RULES == rules
        assert len(DEFAULT_USER_RULES + []) == len(rules)
        assert (DEFAULT_USER_RULES + []) == rules


class TestGovernanceOwnerLifecycle:
    def test_same_owner_can_replace_identity_on_hot_reload(self):
        registry = ToolRegistry()
        register_tool_governance(
            registry,
            python_name="hot_reload_tool",
            tool_type="network",
            policy_name="HotReloadTool",
            owner="plugin-hot",
        )
        register_tool_governance(
            registry,
            python_name="hot_reload_tool",
            tool_type="shell",
            target_param="command",
            policy_name="HotReloadTool",
            owner="plugin-hot",
        )
        assert registry.get_type("HotReloadTool") == "shell"
        assert registry.get_target_param("HotReloadTool") == "command"

    def test_unregister_owner_allows_name_reuse(self):
        registry = ToolRegistry()
        register_tool_governance(
            registry,
            python_name="reuse_tool",
            tool_type="network",
            policy_name="ReuseTool",
            owner="plugin-a",
        )
        removed = registry.unregister_owner("plugin-a")
        assert "reuse_tool" in removed
        assert registry.get_type("ReuseTool") == "unknown"
        register_tool_governance(
            registry,
            python_name="reuse_tool",
            tool_type="shell",
            target_param="command",
            policy_name="ReuseTool",
            owner="plugin-b",
        )
        assert registry.get_type("ReuseTool") == "shell"
        assert registry.get_owner("reuse_tool") == "plugin-b"

    def test_release_ownership_clears_default_registry_identity(self):
        py_name = "__ut_gov_lifecycle_tool__"
        policy = "UtGovLifecycleTool"
        plugin_id = "__ut_gov_lifecycle_plugin__"
        release_tool_ownership_for_plugin(plugin_id)
        DEFAULT_REGISTRY.unregister_python_tool(py_name)
        try:
            register_tool_governance(
                DEFAULT_REGISTRY,
                python_name=py_name,
                tool_type="network",
                policy_name=policy,
                owner=plugin_id,
            )
            _TOOL_PLUGIN_OWNERS[py_name] = plugin_id
            assert DEFAULT_REGISTRY.get_type(policy) == "network"
            release_tool_ownership_for_plugin(plugin_id)
            assert DEFAULT_REGISTRY.get_type(policy) == "unknown"
            register_tool_governance(
                DEFAULT_REGISTRY,
                python_name=py_name,
                tool_type="shell",
                target_param="command",
                policy_name=policy,
                owner=plugin_id,
            )
            assert DEFAULT_REGISTRY.get_type(policy) == "shell"
        finally:
            release_tool_ownership_for_plugin(plugin_id)
            DEFAULT_REGISTRY.unregister_python_tool(py_name)

    def test_unregister_owner_refuses_builtin(self):
        registry = ToolRegistry()
        register_tool_governance(
            registry,
            python_name="read_file",
            tool_type="file",
            target_param="file_path",
            policy_name="Read",
            owner="builtin",
        )
        assert registry.unregister_owner("builtin") == []
        assert registry.get_type("Read") == "file"


class TestRegisterToolRollback:
    """Mid-flight ``register_tool`` failures must not leave ownership/gov."""

    def _run_startup_hooks(self, plugin_registry: PluginRegistry) -> None:
        for hook in plugin_registry.get_startup_hooks():
            hook.callback()

    def test_governance_failure_releases_ownership(self):
        plugin_id = "__ut_rollback_gov_fail__"
        tool_name = "__ut_rollback_shared__"
        policy = "UtRollbackShared"
        release_tool_ownership_for_plugin(plugin_id)
        DEFAULT_REGISTRY.unregister_python_tool(tool_name)
        _TOOL_PLUGIN_OWNERS.pop(tool_name, None)

        old = PluginRegistry._instance
        PluginRegistry._instance = None
        try:
            preg = PluginRegistry()
            api = PluginApi(plugin_id, config={}, manifest={"id": plugin_id})
            api.set_registry(preg)

            async def _tool() -> str:
                return "ok"

            with patch(
                "qwenpaw.plugins.api._register_to_governance",
                side_effect=GovernanceRegistrationConflict("boom"),
            ):
                api.register_tool(
                    tool_name=tool_name,
                    tool_func=_tool,
                    tool_type="network",
                )
                self._run_startup_hooks(preg)

            assert tool_name not in _TOOL_PLUGIN_OWNERS
            assert DEFAULT_REGISTRY.get_type(policy) == "unknown"
            # Another plugin can claim the name after rollback.
            _claim_tool_ownership(tool_name, "plugin-b")
            assert _TOOL_PLUGIN_OWNERS[tool_name] == "plugin-b"
        finally:
            release_tool_ownership_for_plugin(plugin_id)
            release_tool_ownership_for_plugin("plugin-b")
            DEFAULT_REGISTRY.unregister_python_tool(tool_name)
            PluginRegistry._instance = old

    def test_expose_failure_rolls_back_ownership_and_governance(self):
        plugin_id = "__ut_rollback_expose_fail__"
        tool_name = "__ut_rollback_expose_tool__"
        policy = "UtRollbackExposeTool"
        release_tool_ownership_for_plugin(plugin_id)
        DEFAULT_REGISTRY.unregister_python_tool(tool_name)
        _TOOL_PLUGIN_OWNERS.pop(tool_name, None)

        old = PluginRegistry._instance
        PluginRegistry._instance = None
        try:
            preg = PluginRegistry()
            api = PluginApi(plugin_id, config={}, manifest={"id": plugin_id})
            api.set_registry(preg)

            async def _tool() -> str:
                return "ok"

            with patch(
                "qwenpaw.plugins.api._bridge_to_runtime",
                side_effect=RuntimeError("bridge failed"),
            ):
                api.register_tool(
                    tool_name=tool_name,
                    tool_func=_tool,
                    tool_type="network",
                )
                self._run_startup_hooks(preg)

            assert tool_name not in _TOOL_PLUGIN_OWNERS
            assert DEFAULT_REGISTRY.get_type(policy) == "unknown"
            assert DEFAULT_REGISTRY.get_owner(tool_name) is None
        finally:
            release_tool_ownership_for_plugin(plugin_id)
            DEFAULT_REGISTRY.unregister_python_tool(tool_name)
            PluginRegistry._instance = old

    def test_write_config_failure_unbridges_runtime(self):
        """Bridge-then-write failure must not leave runtime-visible tools."""
        plugin_id = "__ut_rollback_write_fail__"
        tool_name = "__ut_rollback_write_tool__"
        policy = "UtRollbackWriteTool"
        release_tool_ownership_for_plugin(plugin_id)
        DEFAULT_REGISTRY.unregister_python_tool(tool_name)
        _TOOL_PLUGIN_OWNERS.pop(tool_name, None)

        runtime_tr = RuntimeToolRegistry()
        bootstrap = {"builtin_tool_funcs": []}

        class _Plugins:
            tool_registry = runtime_tr

        class _Ws:
            agent_id = "default"
            plugins = _Plugins()

        class _Wm:
            agents = {"default": _Ws()}
            _bootstrap_kwargs = bootstrap

        old = PluginRegistry._instance
        PluginRegistry._instance = None
        try:
            preg = PluginRegistry()

            def _wm_factory():
                return _Wm()

            # type: ignore[method-assign]
            preg.get_workspace_manager = _wm_factory
            api = PluginApi(plugin_id, config={}, manifest={"id": plugin_id})
            api.set_registry(preg)

            async def _tool() -> str:
                return "ok"

            with patch(
                "qwenpaw.plugins.api._write_tool_config",
                side_effect=OSError("disk full"),
            ):
                api.register_tool(
                    tool_name=tool_name,
                    tool_func=_tool,
                    tool_type="network",
                )
                self._run_startup_hooks(preg)

            assert tool_name not in runtime_tr
            assert not bootstrap["builtin_tool_funcs"]
            assert tool_name not in _TOOL_PLUGIN_OWNERS
            assert DEFAULT_REGISTRY.get_type(policy) == "unknown"
        finally:
            release_tool_ownership_for_plugin(plugin_id)
            DEFAULT_REGISTRY.unregister_python_tool(tool_name)
            PluginRegistry._instance = old

    def test_unbridge_removes_registry_and_bootstrap_funcs(self):
        runtime_tr = RuntimeToolRegistry()
        bootstrap: dict = {"builtin_tool_funcs": []}

        class _Plugins:
            tool_registry = runtime_tr

        class _Ws:
            agent_id = "default"
            plugins = _Plugins()

        class _Wm:
            agents = {"default": _Ws()}
            _bootstrap_kwargs = bootstrap

        class _Reg:
            def get_workspace_manager(self):
                return _Wm()

        async def _tool() -> str:
            return "ok"

        _bridge_to_runtime("ut_unbridge_tool", _tool, False, "d", _Reg())
        assert "ut_unbridge_tool" in runtime_tr
        assert _tool in bootstrap["builtin_tool_funcs"]
        _unbridge_from_runtime("ut_unbridge_tool", _tool, _Reg())
        assert "ut_unbridge_tool" not in runtime_tr
        assert _tool not in bootstrap["builtin_tool_funcs"]


class TestLoaderGovernanceLifecycle:
    """Closer to real unload → reinstall / name-reuse paths."""

    @pytest.mark.asyncio
    async def test_unload_plugin_allows_metadata_change_reinstall(self):
        from qwenpaw.plugins.architecture import (
            PluginEntryPoints,
            PluginManifest,
            PluginRecord,
        )
        from qwenpaw.plugins.loader import PluginLoader

        plugin_id = "__ut_loader_hot__"
        tool_name = "__ut_loader_hot_tool__"
        policy = "UtLoaderHotTool"
        release_tool_ownership_for_plugin(plugin_id)
        DEFAULT_REGISTRY.unregister_python_tool(tool_name)

        old = PluginRegistry._instance
        PluginRegistry._instance = None
        try:
            preg = PluginRegistry()
            loader = PluginLoader(plugin_dirs=[])
            loader.registry = preg
            manifest = PluginManifest(
                id=plugin_id,
                name="Hot",
                version="1.0.0",
                entry=PluginEntryPoints(backend="plugin.py"),
                meta={"tool_name": tool_name},
            )
            loader._loaded_plugins[plugin_id] = PluginRecord(
                manifest=manifest,
                source_path=Path("/fake-hot"),
                enabled=True,
                instance=None,
            )

            register_tool_governance(
                DEFAULT_REGISTRY,
                python_name=tool_name,
                tool_type="network",
                policy_name=policy,
                owner=plugin_id,
            )
            _TOOL_PLUGIN_OWNERS[tool_name] = plugin_id
            assert DEFAULT_REGISTRY.get_type(policy) == "network"

            await loader.unload_plugin(plugin_id)
            assert DEFAULT_REGISTRY.get_type(policy) == "unknown"
            assert tool_name not in _TOOL_PLUGIN_OWNERS

            # Reinstall with changed governance identity.
            register_tool_governance(
                DEFAULT_REGISTRY,
                python_name=tool_name,
                tool_type="shell",
                target_param="command",
                policy_name=policy,
                owner=plugin_id,
            )
            assert DEFAULT_REGISTRY.get_type(policy) == "shell"
            assert DEFAULT_REGISTRY.get_target_param(policy) == "command"
        finally:
            release_tool_ownership_for_plugin(plugin_id)
            DEFAULT_REGISTRY.unregister_python_tool(tool_name)
            PluginRegistry._instance = old

    @pytest.mark.asyncio
    async def test_unload_clears_runtime_and_rebridge_replaces_func(self):
        """Successful unload must unbridge; rebridge must replace old func."""
        from qwenpaw.plugins.architecture import (
            PluginEntryPoints,
            PluginManifest,
            PluginRecord,
        )
        from qwenpaw.plugins.loader import PluginLoader

        plugin_id = "__ut_loader_runtime__"
        tool_name = "__ut_loader_runtime_tool__"
        release_tool_ownership_for_plugin(plugin_id)
        DEFAULT_REGISTRY.unregister_python_tool(tool_name)

        runtime_tr = RuntimeToolRegistry()
        bootstrap: dict = {"builtin_tool_funcs": []}

        class _Plugins:
            tool_registry = runtime_tr

        class _Ws:
            agent_id = "default"
            plugins = _Plugins()

        class _Wm:
            agents = {"default": _Ws()}
            _bootstrap_kwargs = bootstrap

        old = PluginRegistry._instance
        PluginRegistry._instance = None
        try:
            preg = PluginRegistry()

            def _wm_factory():
                return _Wm()

            # type: ignore[method-assign]
            preg.get_workspace_manager = _wm_factory
            loader = PluginLoader(plugin_dirs=[])
            loader.registry = preg
            manifest = PluginManifest(
                id=plugin_id,
                name="Runtime",
                version="1.0.0",
                entry=PluginEntryPoints(backend="plugin.py"),
                meta={"tool_name": tool_name},
            )
            loader._loaded_plugins[plugin_id] = PluginRecord(
                manifest=manifest,
                source_path=Path("/fake-runtime"),
                enabled=True,
                instance=None,
            )

            async def _old_tool() -> str:
                return "old"

            _old_tool.__name__ = tool_name  # type: ignore[attr-defined]
            _bridge_to_runtime(
                tool_name,
                _old_tool,
                False,
                "old",
                preg,
            )
            _TOOL_PLUGIN_OWNERS[tool_name] = plugin_id
            assert tool_name in runtime_tr
            assert _old_tool in bootstrap["builtin_tool_funcs"]

            await loader.unload_plugin(plugin_id)
            assert tool_name not in runtime_tr
            assert not bootstrap["builtin_tool_funcs"]

            async def _new_tool() -> str:
                return "new"

            _new_tool.__name__ = tool_name  # type: ignore[attr-defined]
            _bridge_to_runtime(
                tool_name,
                _new_tool,
                False,
                "new",
                preg,
            )
            desc = runtime_tr.get(tool_name)
            assert desc is not None
            assert desc.func is _new_tool
            assert _old_tool not in bootstrap["builtin_tool_funcs"]
            assert _new_tool in bootstrap["builtin_tool_funcs"]
        finally:
            release_tool_ownership_for_plugin(plugin_id)
            DEFAULT_REGISTRY.unregister_python_tool(tool_name)
            PluginRegistry._instance = old

    @pytest.mark.asyncio
    async def test_unload_allows_other_plugin_to_reuse_name(self):
        from qwenpaw.plugins.architecture import (
            PluginEntryPoints,
            PluginManifest,
            PluginRecord,
        )
        from qwenpaw.plugins.loader import PluginLoader

        plugin_a = "__ut_loader_a__"
        plugin_b = "__ut_loader_b__"
        tool_name = "__ut_loader_reuse_tool__"
        policy = "UtLoaderReuseTool"
        for pid in (plugin_a, plugin_b):
            release_tool_ownership_for_plugin(pid)
        DEFAULT_REGISTRY.unregister_python_tool(tool_name)

        old = PluginRegistry._instance
        PluginRegistry._instance = None
        try:
            preg = PluginRegistry()
            loader = PluginLoader(plugin_dirs=[])
            loader.registry = preg
            manifest = PluginManifest(
                id=plugin_a,
                name="A",
                version="1.0.0",
                entry=PluginEntryPoints(backend="plugin.py"),
                meta={"tool_name": tool_name},
            )
            loader._loaded_plugins[plugin_a] = PluginRecord(
                manifest=manifest,
                source_path=Path("/fake-a"),
                enabled=True,
                instance=None,
            )

            register_tool_governance(
                DEFAULT_REGISTRY,
                python_name=tool_name,
                tool_type="network",
                policy_name=policy,
                owner=plugin_a,
            )
            _TOOL_PLUGIN_OWNERS[tool_name] = plugin_a

            await loader.unload_plugin(plugin_a)

            register_tool_governance(
                DEFAULT_REGISTRY,
                python_name=tool_name,
                tool_type="internal",
                policy_name=policy,
                owner=plugin_b,
            )
            _claim_tool_ownership(tool_name, plugin_b)
            assert DEFAULT_REGISTRY.get_owner(tool_name) == plugin_b
            assert DEFAULT_REGISTRY.get_type(policy) == "internal"
        finally:
            for pid in (plugin_a, plugin_b):
                release_tool_ownership_for_plugin(pid)
            DEFAULT_REGISTRY.unregister_python_tool(tool_name)
            PluginRegistry._instance = old

    @pytest.mark.asyncio
    async def test_unload_ignores_manifest_tools_not_owned(self):
        """Manifest claims must not delete other plugins' or builtin tools."""
        # pylint: disable=too-many-statements
        import sys

        from qwenpaw.plugins.architecture import (
            PluginEntryPoints,
            PluginManifest,
            PluginRecord,
        )
        from qwenpaw.plugins.loader import PluginLoader

        attacker = "__ut_loader_attacker__"
        victim = "__ut_loader_victim__"
        foreign_tool = "__ut_loader_foreign_tool__"
        builtin_name = "append_file"
        release_tool_ownership_for_plugin(attacker)
        release_tool_ownership_for_plugin(victim)
        DEFAULT_REGISTRY.unregister_python_tool(foreign_tool)

        runtime_tr = RuntimeToolRegistry()
        bootstrap: dict = {"builtin_tool_funcs": []}

        class _Plugins:
            tool_registry = runtime_tr

        class _Ws:
            agent_id = "default"
            plugins = _Plugins()

        class _Wm:
            agents = {"default": _Ws()}
            _bootstrap_kwargs = bootstrap

        old = PluginRegistry._instance
        PluginRegistry._instance = None
        tools_module = sys.modules["qwenpaw.agents.tools"]
        had_foreign_attr = hasattr(tools_module, foreign_tool)
        try:
            preg = PluginRegistry()

            def _wm_factory():
                return _Wm()

            # type: ignore[method-assign]
            preg.get_workspace_manager = _wm_factory
            loader = PluginLoader(plugin_dirs=[])
            loader.registry = preg

            async def _victim_tool() -> str:
                return "victim"

            _victim_tool.__name__ = foreign_tool  # type: ignore[attr-defined]
            _bridge_to_runtime(
                foreign_tool,
                _victim_tool,
                False,
                "victim",
                preg,
            )
            setattr(tools_module, foreign_tool, _victim_tool)
            if foreign_tool not in tools_module.__all__:
                tools_module.__all__.append(foreign_tool)
            _TOOL_PLUGIN_OWNERS[foreign_tool] = victim
            register_tool_governance(
                DEFAULT_REGISTRY,
                python_name=foreign_tool,
                tool_type="network",
                owner=victim,
            )

            # Attacker owns nothing, but manifest claims foreign + builtin.
            loader._loaded_plugins[attacker] = PluginRecord(
                manifest=PluginManifest(
                    id=attacker,
                    name="Attacker",
                    version="1.0.0",
                    entry=PluginEntryPoints(backend="plugin.py"),
                    meta={
                        "tool_name": foreign_tool,
                        "tools": [{"name": builtin_name}],
                    },
                ),
                source_path=Path("/fake-attacker"),
                enabled=True,
                instance=None,
            )

            assert hasattr(tools_module, builtin_name)
            await loader.unload_plugin(attacker)

            # Foreign ownership / runtime / agents.tools must survive.
            assert _TOOL_PLUGIN_OWNERS.get(foreign_tool) == victim
            assert foreign_tool in runtime_tr
            assert getattr(tools_module, foreign_tool) is _victim_tool
            assert foreign_tool in tools_module.__all__
            # Builtin must not be deleted by a hostile manifest claim.
            assert hasattr(tools_module, builtin_name)
            assert DEFAULT_REGISTRY.get_owner(foreign_tool) == victim
        finally:
            release_tool_ownership_for_plugin(attacker)
            release_tool_ownership_for_plugin(victim)
            DEFAULT_REGISTRY.unregister_python_tool(foreign_tool)
            if not had_foreign_attr and hasattr(tools_module, foreign_tool):
                delattr(tools_module, foreign_tool)
            if foreign_tool in getattr(tools_module, "__all__", []):
                tools_module.__all__.remove(foreign_tool)
            PluginRegistry._instance = old


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
