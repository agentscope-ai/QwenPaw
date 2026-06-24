# -*- coding: utf-8 -*-
"""Per-workspace tool registry.

Each builtin tool function carries a ``ToolDescriptor``
(via ``@tool_descriptor``); the registry exposes a single
``filter(...)`` entry point that ``AgentBuilder.build_toolkit`` calls
to decide which descriptors should be wrapped into ``GuardedFunctionTool``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable


@dataclass(frozen=True)
class ToolDescriptor:
    """Declarative description of one tool function.

    The four ``requires_*`` fields each express an independent gating
    condition; all of them must hold for the tool to be selected:

    * ``requires_modes``    — at least one of the agent's active modes
                              must be listed (empty = unconditional).
    * ``requires_skills``   — at least one of the effective skills must
                              be listed (empty = unconditional).
    * ``requires_features`` — every named feature flag must be enabled
                              (empty = unconditional).
    * ``requires_sandbox``  — declarative resource needs the sandbox
                              honors (``"file_read"``, ``"file_write"``,
                              ``"shell_exec"`` …). Not used for selection
                              here; consumed by ``GuardedFunctionTool``.
    """

    name: str
    func: Callable[..., Any]
    enabled_by_default: bool = True
    requires_modes: tuple[str, ...] = ()
    requires_skills: tuple[str, ...] = ()
    requires_features: tuple[str, ...] = ()
    requires_sandbox: tuple[str, ...] = ()
    async_execution: bool = False
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class ToolRegistry:
    """Hold ``ToolDescriptor`` instances and filter them per agent request."""

    def __init__(self) -> None:
        self._descs: dict[str, ToolDescriptor] = {}

    # ---------------------------------------------------------------- register
    def register(self, desc: ToolDescriptor) -> None:
        if not isinstance(desc, ToolDescriptor):
            raise TypeError(
                "register() requires a ToolDescriptor,"
                f" got {type(desc).__name__}",
            )
        if desc.name in self._descs:
            raise ValueError(f"tool {desc.name!r} already registered")
        self._descs[desc.name] = desc

    def register_many(self, descs: Iterable[ToolDescriptor]) -> None:
        for d in descs:
            self.register(d)

    def get(self, name: str) -> ToolDescriptor | None:
        return self._descs.get(name)

    def names(self) -> list[str]:
        return sorted(self._descs.keys())

    def default_enabled_names(self) -> set[str]:
        """Names of all tools whose descriptor has ``enabled_by_default=True``.

        ``AgentBuilder`` uses this to compute the ``allowed`` set when the
        agent config opts a plugin tool back in — preserving the legacy
        rule that hardcoded tools register without being mentioned in
        config while plugin tools must be explicit.
        """
        return {n for n, d in self._descs.items() if d.enabled_by_default}

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._descs

    def __len__(self) -> int:
        return len(self._descs)

    # ------------------------------------------------------------------ filter
    def filter(
        self,
        *,
        active_modes: set[str] | frozenset[str] | None = None,
        active_skills: set[str] | frozenset[str] | None = None,
        enabled_features: set[str] | frozenset[str] | None = None,
        allowed: set[str] | frozenset[str] | None = None,
        denied: set[str] | frozenset[str] | None = None,
    ) -> list[ToolDescriptor]:
        """Return the descriptors selected for the current request.

        Selection rules (any failed check ⇒ skip without error):

        * ``denied`` wins outright.
        * Non-empty ``allowed`` restricts the set to listed names; in that
          case ``enabled_by_default=False`` tools that *are* in ``allowed``
          still pass.
        * ``requires_*`` gates apply as documented on
          :class:`ToolDescriptor`.
        """
        modes = set(active_modes or ())
        skills = set(active_skills or ())
        features = set(enabled_features or ())
        allow = set(allowed or ())
        deny = set(denied or ())

        out: list[ToolDescriptor] = []
        for d in self._descs.values():
            if d.name in deny:
                continue
            if allow and d.name not in allow:
                continue
            if not d.enabled_by_default and d.name not in allow:
                continue
            if d.requires_modes and not set(d.requires_modes) & modes:
                continue
            if d.requires_skills and not set(d.requires_skills) & skills:
                continue
            if d.requires_features and not set(d.requires_features).issubset(
                features,
            ):
                continue
            out.append(d)
        return out


# ---------------------------------------------------------------------------
# Global auto-collection — populated by @tool_descriptor at import time
# ---------------------------------------------------------------------------

_REGISTERED_TOOL_FUNCS: list[Callable[..., Any]] = []
_REGISTERED_IDS: set[int] = set()

# Built-in tools live under this package prefix.  Functions decorated
# outside this prefix (e.g. in tests) are silently ignored by
# ``get_builtin_tool_funcs()``.
_BUILTIN_TOOLS_PREFIX = "qwenpaw.agents.tools."


def get_builtin_tool_funcs() -> list[Callable[..., Any]]:
    """Return all built-in tool functions auto-collected by
    ``@tool_descriptor``.

    Only functions whose ``__module__`` starts with the built-in tools
    package prefix are included, so test helpers or plugin tools that
    also use ``@tool_descriptor`` are not mixed in.
    """
    return [
        fn
        for fn in _REGISTERED_TOOL_FUNCS
        if getattr(fn, "__module__", "").startswith(_BUILTIN_TOOLS_PREFIX)
    ]


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------


def tool_descriptor(
    *,
    name: str | None = None,
    enabled_by_default: bool = True,
    requires_modes: tuple[str, ...] = (),
    requires_skills: tuple[str, ...] = (),
    requires_features: tuple[str, ...] = (),
    requires_sandbox: tuple[str, ...] = (),
    async_execution: bool | None = None,
    description: str = "",
    **metadata: Any,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Attach a :class:`ToolDescriptor` to ``fn._tool_descriptor`` and
    auto-collect the function into the global registry.

    When ``async_execution`` is not explicitly provided it is
    auto-detected via :func:`inspect.iscoroutinefunction`.

    Built-in tools (under ``qwenpaw.agents.tools``) are automatically
    discoverable via :func:`get_builtin_tool_funcs` — no manual list
    maintenance or filesystem scanning required.
    """

    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        import inspect

        resolved_name = name or fn.__name__
        is_async = (
            async_execution
            if async_execution is not None
            else inspect.iscoroutinefunction(fn)
        )
        # pylint: disable=protected-access
        fn._tool_descriptor = ToolDescriptor(  # type: ignore[attr-defined]
            name=resolved_name,
            func=fn,
            enabled_by_default=enabled_by_default,
            requires_modes=tuple(requires_modes),
            requires_skills=tuple(requires_skills),
            requires_features=tuple(requires_features),
            requires_sandbox=tuple(requires_sandbox),
            async_execution=is_async,
            description=(
                description or (fn.__doc__ or "").strip().splitlines()[0]
                if fn.__doc__
                else description
            ),
            metadata=dict(metadata),
        )
        # pylint: enable=protected-access
        if id(fn) not in _REGISTERED_IDS:
            _REGISTERED_IDS.add(id(fn))
            _REGISTERED_TOOL_FUNCS.append(fn)
        return fn

    return deco


__all__ = [
    "ToolDescriptor",
    "ToolRegistry",
    "get_builtin_tool_funcs",
    "tool_descriptor",
]
