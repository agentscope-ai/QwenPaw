# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Workspace storage and monitoring with an optional Driver runtime."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager

from ..drivers.capabilities import (
    DriverInvocationResult,
    DriverRuntimeInfo,
    parse_capability_id,
)
from ..drivers.contracts import coerce_card, validate_card
from ..drivers.credentials.store import AsyncCredentialStore
from ..drivers.errors import (
    DriverNotFoundError,
    UnsupportedProtocolError,
    driver_error_diagnostic,
)
from ..drivers.manager import DriverManager
from ..drivers.storage import AsyncDriverCardStore
from ..plugins._drivers import (
    attach_driver_protocols,
    detach_driver_protocols,
    _workspace_guard,
    workspace_is_current,
)
from ..plugins.registry import PluginRegistry
from ..utils.io_utils import run_async_to_completion, run_sync_io
from .driver_config_watcher import DriverConfigWatcher
from .mcp_plugin_migration import configured_mcp_card

logger = logging.getLogger(__name__)

_MCP_STARTUP_CONCURRENCY = 4


class LazyDriverService:  # pylint: disable=too-many-public-methods
    """Own one workspace's optional runtime and conditional config watcher."""

    def __init__(self, workspace, *, registry=None, ensure_protocol=None):
        self._workspace = workspace
        self._registry = registry or PluginRegistry()
        self._ensure_protocol = ensure_protocol or getattr(
            self._registry,
            "protocol_resolver",
            None,
        )
        self.cards_dir = workspace.workspace_dir / "drivers"
        self.card_store = AsyncDriverCardStore(self.cards_dir)
        self.credential_store = AsyncCredentialStore(
            workspace.workspace_dir / "credentials.yaml",
        )
        self._manager = None
        self._watcher = None
        self._monitoring = set()
        self._explicit_monitoring = set()
        self._operations = {}
        self._watch_lock = asyncio.Lock()
        self._metadata_lock = asyncio.Lock()
        self._manager_lock = asyncio.Lock()
        self._inactive = set()
        self._stopped = False
        self._started = False
        self._start_task = None
        self._reload_owner = None
        self._reload_protocols = {}
        self._reload_baseline = None

    @property
    def manager(self):
        return self._manager

    @property
    def watcher(self):
        return self._watcher

    def is_protocol_suspended(self, protocol):
        return protocol in self._inactive

    def _guard(self, *, allow_draining=False):
        if self._stopped:
            raise RuntimeError("Driver workspace service has stopped")
        _workspace_guard(
            self._registry,
            self._workspace,
            allow_draining=allow_draining,
        )

    def _available(self, protocol):
        eligibility = getattr(self._registry, "protocol_eligibility", None)
        # The callback is assigned by the host after registry construction.
        # pylint: disable=not-callable
        if callable(eligibility) and not eligibility(
            self._workspace.agent_id,
            protocol,
            workspace=self._workspace,
        ):
            return False
        # pylint: enable=not-callable
        state = self._registry.describe_driver_protocol(protocol)
        return (
            state is not None
            and not state.revoked
            and not self.is_protocol_suspended(protocol)
        )

    async def start(self):
        if self._started:
            return
        if self._stopped:
            raise RuntimeError("Driver workspace service has stopped")
        if self._start_task is None or self._start_task.done():
            self._start_task = asyncio.create_task(self._initialize())
        await asyncio.shield(self._start_task)
        self._started = True

    async def _initialize(self):
        self._explicit_monitoring.update(await self._read_monitoring())
        self._monitoring.update(self._explicit_monitoring)
        if workspace_is_current(self._registry, self._workspace):
            await self.activate_registered_protocols()

    async def _read_monitoring(self):
        path = self.cards_dir / ".monitoring.json"
        try:
            metadata = json.loads(await asyncio.to_thread(path.read_text))
            if metadata.get("version") == 1:
                return {
                    item
                    for item in metadata.get("protocols", [])
                    if isinstance(item, str)
                }
        except FileNotFoundError:
            pass
        return set()

    async def activate_registered_protocols(self):
        """Apply protocol intents after workspace publication commits."""
        self._guard()
        await self._ensure_configured_protocols()
        await self._project_protocols(self._registry._driver_protocols.copy())

    async def _ensure_configured_protocols(self):
        # Compatibility consumers can create configured sources after the
        # global inventory. They use the same offline coordinator.
        if self._ensure_protocol:
            protocols = set()
            for path in await self.card_store.list_paths():
                try:
                    card = await self.card_store.load_path(path)
                    if self._configured(card) and not self._available(
                        card.protocol,
                    ):
                        protocols.add(card.protocol)
                except Exception:
                    continue
            for protocol in protocols:
                await self._ensure_protocol(protocol)

    async def _project_protocols(self, protocols, *, preparing=False):
        for protocol, descriptor in protocols.items():
            if descriptor.projected:
                await self._registry.projector.project_one(
                    self._workspace,
                    "driver_protocol",
                    protocol,
                    descriptor.owner.plugin_id,
                    owned_start=preparing,
                )
            else:
                await self.activate_protocol(protocol)

    def is_preparing_registration(self, descriptor):
        protocol = descriptor.spec.protocol
        return (
            self._reload_owner is not None
            and not self._stopped
            and self._reload_owner()
            and self._reload_protocols.get(protocol) is descriptor
            and self._registry._driver_protocols.get(protocol) is descriptor
            and self._available(protocol)
            and self._registry.projector.start_allowed(
                "driver_protocol",
                protocol,
                descriptor.owner.plugin_id,
                self._workspace,
            )
        )

    async def prepare_reload(self, owner):
        """Build connections without publishing requests or polling edits."""
        if not owner():
            raise RuntimeError("Driver preparation is stale")
        await self._ensure_configured_protocols()
        self._reload_owner = owner
        self._reload_protocols = self._registry._driver_protocols.copy()
        await self._project_protocols(self._reload_protocols, preparing=True)

    async def verify_reload_snapshot(self):
        if await self._read_monitoring() != self._explicit_monitoring:
            raise RuntimeError("Driver monitoring changed during reload")
        if self._reload_baseline is not None:
            watcher, snapshot = self._reload_baseline
            if await watcher._snapshot() != snapshot:
                raise RuntimeError(
                    "Driver configuration changed during reload",
                )

    def check_reload(self):
        if (
            not self._reload_owner()
            or self._reload_protocols != self._registry._driver_protocols
        ):
            raise RuntimeError("Driver preparation is stale")
        if self._reload_baseline is None:
            return
        watcher, _ = self._reload_baseline
        for protocol in watcher._protocols:
            descriptor = self._reload_protocols[protocol]
            descriptor.guard()
            if (
                not self.is_preparing_registration(descriptor)
                or descriptor.plugin._instance.activity.blocked
            ):
                raise RuntimeError("Driver protocol is changing")

    def commit_reload(self):
        protocols = self._watch_protocols()
        if protocols and self._reload_baseline is not None:
            watcher, snapshot = self._reload_baseline
            watcher._protocols = protocols
            watcher.start_polling(
                {
                    path: state
                    for path, state in snapshot.items()
                    if path.split("/", 1)[0] in protocols
                },
            )
            self._watcher = watcher
        self._reload_baseline = None
        self._reload_owner = None
        self._reload_protocols = {}

    async def _migrate_legacy_config(self):
        """Convert the sources accepted by workspace admission."""
        snapshot = getattr(self._workspace, "_mcp_legacy_migration", None)
        if snapshot is None:
            return
        from ..config.utils import archive_config_input
        from ..drivers.adapters.mcp_legacy_config import (
            migrate_legacy_mcp_if_needed,
        )

        if snapshot.legacy_backup is not None:
            from .mcp_plugin_upgrade import log_legacy_archive

            await run_sync_io(
                archive_config_input,
                self._workspace.workspace_dir / "agent.json",
                snapshot.legacy_backup,
                "legacy-mcp",
            )
            log_legacy_archive(self._workspace.agent_id, snapshot.legacy_skips)
        await migrate_legacy_mcp_if_needed(
            self._workspace,
            self,
            clients=snapshot.legacy_mcp.clients,
        )
        self._workspace._mcp_legacy_migration = None

    async def request_monitoring(self, protocol):
        """Persist intent without installing or opening a protocol."""
        self._guard()
        # Reuse storage's protocol/path validation before accepting metadata.
        await run_sync_io(
            self.card_store.path_for,
            "monitoring",
            protocol=protocol,
        )
        async with self._metadata_lock:
            self._guard()

            async def commit():
                if protocol not in self._explicit_monitoring:
                    updated = self._explicit_monitoring | {protocol}
                    payload = json.dumps(
                        {"version": 1, "protocols": sorted(updated)},
                    )
                    await run_sync_io(self._write_monitoring, payload)
                    self._explicit_monitoring = updated
                self._monitoring.add(protocol)

            # Cancellation must not split disk and memory publication.
            await run_async_to_completion(commit())
        await self._reconcile_watcher()

    def _write_monitoring(self, payload):
        self.cards_dir.mkdir(parents=True, exist_ok=True)
        path = self.cards_dir / ".monitoring.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(path)

    @staticmethod
    def _configured(card):
        return card.protocol != "mcp" or configured_mcp_card(card)

    async def _configured_cards(self, protocol):
        paths = await self.card_store.list_paths(protocols={protocol})
        cards = []
        for path in paths:
            try:
                card = await self.card_store.load_path(path)
            except Exception as exc:
                logger.warning(
                    "Could not load DriverCard %r in workspace %r: %s",
                    str(path),
                    self._workspace.agent_id,
                    driver_error_diagnostic(exc),
                )
                continue
            if card.protocol == protocol and self._configured(card):
                cards.append(card)
        return cards

    async def _check_protocol_workspace(self, protocol):
        if protocol == "mcp":
            coordinator = self._registry.get_protocol_preparation()
            if coordinator is not None:
                await coordinator.check_workspace(self._workspace)

    async def activate_protocol(self, protocol, *, allow_parallel=False):
        preparing = self._reload_owner is not None
        if not preparing:
            self._guard()
        await self._check_protocol_workspace(protocol)
        self._inactive.discard(protocol)
        if not self._available(protocol):
            return
        if preparing and not self.is_preparing_registration(
            self._reload_protocols[protocol],
        ):
            raise RuntimeError("Driver preparation is stale")
        if protocol == "mcp":
            if preparing:
                await run_async_to_completion(self._migrate_legacy_config())
            else:
                await self._migrate_legacy_config()
        if preparing:
            await self._prepare_watcher(protocol)
        if protocol not in self._monitoring and await self._configured_cards(
            protocol,
        ):
            self._monitoring.add(protocol)
        # Establish the baseline before reading the sources to activate. A
        # write during intent discovery must not be acknowledged without apply.
        if not preparing:
            await self._reconcile_watcher()
        cards = (
            await self._configured_cards(protocol)
            if protocol in self._monitoring
            else []
        )
        for card in cards:
            if not card.enabled:
                logger.debug(
                    "Driver %r in workspace %r is disabled; skipping",
                    card.name,
                    self._workspace.agent_id,
                )
        cards = [card for card in cards if card.enabled]

        async def start_source(card):
            try:
                if preparing:
                    manager = await self._runtime(
                        protocol,
                        ensure=False,
                        preparing=True,
                    )
                    await manager.refresh_driver(card.name)
                else:
                    await self._refresh(card, ensure=False)
            except Exception as exc:
                logger.warning(
                    "Could not start Driver %r in workspace %r: %s",
                    card.name,
                    self._workspace.agent_id,
                    driver_error_diagnostic(exc),
                )

        if protocol == "mcp" and allow_parallel and len(cards) > 1:
            limit = asyncio.Semaphore(_MCP_STARTUP_CONCURRENCY)
            # Multiple card files may resolve to the same runtime source.
            sources = {card.name: card for card in cards}

            async def start_limited(card):
                async with limit:
                    await start_source(card)

            async with asyncio.TaskGroup() as group:
                tasks = [
                    group.create_task(start_limited(card))
                    for card in sources.values()
                ]
                # A source cancellation must still abort activation, including
                # sources queued for a slot.
                await asyncio.gather(*tasks)
        else:
            for card in cards:
                await start_source(card)

        if protocol == "mcp" and not preparing:
            sync = getattr(self._workspace, "sync_mcp_features", None)
            if sync is not None:
                await sync(True)

    async def deactivate_protocol(self, protocol):
        self._inactive.add(protocol)
        if protocol == "mcp" and self._reload_owner is None:
            sync = getattr(self._workspace, "sync_mcp_features", None)
            if sync is not None:
                await sync(False)
        if self._reload_owner is None:
            await self._reconcile_watcher()
        pending = {
            task
            for task, protocols in self._operations.items()
            if protocol in protocols and task is not asyncio.current_task()
        }
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        if self._manager is not None:
            await self._manager.close_protocol(protocol)
            await self._reclaim()

    def _watch_protocols(self):
        return frozenset(
            protocol
            for protocol in self._monitoring
            if not self._stopped and self._available(protocol)
        )

    async def _prepare_watcher(self, protocol):
        # Record empty directories too: the live workspace can add a first
        # source without triggering an agent config revision.
        protocols = frozenset({protocol})
        if self._reload_baseline is not None:
            protocols |= self._reload_baseline[0]._protocols
        watcher = DriverConfigWatcher(
            self,
            self.cards_dir,
            protocols=protocols,
        )
        snapshot = await watcher._snapshot()
        if self._reload_baseline is not None:
            previous_watcher, previous = self._reload_baseline
            self._merge_watcher_baseline(
                snapshot,
                previous,
                previous_watcher._protocols,
            )
        self._reload_baseline = watcher, snapshot

    @staticmethod
    def _merge_watcher_baseline(snapshot, previous, retained_protocols):
        # A change made during activation still needs to be applied.
        for path in tuple(snapshot):
            if path.split("/", 1)[0] in retained_protocols:
                del snapshot[path]
        snapshot.update(
            (path, state)
            for path, state in previous.items()
            if path.split("/", 1)[0] in retained_protocols
        )

    async def _reconcile_watcher(self):
        async with self._watch_lock:
            protocols = self._watch_protocols()
            previous = self._watcher
            if previous is not None and previous._protocols == protocols:
                return
            watcher = None
            if protocols:
                watcher = DriverConfigWatcher(
                    self,
                    self.cards_dir,
                    protocols=protocols,
                )
                snapshot = await watcher._snapshot()
            if previous is not None:
                await previous.stop()
            if watcher is not None:
                if previous is not None:
                    self._merge_watcher_baseline(
                        snapshot,
                        previous._last_snapshot,
                        previous._protocols & protocols,
                    )
                watcher.start_polling(snapshot)
            self._watcher = watcher

    @asynccontextmanager
    async def _operation(self, *owned_protocols):
        self._guard()
        task = asyncio.current_task()
        protocols = self._operations.setdefault(task, [])
        protocols.extend(owned_protocols)
        try:
            yield
        finally:
            for protocol in owned_protocols:
                protocols.remove(protocol)
            if not protocols:
                self._operations.pop(task, None)
            await self._reclaim()

    def _guard_runtime(self, protocol, preparing):
        if not preparing:
            self._guard()
        elif not self.is_preparing_registration(
            self._reload_protocols[protocol],
        ):
            raise RuntimeError("Driver preparation is stale")

    async def _runtime(self, protocol, *, ensure=True, preparing=False):
        await self._check_protocol_workspace(protocol)
        if not self._available(protocol) and ensure and self._ensure_protocol:
            await self._ensure_protocol(protocol)
        self._guard_runtime(protocol, preparing)
        if not self._available(protocol):
            raise UnsupportedProtocolError(protocol)
        async with self._manager_lock:
            self._guard_runtime(protocol, preparing)
            if self._manager is None:
                from .approvals.driver_gate import QwenPawDriverApprovalGate

                self._manager = DriverManager(
                    self.cards_dir,
                    self.credential_store,
                    approval_gate=QwenPawDriverApprovalGate(),
                    card_store=self.card_store,
                )
                logger.debug(
                    "DriverManager initialized for workspace %r",
                    self._workspace.agent_id,
                )
            attach_driver_protocols(
                self._manager,
                self._registry,
                self._workspace,
                prepare=self.is_preparing_registration if preparing else None,
            )
            return self._manager

    async def _reclaim(self):
        async with self._manager_lock:
            manager = self._manager
            if (
                manager is not None
                and not self._operations
                and not manager.has_owned_sources
            ):
                await manager.shutdown_all()
                detach_driver_protocols(manager, self._registry)
                self._manager = None

    async def shutdown_all(self):
        self._stopped = True
        if (
            self._start_task is not None
            and self._start_task is not asyncio.current_task()
        ):
            self._start_task.cancel()
            await asyncio.gather(self._start_task, return_exceptions=True)
        await self._reconcile_watcher()
        pending = set(self._operations) - {asyncio.current_task()}
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        if self._manager is not None:
            await self._manager.shutdown_all()
            detach_driver_protocols(self._manager, self._registry)
            self._manager = None
        self._reload_baseline = None
        self._reload_owner = None
        self._reload_protocols = {}

    async def _load(self, name):
        path = await self.card_store.stored_path(name)
        if path is None:
            raise DriverNotFoundError(name)
        return await self.card_store.load_path(path)

    @staticmethod
    def _info(card):
        return DriverRuntimeInfo(
            name=card.name,
            protocol=card.protocol,
            enabled=card.enabled,
            status="inactive" if card.enabled else "disabled",
            display_name=str(card.config.get("display_name") or card.name),
            description=str(card.config.get("description") or ""),
        )

    async def register_driver(self, card):
        card = coerce_card(card)
        validate_card(card)
        async with self._operation(card.protocol):
            await self.request_monitoring(card.protocol)
            if card.enabled:
                manager = await self._runtime(card.protocol)
                await manager.register_driver(card)
            else:
                await self.card_store.save(card)
                if self._manager:
                    await self._manager.close_driver(card.name)

    async def _refresh(self, card, *, ensure=True, reload=False):
        async with self._operation(card.protocol):
            if self._configured(card):
                self._monitoring.add(card.protocol)
                await self._reconcile_watcher()
            if card.enabled:
                manager = await self._runtime(card.protocol, ensure=ensure)
                if reload:
                    return await manager.reload_driver(card.name)
                return await manager.refresh_driver(card.name)
            if self._manager:
                await self._manager.close_driver(card.name)
            return self._info(card)

    async def reload_driver(self, name):
        return await self._refresh(await self._load(name), reload=True)

    async def refresh_driver(self, name):
        card = await self._load(name)
        return await self._refresh(
            card,
            ensure=self._ensure_protocol is not None
            and self._configured(card),
        )

    async def sync_driver_policy(self, card, *, persist=True):
        self._guard()
        if self._manager and self._available(card.protocol):
            await self._manager.sync_driver_policy(card, persist=persist)
        elif persist:
            await self.card_store.save(card)

    async def delete_driver(self, name):
        self._guard()
        for protocol in tuple(self._monitoring):
            await self.request_monitoring(protocol)
        if self._manager:
            await self._manager.delete_driver(name)
            await self._reclaim()
        else:
            await self.card_store.delete(name)

    async def replace_transient_drivers(self, scope_id, cards):
        if not cards:
            return await self.remove_transient_drivers(scope_id)
        protocols = {card.protocol for card in cards}
        async with self._operation(*protocols):
            for protocol in protocols:
                manager = await self._runtime(protocol)
            await manager.replace_transient_drivers(scope_id, cards)

    async def remove_transient_drivers(self, scope_id):
        if self._manager:
            await self._manager.remove_transient_drivers(scope_id)
            await self._reclaim()

    async def close_driver(self, name, *, session_scope=""):
        if self._manager:
            await self._manager.close_driver(name, session_scope=session_scope)
            await self._reclaim()

    async def list_drivers(self, protocol=None):
        if self._manager:
            return await self._manager.list_drivers(protocol=protocol)
        result = []
        for path in await self.card_store.list_paths(
            protocols={protocol} if protocol else None,
        ):
            try:
                card = await self.card_store.load_path(path)
                if protocol is None or card.protocol == protocol:
                    result.append(self._info(card))
            except Exception as exc:
                result.append(
                    DriverRuntimeInfo(
                        name=path.stem,
                        protocol="",
                        enabled=False,
                        status="error",
                        error=str(exc),
                    ),
                )
        return sorted(result, key=lambda item: item.name)

    async def list_capabilities(
        self,
        *,
        protocol=None,
        kind=None,
        request_context=None,
    ):
        if self._manager is None:
            return []
        self._guard(allow_draining=True)
        return await self._manager.list_capabilities(
            protocol=protocol,
            kind=kind,
            request_context=request_context,
        )

    async def list_driver_capabilities(
        self,
        name,
        *,
        kind=None,
        request_context=None,
    ):
        self._guard(allow_draining=True)
        if self._manager is None:
            raise DriverNotFoundError(name)
        return await self._manager.list_driver_capabilities(
            name,
            kind=kind,
            request_context=request_context,
        )

    async def invoke_capability(self, invocation):
        self._guard(allow_draining=True)
        if self._manager:
            return await self._manager.invoke_capability(invocation)
        try:
            _, name, _, _, _ = parse_capability_id(invocation.capability_id)
        except ValueError as exc:
            return DriverInvocationResult(
                ok=False,
                error_type="invalid_capability_id",
                message=str(exc),
            )
        return DriverInvocationResult(
            ok=False,
            error_type="driver_not_found",
            message=str(DriverNotFoundError(name)),
            metadata={"driver_name": name},
        )
