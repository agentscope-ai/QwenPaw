# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .adapter import DriftFinding, SoulGuardianAdapter
from .constants import (
    CONFIRM_ACCEPT_PHRASE,
    CONFIRM_REESTABLISH_PHRASE,
    CONFIRM_RESTORE_PHRASE,
    DEFAULT_PILOT_TARGETS,
)
from .drift_gate import should_skip_drift_emit
from .drift_store import DriftReviewStore
from .emitter import FileBaselineAlertEmitter
from .paths import drift_reviews_path
from .policy_builder import build_policy
from .settings_store import FileBaselineSettings, SettingsStore
from .sse_hub import FileBaselineSSEHub
from .watch_service import FileBaselineWatchService
from .write_context import file_baseline_maintenance_context
from .write_coordinator import FileBaselineWriteCoordinator
from .os_readonly import (
    apply_os_readonly_for_paths,
    apply_os_readonly_under,
    clear_os_readonly_for_paths,
    clear_os_readonly_under,
    set_os_readonly,
    clear_os_readonly,
    temporary_os_writable,
)
from .paths import file_baseline_root
from .frozen_store import sync_frozen_agent_paths, trust_anchors_path


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class FileBaselineState:
    enabled: bool
    protected_paths: tuple[str, ...]
    alerts: tuple[dict[str, Any], ...]
    startup_scan_ran: bool


class FileBaselineService:
    def __init__(
        self,
        working_dir: Path,
        *,
        adapter: SoulGuardianAdapter | None = None,
        emitter: FileBaselineAlertEmitter | None = None,
        settings_store: SettingsStore | None = None,
        sse_hub: FileBaselineSSEHub | None = None,
    ) -> None:
        self.working_dir = working_dir
        self.settings_store = settings_store or SettingsStore(working_dir)
        self.adapter = adapter or SoulGuardianAdapter()
        self.drift_store = DriftReviewStore(drift_reviews_path(working_dir))
        self.sse_hub = sse_hub or FileBaselineSSEHub()
        self.emitter = emitter or FileBaselineAlertEmitter(
            drift_store=self.drift_store,
            is_enabled=self.is_enabled,
            sse_publish=self.sse_hub.publish,
        )
        self.watch_service = FileBaselineWatchService(self)
        self.coordinator = FileBaselineWriteCoordinator(self)

    def is_enabled(self) -> bool:
        return self.settings_store.load().enabled

    def get_settings_payload(self) -> dict[str, Any]:
        settings = self.settings_store.load()
        agents_payload = []
        for agent_id in self.settings_store.list_agent_ids():
            agent_cfg = settings.agents.get(agent_id) or {}
            agents_payload.append(
                {
                    "agent_id": agent_id,
                    "protected_targets": agent_cfg.get("protected_targets"),
                    "workspace_rel": f"workspaces/{agent_id}",
                    "init_status": agent_cfg.get("init_status", "idle"),
                    "last_init_at": agent_cfg.get("last_init_at"),
                    "last_check_at": agent_cfg.get("last_check_at"),
                },
            )
        effective = self._aggregate_effective_paths(settings)
        return {
            **settings.to_dict(),
            "protected_paths": effective,
            "agents": agents_payload,
            "open_alert_count": self.drift_store.open_count(),
        }

    def get_integrity_projection(self) -> dict[str, Any]:
        settings = self.settings_store.load()
        protected_paths = (
            self._aggregate_effective_paths(settings)
            if settings.enabled
            else []
        )
        return {
            "file_baseline_enabled": settings.enabled,
            "protected_paths": protected_paths,
        }

    async def update_settings(
        self,
        *,
        enabled: bool | None = None,
        protected_targets: list[str] | None = None,
        confirmation_phrase: str | None = None,
    ) -> dict[str, Any]:
        settings = self.settings_store.load()
        current_enabled = settings.enabled

        if protected_targets is not None:
            settings = self.settings_store.update_protected_targets(
                settings,
                protected_targets,
            )
            self.settings_store.save(settings)
            if current_enabled:
                await self._refresh_all_agents(settings)
                self._apply_os_readonly_all(settings)
            return self.get_settings_payload()

        if enabled is None:
            return self.get_settings_payload()

        if enabled and not current_enabled:
            return await self._enable(settings, confirmation_phrase)

        if not enabled and current_enabled:
            return await self._disable(settings)

        return self.get_settings_payload()

    async def _enable(
        self,
        settings: FileBaselineSettings,
        confirmation_phrase: str | None,
    ) -> dict[str, Any]:
        if not settings.protected_targets:
            settings.protected_targets = list(DEFAULT_PILOT_TARGETS)

        if settings.baseline_cleared_at is not None:
            if confirmation_phrase != CONFIRM_REESTABLISH_PHRASE:
                raise PermissionError(
                    "Re-enable requires confirmReestablishFileBaselinePhrase",
                )

        settings.enabled = True
        settings.scan_status = "running"
        self.settings_store.save(settings)

        try:
            await self._refresh_all_agents(settings)
            settings = self.settings_store.load()
            settings.baseline_established = True
            settings.baseline_cleared_at = None
            settings.scan_status = "completed"
            settings.last_scan_at = _utc_now()
            settings.last_scan_drift_count = self.drift_store.open_count()
            self.settings_store.save(settings)
            self._apply_os_readonly_all(settings)
            await self.watch_service.start_all()
        except Exception:
            settings = self.settings_store.load()
            settings.enabled = False
            settings.scan_status = "failed"
            self.settings_store.save(settings)
            await self.watch_service.stop_all()
            self.settings_store.delete_runtime_state()
            raise

        return self.get_settings_payload()

    async def _disable(self, settings: FileBaselineSettings) -> dict[str, Any]:
        self._clear_os_readonly_all(settings)
        await self.watch_service.stop_all()
        await self.sse_hub.close_all()
        settings.enabled = False
        settings.baseline_cleared_at = _utc_now()
        settings.scan_status = None
        settings.last_scan_at = None
        settings.last_scan_drift_count = None
        self.settings_store.save(settings)
        self.settings_store.delete_runtime_state()
        return self.get_settings_payload()

    async def run_startup_scan(self) -> dict[str, Any]:
        settings = self.settings_store.load()
        if not settings.enabled:
            return {"skipped": True, "reason": "disabled"}

        settings.scan_status = "running"
        self.settings_store.save(settings)
        drift_count = 0
        try:
            drift_count = await self._check_all_agents(settings, provenance="startup_scan")
            settings = self.settings_store.load()
            settings.scan_status = "completed"
            settings.last_scan_at = _utc_now()
            settings.last_scan_drift_count = drift_count
            self.settings_store.save(settings)
            self._apply_os_readonly_all(settings)
            await self.watch_service.start_all()
        except Exception:
            settings = self.settings_store.load()
            settings.scan_status = "failed"
            self.settings_store.save(settings)
            raise

        return {
            "skipped": False,
            "drift_count": drift_count,
            "open_alert_count": self.drift_store.open_count(),
        }

    async def list_alerts(self) -> dict[str, Any]:
        settings = self.settings_store.load()
        scanning = settings.scan_status == "running"
        alerts = [review.to_dict() for review in self.drift_store.list_open()]
        return {
            "enabled": settings.enabled,
            "scanning": scanning,
            "alerts": alerts,
            "open_alert_count": len(alerts),
        }

    async def restore(
        self,
        *,
        alert_id: str,
        confirmation_phrase: str,
    ) -> dict[str, Any]:
        if confirmation_phrase != CONFIRM_RESTORE_PHRASE:
            return {"confirmed": False, "message": "confirmation phrase mismatch"}
        review = self._find_open_alert(alert_id)
        if review is None:
            return {"confirmed": False, "message": "alert not found"}
        workspace = self.settings_store.resolve_workspace(review.agent_id)
        state_dir = self.settings_store.agent_state(review.agent_id)
        target = workspace / review.path
        with file_baseline_maintenance_context():
            with temporary_os_writable([target] if target.is_file() else []):
                self.adapter.restore_file(
                    workspace_root=workspace,
                    state_dir=state_dir,
                    relative_path=review.path,
                    working_dir=self.working_dir,
                    agent_id=review.agent_id,
                )
        if target.is_file() and self.is_enabled():
            apply_os_readonly_for_paths(workspace, [review.path])
        if target.is_file():
            import hashlib

            current_sha = hashlib.sha256(target.read_bytes()).hexdigest()
            self.watch_service.suppress.register(
                agent_id=review.agent_id,
                path=review.path,
                sha256=current_sha,
                ttl_seconds=2.0,
            )
        self.drift_store.resolve(alert_id, status="restored")
        self.watch_service.clear_debounce(review.agent_id, review.path)
        await self.emitter.emit_alert_resolved(
            alert_id=alert_id,
            agent_id=review.agent_id,
            path=review.path,
            action="restore",
        )
        return {"confirmed": True, "alert_id": alert_id, "action": "restore"}

    async def accept(
        self,
        *,
        alert_id: str,
        confirmation_phrase: str,
    ) -> dict[str, Any]:
        if confirmation_phrase != CONFIRM_ACCEPT_PHRASE:
            return {"confirmed": False, "message": "confirmation phrase mismatch"}
        review = self._find_open_alert(alert_id)
        if review is None:
            return {"confirmed": False, "message": "alert not found"}
        workspace = self.settings_store.resolve_workspace(review.agent_id)
        state_dir = self.settings_store.agent_state(review.agent_id)
        with file_baseline_maintenance_context():
            self.adapter.approve_file(
                workspace_root=workspace,
                state_dir=state_dir,
                relative_path=review.path,
            )
            sync_frozen_agent_paths(
                self.working_dir,
                review.agent_id,
                workspace=workspace,
                state_dir=state_dir,
                rel_paths=[review.path],
            )
        self.drift_store.resolve(alert_id, status="accepted")
        self.watch_service.clear_debounce(review.agent_id, review.path)
        target = workspace / review.path
        if target.is_file():
            import hashlib

            current_sha = hashlib.sha256(target.read_bytes()).hexdigest()
            await self.emitter.emit_baseline_updated(
                agent_id=review.agent_id,
                path=review.path,
                new_sha256=current_sha,
            )
        await self.emitter.emit_alert_resolved(
            alert_id=alert_id,
            agent_id=review.agent_id,
            path=review.path,
            action="accept",
        )
        return {"confirmed": True, "alert_id": alert_id, "action": "accept"}

    def enable_local(self, protected_paths: tuple[str, ...]) -> None:
        """Direct enable for harness/tests (single default agent workspace)."""
        settings = FileBaselineSettings(
            enabled=True,
            protected_targets=list(protected_paths),
            baseline_established=False,
        )
        self.settings_store.save(settings)
        asyncio.run(self._refresh_all_agents(settings))
        settings = self.settings_store.load()
        settings.baseline_established = True
        settings.baseline_cleared_at = None
        settings.scan_status = "completed"
        settings.last_scan_at = _utc_now()
        settings.last_scan_drift_count = self.drift_store.open_count()
        self.settings_store.save(settings)
        self._apply_os_readonly_all(settings)

    def _apply_os_readonly_all(self, settings: FileBaselineSettings) -> None:
        if not settings.enabled:
            return
        for agent_id in self.settings_store.list_agent_ids():
            paths = self.settings_store.effective_paths(settings, agent_id)
            if not paths:
                continue
            workspace = self.settings_store.resolve_workspace(agent_id)
            apply_os_readonly_for_paths(workspace, paths)
        integrity_root = file_baseline_root(self.working_dir)
        frozen_root = integrity_root / "frozen"
        if frozen_root.is_dir():
            apply_os_readonly_under(frozen_root)
        anchors = trust_anchors_path(self.working_dir)
        if anchors.is_file():
            set_os_readonly(anchors)

    def _clear_os_readonly_all(self, settings: FileBaselineSettings) -> None:
        for agent_id in self.settings_store.list_agent_ids():
            paths = self.settings_store.effective_paths(settings, agent_id)
            if not paths:
                continue
            workspace = self.settings_store.resolve_workspace(agent_id)
            clear_os_readonly_for_paths(workspace, paths)
        integrity_root = file_baseline_root(self.working_dir)
        frozen_root = integrity_root / "frozen"
        if frozen_root.is_dir():
            clear_os_readonly_under(frozen_root)
        anchors = trust_anchors_path(self.working_dir)
        if anchors.is_file():
            clear_os_readonly(anchors)

    def scan_local(self) -> FileBaselineState:
        settings = self.settings_store.load()
        if not settings.enabled:
            return FileBaselineState(
                enabled=False,
                protected_paths=(),
                alerts=(),
                startup_scan_ran=False,
            )
        drift_count = asyncio.run(
            self._check_all_agents(settings, provenance="startup_scan"),
        )
        alerts = tuple(item.to_dict() for item in self.drift_store.list_open())
        effective = tuple(self._aggregate_effective_paths(settings))
        return FileBaselineState(
            enabled=True,
            protected_paths=effective,
            alerts=alerts,
            startup_scan_ran=True,
        )

    def restore_local(self, relative_path: str) -> bool:
        settings = self.settings_store.load()
        if not settings.enabled:
            return False
        agent_id = "default"
        workspace = self.settings_store.resolve_workspace(agent_id)
        state_dir = self.settings_store.agent_state(agent_id)
        target = workspace / relative_path
        try:
            with temporary_os_writable([target] if target.is_file() else []):
                self.adapter.restore_file(
                    workspace_root=workspace,
                    state_dir=state_dir,
                    relative_path=relative_path,
                    working_dir=self.working_dir,
                    agent_id=agent_id,
                )
        except RuntimeError:
            return False
        if target.is_file() and self.is_enabled():
            apply_os_readonly_for_paths(workspace, [relative_path])
        for review in self.drift_store.list_open():
            if review.path == relative_path:
                self.drift_store.resolve(review.alert_id, status="restored")
        return True

    def accept_local(self, relative_path: str) -> bool:
        settings = self.settings_store.load()
        if not settings.enabled:
            return False
        agent_id = "default"
        workspace = self.settings_store.resolve_workspace(agent_id)
        state_dir = self.settings_store.agent_state(agent_id)
        try:
            with file_baseline_maintenance_context():
                self.adapter.approve_file(
                    workspace_root=workspace,
                    state_dir=state_dir,
                    relative_path=relative_path,
                )
                sync_frozen_agent_paths(
                    self.working_dir,
                    agent_id,
                    workspace=workspace,
                    state_dir=state_dir,
                    rel_paths=[relative_path],
                )
        except RuntimeError:
            return False
        for review in self.drift_store.list_open():
            if review.path == relative_path:
                self.drift_store.resolve(review.alert_id, status="accepted")
        return True

    async def _refresh_all_agents(
        self,
        settings: FileBaselineSettings,
        *,
        provenance: str = "startup_scan",
    ) -> int:
        drift_count = 0
        for agent_id in self.settings_store.list_agent_ids():
            drift_count += await self._init_and_check_agent(
                settings,
                agent_id,
                provenance=provenance,
            )
        return drift_count

    async def _check_all_agents(
        self,
        settings: FileBaselineSettings,
        *,
        provenance: str,
    ) -> int:
        drift_count = 0
        for agent_id in self.settings_store.list_agent_ids():
            drift_count += await self._check_agent(settings, agent_id, provenance=provenance)
        return drift_count

    async def _init_and_check_agent(
        self,
        settings: FileBaselineSettings,
        agent_id: str,
        *,
        provenance: str,
    ) -> int:
        paths = self.settings_store.effective_paths(settings, agent_id)
        if not paths:
            return 0
        workspace = self.settings_store.resolve_workspace(agent_id)
        state_dir = self.settings_store.agent_state(agent_id)
        self.settings_store.ensure_protected_files(workspace, paths)
        policy = build_policy(paths, workspace_root=workspace)
        with file_baseline_maintenance_context():
            self.adapter.write_policy(state_dir, policy)
            await asyncio.to_thread(
                self.adapter.init,
                workspace_root=workspace,
                state_dir=state_dir,
            )
            sync_frozen_agent_paths(
                self.working_dir,
                agent_id,
                workspace=workspace,
                state_dir=state_dir,
                rel_paths=paths,
            )
        agent_cfg = settings.agents.setdefault(agent_id, {})
        agent_cfg["init_status"] = "ready"
        agent_cfg["last_init_at"] = _utc_now()
        self.settings_store.save(settings)
        return await self._check_agent(settings, agent_id, provenance=provenance)

    async def _check_agent(
        self,
        settings: FileBaselineSettings,
        agent_id: str,
        *,
        provenance: str,
    ) -> int:
        paths = self.settings_store.effective_paths(settings, agent_id)
        if not paths:
            return 0
        workspace = self.settings_store.resolve_workspace(agent_id)
        state_dir = self.settings_store.agent_state(agent_id)
        drifts, _rc = await asyncio.to_thread(
            self.adapter.check_no_restore,
            workspace_root=workspace,
            state_dir=state_dir,
        )
        agent_cfg = settings.agents.setdefault(agent_id, {})
        agent_cfg["last_check_at"] = _utc_now()
        self.settings_store.save(settings)
        emitted = 0
        for drift in drifts:
            if drift.error:
                continue
            if should_skip_drift_emit(
                approved_sha256=drift.approved_sha256,
                current_sha256=drift.current_sha256,
                agent_id=agent_id,
                rel_path=drift.path,
                provenance=provenance,
            ):
                continue
            await self.emitter.emit_drift(
                agent_id=agent_id,
                path=drift.path,
                approved_sha256=drift.approved_sha256,
                current_sha256=drift.current_sha256,
                provenance=provenance,
                patch_path=drift.patch_path,
            )
            emitted += 1
        return emitted

    async def _emit_drift_for_path(
        self,
        settings: FileBaselineSettings,
        agent_id: str,
        rel_path: str,
        *,
        provenance: str,
    ) -> int:
        workspace = self.settings_store.resolve_workspace(agent_id)
        state_dir = self.settings_store.agent_state(agent_id)
        drifts, _rc = await asyncio.to_thread(
            self.adapter.check_no_restore,
            workspace_root=workspace,
            state_dir=state_dir,
        )
        emitted = 0
        for drift in drifts:
            if drift.error or drift.path != rel_path:
                continue
            if should_skip_drift_emit(
                approved_sha256=drift.approved_sha256,
                current_sha256=drift.current_sha256,
                agent_id=agent_id,
                rel_path=rel_path,
                provenance=provenance,
            ):
                continue
            await self.emitter.emit_drift(
                agent_id=agent_id,
                path=drift.path,
                approved_sha256=drift.approved_sha256,
                current_sha256=drift.current_sha256,
                provenance=provenance,
                patch_path=drift.patch_path,
            )
            emitted += 1
        return emitted

    async def stream_events(self, *, enabled_only: bool = True):
        if enabled_only and not self.is_enabled():
            yield {"type": "disabled"}
            return
        yield {"type": "connected"}
        async for event in self.sse_hub.subscribe():
            yield event

    def _aggregate_effective_paths(self, settings: FileBaselineSettings) -> list[str]:
        paths: list[str] = []
        for agent_id in self.settings_store.list_agent_ids():
            for path in self.settings_store.effective_paths(settings, agent_id):
                if path not in paths:
                    paths.append(path)
        return paths

    def _find_open_alert(self, alert_id: str):
        for review in self.drift_store.list_open():
            if review.alert_id == alert_id:
                return review
        return None
