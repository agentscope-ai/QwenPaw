# -*- coding: utf-8 -*-
"""QwenPawLocalWorkspace — routes tool management to ToolRegistry.

Subclasses AgentScope's :class:`LocalWorkspace` so that
:meth:`list_tools` returns QwenPaw's own tools (managed by
:class:`ToolRegistry`) instead of AgentScope's built-in six.

All tool consumers call ``list_tools()`` — the only public interface:

- **No arguments**: returns default-enabled tools (``WorkspaceBase``
  protocol).
- **With filter kwargs**: returns tools filtered by per-request
  context (modes, skills, features, agent config gates).

``ToolRegistry`` is an internal implementation detail.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agentscope.workspace import LocalWorkspace as AgentScopeLocalWorkspace

if TYPE_CHECKING:
    from ...runtime.tool_registry import ToolRegistry


class QwenPawLocalWorkspace(AgentScopeLocalWorkspace):
    """LocalWorkspace whose ``list_tools`` delegates to ToolRegistry."""

    def __init__(self, tool_registry: ToolRegistry, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._tool_registry = tool_registry
        self._governor: Any = None

    def set_governor(self, governor: Any) -> None:
        """Inject the ResourceGovernor for policy-governed tool wrapping.

        Called by :class:`AgentBuilder` after the governor is created.
        Must be called before the first :meth:`list_tools` invocation
        for the governor to take effect on workspace tools.
        """
        self._governor = governor

    async def list_tools(  # type: ignore[override]
        self,
        *,
        agent_config: Any = None,
        agent_id: str | None = None,  # pylint: disable=unused-argument
        request_context: dict[str, str] | None = None,
        active_modes: tuple[str, ...] | set[str] = (),
        active_skills: tuple[str, ...] | set[str] = (),
        enabled_features: tuple[str, ...] | set[str] = (),
    ) -> list[Any]:
        """Return QwenPaw tools, replacing AgentScope built-ins.

        Without arguments the call satisfies the ``WorkspaceBase``
        protocol and returns every default-enabled tool.  When
        *agent_config* (and optional filter sets) are supplied the
        result is narrowed by config gates and four-dimensional
        filtering.
        """
        from ...governance import PolicyGuardedTool

        if agent_config is not None:
            allowed, denied = self._resolve_config_gates(agent_config)
        else:
            allowed, denied = None, set()

        descs = self._tool_registry.filter(
            active_modes=set(active_modes),
            active_skills=set(active_skills),
            enabled_features=set(enabled_features),
            allowed=allowed,
            denied=denied,
        )

        return [
            PolicyGuardedTool(
                d.func,
                governor=self._governor,
                request_context=request_context,
            )
            for d in descs
        ]

    # -------------------------------------------------------------- internal

    def _resolve_config_gates(
        self,
        agent_config: Any,
    ) -> tuple[set[str] | None, set[str]]:
        """Translate ``agent_config.tools.builtin_tools`` to (allowed, denied).

        Migrated verbatim from ``AgentBuilder._resolve_config_gates``.
        """
        cfg = (
            getattr(
                getattr(agent_config, "tools", None),
                "builtin_tools",
                None,
            )
            or {}
        )
        denied = {
            n for n, c in cfg.items() if getattr(c, "enabled", True) is False
        }
        explicit_enabled = {
            n for n, c in cfg.items() if getattr(c, "enabled", True)
        }

        defaults = self._tool_registry.default_enabled_names()
        plugin_opt_ins = explicit_enabled - defaults
        if plugin_opt_ins:
            return defaults | explicit_enabled, denied
        return None, denied


__all__ = ["QwenPawLocalWorkspace"]
