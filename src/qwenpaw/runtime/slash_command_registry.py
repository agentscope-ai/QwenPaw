# -*- coding: utf-8 -*-
"""Per-workspace slash-command registry.

Named ``SlashCommandRegistry`` (not ``CommandRegistry``) to avoid clashing
with ``app/channels/command_registry.py:CommandRegistry`` — that one is the
IM-channel priority router and is unrelated to runtime slash dispatch.

Unifies the four previously-parallel command mechanisms
(conversation, control, daemon, skill) into a single dispatch point.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable

if TYPE_CHECKING:
    from agentscope.message import Msg

    from .hooks import HookContext


CommandHandler = Callable[["HookContext", str], Awaitable["Msg | None"]]
FallbackHandler = Callable[[str, "HookContext"], Awaitable["Msg | None"]]


@dataclass(frozen=True)
class CommandSpec:
    """Declarative description of one slash command.

    ``aliases`` are extra names that resolve to the same handler.
    ``category`` records the origin (``"daemon"`` / ``"control"`` /
    ``"conversation"`` / ``"skill"`` / ``"auto"`` / ``"user"``) so future
    introspection can group commands without re-parsing source. ``owner_id``
    identifies plugin commands; built-in commands remain ownerless.
    """

    name: str
    handler: CommandHandler
    aliases: tuple[str, ...] = ()
    category: str = "user"
    help_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    owner_id: str | None = None


class SlashCommandRegistry:
    """Resolve raw text starting with ``/`` to a registered ``CommandSpec``.

    Lookup is case-insensitive on the command name; arguments are returned
    verbatim (with leading whitespace stripped). When no name matches and a
    single fallback handler is registered, ``dispatch`` delegates to it —
    typically used by ``/<skill_name>`` resolution.
    """

    def __init__(self) -> None:
        self._by_name: dict[str, CommandSpec] = {}
        self._fallback: FallbackHandler | None = None

    # ---------------------------------------------------------------- register
    def _validate_registration(
        self,
        spec: CommandSpec,
    ) -> tuple[tuple[str, ...], CommandSpec | None]:
        names = (spec.name, *spec.aliases)
        keys = tuple(name.lower() for name in names)
        if any(not key for key in keys):
            raise ValueError(
                f"command spec has empty name in {names!r}",
            )
        if len(set(keys)) != len(keys):
            raise ValueError(
                f"command spec has duplicate names in {names!r}",
            )

        canonical_key = keys[0]
        replacement = self._by_name.get(canonical_key)
        if replacement is not None and (
            not spec.owner_id
            or replacement.owner_id != spec.owner_id
            or replacement.name.lower() != canonical_key
        ):
            replacement = None

        for key in keys:
            existing = self._by_name.get(key)
            if existing is None or existing is replacement:
                continue
            owner = existing.owner_id or existing.category
            raise ValueError(
                f"command /{key} already registered "
                f"by {owner} ({existing.name})",
            )
        return keys, replacement

    def validate(self, spec: CommandSpec) -> None:
        """Validate a registration without changing the registry."""
        self._validate_registration(spec)

    def register(self, spec: CommandSpec) -> None:
        keys, replacement = self._validate_registration(spec)
        if replacement is not None:
            self._by_name = {
                key: existing
                for key, existing in self._by_name.items()
                if existing is not replacement
            }
        self._by_name.update(zip(keys, (spec,) * len(keys)))

    def unregister_owner(self, owner_id: str) -> list[str]:
        """Remove all command mappings owned by a plugin."""
        if not owner_id:
            return []
        removed = sorted(
            key
            for key, spec in self._by_name.items()
            if spec.owner_id == owner_id
        )
        if removed:
            self._by_name = {
                key: spec
                for key, spec in self._by_name.items()
                if spec.owner_id != owner_id
            }
        return removed

    def register_fallback(self, handler: FallbackHandler) -> None:
        if self._fallback is not None:
            raise ValueError(
                "fallback handler already registered; only one allowed",
            )
        self._fallback = handler

    # ------------------------------------------------------------------ query
    def resolve(self, raw_text: str) -> tuple[CommandSpec, str] | None:
        """Parse ``raw_text`` and return ``(spec, args)`` or ``None``.

        Leading whitespace on ``args`` is stripped; everything else is kept
        intact (including embedded quotes and unicode).
        """
        if not raw_text:
            return None
        text = raw_text.lstrip()
        if not text.startswith("/"):
            return None
        body = text[1:]
        if not body:
            return None
        name, _, rest = body.partition(" ")
        spec = self._by_name.get(name.lower())
        if spec is None:
            return None
        return spec, rest.lstrip()

    def names(self) -> list[str]:
        return sorted(self._by_name.keys())

    def advertisable_commands(
        self,
        *,
        exclude_categories: frozenset[str] | None = None,
        exclude_names: frozenset[str] | None = None,
    ) -> list[tuple[str, str]]:
        """Return ``(name, help_text)`` pairs suitable for ACP broadcast.

        Only commands with non-empty ``help_text`` are included.
        Commands in *exclude_categories* or *exclude_names* are skipped.
        Duplicates (aliases) are de-duplicated by spec identity.
        """
        if exclude_categories is None:
            exclude_categories = frozenset()
        if exclude_names is None:
            exclude_names = frozenset()

        seen_specs: set[int] = set()
        result: list[tuple[str, str]] = []
        for name, spec in self._by_name.items():
            if id(spec) in seen_specs:
                continue
            if spec.category in exclude_categories:
                continue
            if name in exclude_names:
                continue
            if not spec.help_text:
                continue
            seen_specs.add(id(spec))
            result.append((name, spec.help_text))
        return result

    # ---------------------------------------------------------------- dispatch
    async def dispatch(
        self,
        raw_text: str,
        ctx: "HookContext",
    ) -> "Msg | None":
        """Resolve and execute. Returns ``None`` if nothing matched."""
        match = self.resolve(raw_text)
        if match is not None:
            spec, args = match
            return await spec.handler(ctx, args)
        if (
            self._fallback is not None
            and raw_text
            and raw_text.lstrip().startswith("/")
        ):
            return await self._fallback(raw_text, ctx)
        return None


__all__ = [
    "CommandHandler",
    "CommandSpec",
    "FallbackHandler",
    "SlashCommandRegistry",
]
