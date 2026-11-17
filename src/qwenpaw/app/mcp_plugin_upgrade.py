# -*- coding: utf-8 -*-
"""Offline optional-plugin upgrade; raw evidence precedes workspace startup."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from dataclasses import dataclass
from uuid import uuid4

from ..plugins.install_receipts import (
    has_install_commit,
    plugin_tree_digest as _digest,
)
from .mcp_plugin_migration import (
    MCPPluginUpgradeResult,
    MCPUsageSnapshot,
    MCPUsageDecision,
    MCPWorkspaceSnapshot,
    classify_mcp_usage,
)

from ..utils.io_utils import run_sync_io
from .mcp_plugin_state import (
    MARKER,
    automatic,
    publish_marker,
    read_marker as _read_marker,
)

PLUGIN_ID = "qwenpaw-mcp"
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
    # Root feature settings can predate per-agent files or be inherited by
    # agents. Never hydrate Config here: ACP's default runners are enabled.
    features = {
        key: root[key] for key in ("mail", "acp", "tools") if key in root
    }
    if features:
        workspaces.append(MCPWorkspaceSnapshot("__root_features__", features))
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


@dataclass(frozen=True)
class StartupMigration:
    config_path: str
    marker: dict | None
    snapshot: MCPUsageSnapshot | None = None
    diagnostics: tuple[str, ...] = ()


def read_startup_migration(*, config_path=None, plugins_dir=None):
    """Inspect the small decision before any host configuration conversion."""
    from ..config.utils import get_config_path, get_plugins_dir
    from .mcp_plugin_migration import validate_mcp_upgrade_preflight

    config_path = Path(config_path) if config_path else get_config_path()
    plugins_dir = Path(plugins_dir) if plugins_dir else get_plugins_dir()
    try:
        root = _read_root(config_path)
    except (OSError, ValueError) as exc:
        raise RuntimeError(
            "Root configuration requires review before startup",
        ) from exc
    if "mcp" in root and root.get("agents", {}).get("profiles") is None:
        legacy = MCPWorkspaceSnapshot("default", {"mcp": root["mcp"]})
        if (
            classify_mcp_usage(MCPUsageSnapshot((legacy,))).status
            == "needs_review"
        ):
            raise RuntimeError(
                "Root configuration requires review before startup",
            )
    settings = root.get("plugins", {}).get(PLUGIN_ID)
    if settings is not None and (
        not isinstance(settings, dict)
        or ("enabled" in settings and type(settings["enabled"]) is not bool)
    ):
        return StartupMigration(
            str(config_path),
            None,
            diagnostics=("invalid_plugin_settings",),
        )
    try:
        marker = _read_marker(plugins_dir / MARKER)
    except (OSError, ValueError):
        return StartupMigration(
            str(config_path),
            None,
            diagnostics=("invalid_upgrade_record",),
        )
    snapshot = None
    if marker is None:
        snapshot = inventory_mcp_usage(
            config_path=config_path,
            plugins_dir=plugins_dir,
        )
        validate_mcp_upgrade_preflight(snapshot)
    return StartupMigration(str(config_path), marker, snapshot)


def _workspace_evidence(workspace_id, directory, config_path=None):
    """Check the target's raw profile as well as its own files."""
    from ..config.utils import get_config_path

    snapshot = _workspace_snapshot(workspace_id, Path(directory))
    try:
        root = _read_root(
            Path(config_path) if config_path else get_config_path(),
        )
        profile = root.get("agents", {}).get("profiles", {}).get(workspace_id)
        invalid = profile is not None and (
            not isinstance(profile, dict)
            or profile.get("id", workspace_id) != workspace_id
            or not isinstance(profile.get("workspace_dir"), str)
            or not profile["workspace_dir"].strip()
        )
    except (OSError, ValueError):
        invalid = True
    if invalid:
        return MCPWorkspaceSnapshot(
            workspace_id,
            snapshot.config,
            snapshot.cards,
            snapshot.errors + ("invalid_profile",),
        )
    return snapshot


async def capture_workspace_usage(workspace_id, directory):
    """Capture before bootstrap can hydrate or rewrite an agent's raw input."""
    from ..plugins.registry import PluginRegistry

    if PluginRegistry().protocol_eligibility is None:
        return None
    coordinator = getattr(
        PluginRegistry().protocol_eligibility,
        "__self__",
        None,
    )
    snapshot = await run_sync_io(
        _workspace_evidence,
        workspace_id,
        directory,
        getattr(coordinator, "config_path", None),
    )
    previous = getattr(coordinator, "initial_evidence", {}).pop(
        workspace_id,
        None,
    )
    if (
        previous is not None
        and classify_mcp_usage(MCPUsageSnapshot((previous,))).status
        == "needs_review"
    ):
        return previous
    return snapshot


def bind_workspace_usage(workspace, snapshot):
    if snapshot is not None:
        workspace._mcp_usage_snapshot = snapshot
        workspace._mcp_usage_status = classify_mcp_usage(
            MCPUsageSnapshot((snapshot,)),
        ).status


class MCPPluginCoordinator:
    """One coordinator per loader; all mutations share its lifecycle lock."""

    def __init__(self, loader):
        self.loader = loader
        self.config_path = None
        self.workspace_statuses = {}
        self.root_valid = True
        self.latest_result = None
        self.initial_evidence = {}

    @property
    def marker_path(self):
        return self.loader.plugin_dirs[0] / MARKER

    def eligible(self, workspace_id, protocol, *, workspace=None):
        if protocol != "mcp":
            return True
        if workspace is None:
            manager = self.loader.registry.get_workspace_manager()
            live = getattr(
                manager,
                "agents",
                getattr(manager, "workspaces", {}),
            )
            workspace = live.get(
                workspace_id,
            ) or self.loader.registry._stop_workspaces.get(workspace_id)
        return (
            self.root_valid
            and PLUGIN_ID not in self.loader.startup_blocked_plugins
            and workspace is not None
            and getattr(workspace, "_mcp_usage_status", "needs_review")
            != "needs_review"
        )

    async def check_workspace(self, workspace, *, refresh=False):
        if refresh or not hasattr(workspace, "_mcp_usage_status"):
            snapshot = await run_sync_io(
                _workspace_evidence,
                workspace.agent_id,
                workspace.workspace_dir,
                self.config_path,
            )
            bind_workspace_usage(workspace, snapshot)
        # Preserved pre-conversion errors must not disappear during hydration.
        return self.eligible(workspace.agent_id, "mcp", workspace=workspace)

    def _result(self, marker, *, status=None, diagnostics=()):
        statuses = (marker or {}).get("workspaces", {})
        mode = automatic(marker)
        decision = MCPUsageDecision(
            "needs_review"
            if mode == "needs_review"
            else "configured"
            if "configured" in statuses.values()
            else "unused",
            statuses,
        )
        self.latest_result = MCPPluginUpgradeResult(
            status
            or {
                "attempted": "failed",
                "needs_review": "needs_review",
                "completed": "unchanged",
            }.get(mode, "skipped"),
            decision,
            tuple(diagnostics or (marker or {}).get("diagnostics", ())),
        )
        return self.latest_result

    async def restore(self, marker, *, diagnostics=()):
        """Restore decisions only; ordinary plugin loading owns runtime health."""
        # Startup snapshots never authorize a later directory publication.
        observed = marker
        diagnostics = ()
        try:
            _, off = await run_sync_io(self._current_settings)
        except (OSError, ValueError):
            off = False
            diagnostics = ("invalid_plugin_settings",)
        try:
            marker = await run_sync_io(_read_marker, self.marker_path)
            if observed is not None and marker is None:
                diagnostics = diagnostics or ("invalid_upgrade_record",)
        except (OSError, ValueError):
            marker = None
            diagnostics = diagnostics or ("invalid_upgrade_record",)
        if off:
            self.loader.startup_blocked_plugins.add(PLUGIN_ID)
            return self._result(marker, status="skipped")
        target = await run_sync_io(
            self.loader.find_installed_plugin_dir,
            PLUGIN_ID,
        )
        if diagnostics:
            if (
                diagnostics == ("invalid_upgrade_record",)
                and target is not None
                and await run_sync_io(has_install_commit, target, PLUGIN_ID)
            ):
                marker = await run_sync_io(
                    publish_marker,
                    self.marker_path,
                    None,
                    recover_invalid=True,
                    automatic="completed",
                )
            else:
                self.loader.startup_blocked_plugins.add(PLUGIN_ID)
                return self._result(
                    marker,
                    status="needs_review",
                    diagnostics=diagnostics,
                )
        if (
            automatic(marker) in (None, "not_required")
            and target is not None
            and await run_sync_io((target / ORIGIN).exists)
            and not await run_sync_io(has_install_commit, target, PLUGIN_ID)
        ):
            marker = await run_sync_io(
                publish_marker,
                self.marker_path,
                marker,
                automatic="needs_review",
                diagnostics=["orphaned_installation_record"],
            )
        if automatic(marker) in {"attempted", "needs_review"}:
            if target is None or not await run_sync_io(
                has_install_commit,
                target,
                PLUGIN_ID,
            ):
                self.loader.startup_blocked_plugins.add(PLUGIN_ID)
                return self._result(marker)
            marker = await run_sync_io(
                publish_marker,
                self.marker_path,
                marker,
                automatic="completed",
                diagnostics=[],
            )
        elif automatic(marker) == "not_required" and target is not None:
            if await run_sync_io(has_install_commit, target, PLUGIN_ID):
                marker = await run_sync_io(
                    publish_marker,
                    self.marker_path,
                    marker,
                    automatic="completed",
                    diagnostics=[],
                )
        if target is None:
            # A directory appearing after this check must not enter discovery.
            self.loader.startup_blocked_plugins.add(PLUGIN_ID)
        else:
            self.loader.startup_blocked_plugins.discard(PLUGIN_ID)
        return self._result(marker)

    async def install_explicitly(self):
        """Use the existing explicit installer and reconcile only committed work."""
        async with self.loader.plugin_lifecycle(PLUGIN_ID):
            try:
                marker = await run_sync_io(_read_marker, self.marker_path)
            except ValueError:
                marker = await run_sync_io(
                    publish_marker,
                    self.marker_path,
                    None,
                    recover_invalid=True,
                    automatic="attempted",
                )
            installed = await run_sync_io(
                self.loader.find_installed_plugin_dir,
                PLUGIN_ID,
            )
            if installed is not None and (marker or {}).get("stage") in {
                "preparing",
                "files_committed",
            }:
                if not await run_sync_io(
                    has_install_commit,
                    installed,
                    PLUGIN_ID,
                ):
                    await run_sync_io(self._validate_origin, installed, marker)
            if installed is None:
                await self.loader.install_plugin_files(
                    get_optional_mcp_plugin_dir(),
                    allow_install=False,
                    user_requested=True,
                )
            record = self.loader.get_loaded_plugin(PLUGIN_ID)
            if record is not None and record.status == "failed":
                await self.loader.lifecycle.reload(PLUGIN_ID)
            record = await self.loader.lifecycle.set_enabled(PLUGIN_ID, True)
            if getattr(record, "status", None) != "active":
                raise RuntimeError("MCP activation did not complete")
            await self.reconcile_explicit()
            return record

    @staticmethod
    def _validate_origin(target, marker):
        origin = json.loads((target / ORIGIN).read_text())
        if (
            origin
            != {
                "schema": 1,
                "transaction": marker["transaction"],
                "digest": marker["digest"],
            }
            or _digest(target) != marker["digest"]
        ):
            raise ValueError("Unowned incomplete installation")

    async def reconcile_explicit(self):
        from .mcp.feature_gate import is_mcp_ready

        if not is_mcp_ready(self.loader):
            return
        try:
            marker = await run_sync_io(_read_marker, self.marker_path)
        except ValueError:
            target = await run_sync_io(
                self.loader.find_installed_plugin_dir,
                PLUGIN_ID,
            )
            if target is None or not await run_sync_io(
                has_install_commit,
                target,
                PLUGIN_ID,
            ):
                raise
            marker = None
        marker = await run_sync_io(
            publish_marker,
            self.marker_path,
            marker,
            recover_invalid=True,
            automatic="completed",
            diagnostics=[],
            **({"stage": "completed"} if "stage" in (marker or {}) else {}),
        )
        self.loader.startup_blocked_plugins.discard(PLUGIN_ID)
        self._result(marker)
        await self._reconcile_live_workspaces(refresh=True)

    async def _reconcile_live_workspaces(self, *, refresh=False):
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
            await self.check_workspace(workspace, refresh=refresh)
            if not self.eligible(
                workspace.agent_id,
                "mcp",
                workspace=workspace,
            ):
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
        from .mcp.feature_gate import is_mcp_ready

        if is_mcp_ready(self.loader):
            return
        async with self.loader.plugin_lifecycle(PLUGIN_ID):
            if is_mcp_ready(self.loader):
                return
            try:
                await self._ensure_protocol_owned()
            except Exception:
                self._failed()

    def _failed(self):
        self.loader.startup_blocked_plugins.add(PLUGIN_ID)
        return self._result(
            None,
            status="failed",
            diagnostics=(
                "offline_upgrade_failed_check_dependencies_and_storage",
            ),
        )

    async def _ensure_protocol_owned(self):
        marker = await run_sync_io(_read_marker, self.marker_path)
        row, off = await run_sync_io(self._current_settings)
        if off:
            return
        restored = await self.restore(marker)
        if restored.status in {"failed", "needs_review"}:
            return
        row, off = await run_sync_io(self._current_settings)
        if off:
            return
        # Receipt reconciliation may have published a new revision.
        marker = await run_sync_io(_read_marker, self.marker_path)
        target = await run_sync_io(
            self.loader.find_installed_plugin_dir,
            PLUGIN_ID,
        )
        if target is None:
            if automatic(marker) not in (None, "not_required"):
                return
            # The real request itself establishes demand, without scanning peers.
            decision = MCPUsageDecision("configured", {})
            await self._install_once(marker, decision)
        else:
            await self._load_installed(target, row)
            if automatic(marker) in (None, "not_required"):
                marker = await run_sync_io(
                    publish_marker,
                    self.marker_path,
                    marker,
                    automatic="completed",
                )
        from .mcp.feature_gate import is_mcp_ready

        if is_mcp_ready(self.loader):
            await self._reconcile_live_workspaces()

    async def ensure(self, snapshot):
        async with self.loader.plugin_lifecycle(PLUGIN_ID):
            try:
                return await self._ensure_snapshot(snapshot)
            except Exception:
                return self._failed()

    async def _ensure_snapshot(self, snapshot):
        self.config_path = snapshot.config_path or self.config_path
        decision = classify_mcp_usage(snapshot)
        self.workspace_statuses = dict(decision.workspace_statuses)
        self.initial_evidence = {
            item.workspace_id: item for item in snapshot.workspaces
        }
        self.root_valid = "__root__" not in self.workspace_statuses
        marker = await run_sync_io(_read_marker, self.marker_path)
        if marker is not None:
            return await self.restore(marker)
        target = await run_sync_io(
            self.loader.find_installed_plugin_dir,
            PLUGIN_ID,
        )
        if (
            target is not None
            and await run_sync_io((target / ORIGIN).exists)
            and not await run_sync_io(has_install_commit, target, PLUGIN_ID)
        ):
            marker = await run_sync_io(
                publish_marker,
                self.marker_path,
                marker,
                automatic="needs_review",
                workspaces=dict(decision.workspace_statuses),
                diagnostics=["orphaned_installation_record"],
            )
            return await self.restore(marker)
        if decision.status in {"unused", "explicit_off", "needs_review"}:
            marker = await run_sync_io(
                publish_marker,
                self.marker_path,
                marker,
                automatic="needs_review"
                if decision.status == "needs_review"
                else "completed"
                if target
                else "not_required",
                workspaces=dict(decision.workspace_statuses),
            )
            return await self.restore(marker)
        if target is not None:
            marker = await run_sync_io(
                publish_marker,
                self.marker_path,
                marker,
                automatic="completed",
                workspaces=dict(decision.workspace_statuses),
            )
            return await self.restore(marker)
        return await self._install_once(marker, decision)

    async def _load_installed(self, target, row, *, activate=True):
        from ..plugins.settings import runtime_config

        _, manifest = await run_sync_io(
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
        if activate:
            await self.loader.activate_plugin_unlocked(PLUGIN_ID)
        return record

    async def _install_once(self, marker, decision):
        from ..plugins.settings import persist_plugin_settings

        self.loader.startup_blocked_plugins.add(PLUGIN_ID)
        marker = await run_sync_io(
            publish_marker,
            self.marker_path,
            marker,
            automatic="attempted",
            workspaces=dict(decision.workspace_statuses),
        )
        try:
            source = get_optional_mcp_plugin_dir()
            _, manifest = await run_sync_io(
                self.loader.read_source_manifest,
                source,
            )
            if manifest.id != PLUGIN_ID:
                raise ValueError("Invalid optional MCP resource")
            digest = await run_sync_io(_digest, source)
            marker = await run_sync_io(
                publish_marker,
                self.marker_path,
                marker,
                transaction=uuid4().hex,
                digest=digest,
                version=manifest.version,
                stage="preparing",
            )
            _, off = await run_sync_io(self._current_settings)
            if off:
                return self._result(marker, status="skipped")
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
            marker = await run_sync_io(
                publish_marker,
                self.marker_path,
                marker,
                stage="files_committed",
            )
            row, off = await run_sync_io(self._current_settings)
            if off:
                return self._result(marker, status="skipped")
            await self._load_installed(
                self.loader.plugin_dirs[0] / PLUGIN_ID,
                row,
                activate=False,
            )
            await run_sync_io(
                persist_plugin_settings,
                PLUGIN_ID,
                enabled=True,
                config_path=Path(self.config_path)
                if self.config_path
                else None,
                refuse_disabled=True,
            )
            # Preserve the original order: intent commits before activation.
            self.loader.startup_blocked_plugins.discard(PLUGIN_ID)
            await self.loader.activate_plugin_unlocked(PLUGIN_ID)
            marker = await run_sync_io(
                publish_marker,
                self.marker_path,
                marker,
                stage="completed",
                automatic="completed",
            )
            return self._result(marker, status="installed")
        except Exception:
            self.loader.startup_blocked_plugins.add(PLUGIN_ID)
            marker = await run_sync_io(
                publish_marker,
                self.marker_path,
                marker,
                diagnostics=[
                    "offline_upgrade_failed_check_dependencies_and_storage",
                ],
            )
            return self._result(marker)
        finally:
            if automatic(marker) != "completed":
                self.loader.startup_blocked_plugins.add(PLUGIN_ID)

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
    startup=None,
):
    """Register startup-critical SDK protocols before workspace publication."""
    from ..config.utils import get_config_path

    loader.registry.set_workspace_manager(workspace_manager)
    if app is not None:
        app.state.plugin_loader = loader
        app.state.plugin_registry = loader.registry
        loader.registry.set_plugin_http_app(app)
    coordinator = get_coordinator(loader)
    if startup is not None:
        coordinator.config_path = startup.config_path
    if startup is not None and startup.snapshot is None:
        result = await coordinator.restore(
            startup.marker,
            diagnostics=startup.diagnostics,
        )
        current = MCPUsageSnapshot((), config_path=startup.config_path)
    else:
        result = None
        snapshot = startup.snapshot if startup else snapshot
    if result is None:
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
    if result is None:
        result = await coordinator.ensure(current)
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
    record = loader.get_loaded_plugin(PLUGIN_ID)
    if (
        record is not None
        and record.enabled
        and get_coordinator(loader).root_valid
        and PLUGIN_ID not in loader.startup_blocked_plugins
    ):
        try:
            async with loader.plugin_lifecycle(PLUGIN_ID):
                await loader.activate_plugin_unlocked(PLUGIN_ID)
                marker = await run_sync_io(
                    _read_marker,
                    coordinator.marker_path,
                )
                if automatic(marker) == "not_required":
                    marker = await run_sync_io(
                        publish_marker,
                        coordinator.marker_path,
                        marker,
                        automatic="completed",
                    )
                    coordinator._result(marker)
        except Exception:
            # Optional Mail/ACP must not prevent ordinary agents from starting.
            loader.startup_blocked_plugins.add(PLUGIN_ID)
    return result
