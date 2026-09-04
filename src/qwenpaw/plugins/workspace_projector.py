# -*- coding: utf-8 -*-
"""Project process-level plugin intents onto live workspaces."""

from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from ..app.channels.manager import (
    channel_cfg_for_key,
    channel_enabled,
)
from ..config import get_available_channels

logger = logging.getLogger(__name__)

ApplyFn = Callable[[Any], Any]
RevokeFn = Callable[[Any], Any]


@dataclass
class WorkspaceIntent:
    """One contribution to apply to current and future workspaces."""

    kind: str
    name: str
    plugin_id: str
    apply: ApplyFn
    revoke: RevokeFn


@dataclass
class OwnerScan:
    """Result of scanning live workspace tables by ``owner_plugin_id``."""

    stamped_leaks: list[str] = field(default_factory=list)
    saw_unstamped: bool = False


class WorkspaceProjector:
    """Store intents; apply/revoke against the *current* live workspace set.

    Do not keep Workspace object pointers for revoke — ``reload_agent``
    replaces those objects.
    """

    def __init__(
        self,
        live_workspaces: Callable[[], list[Any]] | None = None,
    ) -> None:
        self._intents: list[WorkspaceIntent] = []
        self._live = live_workspaces or default_live_workspaces

    def intend(
        self,
        kind: str,
        name: str,
        plugin_id: str,
        apply: ApplyFn,
        revoke: RevokeFn,
    ) -> WorkspaceIntent:
        intent = WorkspaceIntent(
            kind=kind,
            name=name,
            plugin_id=plugin_id,
            apply=apply,
            revoke=revoke,
        )
        self._intents.append(intent)
        return intent

    def _find(
        self,
        kind: str,
        name: str,
        plugin_id: str,
    ) -> WorkspaceIntent | None:
        for intent in self._intents:
            if (
                intent.kind == kind
                and intent.name == name
                and intent.plugin_id == plugin_id
            ):
                return intent
        return None

    async def project(self, kind: str, name: str, plugin_id: str) -> None:
        intent = self._find(kind, name, plugin_id)
        if intent is None:
            return
        for workspace in self._live():
            await _run(intent.apply, workspace)

    async def project_one(
        self,
        workspace: Any,
        kind: str,
        name: str,
        plugin_id: str,
    ) -> None:
        intent = self._find(kind, name, plugin_id)
        if intent is None:
            return
        await _run(intent.apply, workspace)

    async def revoke(self, kind: str, name: str, plugin_id: str) -> None:
        intent = self._find(kind, name, plugin_id)
        if intent is None:
            return
        self._intents.remove(intent)
        for workspace in self._live():
            try:
                await _run(intent.revoke, workspace)
            except Exception:  # noqa: BLE001
                logger.error(
                    "Revoke %s %r for plugin '%s' failed",
                    kind,
                    name,
                    plugin_id,
                    exc_info=True,
                )

    def drop_plugin(self, plugin_id: str) -> None:
        self._intents = [
            intent for intent in self._intents if intent.plugin_id != plugin_id
        ]


def default_live_workspaces() -> list[Any]:
    """Read the current workspace manager; never cached object pointers."""
    try:
        from .registry import PluginRegistry

        manager = PluginRegistry().get_workspace_manager()
        if manager is None:
            return []
        return list(getattr(manager, "agents", {}).values())
    except Exception:  # noqa: BLE001
        return []


def channel_passes_gates(workspace: Any, key: str) -> bool:
    """Three-gate: available, has a config section, and enabled."""
    available = get_available_channels()
    if key not in available:
        return False
    config = getattr(workspace, "_config", None)
    if config is None:
        return False
    ch_cfg = channel_cfg_for_key(config, key)
    if ch_cfg is None:
        return False
    return channel_enabled(ch_cfg)


def scan_owner_rows(plugin_id: str, workspaces: list[Any]) -> OwnerScan:
    """Report stamped leftovers. Unstamped rows are invisible to this scan."""
    report = OwnerScan()
    for workspace in workspaces:
        _scan_one_workspace(plugin_id, workspace, report)
    return report


def _scan_one_workspace(
    plugin_id: str,
    workspace: Any,
    report: OwnerScan,
) -> None:
    plugins = getattr(workspace, "plugins", None)
    if plugins is None:
        return
    agent_id = getattr(workspace, "agent_id", "?")
    _scan_slash(plugin_id, plugins, agent_id, report)
    _scan_tools(plugin_id, plugins, agent_id, report)
    _scan_hooks(plugin_id, plugins, agent_id, report)
    _scan_prompts(plugin_id, plugins, agent_id, report)
    _scan_modes(plugin_id, plugins, agent_id, report)
    _scan_stop_handlers(plugin_id, plugins, agent_id, report)


def _scan_slash(
    plugin_id: str,
    plugins: Any,
    agent_id: str,
    report: OwnerScan,
) -> None:
    registry = getattr(plugins, "slash_command_registry", None)
    by_name = getattr(registry, "_by_name", {}) or {}
    seen: set[int] = set()
    for spec in by_name.values():
        if id(spec) in seen:
            continue
        seen.add(id(spec))
        _note_owner(
            report,
            getattr(spec, "owner_plugin_id", "") or "",
            plugin_id,
            f"slash:/{spec.name}@{agent_id}",
        )


def _scan_tools(
    plugin_id: str,
    plugins: Any,
    agent_id: str,
    report: OwnerScan,
) -> None:
    registry = getattr(plugins, "tool_registry", None)
    descs = getattr(registry, "_descs", {}) or {}
    for name, desc in descs.items():
        _note_owner(
            report,
            getattr(desc, "owner_plugin_id", "") or "",
            plugin_id,
            f"tool:{name}@{agent_id}",
        )


def _scan_hooks(
    plugin_id: str,
    plugins: Any,
    agent_id: str,
    report: OwnerScan,
) -> None:
    registry = getattr(plugins, "hook_registry", None)
    by_phase = getattr(registry, "_by_phase", {}) or {}
    for hooks in by_phase.values():
        for hook in hooks:
            _note_owner(
                report,
                getattr(hook, "owner_plugin_id", "") or "",
                plugin_id,
                f"hook:{hook.name}@{agent_id}",
            )


def _scan_prompts(
    plugin_id: str,
    plugins: Any,
    agent_id: str,
    report: OwnerScan,
) -> None:
    manager = getattr(plugins, "prompt_manager", None)
    contributors = getattr(manager, "_contributors", []) or []
    for contributor in contributors:
        _note_owner(
            report,
            getattr(contributor, "owner_plugin_id", "") or "",
            plugin_id,
            f"prompt:{contributor.name}@{agent_id}",
        )


def _scan_modes(
    plugin_id: str,
    plugins: Any,
    agent_id: str,
    report: OwnerScan,
) -> None:
    for mode in getattr(plugins, "modes", []) or []:
        _note_owner(
            report,
            getattr(mode, "owner_plugin_id", "") or "",
            plugin_id,
            f"mode:{mode.name}@{agent_id}",
        )


def _scan_stop_handlers(
    plugin_id: str,
    plugins: Any,
    agent_id: str,
    report: OwnerScan,
) -> None:
    for reg in getattr(plugins, "stop_handlers", []) or []:
        owner = getattr(reg, "owner_plugin_id", "") or ""
        _note_owner(
            report,
            owner,
            plugin_id,
            f"stop_handler:{reg.name}@{agent_id}",
        )


def _note_owner(
    report: OwnerScan,
    owner: str,
    plugin_id: str,
    leak: str,
) -> None:
    if not owner:
        report.saw_unstamped = True
        return
    if owner == plugin_id:
        report.stamped_leaks.append(leak)


async def _run(fn: Callable[[Any], Any], workspace: Any) -> None:
    result = fn(workspace)
    if inspect.isawaitable(result):
        await result
