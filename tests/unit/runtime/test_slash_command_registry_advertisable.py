# -*- coding: utf-8 -*-
"""Tests for SlashCommandRegistry.advertisable_commands()."""
from __future__ import annotations

import pytest

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


class TestOwnerAwareRegistration:
    """Verify plugin ownership, replacement, and cleanup semantics."""

    @pytest.mark.parametrize(
        ("name", "aliases"),
        [
            ("taken", ("new-alias",)),
            ("new-command", ("taken",)),
        ],
    )
    def test_collision_is_atomic(self, name, aliases) -> None:
        registry = SlashCommandRegistry()
        original = CommandSpec(name="taken", handler=_noop_handler)
        registry.register(original)

        with pytest.raises(ValueError, match="already registered"):
            registry.register(
                CommandSpec(
                    name=name,
                    aliases=aliases,
                    handler=_noop_handler,
                    owner_id="plugin-a",
                ),
            )

        assert registry.names() == ["taken"]
        assert registry.resolve("/taken")[0] is original

    def test_builtin_and_cross_plugin_collisions_are_rejected(self) -> None:
        registry = SlashCommandRegistry()
        builtin = CommandSpec(name="builtin", handler=_noop_handler)
        plugin = CommandSpec(
            name="plugin",
            handler=_noop_handler,
            owner_id="plugin-a",
        )
        registry.register(builtin)
        registry.register(plugin)

        with pytest.raises(ValueError):
            registry.register(
                CommandSpec(
                    name="builtin",
                    handler=_noop_handler,
                    owner_id="plugin-a",
                ),
            )
        with pytest.raises(ValueError):
            registry.register(
                CommandSpec(
                    name="plugin",
                    handler=_noop_handler,
                    owner_id="plugin-b",
                ),
            )

        assert registry.resolve("/builtin")[0] is builtin
        assert registry.resolve("/plugin")[0] is plugin

    def test_same_owner_replaces_handler_and_removes_stale_aliases(
        self,
    ) -> None:
        registry = SlashCommandRegistry()

        async def old_handler(_ctx, _args):
            return None

        async def new_handler(_ctx, _args):
            return None

        registry.register(
            CommandSpec(
                name="deploy",
                aliases=("old", "legacy"),
                handler=old_handler,
                owner_id="plugin-a",
            ),
        )
        replacement = CommandSpec(
            name="deploy",
            aliases=("new",),
            handler=new_handler,
            owner_id="plugin-a",
        )
        registry.register(replacement)

        assert registry.names() == ["deploy", "new"]
        assert registry.resolve("/deploy")[0].handler is new_handler
        assert registry.resolve("/new")[0] is replacement
        assert registry.resolve("/old") is None
        assert registry.resolve("/legacy") is None

    def test_same_owner_alias_collision_does_not_replace_other_command(
        self,
    ) -> None:
        registry = SlashCommandRegistry()
        original = CommandSpec(
            name="alpha",
            aliases=("shared",),
            handler=_noop_handler,
            owner_id="plugin-a",
        )
        registry.register(original)

        with pytest.raises(ValueError, match="already registered"):
            registry.register(
                CommandSpec(
                    name="beta",
                    aliases=("shared",),
                    handler=_noop_handler,
                    owner_id="plugin-a",
                ),
            )

        assert registry.names() == ["alpha", "shared"]
        assert registry.resolve("/alpha")[0] is original
        assert registry.resolve("/shared")[0] is original
        assert registry.resolve("/beta") is None

    def test_unregister_owner_removes_only_owners_mappings(self) -> None:
        registry = SlashCommandRegistry()
        builtin = CommandSpec(name="builtin", handler=_noop_handler)
        other = CommandSpec(
            name="other",
            aliases=("other-alias",),
            handler=_noop_handler,
            owner_id="plugin-b",
        )
        registry.register(builtin)
        registry.register(
            CommandSpec(
                name="owned",
                aliases=("owned-alias",),
                handler=_noop_handler,
                owner_id="plugin-a",
            ),
        )
        registry.register(other)

        assert registry.unregister_owner("plugin-a") == [
            "owned",
            "owned-alias",
        ]
        assert registry.names() == ["builtin", "other", "other-alias"]
        assert registry.resolve("/builtin")[0] is builtin
        assert registry.resolve("/other")[0] is other
        assert registry.unregister_owner("") == []
