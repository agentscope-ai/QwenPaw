# -*- coding: utf-8 -*-
"""Project process-level plugin intents onto live workspaces."""

from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from ..app.channels.manager import (
    StopReceipt,
    channel_cfg_for_key,
    channel_enabled,
)
from ..config import get_available_channels
from .lifecycle import QuiescenceError

logger = logging.getLogger(__name__)

ApplyFn = Callable[[Any], Any]
RevokeFn = Callable[..., Any]


class ProjectionError(RuntimeError):
    """A workspace projection failed and must fail the load transaction."""


@dataclass
class WorkspaceIntent:
    """One contribution to apply to current and future workspaces."""

    kind: str
    name: str
    plugin_id: str
    apply: ApplyFn
    revoke: RevokeFn
    bindings: dict[str, Any] = field(default_factory=dict)


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
        errors: list[str] = []
        for workspace in self._live():
            key = _workspace_key(workspace)
            if key in intent.bindings:
                continue
            try:
                token = await _run(intent.apply, workspace)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{key}:{exc}")
                continue
            if token is not None:
                intent.bindings[key] = token
        if errors:
            raise ProjectionError(
                f"{kind} {name!r} failed: {'; '.join(errors)}",
            )

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
        key = _workspace_key(workspace)
        if key in intent.bindings:
            return
        token = await _run(intent.apply, workspace)
        if token is not None:
            intent.bindings[key] = token

    async def revoke(self, kind: str, name: str, plugin_id: str) -> None:
        intent = self._find(kind, name, plugin_id)
        if intent is None:
            return
        errors: list[str] = []
        failed_stop: StopReceipt | None = None
        for workspace in self._live():
            key = _workspace_key(workspace)
            if key not in intent.bindings:
                continue
            token = intent.bindings[key]
            try:
                result = await _run_revoke(intent.revoke, workspace, token)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{key}:{exc}")
                continue
            if isinstance(result, StopReceipt) and not result.stopped:
                if result.detail == "not running":
                    intent.bindings.pop(key, None)
                    continue
                failed_stop = result
                errors.append(f"{key}:{result.detail or 'stop failed'}")
                continue
            intent.bindings.pop(key, None)
        if not intent.bindings:
            self._intents.remove(intent)
        if failed_stop is not None:
            raise QuiescenceError(
                f"Revoke {kind} {name!r} failed: {'; '.join(errors)}",
                receipt=failed_stop,
            )
        if errors:
            raise RuntimeError(
                f"Revoke {kind} {name!r} failed: {'; '.join(errors)}",
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


def _workspace_key(workspace: Any) -> str:
    return str(getattr(workspace, "agent_id", None) or id(workspace))


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


async def _run(fn: Callable[[Any], Any], workspace: Any) -> Any:
    result = fn(workspace)
    if inspect.isawaitable(result):
        return await result
    return result


async def _run_revoke(
    fn: Callable[..., Any],
    workspace: Any,
    token: Any,
) -> Any:
    try:
        result = fn(workspace, token)
    except TypeError:
        result = fn(workspace)
    if inspect.isawaitable(result):
        return await result
    return result
