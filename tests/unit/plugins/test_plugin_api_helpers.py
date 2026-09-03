# -*- coding: utf-8 -*-
"""Tests for plugin API convenience helpers.

Covers the module-level ``get_tool_config`` (registry delegation and
all early-return paths), ``PluginApi._get_workspace_from_info``
(direct workspace, agent_id lookup, missing agent, exception swallow),
``_write_tool_config`` (no-agent-id guard), and
``register_prompt_section`` (registry delegation + condition wrapping).
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument,use-implicit-booleaness-not-comparison  # noqa: E501
from __future__ import annotations

from unittest.mock import MagicMock, patch


from qwenpaw.plugins import api as plugins_api
from qwenpaw.plugins.api import PluginApi


# ---------------------------------------------------------------------------
# module-level get_tool_config
# ---------------------------------------------------------------------------


class TestGetToolConfig:
    def test_no_agent_id_returns_none(self):
        with patch(
            "qwenpaw.plugins.api.get_current_agent_id",
            create=True,
            return_value=None,
        ):
            with patch(
                "qwenpaw.app.agent_context.get_current_agent_id",
                return_value=None,
            ):
                result = plugins_api.get_tool_config("my_tool")
        assert result is None

    def test_returns_registry_config(self):
        fake_registry = MagicMock()
        fake_registry.get_tool_config.return_value = {"api_key": "abc"}
        with (
            patch(
                "qwenpaw.app.agent_context.get_current_agent_id",
                return_value="agent-1",
            ),
            patch(
                "qwenpaw.plugins.registry.PluginRegistry",
                return_value=fake_registry,
            ),
        ):
            result = plugins_api.get_tool_config("my_tool")
        assert result == {"api_key": "abc"}
        fake_registry.get_tool_config.assert_called_once_with(
            "my_tool",
            "agent-1",
        )

    def test_exception_returns_none(self):
        with patch(
            "qwenpaw.app.agent_context.get_current_agent_id",
            side_effect=RuntimeError("boom"),
        ):
            result = plugins_api.get_tool_config("my_tool")
        assert result is None


# ---------------------------------------------------------------------------
# _get_workspace_from_info
# ---------------------------------------------------------------------------


class TestGetWorkspaceFromInfo:
    def test_workspace_in_dict(self):
        api = PluginApi("test-plugin", {})
        ws = MagicMock(name="workspace")
        result = api._get_workspace_from_info({"workspace": ws})
        assert result is ws

    def test_agent_id_lookup(self):
        api = PluginApi("test-plugin", {})
        ws = MagicMock(name="workspace")
        fake_mgr = MagicMock()
        fake_mgr.agents = {"agent-1": ws}
        fake_registry = MagicMock()
        fake_registry.get_workspace_manager.return_value = fake_mgr
        with patch(
            "qwenpaw.plugins.registry.PluginRegistry",
            return_value=fake_registry,
        ):
            result = api._get_workspace_from_info({"agent_id": "agent-1"})
        assert result is ws

    def test_no_agent_id_returns_none(self):
        api = PluginApi("test-plugin", {})
        result = api._get_workspace_from_info({})
        assert result is None

    def test_no_workspace_manager_returns_none(self):
        api = PluginApi("test-plugin", {})
        fake_registry = MagicMock()
        fake_registry.get_workspace_manager.return_value = None
        with patch(
            "qwenpaw.plugins.registry.PluginRegistry",
            return_value=fake_registry,
        ):
            result = api._get_workspace_from_info({"agent_id": "agent-1"})
        assert result is None

    def test_registry_exception_returns_none(self):
        api = PluginApi("test-plugin", {})
        with patch(
            "qwenpaw.plugins.registry.PluginRegistry",
            side_effect=RuntimeError("registry down"),
        ):
            result = api._get_workspace_from_info({"agent_id": "agent-1"})
        assert result is None


# ---------------------------------------------------------------------------
# _write_tool_config
# ---------------------------------------------------------------------------


class TestWriteToolConfig:
    def test_no_agent_id_skips_write(self, caplog):
        with patch(
            "qwenpaw.app.agent_context.get_current_agent_id",
            return_value=None,
        ):
            plugins_api._write_tool_config(
                "my_tool",
                enabled=True,
                description="desc",
                icon="icon.png",
            )
        assert "No current agent ID" in caplog.text

    def test_writes_to_agent_config(self):
        fake_config = MagicMock()
        fake_config.tools = None
        with (
            patch(
                "qwenpaw.app.agent_context.get_current_agent_id",
                return_value="agent-1",
            ),
            patch(
                "qwenpaw.config.config.load_agent_config",
                return_value=fake_config,
            ),
            patch("qwenpaw.config.config.save_agent_config") as save_mock,
        ):
            plugins_api._write_tool_config(
                "my_tool",
                enabled=True,
                description="A tool",
                icon="icon.png",
            )
        save_mock.assert_called_once()

    def test_updates_existing_tool_entry(self):
        fake_config = MagicMock()
        from qwenpaw.config.config import ToolsConfig

        fake_config.tools = ToolsConfig()
        fake_config.tools.builtin_tools["existing_tool"] = MagicMock()
        with (
            patch(
                "qwenpaw.app.agent_context.get_current_agent_id",
                return_value="agent-1",
            ),
            patch(
                "qwenpaw.config.config.load_agent_config",
                return_value=fake_config,
            ),
            patch("qwenpaw.config.config.save_agent_config") as save_mock,
        ):
            plugins_api._write_tool_config(
                "existing_tool",
                enabled=False,
                description="updated",
                icon="new.png",
            )
        # Entry should be updated, not duplicated
        assert "existing_tool" in fake_config.tools.builtin_tools
        save_mock.assert_called_once()


# ---------------------------------------------------------------------------
# register_prompt_section
# ---------------------------------------------------------------------------


class TestRegisterPromptSection:
    def test_without_registry_does_nothing(self):
        api = PluginApi("test-plugin", {})
        api.set_registry(None)
        # Should not raise
        api.register_prompt_section(
            name="test_section",
            after="workspace",
            provider=lambda agent: "text",
        )

    def test_delegates_to_registry(self):
        api = PluginApi("test-plugin", {})
        fake_registry = MagicMock()
        api.set_registry(fake_registry)
        provider = lambda agent: "injected text"
        api.register_prompt_section(
            name="my_section",
            after="workspace",
            provider=provider,
            priority=50,
        )
        fake_registry.register_prompt_section.assert_called_once()
        call_kwargs = fake_registry.register_prompt_section.call_args.kwargs
        assert call_kwargs["plugin_id"] == "test-plugin"
        assert call_kwargs["name"] == "my_section"
        assert call_kwargs["after"] == "workspace"

    def test_condition_wraps_provider(self):
        api = PluginApi("test-plugin", {})
        fake_registry = MagicMock()
        api.set_registry(fake_registry)
        call_log = []

        def provider(agent):
            call_log.append("called")
            return "gated text"

        def condition(agent):
            return False

        api.register_prompt_section(
            name="gated",
            after="env_context",
            provider=provider,
            condition=condition,
        )
        # The registered provider should be the gated wrapper
        registered_provider = (
            fake_registry.register_prompt_section.call_args.kwargs["provider"]
        )
        result = registered_provider(MagicMock())
        assert result == ""  # condition is False
        assert call_log == []  # provider not called

    def test_condition_true_calls_provider(self):
        api = PluginApi("test-plugin", {})
        fake_registry = MagicMock()
        api.set_registry(fake_registry)

        api.register_prompt_section(
            name="gated",
            after="env_context",
            provider=lambda agent: "content",
            condition=lambda agent: True,
        )
        registered_provider = (
            fake_registry.register_prompt_section.call_args.kwargs["provider"]
        )
        assert registered_provider(MagicMock()) == "content"

    def test_condition_exception_returns_empty(self):
        api = PluginApi("test-plugin", {})
        fake_registry = MagicMock()
        api.set_registry(fake_registry)

        api.register_prompt_section(
            name="gated",
            after="env_context",
            provider=lambda agent: "content",
            condition=lambda agent: 1 / 0,
        )
        registered_provider = (
            fake_registry.register_prompt_section.call_args.kwargs["provider"]
        )
        assert registered_provider(MagicMock()) == ""
