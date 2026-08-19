# -*- coding: utf-8 -*-
"""Runtime orchestration service for QwenPaw Hub."""

from __future__ import annotations

import builtins
import re
import threading
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path

from .config import HubConfig
from .provisioner import (
    RuntimeProvisioner,
    RuntimeProvisionerAvailability,
    RuntimeProvisionerUnavailableError,
)
from .models import RuntimeRecord, RuntimeSpec, RuntimeState
from .registry import RuntimeRegistry

_RUNTIME_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$")


class RuntimeService:
    """Coordinate persistent metadata with deployment-specific provisioners."""

    def __init__(
        self,
        *,
        root_dir: Path,
        registry: RuntimeRegistry,
        provisioners: dict[str, RuntimeProvisioner],
        credential_provider: Callable[[RuntimeRecord], Mapping[str, str]],
        hub_config: HubConfig | None = None,
    ) -> None:
        self.root_dir = root_dir.resolve()
        self.registry = registry
        self.provisioners = dict(provisioners)
        self.credential_provider = credential_provider
        self.hub_config = hub_config or HubConfig()
        self.default_provisioner = self.hub_config.default_provisioner
        self.allowed_provisioners = self.hub_config.allowed_provisioners
        self._validate_provisioner_policy()
        self._lock_registry = threading.Lock()
        self._admission_lock = threading.Lock()
        self._runtime_locks: dict[str, threading.RLock] = {}
        self._provisioner_availability = self._preflight_provisioners()

    def create(self, spec: RuntimeSpec) -> RuntimeRecord:
        """Register a runtime and prepare its isolated data directories."""
        with self._lock_registry:
            return self._create_locked(spec)

    def _create_locked(self, spec: RuntimeSpec) -> RuntimeRecord:
        """Create a runtime while the lifecycle lock is held."""
        self._validate_identifier(spec.runtime_id, "runtime_id")
        self._validate_identifier(spec.tenant_id, "tenant_id")
        provisioner_name = spec.provisioner or self.default_provisioner
        if provisioner_name not in self.provisioners:
            raise ValueError(
                f"Unknown runtime provisioner: {provisioner_name}",
            )
        if (
            self.allowed_provisioners is not None
            and provisioner_name not in self.allowed_provisioners
        ):
            raise ValueError(
                f"Runtime provisioner is not allowed: {provisioner_name}",
            )
        self.require_provisioner_available(provisioner_name)
        if self.registry.get(spec.runtime_id) is not None:
            raise ValueError(f"Runtime already exists: {spec.runtime_id}")
        quota = self.hub_config.quota_for(spec.tenant_id)
        tenant_runtime_count = sum(
            record.tenant_id == spec.tenant_id
            for record in self.registry.list()
        )
        if (
            quota.max_runtimes is not None
            and tenant_runtime_count >= quota.max_runtimes
        ):
            raise ValueError(
                f"Tenant runtime limit reached: {quota.max_runtimes}",
            )

        runtime_root = self._runtime_root(spec.runtime_id)
        record = RuntimeRecord(
            runtime_id=spec.runtime_id,
            tenant_id=spec.tenant_id,
            owner_user_id=spec.owner_user_id,
            provisioner=provisioner_name,
            host=spec.host,
            port=spec.port,
            state=RuntimeState.CREATED,
            working_dir=runtime_root / "working",
            secret_dir=runtime_root / "secrets",
            backup_dir=runtime_root / "backups",
            log_file=runtime_root / "logs" / "app.log",
            metadata=dict(spec.metadata),
        )
        for path in (
            record.working_dir,
            record.secret_dir,
            record.backup_dir,
            record.log_file.parent,
        ):
            path.mkdir(parents=True, exist_ok=True)
        return self.registry.create(record)

    def list(self, owner_user_id: str | None = None) -> list[RuntimeRecord]:
        """Refresh and return all runtime records."""
        return [
            self.status(record.runtime_id)
            for record in self.registry.list(owner_user_id)
        ]

    def list_page(
        self,
        *,
        page: int,
        page_size: int,
        owner_user_id: str | None = None,
        query: str | None = None,
        state: RuntimeState | None = None,
        provisioner: str | None = None,
        owner: str | None = None,
    ) -> tuple[builtins.list[RuntimeRecord], int]:
        """Refresh only one filtered page of runtime records."""
        records, total = self.registry.list_page(
            page=page,
            page_size=page_size,
            owner_user_id=owner_user_id,
            query=query,
            state=state,
            provisioner=provisioner,
            owner=owner,
        )
        return (
            [self.status(record.runtime_id) for record in records],
            total,
        )

    def get(self, runtime_id: str) -> RuntimeRecord:
        """Return a runtime or raise KeyError."""
        record = self.registry.get(runtime_id)
        if record is None:
            raise KeyError(runtime_id)
        return record

    def start(self, runtime_id: str) -> RuntimeRecord:
        """Start a runtime and persist either success or failure."""
        with self._runtime_lock(runtime_id):
            with self._admission_lock:
                return self._start_locked(runtime_id)

    def _start_locked(self, runtime_id: str) -> RuntimeRecord:
        """Start a runtime while the lifecycle lock is held."""
        record = self.get(runtime_id)
        self.require_provisioner_available(record.provisioner)
        quota = self.hub_config.quota_for(record.tenant_id)
        running_count = sum(
            item.tenant_id == record.tenant_id
            and item.runtime_id != record.runtime_id
            and item.state
            in {
                RuntimeState.STARTING,
                RuntimeState.RUNNING,
            }
            for item in self.registry.list()
        )
        if (
            quota.max_running_runtimes is not None
            and running_count >= quota.max_running_runtimes
        ):
            raise ValueError(
                "Tenant running runtime limit reached: "
                f"{quota.max_running_runtimes}",
            )
        provisioner = self._provisioner(record)
        starting = self.registry.save(
            replace(
                record,
                desired_state=RuntimeState.RUNNING,
                state=RuntimeState.STARTING,
                last_error=None,
            ),
        )
        try:
            credentials = self.credential_provider(starting)
            running = provisioner.start(starting, credentials)
        except Exception as exc:
            self.registry.save(
                replace(
                    starting,
                    state=RuntimeState.FAILED,
                    pid=None,
                    last_error=str(exc),
                ),
            )
            raise
        return self.registry.save(running)

    def stop(self, runtime_id: str) -> RuntimeRecord:
        """Stop a runtime through its configured provisioner."""
        with self._runtime_lock(runtime_id):
            record = self.get(runtime_id)
            requested = replace(
                record,
                desired_state=RuntimeState.STOPPED,
            )
            stopped = self._provisioner(requested).stop(requested)
            return self.registry.save(stopped)

    def restart(self, runtime_id: str) -> RuntimeRecord:
        """Restart one runtime as an atomic lifecycle operation."""
        with self._runtime_lock(runtime_id):
            record = self.get(runtime_id)
            if record.state in {
                RuntimeState.STARTING,
                RuntimeState.RUNNING,
            }:
                requested = replace(
                    record,
                    desired_state=RuntimeState.STOPPED,
                )
                stopped = self._provisioner(requested).stop(requested)
                self.registry.save(stopped)
            with self._admission_lock:
                return self._start_locked(runtime_id)

    def status(self, runtime_id: str) -> RuntimeRecord:
        """Refresh one runtime's observed state."""
        with self._runtime_lock(runtime_id):
            record = self.get(runtime_id)
            observed = self._provisioner(record).status(record)
            if observed == record:
                return record
            return self.registry.save(observed)

    def delete(self, runtime_id: str) -> None:
        """Remove registration while deliberately retaining runtime data."""
        with self._runtime_lock(runtime_id):
            record = self.status(runtime_id)
            if record.state in {
                RuntimeState.RUNNING,
                RuntimeState.STARTING,
            }:
                raise ValueError(
                    f"Runtime must be stopped before deletion: {runtime_id}",
                )
            self.registry.delete(runtime_id)

    def close(self) -> None:
        """Close all provisioners and persist the resulting stopped states."""
        for provisioner in self.provisioners.values():
            provisioner.close()
        for record in self.registry.list():
            if record.state in {
                RuntimeState.RUNNING,
                RuntimeState.STARTING,
            }:
                self.registry.save(
                    replace(
                        record,
                        desired_state=RuntimeState.STOPPED,
                        state=RuntimeState.STOPPED,
                        pid=None,
                    ),
                )

    def security_level(self, provisioner_name: str) -> str:
        """Expose the security contract of a registered provisioner."""
        provisioner = self.provisioners.get(provisioner_name)
        if provisioner is None:
            raise ValueError(
                f"Unknown runtime provisioner: {provisioner_name}",
            )
        return provisioner.security_level

    def provisioner_statuses(self) -> dict[str, dict[str, object]]:
        """Return cached startup preflight results for every provisioner."""
        return {
            name: {
                "available": availability.available,
                "reason": availability.reason,
                "security_level": self.provisioners[name].security_level,
            }
            for name, availability in self._provisioner_availability.items()
        }

    def runtime_available(self) -> bool:
        """Return whether the configured default provisioner is safe to use."""
        availability = self._provisioner_availability[self.default_provisioner]
        return availability.available

    def require_provisioner_available(self, provisioner_name: str) -> None:
        """Reject execution after a provisioner preflight failure."""
        availability = self._provisioner_availability.get(provisioner_name)
        if availability is None:
            raise ValueError(
                f"Unknown runtime provisioner: {provisioner_name}",
            )
        if availability.available:
            return
        reason = availability.reason or "security preflight failed"
        raise RuntimeProvisionerUnavailableError(
            f"Runtime provisioner '{provisioner_name}' is unavailable: "
            f"{reason}",
        )

    def _provisioner(self, record: RuntimeRecord) -> RuntimeProvisioner:
        provisioner = self.provisioners.get(record.provisioner)
        if provisioner is None:
            raise ValueError(
                f"Unknown runtime provisioner: {record.provisioner}",
            )
        return provisioner

    def _preflight_provisioners(
        self,
    ) -> dict[str, RuntimeProvisionerAvailability]:
        """Probe all configured provisioners before accepting runtime work."""
        return {
            name: provisioner.preflight(
                self.root_dir / "preflight" / name,
            )
            for name, provisioner in self.provisioners.items()
        }

    def _runtime_root(self, runtime_id: str) -> Path:
        candidate = (self.root_dir / "runtimes" / runtime_id).resolve()
        expected_parent = (self.root_dir / "runtimes").resolve()
        if candidate.parent != expected_parent:
            raise ValueError(f"Runtime path escapes Hub root: {runtime_id}")
        return candidate

    def _runtime_lock(self, runtime_id: str) -> threading.RLock:
        with self._lock_registry:
            return self._runtime_locks.setdefault(
                runtime_id,
                threading.RLock(),
            )

    def _validate_provisioner_policy(self) -> None:
        """Fail startup when configuration names unavailable provisioners."""
        available = set(self.provisioners)
        if self.default_provisioner not in available:
            raise ValueError(
                "Unknown default runtime provisioner: "
                f"{self.default_provisioner}",
            )
        if self.allowed_provisioners is None:
            return
        unknown = sorted(self.allowed_provisioners - available)
        if unknown:
            raise ValueError(
                f"Unknown allowed runtime provisioners: {', '.join(unknown)}",
            )
        if self.default_provisioner not in self.allowed_provisioners:
            raise ValueError(
                "default_provisioner must be included in allowed_provisioners",
            )

    @staticmethod
    def _validate_identifier(value: str, field_name: str) -> None:
        if not _RUNTIME_ID_PATTERN.fullmatch(value):
            raise ValueError(
                f"Invalid {field_name}: use 1-64 letters, numbers, '.', "
                f"'_' or '-'",
            )
