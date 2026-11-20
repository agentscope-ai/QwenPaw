# -*- coding: utf-8 -*-
"""Offline optional-plugin upgrade; raw evidence precedes workspace startup."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from dataclasses import dataclass
from uuid import uuid4

from ..plugins.install_receipts import (
    has_install_commit,
    plugin_tree_digest as _digest,
    write_install_commit,
)
from ..plugins.safe_fs import same_location
from ..drivers.errors import driver_error_diagnostic
from .mcp_plugin_migration import (
    MCPPluginUpgradeResult,
    MCPUsageSnapshot,
    MCPUsageDecision,
    MCPWorkspaceSnapshot,
    classify_mcp_usage,
    needs_legacy_migration,
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
_OFFLINE_FAILURE = "offline_upgrade_failed_check_dependencies_and_storage"
logger = logging.getLogger(__name__)


def _read_root(path):
    from ..config.utils import parse_config_data

    try:
        return parse_config_data(path.read_bytes())[0] or {}
    except FileNotFoundError:
        return {}


def _root_profiles(root):
    agents = root.get("agents")
    profiles = agents.get("profiles") if isinstance(agents, dict) else None
    return profiles if isinstance(profiles, dict) else None


def _root_plugins(root):
    plugins = root.get("plugins")
    return plugins if isinstance(plugins, dict) else {}


def normalize_legacy_mcp(raw, *, root=False):
    """Use the legacy model on saved values, leaving model defaults implicit."""
    from pydantic import ValidationError

    from ..config.config import MCPClientConfig, MCPConfig
    from ..drivers.adapters.mcp_legacy_config import (
        CURRENT_MCP_MIGRATION_VERSION,
        args_may_contain_secret,
    )
    from ..drivers.contracts import validate_card_name
    from ..drivers.errors import DriverCardError
    from ..exceptions import ConfigurationException

    if raw is None and not root:
        return None, ()
    if not isinstance(raw, dict) or not isinstance(
        raw.get("clients", {}),
        dict,
    ):
        return MCPConfig(clients={}), (("mcp", "invalid section"),)
    try:
        mcp = MCPConfig.model_validate({**raw, "clients": {}})
    except ValidationError:
        return MCPConfig(clients={}), (("mcp", "invalid settings"),)
    if not 0 <= mcp.migration_version <= CURRENT_MCP_MIGRATION_VERSION:
        return MCPConfig(clients={}), (("mcp", "invalid migration version"),)
    if mcp.migration_version:
        # Consumed source definitions can remain on disk for downgrade.
        return mcp, ()

    skipped = []
    for index, (name, value) in enumerate(raw.get("clients", {}).items(), 1):
        try:
            validate_card_name(name)
        except DriverCardError:
            skipped.append((f"entry #{index}", "invalid source name"))
            continue
        try:
            model = MCPClientConfig.model_validate(value)
        except (DriverCardError, ValidationError, ConfigurationException):
            skipped.append((name, "invalid client configuration"))
        else:
            if args_may_contain_secret(model.args):
                skipped.append((name, "possible secret in launch arguments"))
                continue
            mcp.clients[name] = model
    return mcp, tuple(skipped)


def log_legacy_archive(scope, skipped):
    for source, reason in skipped:
        logger.warning(
            "Archived legacy MCP configuration in %r; skipped %r (%s)",
            scope,
            source,
            reason,
        )


def _legacy_review_path(config_path):
    return config_path.with_name(f"{config_path.name}.legacy-mcp.pending.bak")


def legacy_mcp_was_archived(config_path):
    return _legacy_review_path(config_path).is_file() or any(
        path.is_file()
        for path in config_path.parent.glob(
            f"{config_path.name}.legacy-mcp-*.bak",
        )
    )


def _reviewed_workspaces(marker):
    if (
        automatic(marker) != "needs_review"
        or marker.get("diagnostics")
        or "transaction" in marker
    ):
        return set()
    return {
        name
        for name, status in marker["workspaces"].items()
        if status == "needs_review"
    }


def _legacy_review_marker(marker, snapshot):
    reviewed = _reviewed_workspaces(marker)
    if not reviewed:
        return False
    if classify_mcp_usage(snapshot).status == "configured":
        # A review-only marker never attempted an installation. A valid
        # source now provides the evidence that was missing at first boot.
        return True
    if (
        "default" in reviewed
        and snapshot.config_path
        and _legacy_review_path(Path(snapshot.config_path)).is_file()
    ):
        reviewed.remove("default")
    return not reviewed


def _workspace_snapshot(
    workspace_id,
    directory,
    inherited_mcp=None,
    *,
    report_card_errors=False,
):
    from ..config.config import _read_agent_config_snapshot
    from ..drivers.errors import DriverCardError, driver_error_diagnostic
    from ..drivers.storage import list_card_paths, load_card

    config, original = {}, None
    path = directory / "agent.json"
    try:
        original, _ = _read_agent_config_snapshot(path)
        config = json.loads(original)
        if not isinstance(config, dict):
            raise ValueError("Agent config must be an object")
    except FileNotFoundError:
        pass
    except (OSError, ValueError):
        return MCPWorkspaceSnapshot(
            workspace_id,
            errors=("unreadable_workspace_evidence",),
        )

    mcp, skipped_legacy = normalize_legacy_mcp(config.get("mcp"))
    skipped = bool(skipped_legacy)
    if original is None:
        mcp = inherited_mcp
    cards = []
    try:
        for card_path in list_card_paths(
            directory / "drivers",
            protocols={"mcp"},
        ):
            try:
                card = load_card(card_path)
            except (DriverCardError, ValueError) as exc:
                if report_card_errors:
                    logger.warning(
                        "MCP startup scan skipped DriverCard %r "
                        "in workspace %r: %s",
                        str(card_path),
                        workspace_id,
                        driver_error_diagnostic(exc),
                    )
                skipped = True
                continue
            if card.protocol == "mcp":
                cards.append(card)
    except (OSError, DriverCardError) as exc:
        if report_card_errors:
            logger.warning(
                "Could not list DriverCards for MCP startup in workspace %r: %s",
                workspace_id,
                driver_error_diagnostic(exc),
            )
        skipped = True
    return MCPWorkspaceSnapshot(
        workspace_id,
        {
            key: config[key]
            for key in ("mail", "acp", "tools")
            if key in config
        },
        tuple(cards),
        legacy_mcp=mcp,
        skipped_sources=skipped,
        legacy_backup=original if skipped_legacy else None,
        legacy_skips=skipped_legacy,
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
    from pydantic import ValidationError

    from ..config.config import AgentProfileRef, AgentsConfig
    from ..config.utils import _normalize_working_dir_bound_paths

    root = _normalize_working_dir_bound_paths(root)
    workspaces = []
    # Inspect only saved feature settings and source definitions.
    features = {
        key: root[key] for key in ("mail", "acp", "tools") if key in root
    }
    if features:
        workspaces.append(MCPWorkspaceSnapshot("__root_features__", features))
    inherited_mcp, _ = normalize_legacy_mcp(root.get("mcp"))
    profiles = _root_profiles(root)
    if profiles is None:
        profiles = {
            name: ref.model_dump()
            for name, ref in AgentsConfig().profiles.items()
        }
    for workspace_id, profile in profiles.items():
        try:
            agent = AgentProfileRef.model_validate(profile)
        except ValidationError:
            continue
        workspaces.append(
            _workspace_snapshot(
                workspace_id,
                Path(agent.workspace_dir).expanduser(),
                inherited_mcp,
                report_card_errors=True,
            ),
        )
    settings = _root_plugins(root).get(PLUGIN_ID)
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
    from ..plugins.optional_mcp import get_optional_mcp_plugin_dir as locate

    return locate()


@dataclass(frozen=True)
class StartupMigration:
    config_path: str
    marker: dict | None
    snapshot: MCPUsageSnapshot | None = None


def read_startup_migration(*, config_path=None, plugins_dir=None):
    """Inspect the small decision before any host configuration conversion."""
    from ..config.utils import (
        get_config_path,
        get_plugins_dir,
        isolate_legacy_root_mcp,
    )

    config_path = Path(config_path) if config_path else get_config_path()
    plugins_dir = Path(plugins_dir) if plugins_dir else get_plugins_dir()
    try:
        root = _read_root(config_path)
    except (OSError, ValueError):
        return StartupMigration(str(config_path), None)
    if "mcp" in root and _root_profiles(root) is None:
        legacy, skipped = normalize_legacy_mcp(root["mcp"], root=True)
        if skipped:
            isolate_legacy_root_mcp(config_path, root, legacy.model_dump())
            log_legacy_archive("root config", skipped)
    settings = _root_plugins(root).get(PLUGIN_ID)
    if settings is not None and (
        not isinstance(settings, dict)
        or ("enabled" in settings and type(settings["enabled"]) is not bool)
    ):
        return StartupMigration(str(config_path), None)
    try:
        marker = _read_marker(plugins_dir / MARKER)
    except (OSError, ValueError):
        return StartupMigration(str(config_path), None)
    snapshot = None
    if marker is None or _reviewed_workspaces(marker):
        snapshot = inventory_mcp_usage(
            config_path=config_path,
            plugins_dir=plugins_dir,
        )
        if marker is not None and not _legacy_review_marker(marker, snapshot):
            snapshot = None
    return StartupMigration(str(config_path), marker, snapshot)


def _workspace_evidence(
    workspace_id,
    directory,
    config_path=None,
    *,
    report_card_errors=False,
):
    """Use the same MCP inheritance as the host's missing-profile fallback."""
    from ..config.utils import get_config_path

    config_path = Path(config_path) if config_path else get_config_path()
    directory = Path(directory).expanduser()
    inherited_mcp = None
    if not (directory / "agent.json").is_file():
        try:
            root = _read_root(config_path)
        except (OSError, ValueError):
            root = {}
        inherited_mcp, _ = normalize_legacy_mcp(root.get("mcp"))
    return _workspace_snapshot(
        workspace_id,
        directory,
        inherited_mcp,
        report_card_errors=report_card_errors,
    )


async def capture_workspace_usage(workspace_id, directory):
    """Capture before bootstrap can hydrate or rewrite an agent's raw input."""
    from ..plugins.registry import PluginRegistry

    coordinator = PluginRegistry().get_protocol_preparation()
    if coordinator is None:
        return None
    return await coordinator.capture_workspace_usage(workspace_id, directory)


def bind_workspace_usage(workspace, snapshot):
    # pylint: disable=protected-access
    if snapshot is not None:
        workspace._mcp_legacy_migration = (
            snapshot if needs_legacy_migration(snapshot) else None
        )
        workspace._mcp_skipped_sources = snapshot.skipped_sources
        workspace._mcp_usage_status = classify_mcp_usage(
            MCPUsageSnapshot((snapshot,)),
        ).status


class MCPPluginCoordinator:
    """One coordinator per loader; all mutations share its lifecycle lock."""

    def __init__(self, loader):
        self.loader = loader
        self.config_path = None
        self.root_valid = True
        self.latest_result = None
        self.initial_evidence = {}

    @property
    def marker_path(self):
        return self.loader.plugin_dirs[0] / MARKER

    async def capture_workspace_usage(self, workspace_id, directory):
        snapshot = await run_sync_io(
            _workspace_evidence,
            workspace_id,
            directory,
            self.config_path,
            report_card_errors=workspace_id not in self.initial_evidence,
        )
        previous = self.initial_evidence.pop(workspace_id, None)
        if (
            previous is not None
            and classify_mcp_usage(MCPUsageSnapshot((previous,))).status
            == "needs_review"
        ):
            return previous
        return snapshot

    def eligible(self, workspace_id, protocol, *, workspace=None):
        if protocol != "mcp":
            return True
        if workspace is None:
            workspace = self.loader.registry.get_driver_workspace(workspace_id)
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
            (
                "needs_review"
                if mode == "needs_review"
                else (
                    "configured"
                    if "configured" in statuses.values()
                    else "unused"
                )
            ),
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

    async def restore(self, marker):
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
            from .mcp.feature_gate import reconcile_mcp_features

            await reconcile_mcp_features(self.loader, PLUGIN_ID, record=record)
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

    def _explicit_descriptor(self, record):
        """Validate runtime ownership without requiring migration readiness."""
        state = self.loader.registry.describe_driver_protocol(
            "mcp",
            loader=self.loader,
        )
        if (
            self.loader.get_loaded_plugin(PLUGIN_ID) is not record
            or state is None
            or state.plugin_id != PLUGIN_ID
            or not state.active
        ):
            raise RuntimeError("MCP recovery runtime has changed")
        return state.registration

    def _publish_explicit_recovery(self, record):
        """Persist trusted explicit success before releasing admission."""
        _, off = self._current_settings()
        if off:
            raise RuntimeError("MCP is disabled or uninstalled")
        target = self.loader.find_installed_plugin_dir(PLUGIN_ID)
        if target is None or not same_location(target, record.source_path):
            raise ValueError("MCP recovery requires the installed source")
        # Reuse the installer's containment check for symlinks/junctions.
        self.loader._install_paths(PLUGIN_ID, target.parent)
        committed = has_install_commit(target, PLUGIN_ID)
        try:
            marker = _read_marker(self.marker_path)
        except ValueError:
            if not committed:
                raise
            marker = None
        if not committed:
            if (marker or {}).get("stage") in {"preparing", "files_committed"}:
                self._validate_origin(target, marker)
            elif (target / ORIGIN).exists() and not (marker or {}).get(
                "transaction",
            ):
                raise ValueError("Unowned incomplete installation")
            write_install_commit(target, PLUGIN_ID)
        if (
            automatic(marker) == "completed"
            and (marker or {}).get("stage", "completed") == "completed"
            and not marker.get("diagnostics")
        ):
            return marker
        return publish_marker(
            self.marker_path,
            marker,
            recover_invalid=True,
            automatic="completed",
            diagnostics=[],
            **({"stage": "completed"} if "stage" in (marker or {}) else {}),
        )

    async def reconcile_explicit(self, record=None):
        from .mcp.feature_gate import is_mcp_ready

        async with self.loader.plugin_lifecycle(PLUGIN_ID):
            current = self.loader.get_loaded_plugin(PLUGIN_ID)
            if record is not None and (
                not record.enabled or record.status != "active"
            ):
                return False
            if record is not None and record is not current:
                raise RuntimeError("MCP recovery record has changed")
            record = current
            if (
                record is None
                or not record.enabled
                or record.status != "active"
            ):
                return False
            self.loader.startup_blocked_plugins.add(PLUGIN_ID)
            descriptor = self._explicit_descriptor(record)
            try:
                marker = await run_sync_io(
                    self._publish_explicit_recovery,
                    record,
                )
            except Exception as exc:
                self._failed("publish explicit recovery", exc)
                raise
            _, off = await run_sync_io(self._current_settings)
            if off:
                raise RuntimeError("MCP is disabled or uninstalled")
            if self._explicit_descriptor(record) is not descriptor:
                raise RuntimeError("MCP recovery generation has changed")
            self.loader.startup_blocked_plugins.discard(PLUGIN_ID)
            self._result(marker)
            return is_mcp_ready(self.loader)

    async def _reconcile_live_workspaces(self, *, refresh=False):
        """Reconcile existing facades without starting agents."""
        _, off = await run_sync_io(self._current_settings)
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
            try:
                await service.activate_protocol("mcp")
            except Exception as exc:
                logger.warning(
                    "MCP service recovery failed in workspace %r: %s",
                    workspace.agent_id,
                    driver_error_diagnostic(exc),
                )

    async def prepare_for_use(self, workspace_id=None):
        """Prepare explicit demand without exposing coordinator bookkeeping."""
        from .mcp.feature_gate import is_mcp_ready

        if is_mcp_ready(self.loader, workspace_id):
            return True
        record = self.loader.get_loaded_plugin(PLUGIN_ID)
        if record is not None and record.status == "failed":
            return False
        previous = self.latest_result
        if previous is not None and previous.status in {
            "failed",
            "needs_review",
        }:
            return False
        try:
            await self.ensure_protocol("mcp")
        except Exception as exc:
            logger.warning(
                "Local MCP preparation failed; use official plugins: %s",
                driver_error_diagnostic(exc),
            )
            return False
        if workspace_id is not None:
            workspace = self.loader.registry.get_driver_workspace(workspace_id)
            if workspace is not None:
                await self.check_workspace(workspace)
        return is_mcp_ready(self.loader, workspace_id)

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
            except Exception as exc:
                self._failed("prepare runtime", exc)

    def _failed(self, stage, exc):
        logger.warning(
            "MCP setup failed during %s: %s",
            stage,
            driver_error_diagnostic(exc),
        )
        self.loader.startup_blocked_plugins.add(PLUGIN_ID)
        return self._result(
            None,
            status="failed",
            diagnostics=(_OFFLINE_FAILURE,),
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
            except Exception as exc:
                return self._failed("prepare startup", exc)

    async def _ensure_snapshot(self, snapshot):
        self.config_path = snapshot.config_path or self.config_path
        decision = classify_mcp_usage(snapshot)
        self.initial_evidence = {
            item.workspace_id: item for item in snapshot.workspaces
        }
        self.root_valid = "__root__" not in decision.workspace_statuses
        marker = await run_sync_io(_read_marker, self.marker_path)
        if marker is not None and (
            decision.status in {"needs_review", "explicit_off"}
            or not await run_sync_io(
                _legacy_review_marker,
                marker,
                snapshot,
            )
        ):
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
                automatic=(
                    "needs_review"
                    if decision.status == "needs_review"
                    else "completed"
                    if target
                    else "not_required"
                ),
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
        try:
            marker = await run_sync_io(
                publish_marker,
                self.marker_path,
                marker,
                automatic="attempted",
                workspaces=dict(decision.workspace_statuses),
            )
        except Exception as exc:
            return self._failed("write initial migration marker", exc)
        stage = "read bundled resource"
        try:
            source = get_optional_mcp_plugin_dir()
            _, manifest = await run_sync_io(
                self.loader.read_source_manifest,
                source,
            )
            if manifest.id != PLUGIN_ID:
                raise ValueError("Invalid optional MCP resource")
            digest = await run_sync_io(_digest, source)
            stage = "write migration marker"
            marker = await run_sync_io(
                publish_marker,
                self.marker_path,
                marker,
                transaction=uuid4().hex,
                digest=digest,
                stage="preparing",
            )
            stage = "read plugin settings"
            _, off = await run_sync_io(self._current_settings)
            if off:
                return self._result(marker, status="skipped")
            stage = "install bundled files"
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
            stage = "write migration marker"
            marker = await run_sync_io(
                publish_marker,
                self.marker_path,
                marker,
                stage="files_committed",
            )
            stage = "read plugin settings"
            row, off = await run_sync_io(self._current_settings)
            if off:
                return self._result(marker, status="skipped")
            stage = "load installed plugin"
            await self._load_installed(
                self.loader.plugin_dirs[0] / PLUGIN_ID,
                row,
                activate=False,
            )
            stage = "persist plugin settings"
            await run_sync_io(
                persist_plugin_settings,
                PLUGIN_ID,
                enabled=True,
                config_path=(
                    Path(self.config_path) if self.config_path else None
                ),
                refuse_disabled=True,
            )
            # Preserve the original order: intent commits before activation.
            self.loader.startup_blocked_plugins.discard(PLUGIN_ID)
            stage = "activate plugin"
            await self.loader.activate_plugin_unlocked(PLUGIN_ID)
            stage = "write migration marker"
            marker = await run_sync_io(
                publish_marker,
                self.marker_path,
                marker,
                stage="completed",
                automatic="completed",
            )
            return self._result(marker, status="installed")
        except Exception as exc:
            self._failed(stage, exc)
            try:
                marker = await run_sync_io(
                    publish_marker,
                    self.marker_path,
                    marker,
                    diagnostics=[_OFFLINE_FAILURE],
                )
            except Exception as marker_exc:
                return self._failed("write failure marker", marker_exc)
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
        row = _root_plugins(root).get(PLUGIN_ID)
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


def get_coordinator(loader=None):
    if loader is None:
        from ..plugins.registry import PluginRegistry

        registry = PluginRegistry()
        coordinator = registry.get_protocol_preparation()
        if coordinator is not None:
            return coordinator
        loader = registry.driver_protocol_loader("mcp", plugin_id=PLUGIN_ID)
        if loader is None:
            return None
    coordinator = getattr(loader, "protocol_coordinator", None)
    if coordinator is None:
        coordinator = MCPPluginCoordinator(loader)
        loader.protocol_coordinator = coordinator
        loader.registry.register_protocol_preparation(coordinator)
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
        try:
            result = await coordinator.restore(startup.marker)
        except Exception as exc:
            result = coordinator._failed("restore migration state", exc)
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
            (
                Path(current.config_path)
                if current.config_path
                else get_config_path()
            ),
        )
    except (OSError, ValueError):
        return result
    await loader.load_all_plugins(
        configs=_root_plugins(root),
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
        stage = "activate plugin"
        try:
            async with loader.plugin_lifecycle(PLUGIN_ID):
                await loader.activate_plugin_unlocked(PLUGIN_ID)
                stage = "read migration marker"
                marker = await run_sync_io(
                    _read_marker,
                    coordinator.marker_path,
                )
                if automatic(marker) == "not_required":
                    stage = "write migration marker"
                    marker = await run_sync_io(
                        publish_marker,
                        coordinator.marker_path,
                        marker,
                        automatic="completed",
                    )
                    coordinator._result(marker)
        except Exception as exc:
            # Optional Mail/ACP must not prevent ordinary agents from starting.
            result = coordinator._failed(stage, exc)
    return result
