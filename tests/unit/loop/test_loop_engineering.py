# -*- coding: utf-8 -*-
"""Unit tests for loop engineering infrastructure."""

import pytest

from qwenpaw.loop.gates import (
    StopAction,
    StopHandlerResult,
    StopHandlerRegistration,
)


class TestStopHandler:
    """Tests for stop handler data structures."""

    def test_stop_action_enum(self):
        assert StopAction.STOP == "stop"
        assert StopAction.CONTINUE == "continue"

    def test_stop_handler_result_defaults(self):
        result = StopHandlerResult()
        assert result.action == StopAction.STOP
        assert result.continuation_message == ""
        assert result.reason == ""

    def test_stop_handler_result_continue(self):
        result = StopHandlerResult(
            action=StopAction.CONTINUE,
            continuation_message="Keep working",
            reason="Task incomplete",
        )
        assert result.action == StopAction.CONTINUE
        assert result.continuation_message == "Keep working"

    def test_registration_dataclass(self):
        reg = StopHandlerRegistration(
            plugin_id="test-plugin",
            handler=lambda ctx: None,
            priority=50,
            name="test_stop",
        )
        assert reg.plugin_id == "test-plugin"
        assert reg.priority == 50
        assert reg.name == "test_stop"


class TestPluginApiLoopMethods:
    """Test that PluginApi exposes all loop methods."""

    def test_has_all_methods(self):
        from qwenpaw.plugins.api import PluginApi

        api = PluginApi("test", {})
        assert hasattr(api, "register_slash_command")
        assert hasattr(api, "register_mode")
        assert hasattr(api, "register_runtime_hook")
        assert hasattr(api, "register_agent_stop_handler")
        assert hasattr(api, "register_prompt_section")

    # pylint: disable=protected-access
    def test_register_slash_command_deferred(self):
        from qwenpaw.plugins.api import PluginApi
        from qwenpaw.plugins.registry import PluginRegistry

        registry = PluginRegistry()
        registry._instance = registry
        registry._initialized = True
        registry._startup_hooks = []
        registry._workspace_created_hooks = []

        api = PluginApi("test-plugin", {})
        api.set_registry(registry)

        async def handler(_ctx, _args):
            pass

        api.register_slash_command(
            name="mycommand",
            handler=handler,
            help_text="Test command",
        )

        hook_names = [h.hook_name for h in registry._startup_hooks]
        assert any("slash_cmd" in n for n in hook_names)

        ws_hook_names = [
            h.hook_name for h in registry._workspace_created_hooks
        ]
        assert any("slash_cmd_ws" in n for n in ws_hook_names)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
