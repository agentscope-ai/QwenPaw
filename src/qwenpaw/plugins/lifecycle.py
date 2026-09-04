# -*- coding: utf-8 -*-
"""Plugin instance ledger, unload modes, and lifecycle facade."""

from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Literal

logger = logging.getLogger(__name__)

# Generous until CloudPaw / other slow startups are calibrated. Only
# bounds ``await``; a synchronous ``requests.get`` still blocks the loop.
REGISTER_WALL_CLOCK_SECONDS = 300.0

# Last instance created for each id. Runtime hooks use this to attach
# diagnostics without holding a loader reference.
_LIVE_INSTANCES: dict[str, "PluginInstance"] = {}


def note_plugin_diagnostic(plugin_id: str, message: str) -> None:
    """Record a runtime diagnostic on the live instance, if any."""
    inst = _LIVE_INSTANCES.get(plugin_id)
    if inst is None:
        return
    inst.add_diagnostic(message)


class UnloadMode(str, Enum):
    """Three projections of the same teardown ledger."""

    SHUTDOWN = "shutdown"
    UNLOAD = "unload"
    UNINSTALL = "uninstall"


class PluginState(str, Enum):
    """Runtime state of one loaded (or failed) plugin instance."""

    ACTIVE = "active"
    FAILED = "failed"
    UNLOADING = "unloading"
    DISPOSED = "disposed"


@dataclass
class UnloadReceipt:
    """Reply from ``LifecycleDelegate.notify_unload``."""

    ok: bool = True
    detail: str = ""
    leftovers: list[str] = field(default_factory=list)


@dataclass
class UnloadReport:
    """Result of ``PluginInstance.dispose`` / ``PluginLifecycle.unload``."""

    plugin_id: str
    mode: UnloadMode
    clean: bool = True
    errors: list[str] = field(default_factory=list)
    leftovers: list[str] = field(default_factory=list)
    workspace_leaks: list[str] = field(default_factory=list)
    receipt: UnloadReceipt | None = None
    quiescent: bool = True

    def absorb(self, other: "UnloadReport") -> None:
        """Merge errors and flags from another report into this one."""
        if not other.clean:
            self.clean = False
        if not other.quiescent:
            self.quiescent = False
        self.errors.extend(other.errors)
        self.leftovers.extend(other.leftovers)
        self.workspace_leaks.extend(other.workspace_leaks)
        if other.receipt is not None:
            self.receipt = other.receipt


@dataclass
class ReloadReport:
    """Result of ``PluginLifecycle.reload``."""

    plugin_id: str
    ok: bool = True
    unchanged: bool = False
    errors: list[str] = field(default_factory=list)
    generation: int = 0


@dataclass
class ConfigUpdateReport:
    """Result of ``PluginLifecycle.update_config``."""

    plugin_id: str
    ok: bool = True
    unchanged: bool = False
    errors: list[str] = field(default_factory=list)
    requires_confirmation: bool = False
    legacy_hooks: list[str] = field(default_factory=list)


@dataclass
class LedgerEntry:
    """One recorded registration and how to undo it."""

    desc: str
    teardown: Callable[..., Any] | None
    layer: Literal["runtime", "install"]
    shutdown_critical: bool = True
    kind: str = "official"


class LifecycleDelegate:
    """Single predicate for the five reserved branch points.

    Default implementation equals today's in-process, shared-site behaviour.
    Isolation fills these in later; callers only ask the delegate.
    """

    def owns_commit(self, plugin_id: str) -> bool:
        del plugin_id
        return True

    def owns_dependency_env(self, plugin_id: str) -> bool:
        del plugin_id
        return True

    def notify_unload(
        self,
        plugin_id: str,
        mode: UnloadMode,
    ) -> UnloadReceipt:
        del plugin_id, mode
        return UnloadReceipt(ok=True, detail="local")


class PluginInstance:
    """One loaded plugin: state, generation, two-layer ledger."""

    def __init__(self, plugin_id: str) -> None:
        self.plugin_id = plugin_id
        self.delegate: LifecycleDelegate | None = None
        self.state = PluginState.ACTIVE
        self.generation = 0
        self.diagnostics: list[str] = []
        self.source_path: Any = None
        self.config: dict[str, Any] = {}
        self._runtime: list[LedgerEntry] = []
        self._install: list[LedgerEntry] = []
        self._dispose_task: asyncio.Task[UnloadReport] | None = None
        _LIVE_INSTANCES[plugin_id] = self

    def legacy_uninstall_descs(self) -> list[str]:
        """Return runtime rows recorded as legacy uninstall hooks."""
        return [
            entry.desc
            for entry in self._runtime
            if entry.kind == "legacy_uninstall"
        ]

    def guard_register(self) -> None:
        """Refuse new long-lived registrations while unloading."""
        if self.state is PluginState.UNLOADING:
            raise RuntimeError(
                f"Plugin '{self.plugin_id}' is unloading; "
                "new registrations are forbidden",
            )

    def record_runtime(
        self,
        desc: str,
        teardown: Callable[..., Any] | None = None,
        *,
        shutdown_critical: bool = True,
        kind: str = "official",
    ) -> None:
        self.guard_register()
        self._runtime.append(
            LedgerEntry(
                desc=desc,
                teardown=teardown,
                layer="runtime",
                shutdown_critical=shutdown_critical,
                kind=kind,
            ),
        )

    def record_install(
        self,
        desc: str,
        teardown: Callable[..., Any] | None = None,
        *,
        kind: str = "provision",
    ) -> None:
        self.guard_register()
        self._install.append(
            LedgerEntry(
                desc=desc,
                teardown=teardown,
                layer="install",
                shutdown_critical=False,
                kind=kind,
            ),
        )

    def owns_commit(self) -> bool:
        """Whether provision / directory swap belong to this process."""
        if self.delegate is None:
            return True
        return self.delegate.owns_commit(self.plugin_id)

    def mark_failed(self, reason: str) -> None:
        self.state = PluginState.FAILED
        if reason and reason not in self.diagnostics:
            self.diagnostics.append(reason)

    def add_diagnostic(self, message: str) -> None:
        if message and message not in self.diagnostics:
            self.diagnostics.append(message)

    async def teardown_runtime(self) -> UnloadReport:
        """Undo runtime ledger rows; keep modules and this instance.

        Does not run the install layer, does not mark the instance
        disposed, and does not touch ``sys.modules``.
        """
        report = UnloadReport(
            plugin_id=self.plugin_id,
            mode=UnloadMode.UNLOAD,
        )
        previous = self.state
        self.state = PluginState.UNLOADING
        entries = list(self._runtime)
        self._runtime.clear()
        try:
            for entry in reversed(entries):
                if entry.teardown is None:
                    continue
                try:
                    result = entry.teardown()
                    if inspect.isawaitable(result):
                        await result
                except Exception as exc:  # noqa: BLE001
                    report.clean = False
                    report.errors.append(f"{entry.desc}: {exc}")
                    logger.error(
                        "Runtime teardown '%s' failed for plugin '%s': %s",
                        entry.desc,
                        self.plugin_id,
                        exc,
                        exc_info=True,
                    )
        finally:
            if previous is PluginState.FAILED:
                self.state = PluginState.FAILED
            else:
                self.state = PluginState.ACTIVE
            self._dispose_task = None
        return report

    async def dispose(self, mode: UnloadMode) -> UnloadReport:
        """Run the ledger for *mode*. Waitable and idempotent."""
        if (
            self._dispose_task is not None
            and not self._dispose_task.done()
            and self.state is PluginState.UNLOADING
        ):
            return await self._dispose_task
        if self.state is PluginState.DISPOSED:
            return UnloadReport(
                plugin_id=self.plugin_id,
                mode=mode,
                clean=True,
            )
        loop = asyncio.get_running_loop()
        self._dispose_task = loop.create_task(self._dispose_body(mode))
        return await self._dispose_task

    async def _dispose_body(self, mode: UnloadMode) -> UnloadReport:
        self.state = PluginState.UNLOADING
        report = UnloadReport(plugin_id=self.plugin_id, mode=mode)
        try:
            entries = _entries_for_mode(self._runtime, self._install, mode)
            for entry in reversed(entries):
                if entry.teardown is None:
                    continue
                try:
                    result = entry.teardown()
                    if inspect.isawaitable(result):
                        await result
                except TimeoutError as exc:
                    report.clean = False
                    report.quiescent = False
                    report.errors.append(f"{entry.desc}: {exc}")
                    logger.error(
                        "Teardown '%s' did not go quiescent for "
                        "plugin '%s': %s",
                        entry.desc,
                        self.plugin_id,
                        exc,
                    )
                except Exception as exc:  # noqa: BLE001
                    report.clean = False
                    report.errors.append(f"{entry.desc}: {exc}")
                    logger.error(
                        "Teardown '%s' failed for plugin '%s': %s",
                        entry.desc,
                        self.plugin_id,
                        exc,
                        exc_info=True,
                    )
        finally:
            if mode is UnloadMode.SHUTDOWN:
                # Process is dying; leave tables/modules in place.
                self.state = PluginState.DISPOSED
            else:
                self.state = PluginState.DISPOSED
        return report


def _entries_for_mode(
    runtime: list[LedgerEntry],
    install: list[LedgerEntry],
    mode: UnloadMode,
) -> list[LedgerEntry]:
    """Project the two-layer ledger onto one unload mode."""
    selected: list[LedgerEntry] = []
    if mode is UnloadMode.SHUTDOWN:
        # Hosted resources only. Table / intent / hook-row teardowns
        # are skipped; author shutdown callbacks run separately.
        selected.extend(
            e
            for e in runtime
            if e.shutdown_critical and e.kind in {"custody", "effect"}
        )
        return selected
    # unload / uninstall: all runtime, including shutdown_critical=False
    selected.extend(runtime)
    if mode is UnloadMode.UNINSTALL:
        selected.extend(install)
    return selected


class PluginLifecycle:
    """Facade for load / unload / reload / update_config."""

    def __init__(self, loader: Any) -> None:
        self._loader = loader
        self.delegate = LifecycleDelegate()
        self._instances: dict[str, PluginInstance] = {}

    def get_instance(self, plugin_id: str) -> PluginInstance | None:
        return self._instances.get(plugin_id)

    def ensure_instance(self, plugin_id: str) -> PluginInstance:
        inst = self._instances.get(plugin_id)
        if inst is None or inst.state is PluginState.DISPOSED:
            inst = PluginInstance(plugin_id)
            self._instances[plugin_id] = inst
        inst.delegate = self.delegate
        return inst

    def drop_instance(self, plugin_id: str) -> None:
        dropped = self._instances.pop(plugin_id, None)
        if _LIVE_INSTANCES.get(plugin_id) is dropped:
            _LIVE_INSTANCES.pop(plugin_id, None)

    async def load(
        self,
        manifest: Any,
        source_path: Any,
        config: dict[str, Any] | None = None,
        *,
        allow_install: bool = False,
    ) -> Any:
        """Load one plugin under the loader lock."""
        return await self._loader.load_plugin(
            manifest,
            source_path,
            config,
            allow_install=allow_install,
        )

    async def unload(
        self,
        plugin_id: str,
        mode: UnloadMode,
        *,
        delete_files: bool = False,
    ) -> UnloadReport:
        """Unload one plugin. ``delete_files`` only applies to uninstall."""
        async with self._loader.plugin_lifecycle(plugin_id):
            return await self._unload_unlocked(
                plugin_id,
                mode,
                delete_files=delete_files,
            )

    async def _unload_unlocked(
        self,
        plugin_id: str,
        mode: UnloadMode,
        *,
        delete_files: bool,
    ) -> UnloadReport:
        if not self.delegate.owns_commit(plugin_id):
            receipt = self.delegate.notify_unload(plugin_id, mode)
            report = UnloadReport(
                plugin_id=plugin_id,
                mode=mode,
                clean=receipt.ok,
                leftovers=list(receipt.leftovers),
                receipt=receipt,
            )
            return report

        inst = self._instances.get(plugin_id)
        if inst is None:
            inst = PluginInstance(plugin_id)
            self._instances[plugin_id] = inst

        if mode is UnloadMode.UNINSTALL:
            delete_files = True
        elif mode is UnloadMode.SHUTDOWN:
            delete_files = False

        report = await self._loader.unload_plugin_with_mode(
            plugin_id,
            mode,
            instance=inst,
            delete_files=delete_files,
        )
        if mode is not UnloadMode.SHUTDOWN:
            self.drop_instance(plugin_id)
        return report

    async def reload(
        self,
        plugin_id: str,
        new_source: Any = None,
        config: dict[str, Any] | None = None,
        *,
        allow_install: bool = False,
    ) -> ReloadReport:
        """Replace plugin code: probe first, then unload, then load."""
        async with self._loader.plugin_lifecycle(plugin_id):
            if not self.delegate.owns_commit(plugin_id):
                return ReloadReport(
                    plugin_id=plugin_id,
                    ok=False,
                    unchanged=True,
                    errors=["commit is not owned by this process"],
                )
            return await self._loader.reload_plugin_unlocked(
                plugin_id,
                new_source=new_source,
                config=config,
                allow_install=allow_install,
                owns_dependency_env=self.delegate.owns_dependency_env(
                    plugin_id,
                ),
            )

    async def update_config(
        self,
        plugin_id: str,
        new_config: dict[str, Any],
        *,
        confirm_legacy: bool = False,
    ) -> ConfigUpdateReport:
        """Rebuild contributions from *new_config* without reimporting."""
        async with self._loader.plugin_lifecycle(plugin_id):
            return await self._update_config_unlocked(
                plugin_id,
                new_config,
                confirm_legacy=confirm_legacy,
            )

    async def _update_config_unlocked(
        self,
        plugin_id: str,
        new_config: dict[str, Any],
        *,
        confirm_legacy: bool,
    ) -> ConfigUpdateReport:
        from .settings import persist_plugin_settings, runtime_config

        if not isinstance(new_config, dict):
            return ConfigUpdateReport(
                plugin_id=plugin_id,
                ok=False,
                unchanged=True,
                errors=["config must be an object"],
            )
        inst = self._instances.get(plugin_id)
        record = self._loader.get_loaded_plugin(plugin_id)
        if inst is None or record is None or record.instance is None:
            return ConfigUpdateReport(
                plugin_id=plugin_id,
                ok=False,
                unchanged=True,
                errors=[f"Plugin '{plugin_id}' is not loaded"],
            )
        legacy = inst.legacy_uninstall_descs()
        if legacy and not confirm_legacy:
            return ConfigUpdateReport(
                plugin_id=plugin_id,
                ok=False,
                unchanged=True,
                requires_confirmation=True,
                legacy_hooks=legacy,
                errors=[
                    "plugin uses a legacy uninstall hook; "
                    "confirm to continue",
                ],
            )
        incoming = runtime_config(new_config)
        previous = dict(inst.config or {})
        await inst.teardown_runtime()
        self._loader.registry.unregister_plugin(plugin_id)
        try:
            await self._loader.reregister_unlocked(plugin_id, incoming)
            await self._loader.run_plugin_startup_hooks(plugin_id)
        except Exception as exc:  # noqa: BLE001
            await inst.teardown_runtime()
            self._loader.registry.unregister_plugin(plugin_id)
            restore_error = ""
            try:
                await self._loader.reregister_unlocked(plugin_id, previous)
                await self._loader.run_plugin_startup_hooks(plugin_id)
                inst.config = previous
            except Exception as restore_exc:  # noqa: BLE001
                restore_error = str(restore_exc)
                logger.exception(
                    "Failed to restore config for plugin '%s'",
                    plugin_id,
                )
            errors = [str(exc)]
            if restore_error:
                errors.append(f"restore failed: {restore_error}")
            return ConfigUpdateReport(
                plugin_id=plugin_id,
                ok=False,
                errors=errors,
            )
        inst.config = incoming
        persist_plugin_settings(plugin_id, config=incoming)
        return ConfigUpdateReport(plugin_id=plugin_id, ok=True)

    async def set_enabled(
        self,
        plugin_id: str,
        enabled: bool,
    ) -> Any:
        """Persist ``enabled`` and load or unload the instance."""
        from .settings import persist_plugin_settings

        persist_plugin_settings(plugin_id, enabled=enabled)
        async with self._loader.plugin_lifecycle(plugin_id):
            loaded = plugin_id in self._loader.get_all_loaded_plugins()
            if not enabled and loaded:
                return await self._unload_unlocked(
                    plugin_id,
                    UnloadMode.UNLOAD,
                    delete_files=False,
                )
            if enabled and not loaded:
                return await self._loader.load_installed_unlocked(plugin_id)
        return self._loader.get_loaded_plugin(plugin_id)

    async def unload_all(self, mode: UnloadMode) -> list[UnloadReport]:
        """Unload every known instance (used at process shutdown)."""
        reports: list[UnloadReport] = []
        for plugin_id in list(self._instances):
            try:
                reports.append(
                    await self.unload(plugin_id, mode, delete_files=False),
                )
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Failed to %s plugin '%s': %s",
                    mode.value,
                    plugin_id,
                    exc,
                    exc_info=True,
                )
                reports.append(
                    UnloadReport(
                        plugin_id=plugin_id,
                        mode=mode,
                        clean=False,
                        errors=[str(exc)],
                    ),
                )
        return reports


async def await_with_budget(
    result: Any,
    *,
    seconds: float,
    what: str,
    plugin_id: str,
) -> Any:
    """Await *result* with a wall-clock budget. Sync values pass through."""
    if not inspect.isawaitable(result):
        return result
    try:
        return await asyncio.wait_for(result, timeout=seconds)
    except asyncio.TimeoutError as exc:
        raise TimeoutError(
            f"Plugin '{plugin_id}' {what} exceeded {seconds:.0f}s",
        ) from exc
