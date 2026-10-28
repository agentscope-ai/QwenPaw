# -*- coding: utf-8 -*-
"""Offline optional-plugin upgrade; raw evidence precedes workspace startup."""

from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from uuid import uuid4

from ..plugins.install_receipts import (
    has_install_commit,
    plugin_tree_digest as _digest,
)
from .mcp_plugin_migration import (
    MCPPluginUpgradeResult,
    MCPUsageSnapshot,
    MCPWorkspaceSnapshot,
    classify_mcp_usage,
)

PLUGIN_ID = "qwenpaw-mcp"
MARKER = ".mcp-plugin-migration.json"
ORIGIN = ".plugin-install-origin.json"


def _read_root(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    if not isinstance(value, dict):
        raise ValueError("Invalid root configuration")
    agents = value.get("agents", {})
    plugins = value.get("plugins", {})
    if (
        not isinstance(agents, dict)
        or not isinstance(agents.get("profiles", {}), dict)
        or not isinstance(plugins, dict)
    ):
        raise ValueError("Invalid root configuration")
    return value


def _workspace_snapshot(workspace_id, directory):
    import yaml

    config, cards, errors = {}, [], []
    try:
        try:
            config = json.loads(
                (directory / "agent.json").read_text(encoding="utf-8"),
            )
        except FileNotFoundError:
            pass
        root = directory / "drivers" / "mcp"

        def unreadable(error):
            if not isinstance(error, FileNotFoundError):
                raise error

        for parent, directories, files in os.walk(root, onerror=unreadable):
            directories[:] = [
                name for name in directories if not name.startswith(".")
            ]
            for name in sorted(files):
                path = Path(parent) / name
                if not name.startswith(".") and path.suffix.lower() in {
                    ".yaml",
                    ".yml",
                }:
                    cards.append(
                        yaml.safe_load(path.read_text(encoding="utf-8")),
                    )
    except (OSError, ValueError, yaml.YAMLError):
        errors.append("unreadable_workspace_evidence")
    return MCPWorkspaceSnapshot(
        workspace_id,
        config,
        tuple(cards),
        tuple(errors),
    )


def inventory_mcp_usage(*, config_path=None, plugins_dir=None):
    """Read configured paths, including inactive/custom workspaces."""
    from ..config.utils import get_config_path, get_plugins_dir
    from ..plugins.settings import read_plugin_intent

    config_path = (
        Path(config_path) if config_path is not None else get_config_path()
    )
    plugins_dir = (
        Path(plugins_dir) if plugins_dir is not None else get_plugins_dir()
    )
    try:
        root = _read_root(config_path)
    except (OSError, ValueError):
        return MCPUsageSnapshot(
            (
                MCPWorkspaceSnapshot(
                    "__root__",
                    errors=("invalid_root_config",),
                ),
            ),
            config_path=str(config_path),
        )
    workspaces = []
    profiles = root.get("agents", {}).get("profiles")
    if profiles is None:
        # Old single-agent root config is inventoried before host conversion.
        if "mcp" in root:
            legacy = MCPWorkspaceSnapshot("default", {"mcp": root["mcp"]})
            if (
                classify_mcp_usage(MCPUsageSnapshot((legacy,))).status
                == "needs_review"
            ):
                legacy = MCPWorkspaceSnapshot(
                    "default",
                    legacy.config,
                    errors=("invalid_legacy_root_mcp",),
                )
            workspaces.append(legacy)
        else:
            profiles = {
                "default": {
                    "workspace_dir": str(
                        config_path.parent / "workspaces/default",
                    ),
                },
            }
    for workspace_id, profile in (profiles or {}).items():
        if (
            not isinstance(profile, dict)
            or not isinstance(profile.get("workspace_dir"), str)
            or not profile["workspace_dir"].strip()
            or (profile.get("id", workspace_id) != workspace_id)
        ):
            workspaces.append(
                MCPWorkspaceSnapshot(
                    workspace_id,
                    errors=("invalid_profile",),
                ),
            )
            continue
        raw_path = profile["workspace_dir"]
        for legacy_root in ("~/.copaw", str(Path("~/.copaw").expanduser())):
            if raw_path == legacy_root or raw_path.startswith(
                legacy_root + "/",
            ):
                raw_path = (
                    str(config_path.parent) + raw_path[len(legacy_root) :]
                )
                break
        directory = Path(raw_path).expanduser()
        if not directory.is_absolute():
            directory = config_path.parent / directory
        workspaces.append(_workspace_snapshot(workspace_id, directory))
    settings = root.get("plugins", {}).get(PLUGIN_ID)
    uninstalled = False
    try:
        uninstalled = (
            read_plugin_intent(PLUGIN_ID, plugins_dir=plugins_dir) is not None
        )
    except (OSError, ValueError):
        settings = {"enabled": "invalid"}
    return MCPUsageSnapshot(
        tuple(workspaces),
        settings,
        uninstalled,
        str(config_path),
    )


def get_optional_mcp_plugin_dir():
    """Locate inert package data without adding it to plugin discovery."""
    package = Path(__file__).resolve().parents[1]
    bundled = package / "plugins/bundled/optional/mcp"
    return (
        bundled
        if bundled.is_dir()
        else package.parent.parent / "plugins/protocol/mcp"
    )


def _read_marker(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    if not isinstance(value, dict) or not all(
        isinstance(value.get(key), expected)
        for key, expected in {
            "transaction": str,
            "digest": str,
            "version": str,
            "workspaces": dict,
        }.items()
    ):
        raise ValueError("Invalid MCP upgrade record")
    valid_header = (
        type(value.get("schema")) is int
        and value["schema"] == 1
        and value.get("stage") in ("preparing", "files_committed", "completed")
        and re.fullmatch(r"[a-f0-9]{32}", value["transaction"])
        and re.fullmatch(r"[a-f0-9]{64}", value["digest"])
    )
    if not valid_header or not all(
        isinstance(key, str)
        and status in ("unused", "configured", "needs_review")
        for key, status in value["workspaces"].items()
    ):
        raise ValueError("Invalid MCP upgrade record")
    return value


class MCPPluginCoordinator:
    """One coordinator per loader; all mutations share its lifecycle lock."""

    def __init__(self, loader):
        self.loader = loader
        self.config_path = None
        self.workspace_statuses = {}
        self.root_valid = True
        self.latest_result = None

    def eligible(self, workspace_id, protocol):
        return protocol != "mcp" or (
            self.root_valid
            and PLUGIN_ID not in self.loader.startup_blocked_plugins
            and self.workspace_statuses.get(workspace_id) != "needs_review"
        )

    async def install_explicitly(self):
        """Retry offline installation, then refresh saved recovery evidence."""
        async with self.loader.plugin_lifecycle(PLUGIN_ID):
            snapshot = await asyncio.to_thread(
                inventory_mcp_usage,
                config_path=self.config_path,
                plugins_dir=self.loader.plugin_dirs[0],
            )
            try:
                installed = await asyncio.to_thread(
                    self.loader.find_installed_plugin_dir,
                    PLUGIN_ID,
                )
                if installed is None:
                    source = get_optional_mcp_plugin_dir()
                    _, manifest = await asyncio.to_thread(
                        self.loader.read_source_manifest,
                        source,
                    )
                    if manifest.id != PLUGIN_ID:
                        raise ValueError("Invalid optional MCP resource")
                    await self.loader.install_plugin_files(
                        source,
                        allow_install=False,
                        user_requested=True,
                    )
                record = self.loader.get_loaded_plugin(PLUGIN_ID)
                if record is not None and record.status == "failed":
                    await self.loader.lifecycle.reload(PLUGIN_ID)
                record = await self.loader.lifecycle.set_enabled(
                    PLUGIN_ID,
                    True,
                )
                snapshot = await asyncio.to_thread(
                    inventory_mcp_usage,
                    config_path=self.config_path,
                    plugins_dir=self.loader.plugin_dirs[0],
                )
                result = await self._ensure_owned(snapshot)
                await self._reconcile_live_workspaces()
                self.latest_result = result
                return record
            except Exception:
                self.latest_result = MCPPluginUpgradeResult(
                    "failed",
                    classify_mcp_usage(snapshot),
                    ("offline_upgrade_failed_check_dependencies_and_storage",),
                )
                raise

    async def _reconcile_live_workspaces(self):
        """Reconcile existing facades without starting agents."""
        _, off = await asyncio.to_thread(self._current_settings)
        if off:
            return
        manager = self.loader.registry.get_workspace_manager()
        workspaces = getattr(
            manager,
            "agents",
            getattr(manager, "workspaces", {}),
        )
        for workspace in tuple(workspaces.values()):
            if not self.eligible(workspace.agent_id, "mcp"):
                continue
            service = getattr(workspace, "driver_manager", None)
            if not hasattr(service, "activate_protocol") or getattr(
                service,
                "_stopped",
                False,
            ):
                continue
            # The facade rechecks exact workspace identity before activation
            # and retains cleanup ownership if retirement races this call.
            await service.activate_protocol("mcp")

    async def ensure_protocol(self, protocol):
        if protocol != "mcp":
            return
        snapshot = await asyncio.to_thread(
            inventory_mcp_usage,
            config_path=self.config_path,
            plugins_dir=self.loader.plugin_dirs[0],
        )
        # A nonempty transient request is itself evidence. Preserve every
        # existing workspace decision and explicit saved plugin intent.
        if classify_mcp_usage(snapshot).status == "unused":
            snapshot = MCPUsageSnapshot(
                snapshot.workspaces
                + (
                    MCPWorkspaceSnapshot(
                        "__request__",
                        {
                            "mcp": {
                                "clients": {
                                    "request": {
                                        "name": "request",
                                        "command": "request",
                                    },
                                },
                            },
                        },
                    ),
                ),
                snapshot.plugin_settings,
                snapshot.plugin_uninstalled,
                snapshot.config_path,
            )
        result = await self.ensure(snapshot)
        if result.status in {"installed", "unchanged"}:
            async with self.loader.plugin_lifecycle(PLUGIN_ID):
                _, off = await asyncio.to_thread(self._current_settings)
                if not off:
                    await self.loader.activate_plugin_unlocked(PLUGIN_ID)

    async def ensure(self, snapshot):
        async with self.loader.plugin_lifecycle(PLUGIN_ID):
            self.latest_result = await self._ensure_owned(snapshot)
            return self.latest_result

    async def _ensure_owned(self, snapshot):
        self.config_path = snapshot.config_path or self.config_path
        decision = classify_mcp_usage(snapshot)
        self.workspace_statuses = dict(decision.workspace_statuses)
        self.root_valid = "__root__" not in self.workspace_statuses
        self.loader.startup_blocked_plugins.add(PLUGIN_ID)
        try:
            marker = await asyncio.to_thread(
                _read_marker,
                self.loader.plugin_dirs[0] / MARKER,
            )
            installed = await asyncio.to_thread(
                self.loader.find_installed_plugin_dir,
                PLUGIN_ID,
            )
            if (
                marker is None
                and installed is not None
                and await asyncio.to_thread((installed / ORIGIN).exists)
                and not await asyncio.to_thread(
                    has_install_commit,
                    installed,
                    PLUGIN_ID,
                )
            ):
                return MCPPluginUpgradeResult(
                    "needs_review",
                    decision,
                    ("orphaned_installation_record",),
                )
        except (OSError, ValueError):
            return MCPPluginUpgradeResult(
                "needs_review",
                decision,
                ("invalid_upgrade_record",),
            )
        if decision.status in {"unused", "explicit_off", "needs_review"}:
            if decision.status == "unused":
                if installed and (
                    marker is None
                    or marker["stage"] == "completed"
                    or await asyncio.to_thread(
                        has_install_commit,
                        installed,
                        PLUGIN_ID,
                    )
                ):
                    self.loader.startup_blocked_plugins.discard(PLUGIN_ID)
            return MCPPluginUpgradeResult(
                "needs_review"
                if decision.status == "needs_review"
                else "skipped",
                decision,
                decision.reasons,
            )
        try:
            result = await self._ensure_locked(snapshot, decision)
            if result.status in {"installed", "unchanged"}:
                self.loader.startup_blocked_plugins.discard(PLUGIN_ID)
            return result
        except Exception:
            # Parser, dependency and filesystem errors may contain secrets.
            return MCPPluginUpgradeResult(
                "failed",
                decision,
                ("offline_upgrade_failed_check_dependencies_and_storage",),
            )

    def _current_settings(self):
        from ..config.utils import get_config_path
        from ..plugins.settings import read_plugin_intent

        root = _read_root(
            Path(self.config_path) if self.config_path else get_config_path(),
        )
        row = root.get("plugins", {}).get(PLUGIN_ID)
        if row is not None and (
            not isinstance(row, dict)
            or ("enabled" in row and type(row["enabled"]) is not bool)
        ):
            raise ValueError("Invalid plugin settings")
        off = (row or {}).get("enabled") is False or read_plugin_intent(
            PLUGIN_ID,
            plugins_dir=self.loader.plugin_dirs[0],
        ) is not None
        return row, off

    async def _ensure_locked(self, snapshot, decision):
        from ..plugins.settings import persist_plugin_settings, runtime_config
        from ..utils.io_utils import run_sync_io, write_json_atomic

        row, off = await asyncio.to_thread(self._current_settings)
        if off:
            fresh = MCPUsageSnapshot(
                snapshot.workspaces,
                row,
                True,
                snapshot.config_path,
            )
            return MCPPluginUpgradeResult("skipped", classify_mcp_usage(fresh))
        base = self.loader.plugin_dirs[0]
        marker_path = base / MARKER
        marker = await asyncio.to_thread(_read_marker, marker_path)
        target = await asyncio.to_thread(
            self.loader.find_installed_plugin_dir,
            PLUGIN_ID,
        )
        installed = False
        explicit_commit = False
        if target is None:
            source = get_optional_mcp_plugin_dir()
            _, manifest = await asyncio.to_thread(
                self.loader.read_source_manifest,
                source,
            )
            if manifest.id != PLUGIN_ID:
                raise ValueError("Invalid optional MCP resource")
            digest = await asyncio.to_thread(_digest, source)
            marker = {
                "schema": 1,
                "transaction": uuid4().hex,
                "stage": "preparing",
                "version": manifest.version,
                "digest": digest,
                "workspaces": dict(decision.workspace_statuses),
            }
            await run_sync_io(write_json_atomic, marker_path, marker)
            await self.loader.install_plugin_files(
                source,
                allow_install=False,
                user_requested=False,
                install_origin={
                    "schema": 1,
                    "transaction": marker["transaction"],
                    "digest": digest,
                },
            )
            target = base / PLUGIN_ID
            installed = True
        elif marker is None or marker["stage"] != "completed":
            explicit_commit = await asyncio.to_thread(
                has_install_commit,
                target,
                PLUGIN_ID,
            )
        if (
            not installed
            and not explicit_commit
            and marker is not None
            and marker["stage"] != "completed"
        ):
            origin = json.loads(
                await asyncio.to_thread((target / ORIGIN).read_text),
            )
            if (
                origin
                != {
                    "schema": 1,
                    "transaction": marker["transaction"],
                    "digest": marker["digest"],
                }
                or await asyncio.to_thread(_digest, target) != marker["digest"]
            ):
                raise ValueError("Unowned incomplete installation")
        if (
            not explicit_commit
            and marker is not None
            and marker["stage"] != "completed"
        ):
            marker = {**marker, "stage": "files_committed"}
            await run_sync_io(write_json_atomic, marker_path, marker)
        row, off = await asyncio.to_thread(self._current_settings)
        if off:
            fresh = MCPUsageSnapshot(
                snapshot.workspaces,
                row,
                True,
                snapshot.config_path,
            )
            return MCPPluginUpgradeResult("skipped", classify_mcp_usage(fresh))
        _, manifest = await asyncio.to_thread(
            self.loader.read_source_manifest,
            target,
        )
        record = await self.loader.load_plugin(
            manifest,
            target,
            runtime_config(row),
            allow_install=False,
            activate=False,
        )
        if record.status == "failed":
            raise RuntimeError(
                "Optional MCP dependencies or registration unavailable",
            )
        if explicit_commit:
            await run_sync_io(
                write_json_atomic,
                marker_path,
                {
                    "schema": 1,
                    "transaction": uuid4().hex,
                    "stage": "completed",
                    "version": manifest.version,
                    "digest": await asyncio.to_thread(_digest, target),
                    "workspaces": dict(decision.workspace_statuses),
                },
            )
        elif marker is not None and marker["stage"] != "completed":
            await run_sync_io(
                persist_plugin_settings,
                PLUGIN_ID,
                enabled=True,
                config_path=Path(self.config_path)
                if self.config_path
                else None,
                refuse_disabled=True,
            )
            marker = {
                **marker,
                "stage": "completed",
                "workspaces": dict(decision.workspace_statuses),
            }
            await run_sync_io(write_json_atomic, marker_path, marker)
        return MCPPluginUpgradeResult(
            "installed" if installed else "unchanged",
            decision,
            decision.reasons,
        )


def get_coordinator(loader):
    coordinator = getattr(loader, "protocol_coordinator", None)
    if coordinator is None:
        coordinator = MCPPluginCoordinator(loader)
        loader.protocol_coordinator = coordinator
        loader.registry.protocol_resolver = coordinator.ensure_protocol
        loader.registry.protocol_eligibility = coordinator.eligible
    return coordinator


async def prepare_startup_plugins(
    loader,
    workspace_manager,
    *,
    app=None,
    snapshot=None,
):
    """Register startup-critical SDK protocols before workspace publication."""
    from ..config.utils import get_config_path

    loader.registry.set_workspace_manager(workspace_manager)
    if app is not None:
        app.state.plugin_loader = loader
        app.state.plugin_registry = loader.registry
        loader.registry.set_plugin_http_app(app)
    current = await asyncio.to_thread(
        inventory_mcp_usage,
        config_path=snapshot.config_path if snapshot else None,
        plugins_dir=loader.plugin_dirs[0],
    )
    if snapshot is not None:
        preserved = {
            item.workspace_id: item
            for item in snapshot.workspaces
            if classify_mcp_usage(MCPUsageSnapshot((item,))).status
            in {"configured", "needs_review"}
        }
        merged = {item.workspace_id: item for item in current.workspaces}
        for workspace_id, previous in preserved.items():
            latest = merged.get(workspace_id)
            before = classify_mcp_usage(MCPUsageSnapshot((previous,))).status
            after = (
                classify_mcp_usage(MCPUsageSnapshot((latest,))).status
                if latest is not None
                else "unused"
            )
            if before == "needs_review" or after == "unused":
                merged[workspace_id] = previous
        current = MCPUsageSnapshot(
            tuple(merged.values()),
            current.plugin_settings,
            current.plugin_uninstalled,
            current.config_path,
        )
    result = await get_coordinator(loader).ensure(current)
    try:
        root = await asyncio.to_thread(
            _read_root,
            Path(current.config_path)
            if current.config_path
            else get_config_path(),
        )
    except (OSError, ValueError):
        return result
    await loader.load_all_plugins(
        configs=root.get("plugins", {}),
        types=["channel", "memory", "hub"],
        capabilities=["drivers"],
        activate=False,
    )
    return result
