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
from .drift_store import DriftReviewStore
from .emitter import PersonaAlertEmitter
from .paths import drift_reviews_path
from .policy_builder import build_policy
from .settings_store import PersonaSettings, SettingsStore
from .sse_hub import PersonaSSEHub
from .watch_service import PersonaWatchService
from .write_context import persona_maintenance_context
from .write_coordinator import PersonaWriteCoordinator


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class PersonaBaselineState:
    enabled: bool
    protected_paths: tuple[str, ...]
    alerts: tuple[dict[str, Any], ...]
    startup_scan_ran: bool


class PersonaBaselineService:
    def __init__(
        self,
        working_dir: Path,
        *,
        adapter: SoulGuardianAdapter | None = None,
        emitter: PersonaAlertEmitter | None = None,
        settings_store: SettingsStore | None = None,
        sse_hub: PersonaSSEHub | None = None,
    ) -> None:
        self.working_dir = working_dir
        self.settings_store = settings_store or SettingsStore(working_dir)
        self.adapter = adapter or SoulGuardianAdapter()
        self.drift_store = DriftReviewStore(drift_reviews_path(working_dir))
        self.sse_hub = sse_hub or PersonaSSEHub()
        self.emitter = emitter or PersonaAlertEmitter(
            drift_store=self.drift_store,
            is_enabled=self.is_enabled,
            sse_publish=self.sse_hub.publish,
        )
        self.watch_service = PersonaWatchService(self)
        self.coordinator = PersonaWriteCoordinator(self)

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
            "persona_protection_enabled": settings.enabled,
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

        if protected_targets is not None and not current_enabled and enabled is not False:
            raise ValueError(
                "Cannot change protected_targets while persona protection is disabled",
            )

        if protected_targets is not None and current_enabled:
            settings = self.settings_store.update_protected_targets(
                settings,
                protected_targets,
            )
            self.settings_store.save(settings)
            await self._refresh_all_agents(settings)
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
        settings: PersonaSettings,
        confirmation_phrase: str | None,
    ) -> dict[str, Any]:
        if not settings.protected_targets:
            settings.protected_targets = list(DEFAULT_PILOT_TARGETS)

        if settings.baseline_cleared_at is not None:
            if confirmation_phrase != CONFIRM_REESTABLISH_PHRASE:
                raise PermissionError(
                    "Re-enable requires confirmReestablishBaselinePhrase",
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

    async def _disable(self, settings: PersonaSettings) -> dict[str, Any]:
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
        with persona_maintenance_context():
            self.adapter.restore_file(
                workspace_root=workspace,
                state_dir=state_dir,
                relative_path=review.path,
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
        with persona_maintenance_context():
            self.adapter.approve_file(
                workspace_root=workspace,
                state_dir=state_dir,
                relative_path=review.path,
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
        settings = PersonaSettings(
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

    def scan_local(self) -> PersonaBaselineState:
        settings = self.settings_store.load()
        if not settings.enabled:
            return PersonaBaselineState(
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
        return PersonaBaselineState(
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
        try:
            self.adapter.restore_file(
                workspace_root=workspace,
                state_dir=state_dir,
                relative_path=relative_path,
            )
        except RuntimeError:
            return False
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
            self.adapter.approve_file(
                workspace_root=workspace,
                state_dir=state_dir,
                relative_path=relative_path,
            )
        except RuntimeError:
            return False
        for review in self.drift_store.list_open():
            if review.path == relative_path:
                self.drift_store.resolve(review.alert_id, status="accepted")
        return True

    async def _refresh_all_agents(
        self,
        settings: PersonaSettings,
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
        settings: PersonaSettings,
        *,
        provenance: str,
    ) -> int:
        drift_count = 0
        for agent_id in self.settings_store.list_agent_ids():
            drift_count += await self._check_agent(settings, agent_id, provenance=provenance)
        return drift_count

    async def _init_and_check_agent(
        self,
        settings: PersonaSettings,
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
        with persona_maintenance_context():
            self.adapter.write_policy(state_dir, policy)
            await asyncio.to_thread(
                self.adapter.init,
                workspace_root=workspace,
                state_dir=state_dir,
            )
        agent_cfg = settings.agents.setdefault(agent_id, {})
        agent_cfg["init_status"] = "ready"
        agent_cfg["last_init_at"] = _utc_now()
        self.settings_store.save(settings)
        return await self._check_agent(settings, agent_id, provenance=provenance)

    async def _check_agent(
        self,
        settings: PersonaSettings,
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
        settings: PersonaSettings,
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

    def _aggregate_effective_paths(self, settings: PersonaSettings) -> list[str]:
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
