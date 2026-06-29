# -*- coding: utf-8 -*-
"""Unit tests for loop engineering infrastructure."""
from unittest.mock import MagicMock

import pytest

from qwenpaw.loop.stop_handler import (
    StopAction,
    StopHandlerResult,
    StopHandlerRegistration,
)
from qwenpaw.loop.doom_loop import (
    DoomLoopDetector,
    DoomLoopSignal,
)
from qwenpaw.loop.schema import (
    LoopSkillConfig,
    BUDGET_PRESETS,
)
from qwenpaw.loop.loader import LoopLoader


class TestStopHandler:
    """Tests for stop handler data structures."""

    def test_stop_action_enum(self):
        assert StopAction.ALLOW == "allow"
        assert StopAction.BLOCK == "block"

    def test_stop_handler_result_defaults(self):
        result = StopHandlerResult()
        assert result.action == StopAction.ALLOW
        assert result.continuation_message == ""
        assert result.reason == ""

    def test_stop_handler_result_block(self):
        result = StopHandlerResult(
            action=StopAction.BLOCK,
            continuation_message="Keep working",
            reason="Task incomplete",
        )
        assert result.action == StopAction.BLOCK
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


class TestDoomLoopDetector:
    """Tests for doom loop detection logic."""

    def test_no_history(self):
        detector = DoomLoopDetector(window_size=3)
        assert detector.check() == DoomLoopSignal.OK

    def test_insufficient_history(self):
        detector = DoomLoopDetector(window_size=3)
        detector.record("tool_a", "hash1", True)
        detector.record("tool_b", "hash2", True)
        assert detector.check() == DoomLoopSignal.OK

    def test_diverse_calls_ok(self):
        detector = DoomLoopDetector(
            window_size=3,
            similarity_threshold=0.8,
        )
        detector.record("tool_a", "hash1", True)
        detector.record("tool_b", "hash2", True)
        detector.record("tool_c", "hash3", True)
        assert detector.check() == DoomLoopSignal.OK

    def test_identical_calls_triggers(self):
        detector = DoomLoopDetector(
            window_size=3,
            similarity_threshold=0.8,
        )
        detector.record("tool_a", "hash1", True)
        detector.record("tool_a", "hash1", True)
        detector.record("tool_a", "hash1", True)
        assert detector.check() == DoomLoopSignal.ESCALATE_HITL

    def test_force_stop_action(self):
        detector = DoomLoopDetector(
            window_size=3,
            similarity_threshold=0.8,
            action="force_stop",
        )
        detector.record("tool_a", "hash1", True)
        detector.record("tool_a", "hash1", True)
        detector.record("tool_a", "hash1", True)
        assert detector.check() == DoomLoopSignal.FORCE_STOP

    def test_partial_repetition_below_threshold(self):
        detector = DoomLoopDetector(
            window_size=4,
            similarity_threshold=0.9,
        )
        detector.record("tool_a", "hash1", True)
        detector.record("tool_a", "hash1", True)
        detector.record("tool_a", "hash1", True)
        detector.record("tool_b", "hash2", True)
        # 3/4 same = similarity ~0.67, below 0.9
        assert detector.check() == DoomLoopSignal.OK

    def test_reset_clears_history(self):
        detector = DoomLoopDetector(window_size=3)
        detector.record("tool_a", "hash1", True)
        detector.record("tool_a", "hash1", True)
        detector.record("tool_a", "hash1", True)
        assert detector.check() == DoomLoopSignal.ESCALATE_HITL
        detector.reset()
        assert detector.check() == DoomLoopSignal.OK

    def test_hitl_message(self):
        detector = DoomLoopDetector(
            hitl_message="Agent stuck!",
        )
        assert detector.hitl_message == "Agent stuck!"


class TestDoomLoopSignal:
    """Tests for DoomLoopSignal enum."""

    def test_signal_values(self):
        assert DoomLoopSignal.OK == "ok"
        assert DoomLoopSignal.ESCALATE_HITL == "escalate_hitl"
        assert DoomLoopSignal.FORCE_STOP == "force_stop"


class TestLoopSkillConfig:
    """Tests for loop skill configuration schema."""

    def test_minimal_config(self):
        cfg = LoopSkillConfig(
            name="test-loop",
            slash_command="test",
            skill_prompt="Do the thing",
        )
        assert cfg.name == "test-loop"
        assert cfg.slash_command == "test"
        assert cfg.safety.max_iterations == 30
        assert cfg.safety.budget.max_tokens == 500000
        assert cfg.safety.budget.max_cost_usd == 5.0

    def test_full_config(self):
        cfg = LoopSkillConfig(
            name="ralph",
            slash_command="ralph",
            description="Persistent completion loop",
            skill_prompt="You are a task agent...",
            rubric={
                "mode": "hard_check",
                "check_expression": "stories.every(s => s.done)",
                "continuation_prompt": "Continue working",
            },
            state={
                "mode": "json_file",
                "filename": "ralph-state.json",
            },
            doom_loop={
                "enabled": True,
                "window_size": 3,
                "similarity_threshold": 0.8,
                "action": "hitl",
            },
            safety={
                "max_iterations": 20,
                "budget": {
                    "max_tokens": 300000,
                    "max_cost_usd": 3.0,
                    "on_exceed": "hitl",
                    "warning_threshold": 0.8,
                },
            },
        )
        assert cfg.rubric.mode == "hard_check"
        assert cfg.state.filename == "ralph-state.json"
        assert cfg.doom_loop.window_size == 3
        assert cfg.safety.budget.max_cost_usd == 3.0

    def test_budget_presets(self):
        assert "low" in BUDGET_PRESETS
        assert "medium" in BUDGET_PRESETS
        assert "high" in BUDGET_PRESETS
        assert BUDGET_PRESETS["low"]["max_tokens"] == 100000
        assert BUDGET_PRESETS["medium"]["max_cost_usd"] == 3.0
        assert BUDGET_PRESETS["high"]["max_iterations"] == 30

    def test_config_serialization(self):
        cfg = LoopSkillConfig(
            name="test",
            slash_command="test",
            skill_prompt="prompt",
        )
        data = cfg.model_dump()
        assert data["name"] == "test"
        assert "safety" in data
        assert "budget" in data["safety"]

    def test_config_from_json(self):
        raw = {
            "name": "my-loop",
            "slash_command": "myloop",
            "skill_prompt": "Do it",
            "safety": {
                "max_iterations": 10,
                "budget": {"max_tokens": 50000},
            },
        }
        cfg = LoopSkillConfig(**raw)
        assert cfg.safety.max_iterations == 10
        assert cfg.safety.budget.max_tokens == 50000


class TestLoopLoader:
    """Tests for LoopLoader integration."""

    def test_load_from_dict(self):
        mock_api = MagicMock()
        loader = LoopLoader(mock_api)

        config = {
            "name": "test-loop",
            "slash_command": "test",
            "skill_prompt": "Test prompt",
            "rubric": {"mode": "hard_check"},
            "doom_loop": {"enabled": True},
        }
        loader.load_from_dict(config)

        mock_api.register_slash_command.assert_called_once()
        mock_api.register_prompt_section.assert_called_once()
        mock_api.register_agent_stop_handler.assert_called_once()
        mock_api.register_tool_call_observer.assert_called_once()

    def test_load_without_rubric(self):
        mock_api = MagicMock()
        loader = LoopLoader(mock_api)

        config = {
            "name": "simple",
            "slash_command": "simple",
            "skill_prompt": "Simple prompt",
            "rubric": {"mode": "none"},
            "doom_loop": {"enabled": False},
        }
        loader.load_from_dict(config)

        mock_api.register_slash_command.assert_called_once()
        mock_api.register_prompt_section.assert_called_once()
        mock_api.register_agent_stop_handler.assert_not_called()
        mock_api.register_tool_call_observer.assert_not_called()

    def test_deactivate(self):
        mock_api = MagicMock()
        loader = LoopLoader(mock_api)
        assert loader.deactivate("nonexist") is False

    def test_get_status_none(self):
        mock_api = MagicMock()
        loader = LoopLoader(mock_api)
        assert loader.get_status("nonexist") is None


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
        assert hasattr(api, "register_tool_call_observer")

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
