# -*- coding: utf-8 -*-
"""Unit tests for qwenpaw.app.channels.command_registry."""

from __future__ import annotations

# pylint: disable=protected-access,redefined-outer-name,unused-argument,use-implicit-booleaness-not-comparison,unused-import  # noqa: E501

import pytest

from qwenpaw.app.channels.command_registry import CommandRegistry


@pytest.fixture
def registry() -> CommandRegistry:
    return CommandRegistry()


# ---------------------------------------------------------------------------
# Initialization & defaults
# ---------------------------------------------------------------------------


class TestCommandRegistryDefaults:
    def test_default_priority_levels(self, registry: CommandRegistry):
        assert registry.get_priority_name(0) == "critical"
        assert registry.get_priority_name(10) == "high"
        assert registry.get_priority_name(20) == "normal"
        assert registry.get_priority_name(30) == "low"

    def test_priority_name_for_custom_level(self, registry: CommandRegistry):
        assert registry.get_priority_name(5) == "custom-5"

    def test_get_all_priority_names_sorted(self, registry: CommandRegistry):
        names = registry.get_all_priority_names()
        assert names == ["critical", "high", "normal", "low"]

    def test_stop_registered_critical(self, registry: CommandRegistry):
        assert registry.get_priority_level("/stop") == 0

    def test_daemon_commands_registered_high(self, registry: CommandRegistry):
        for cmd in (
            "/daemon status",
            "/daemon restart",
            "/daemon reload-config",
            "/daemon version",
            "/daemon logs",
            "/daemon approve",
        ):
            assert registry.get_priority_level(cmd) == 10

    def test_daemon_short_aliases_registered_high(
        self,
        registry: CommandRegistry,
    ):
        for cmd in (
            "/status",
            "/restart",
            "/reload-config",
            "/reload_config",
            "/version",
            "/logs",
            "/approve",
            "/deny",
        ):
            assert registry.get_priority_level(cmd) == 10, cmd


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegisterCommand:
    def test_register_with_priority_name(self, registry: CommandRegistry):
        registry.register_command("/foo", priority="critical")
        assert registry.get_priority_level("/foo") == 0

    def test_register_with_priority_level(self, registry: CommandRegistry):
        registry.register_command("/bar", priority_level=5)
        assert registry.get_priority_level("/bar") == 5

    def test_register_unknown_priority_name_raises(
        self,
        registry: CommandRegistry,
    ):
        with pytest.raises(ValueError):
            registry.register_command("/foo", priority="nonexistent")

    def test_register_no_priority_raises(self, registry: CommandRegistry):
        with pytest.raises(ValueError):
            registry.register_command("/foo")

    def test_priority_level_overrides_priority_name(
        self,
        registry: CommandRegistry,
    ):
        registry.register_command("/foo", priority="high", priority_level=15)
        assert registry.get_priority_level("/foo") == 15

    def test_register_is_case_insensitive(self, registry: CommandRegistry):
        registry.register_command("/FooBar", priority_level=5)
        assert registry.get_priority_level("/FOOBAR") == 5
        assert registry.get_priority_level("/foobar") == 5

    def test_register_overwrites_previous(self, registry: CommandRegistry):
        registry.register_command("/foo", priority_level=5)
        registry.register_command("/foo", priority_level=10)
        assert registry.get_priority_level("/foo") == 10


# ---------------------------------------------------------------------------
# Lookup conflict resolution
# ---------------------------------------------------------------------------


class TestLookupAndConflictResolution:
    def test_unknown_command_returns_default(self, registry: CommandRegistry):
        assert registry.get_priority_level("/unknown-command") == 20

    def test_non_slash_command_returns_default(
        self,
        registry: CommandRegistry,
    ):
        assert registry.get_priority_level("hello world") == 20

    def test_empty_query_returns_default(self, registry: CommandRegistry):
        assert registry.get_priority_level("") == 20

    def test_none_query_returns_default(self, registry: CommandRegistry):
        assert registry.get_priority_level(None) == 20  # noqa

    def test_non_string_query_returns_default(
        self,
        registry: CommandRegistry,
    ):
        assert registry.get_priority_level(123) == 20  # type: ignore[arg-type]

    def test_longest_prefix_wins(self, registry: CommandRegistry):
        # /daemon is not registered, but /daemon status is.
        # Register a shorter overlapping prefix.
        registry.register_command("/daemon", priority_level=20)
        # Longer prefix should still win
        assert registry.get_priority_level("/daemon status") == 10
        # Shorter prefix for plain /daemon
        assert registry.get_priority_level("/daemon") == 20

    def test_stop_with_args_remains_critical(
        self,
        registry: CommandRegistry,
    ):
        assert registry.get_priority_level("/stop now please") == 0

    def test_prefix_word_boundary_no_false_match(
        self,
        registry: CommandRegistry,
    ):
        # /stopx is NOT /stop — should fall back to default
        assert registry.get_priority_level("/stopx") == 20

    def test_case_insensitive_lookup(self, registry: CommandRegistry):
        assert registry.get_priority_level("/STOP") == 0
        assert registry.get_priority_level("/Daemon STATUS") == 10

    def test_whitespace_tolerant(self, registry: CommandRegistry):
        # Leading/trailing whitespace is stripped
        assert registry.get_priority_level("  /stop  ") == 0
        # Boundary whitespace (space between command and args) is matched
        assert registry.get_priority_level("/daemon status info") == 10


# ---------------------------------------------------------------------------
# is_control_command
# ---------------------------------------------------------------------------


class TestIsControlCommand:
    def test_known_control_command(self, registry: CommandRegistry):
        assert registry.is_control_command("/stop")

    def test_known_control_with_args(self, registry: CommandRegistry):
        assert registry.is_control_command("/daemon status now")

    def test_unknown_command_returns_false(self, registry: CommandRegistry):
        assert not registry.is_control_command("/unknown-xyz")

    def test_non_slash_returns_false(self, registry: CommandRegistry):
        assert not registry.is_control_command("hello")

    def test_empty_returns_false(self, registry: CommandRegistry):
        assert not registry.is_control_command("")
        assert not registry.is_control_command(None)  # type: ignore[arg-type]

    def test_no_word_boundary_false(self, registry: CommandRegistry):
        assert not registry.is_control_command("/stopx")

    def test_tab_delimiter_recognized(self, registry: CommandRegistry):
        assert registry.is_control_command("/stop\tnow")


# ---------------------------------------------------------------------------
# Unregister
# ---------------------------------------------------------------------------


class TestUnregisterCommand:
    def test_unregister_known_command(self, registry: CommandRegistry):
        assert registry.unregister_command("/stop")
        assert registry.get_priority_level("/stop") == 20
        assert not registry.is_registered("/stop")

    def test_unregister_unknown_returns_false(
        self,
        registry: CommandRegistry,
    ):
        assert not registry.unregister_command("/never-registered")

    def test_unregister_case_insensitive(self, registry: CommandRegistry):
        registry.register_command("/Foo", priority_level=5)
        assert registry.unregister_command("/FOO")
        assert not registry.is_registered("/foo")

    def test_is_registered_case_insensitive(self, registry: CommandRegistry):
        registry.register_command("/Foo", priority_level=5)
        assert registry.is_registered("/foo")
        assert registry.is_registered("/FOO")


# ---------------------------------------------------------------------------
# get_registered_commands
# ---------------------------------------------------------------------------


class TestGetRegisteredCommands:
    def test_returns_copy(self, registry: CommandRegistry):
        cmds = registry.get_registered_commands()
        cmds["/injected"] = 99
        assert not registry.is_registered("/injected")

    def test_includes_registered(self, registry: CommandRegistry):
        registry.register_command("/foo", priority_level=7)
        cmds = registry.get_registered_commands()
        assert cmds["/foo"] == 7
        assert "/stop" in cmds
