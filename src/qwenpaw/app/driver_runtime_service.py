# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Workspace storage and monitoring with an optional Driver runtime."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from dataclasses import asdict

from ..drivers.capabilities import (
    DriverInvocationResult,
    DriverRuntimeInfo,
    parse_capability_id,
)
from ..drivers.contracts import coerce_card, validate_card
from ..drivers.credentials.store import AsyncCredentialStore
from ..drivers.errors import DriverNotFoundError, UnsupportedProtocolError
from ..drivers.manager import DriverManager
from ..drivers.storage import AsyncDriverCardStore
from ..plugins._drivers import (
    attach_driver_protocols,
    detach_driver_protocols,
    _workspace_guard,
    workspace_is_current,
)
from ..plugins.registry import PluginRegistry
from .driver_config_watcher import DriverConfigWatcher
from .mcp_plugin_migration import (
    MCPUsageSnapshot,
    MCPWorkspaceSnapshot,
    classify_mcp_usage,
)

logger = logging.getLogger(__name__)


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

    @property
    def manager(self):
        return self._manager

    @property
    def watcher(self):
        return self._watcher

    def _guard(self):
        if self._stopped:
            raise RuntimeError("Driver workspace service has stopped")
        _workspace_guard(self._registry, self._workspace)

    def _available(self, protocol):
        eligibility = getattr(self._registry, "protocol_eligibility", None)
        # The callback is assigned by the host after registry construction.
        # pylint: disable=not-callable
        if callable(eligibility) and not eligibility(
            self._workspace.agent_id,
            protocol,
        ):
            return False
        # pylint: enable=not-callable
        descriptor = self._registry._driver_protocols.get(protocol)
        return (
            descriptor is not None
            and not descriptor.revoked
            and protocol not in self._inactive
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
        path = self.cards_dir / ".monitoring.json"
        try:
            metadata = json.loads(await asyncio.to_thread(path.read_text))
            if metadata.get("version") == 1:
                self._explicit_monitoring.update(
                    item
                    for item in metadata.get("protocols", [])
                    if isinstance(item, str)
                )
        except FileNotFoundError:
            pass
        self._monitoring.update(self._explicit_monitoring)
        if workspace_is_current(self._registry, self._workspace):
            await self.activate_registered_protocols()

    async def activate_registered_protocols(self):
        """Apply protocol intents after workspace publication commits."""
        self._guard()
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
        for protocol, descriptor in tuple(
            self._registry._driver_protocols.items(),
        ):
            if descriptor.projected:
                await self._registry.projector.project_one(
                    self._workspace,
                    "driver_protocol",
                    protocol,
                    descriptor.owner.plugin_id,
                )
            else:
                await self.activate_protocol(protocol)

    async def _migrate_legacy_config(self):
        """Convert confirmed raw usage only after host protocol activation.

        The installation coordinator must inventory all workspaces before
        this compatibility conversion, including inactive workspaces.
        """
        if not self._available("mcp"):
            return
        import yaml
        from ..drivers.adapters.mcp_legacy_config import (
            CURRENT_MCP_MIGRATION_VERSION,
            migrate_legacy_mcp_if_needed,
        )

        try:
            raw = json.loads(
                await asyncio.to_thread(
                    (self._workspace.workspace_dir / "agent.json").read_text,
                ),
            )
            version = raw.get("mcp", {}).get("migration_version", 0)
            if (
                type(version) is not int
                or not 0 <= version < CURRENT_MCP_MIGRATION_VERSION
            ):
                return
            # Ignore converted clients, but preserve malformed/unknown fields
            # so the classifier can still require review of the raw evidence.
            evidence = (
                raw
                if version == 0
                else {
                    **raw,
                    "mcp": {**raw["mcp"], "clients": {}},
                }
            )
            cards = []
            for path in await self.card_store.list_paths(protocols={"mcp"}):
                cards.append(
                    yaml.safe_load(await asyncio.to_thread(path.read_text)),
                )
            decision = classify_mcp_usage(
                MCPUsageSnapshot(
                    (
                        MCPWorkspaceSnapshot(
                            self._workspace.agent_id,
                            evidence,
                            tuple(cards),
                        ),
                    ),
                ),
            )
        except (
            OSError,
            ValueError,
            TypeError,
            AttributeError,
            yaml.YAMLError,
        ):
            # Preserve uncertain evidence for the coordinator to report.
            return
        if decision.status == "configured":
            await migrate_legacy_mcp_if_needed(self._workspace, self)

    async def request_monitoring(self, protocol):
        """Persist intent without installing or opening a protocol."""
        self._guard()
        # Reuse storage's protocol/path validation before accepting metadata.
        self.card_store.path_for("monitoring", protocol=protocol)
        async with self._metadata_lock:
            self._monitoring.add(protocol)
            if protocol not in self._explicit_monitoring:
                updated = self._explicit_monitoring | {protocol}
                payload = json.dumps(
                    {"version": 1, "protocols": sorted(updated)},
                )
                await asyncio.to_thread(self._write_monitoring, payload)
                self._explicit_monitoring = updated
        await self._reconcile_watcher()

    def _write_monitoring(self, payload):
        self.cards_dir.mkdir(parents=True, exist_ok=True)
        path = self.cards_dir / ".monitoring.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(path)

    @staticmethod
    def _configured(card):
        if card.protocol != "mcp":
            return True
        decision = classify_mcp_usage(
            MCPUsageSnapshot(
                (MCPWorkspaceSnapshot("source", cards=(asdict(card),)),),
            ),
        )
        return decision.status != "unused"

    async def _configured_cards(self, protocol):
        paths = await self.card_store.list_paths(protocols={protocol})
        cards = []
        for path in paths:
            try:
                card = await self.card_store.load_path(path)
            except Exception:
                logger.warning(
                    "Could not load DriverCard %s",
                    path,
                    exc_info=True,
                )
                continue
            if card.protocol == protocol and self._configured(card):
                cards.append(card)
        return cards

    async def activate_protocol(self, protocol):
        self._guard()
        self._inactive.discard(protocol)
        if not self._available(protocol):
            return
        if protocol == "mcp":
            await self._migrate_legacy_config()
        if protocol not in self._monitoring and await self._configured_cards(
            protocol,
        ):
            self._monitoring.add(protocol)
        # Establish the baseline before reading the sources to activate. A
        # write during intent discovery must not be acknowledged without apply.
        await self._reconcile_watcher()
        if protocol not in self._monitoring:
            return
        cards = await self._configured_cards(protocol)
        for card in cards:
            if card.enabled:
                try:
                    await self._refresh(card, ensure=False)
                except Exception:
                    logger.warning(
                        "Could not start Driver %s",
                        card.name,
                        exc_info=True,
                    )

    async def deactivate_protocol(self, protocol):
        self._inactive.add(protocol)
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

    async def _reconcile_watcher(self):
        async with self._watch_lock:
            protocols = frozenset(
                protocol
                for protocol in self._monitoring
                if not self._stopped and self._available(protocol)
            )
            previous = {}
            retained_protocols = frozenset()
            if self._watcher is not None:
                if self._watcher._protocols == protocols:
                    return
                retained_protocols = self._watcher._protocols & protocols
                await self._watcher.stop()
                previous = self._watcher._last_snapshot
                self._watcher = None
            if protocols:
                self._watcher = DriverConfigWatcher(
                    self,
                    self.cards_dir,
                    protocols=protocols,
                )
                await self._watcher.start()

                # Changing the watched protocol set must not acknowledge an
                # unapplied edit in an already monitored protocol.
                def retained(path):
                    return any(
                        path.startswith(protocol + "/")
                        for protocol in retained_protocols
                    )

                self._watcher._last_snapshot = {
                    **{
                        path: state
                        for path, state in self._watcher._last_snapshot.items()
                        if not retained(path)
                    },
                    **{
                        path: state
                        for path, state in previous.items()
                        if retained(path)
                    },
                }

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

    async def _runtime(self, protocol, *, ensure=True):
        if not self._available(protocol) and ensure and self._ensure_protocol:
            await self._ensure_protocol(protocol)
        self._guard()
        if not self._available(protocol):
            raise UnsupportedProtocolError(protocol)
        async with self._manager_lock:
            self._guard()
            if self._manager is None:
                from .approvals.driver_gate import QwenPawDriverApprovalGate

                self._manager = DriverManager(
                    self.cards_dir,
                    self.credential_store,
                    approval_gate=QwenPawDriverApprovalGate(),
                    card_store=self.card_store,
                )
            attach_driver_protocols(
                self._manager,
                self._registry,
                self._workspace,
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

    async def upsert_driver(self, card, credential=None):
        self._guard()
        if credential is not None:
            await self.credential_store.put(credential)
        await self.register_driver(card)
        return (
            self._manager._runtime_info_from_card(card)
            if self._manager
            else self._info(card)
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

    async def sync_driver_policy(self, card):
        self._guard()
        if self._manager and self._available(card.protocol):
            await self._manager.sync_driver_policy(card)
        else:
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
        self._guard()
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
        self._guard()
        if self._manager is None:
            raise DriverNotFoundError(name)
        return await self._manager.list_driver_capabilities(
            name,
            kind=kind,
            request_context=request_context,
        )

    async def invoke_capability(self, invocation):
        self._guard()
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
