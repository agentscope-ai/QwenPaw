# -*- coding: utf-8 -*-
"""Tests for SlashCommandRegistry.advertisable_commands()."""
from __future__ import annotations

from qwenpaw.runtime.slash_command_registry import (
    CommandSpec,
    SlashCommandRegistry,
)


def _noop_handler(_ctx, _args):  # noqa: W0613
    """Dummy async handler for testing."""
    return None


class TestAdvertisableCommands:
    """Verify advertisable_commands() filtering logic."""

    def test_returns_only_commands_with_help_text(self) -> None:
        registry = SlashCommandRegistry()
        registry.register(
            CommandSpec(
                name="visible",
                handler=_noop_handler,
                help_text="A visible command",
            ),
        )
        registry.register(
            CommandSpec(name="hidden", handler=_noop_handler, help_text=""),
        )

        result = registry.advertisable_commands()
        names = [name for name, _ in result]
        assert "visible" in names
        assert "hidden" not in names

    def test_excludes_by_category(self) -> None:
        registry = SlashCommandRegistry()
        registry.register(
            CommandSpec(
                name="user_cmd",
                handler=_noop_handler,
                category="user",
                help_text="User",
            ),
        )
        registry.register(
            CommandSpec(
                name="daemon_cmd",
                handler=_noop_handler,
                category="daemon",
                help_text="Daemon",
            ),
        )

        result = registry.advertisable_commands(
            exclude_categories=frozenset({"daemon"}),
        )
        names = [name for name, _ in result]
        assert "user_cmd" in names
        assert "daemon_cmd" not in names

    def test_excludes_by_name(self) -> None:
        registry = SlashCommandRegistry()
        registry.register(
            CommandSpec(name="keep", handler=_noop_handler, help_text="Keep"),
        )
        registry.register(
            CommandSpec(name="drop", handler=_noop_handler, help_text="Drop"),
        )

        result = registry.advertisable_commands(
            exclude_names=frozenset({"drop"}),
        )
        names = [name for name, _ in result]
        assert "keep" in names
        assert "drop" not in names

    def test_deduplicates_aliases(self) -> None:
        registry = SlashCommandRegistry()
        spec = CommandSpec(
            name="primary",
            handler=_noop_handler,
            aliases=("alias1",),
            help_text="Desc",
        )
        registry.register(spec)

        result = registry.advertisable_commands()
        # Should only appear once despite having an alias
        assert len(result) == 1
        assert result[0][0] == "primary"

    def test_empty_registry_returns_empty(self) -> None:
        registry = SlashCommandRegistry()
        result = registry.advertisable_commands()
        assert not result

    def test_combined_filters(self) -> None:
        registry = SlashCommandRegistry()
        registry.register(
            CommandSpec(
                name="a",
                handler=_noop_handler,
                category="user",
                help_text="A",
            ),
        )
        registry.register(
            CommandSpec(
                name="b",
                handler=_noop_handler,
                category="daemon",
                help_text="B",
            ),
        )
        registry.register(
            CommandSpec(
                name="c",
                handler=_noop_handler,
                category="user",
                help_text="C",
            ),
        )

        result = registry.advertisable_commands(
            exclude_categories=frozenset({"daemon"}),
            exclude_names=frozenset({"c"}),
        )
        names = [name for name, _ in result]
        assert names == ["a"]
