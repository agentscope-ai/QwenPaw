# -*- coding: utf-8 -*-
"""Project process-level plugin intents onto live workspaces."""

from __future__ import annotations

import asyncio
import inspect
import logging
import weakref
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
PROJECTION_DRAIN_TIMEOUT = 5.0


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
    workspaces: dict[str, Callable[[], Any]] = field(default_factory=dict)
    pending: dict[str, asyncio.Task[None]] = field(default_factory=dict)
    retiring: dict[str, Callable[[], Any]] = field(default_factory=dict)
    revoking: bool = False


@dataclass
class OwnerScan:
    """Result of scanning live workspace tables by ``owner_plugin_id``."""

    stamped_leaks: list[str] = field(default_factory=list)
    saw_unstamped: bool = False


class WorkspaceProjector:
    """Store intents; apply/revoke against the *current* live workspace set.

    Resolve current workspaces at revoke time. Weak references also keep
    bindings reachable while replaced workspaces drain in-flight requests.
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
            try:
                await self._project_one(intent, workspace)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{key}:{exc}")
                continue
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
        *,
        expected: WorkspaceIntent | None = None,
    ) -> None:
        intent = self._find(kind, name, plugin_id)
        if intent is None or (expected is not None and intent is not expected):
            return
        await self._project_one(intent, workspace)

    async def _project_one(
        self,
        intent: WorkspaceIntent,
        workspace: Any,
    ) -> None:
        key = _workspace_key(workspace)
        retiring = intent.retiring.get(key)
        if intent.revoking or (
            retiring is not None and retiring() is workspace
        ):
            return
        if self._has_binding(intent, workspace):
            return
        task = intent.pending.get(key)
        if task is None:

            async def apply() -> None:
                token = await self._apply(intent, workspace)
                if token is not None:
                    self._remember(intent, workspace, token)

            def finished(completed: asyncio.Task[None]) -> None:
                intent.pending.pop(key, None)
                if not completed.cancelled():
                    completed.exception()

            task = asyncio.create_task(apply())
            intent.pending[key] = task
            task.add_done_callback(finished)
        # A cancelled workspace hook must not abandon a starting resource.
        await asyncio.shield(task)

    @staticmethod
    async def _drain(intent: WorkspaceIntent, key: str | None = None) -> None:
        tasks = [
            task
            for workspace_key, task in intent.pending.items()
            if key is None or workspace_key == key
        ]
        if tasks:
            _, pending = await asyncio.wait(
                tasks,
                timeout=PROJECTION_DRAIN_TIMEOUT,
            )
            if pending:
                raise QuiescenceError(
                    f"Projection {intent.kind} {intent.name!r} still starting",
                )

    async def revoke(self, kind: str, name: str, plugin_id: str) -> None:
        intent = self._find(kind, name, plugin_id)
        if intent is None:
            return
        intent.revoking = True
        await self._drain(intent)
        errors: list[str] = []
        failed_stop: StopReceipt | None = None
        workspaces = {_workspace_key(ws): ws for ws in self._live()}
        for key, resolve in intent.workspaces.items():
            workspace = resolve()
            if workspace is not None:
                workspaces.setdefault(key, workspace)
        for key in list(intent.bindings):
            workspace = workspaces.get(key)
            if workspace is None:
                # The replaced workspace is gone; never use its token on
                # another instance with the same agent id.
                intent.bindings.pop(key, None)
                intent.workspaces.pop(key, None)
                continue
            if key not in intent.bindings:
                continue
            token = intent.bindings[key]
            try:
                result = await _run_revoke(intent.revoke, workspace, token)
            except Exception as exc:  # noqa: BLE001
                intent.workspaces[key] = _hold_workspace(workspace)
                errors.append(f"{key}:{exc}")
                continue
            if isinstance(result, StopReceipt) and not result.stopped:
                if result.detail == "not running":
                    intent.bindings.pop(key, None)
                    intent.workspaces.pop(key, None)
                    continue
                failed_stop = result
                intent.workspaces[key] = _hold_workspace(workspace)
                errors.append(f"{key}:{result.detail or 'stop failed'}")
                continue
            intent.bindings.pop(key, None)
            intent.workspaces.pop(key, None)
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

    async def revoke_workspace(self, workspace: Any) -> None:
        """Release one retiring workspace without dropping future intents."""
        key = _workspace_key(workspace)
        errors: list[str] = []
        for intent in reversed(self._intents):
            intent.retiring = {
                item: resolve
                for item, resolve in intent.retiring.items()
                if resolve() is not None
            }
            intent.retiring[key] = _workspace_ref(workspace)
            try:
                await self._drain(intent, key)
            except QuiescenceError as exc:
                errors.append(
                    f"{intent.plugin_id}:{intent.kind}:{intent.name}: {exc}",
                )
                continue
            if not self._has_binding(intent, workspace):
                continue
            try:
                result = await _run_revoke(
                    intent.revoke,
                    workspace,
                    intent.bindings[key],
                )
                if (
                    isinstance(result, StopReceipt)
                    and not result.stopped
                    and result.detail != "not running"
                ):
                    raise QuiescenceError(result.detail, receipt=result)
            except BaseException as exc:
                # Keep the retiring object reachable if resource stop fails.
                intent.workspaces[key] = _hold_workspace(workspace)
                if not isinstance(exc, Exception):
                    raise
                errors.append(
                    f"{intent.plugin_id}:{intent.kind}:{intent.name}: {exc}",
                )
                continue
            intent.bindings.pop(key, None)
            intent.workspaces.pop(key, None)
        if errors:
            raise QuiescenceError(
                "Workspace plugin cleanup failed: " + "; ".join(errors),
            )

    @staticmethod
    def _has_binding(intent: WorkspaceIntent, workspace: Any) -> bool:
        key = _workspace_key(workspace)
        if key not in intent.bindings:
            return False
        if intent.workspaces[key]() is workspace:
            return True
        # Object ids can be reused after a workspace has been collected.
        intent.bindings.pop(key, None)
        intent.workspaces.pop(key, None)
        return False

    @staticmethod
    def _remember(intent: WorkspaceIntent, workspace: Any, token: Any) -> None:
        key = _workspace_key(workspace)
        intent.bindings[key] = token
        if intent.revoking or key in intent.retiring:
            intent.workspaces[key] = _hold_workspace(workspace)
            return
        intent.workspaces[key] = _workspace_ref(workspace)

    async def _apply(self, intent: WorkspaceIntent, workspace: Any) -> Any:
        try:
            return await _run(intent.apply, workspace)
        except BaseException as exc:
            # Partial channel/mode startup can fail while cleanup also fails.
            # Such failures carry the actual handle so rollback can retry.
            cause = exc
            while cause is not None:
                token = getattr(cause, "binding", None)
                if token is not None:
                    self._remember(intent, workspace, token)
                    break
                cause = cause.__cause__
            raise

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


def live_channel_managers() -> list[Any]:
    """ChannelManager instances on the current live workspace set."""
    managers: list[Any] = []
    seen: set[int] = set()
    for workspace in default_live_workspaces():
        manager = getattr(workspace, "channel_manager", None)
        if manager is None:
            continue
        ident = id(manager)
        if ident in seen:
            continue
        seen.add(ident)
        managers.append(manager)
    return managers


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


def _hold_workspace(workspace: Any) -> Callable[[], Any]:
    """Retain one workspace for cleanup retries with a typed resolver."""

    def resolve() -> Any:
        return workspace

    return resolve


def _workspace_ref(workspace: Any) -> Callable[[], Any]:
    try:
        return weakref.ref(workspace)
    except TypeError:
        # Lightweight adapters may not support weak references.
        return _hold_workspace(workspace)


def _workspace_key(workspace: Any) -> str:
    return f"{getattr(workspace, 'agent_id', '?')}@{id(workspace)}"


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
        inspect.signature(fn).bind(workspace, token)
    except TypeError:
        result = fn(workspace)
    else:
        result = fn(workspace, token)
    if inspect.isawaitable(result):
        return await result
    return result
