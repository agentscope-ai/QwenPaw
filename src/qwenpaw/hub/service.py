# -*- coding: utf-8 -*-
"""Runtime orchestration service for QwenPaw Hub."""

from __future__ import annotations

import builtins
import re
import threading
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path

from ..utils.http import is_loopback_host
from .config import HubConfig
from .provisioner import (
    RuntimeProvisioner,
    RuntimeProvisionerAvailability,
    RuntimeProvisionerUnavailableError,
)
from .models import (
    RuntimeRecord,
    RuntimeSpec,
    RuntimeStartPolicy,
    RuntimeState,
)
from .registry import RuntimeRegistry

_RUNTIME_ID_PATTERN = re.compile(
    r"^[a-z0-9](?:[a-z0-9_.-]{0,62}[a-z0-9_-])?$",
)
_WINDOWS_RESERVED_NAMES = {
    "aux",
    "con",
    "nul",
    "prn",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


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
        self._validate_provisioner_policy()
        self._configure_provisioners()
        self._lock_registry = threading.Lock()
        self._admission_lock = threading.Lock()
        self._runtime_locks: dict[str, threading.RLock] = {}
        self._provisioner_availability = self._preflight_provisioners()

    def create(self, spec: RuntimeSpec) -> RuntimeRecord:
        """Register a runtime and prepare its isolated data directories."""
        with self._lock_registry:
            return self._create_locked(spec)

    def apply_config(self, config: HubConfig) -> None:
        """Apply validated admission and provisioner policy immediately."""
        with self._lock_registry, self._admission_lock:
            previous = (
                self.hub_config,
                self.default_provisioner,
            )
            self.hub_config = config
            self.default_provisioner = config.default_provisioner
            try:
                self._validate_provisioner_policy()
                self._configure_provisioners()
            except ValueError:
                (
                    self.hub_config,
                    self.default_provisioner,
                ) = previous
                raise

    def _create_locked(self, spec: RuntimeSpec) -> RuntimeRecord:
        """Create a runtime while the lifecycle lock is held."""
        self._validate_identifier(spec.runtime_id, "runtime_id")
        self._validate_identifier(spec.tenant_id, "tenant_id")
        if spec.provisioner and spec.provisioner != self.default_provisioner:
            raise ValueError(
                "Runtime provisioner is controlled by the administrator.",
            )
        provisioner_name = self.default_provisioner
        if provisioner_name not in self.provisioners:
            raise ValueError(
                f"Unknown runtime provisioner: {provisioner_name}",
            )
        self.require_provisioner_available(provisioner_name)
        provisioner = self.provisioners[provisioner_name]
        metadata = dict(spec.metadata)
        metadata.pop(provisioner_name, None)
        normalized_config = provisioner.validate_config({})
        if normalized_config:
            metadata[provisioner_name] = normalized_config
        if self.registry.get(spec.runtime_id) is not None:
            raise ValueError(f"Runtime already exists: {spec.runtime_id}")
        if any(
            record.tenant_id == spec.tenant_id
            for record in self.registry.list()
        ):
            raise ValueError(
                f"Tenant already has a runtime: {spec.tenant_id}",
            )

        runtime_root = self._runtime_root(spec.runtime_id)
        record = RuntimeRecord(
            runtime_id=spec.runtime_id,
            tenant_id=spec.tenant_id,
            owner_user_id=spec.owner_user_id,
            provisioner=provisioner_name,
            host="127.0.0.1",
            port=0,
            state=RuntimeState.CREATED,
            working_dir=runtime_root / "working",
            secret_dir=runtime_root / "secrets",
            backup_dir=runtime_root / "backups",
            log_file=runtime_root / "logs" / "app.log",
            metadata=metadata,
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
        if not is_loopback_host(record.host):
            raise ValueError("Managed runtime host must be loopback-only.")
        self.require_provisioner_available(record.provisioner)
        capacity = self.hub_config.capacity
        running_count = sum(
            item.runtime_id != record.runtime_id
            and item.state
            in {
                RuntimeState.STARTING,
                RuntimeState.RUNNING,
            }
            for item in self.registry.list()
        )
        if (
            capacity.max_running_runtimes is not None
            and running_count >= capacity.max_running_runtimes
        ):
            raise ValueError(
                "Hub running runtime limit reached: "
                f"{capacity.max_running_runtimes}",
            )
        provisioner = self._provisioner(record)
        starting = self.registry.save(
            replace(
                record,
                desired_state=RuntimeState.RUNNING,
                start_policy=RuntimeStartPolicy.OWNER_ALLOWED,
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

    def stop(
        self,
        runtime_id: str,
        *,
        start_policy: RuntimeStartPolicy = RuntimeStartPolicy.OWNER_ALLOWED,
    ) -> RuntimeRecord:
        """Stop a runtime through its configured provisioner."""
        with self._runtime_lock(runtime_id):
            record = self.get(runtime_id)
            requested = replace(
                record,
                desired_state=RuntimeState.STOPPED,
                start_policy=start_policy,
            )
            stopped = self._provisioner(requested).stop(requested)
            return self.registry.save(stopped)

    def restart(
        self,
        runtime_id: str,
        *,
        owner_initiated: bool = False,
    ) -> RuntimeRecord:
        """Restart one runtime with the current administrator policy."""
        with self._runtime_lock(runtime_id), self._admission_lock:
            record = self.get(runtime_id)
            if (
                owner_initiated
                and record.start_policy is RuntimeStartPolicy.ADMIN_ONLY
            ):
                raise PermissionError(
                    "Runtime start is restricted by an administrator.",
                )
            provisioner_name, metadata = self._current_runtime_policy(record)
            if record.state in {
                RuntimeState.STARTING,
                RuntimeState.RUNNING,
            }:
                requested = replace(
                    record,
                    desired_state=RuntimeState.STOPPED,
                )
                stopped = self._provisioner(requested).stop(requested)
                record = self.registry.save(stopped)
            reconciled = replace(
                record,
                provisioner=provisioner_name,
                host=(
                    "127.0.0.1"
                    if provisioner_name != record.provisioner
                    else record.host
                ),
                port=(
                    0
                    if provisioner_name != record.provisioner
                    else record.port
                ),
                pid=None,
                last_error=None,
                metadata=metadata,
            )
            if reconciled != record:
                self.registry.save(reconciled)
            return self._start_locked(runtime_id)

    def rebuild(self, runtime_id: str) -> RuntimeRecord:
        """Recreate a Docker runtime with the current global image policy."""
        with self._runtime_lock(runtime_id), self._admission_lock:
            record = self.get(runtime_id)
            if record.provisioner != "docker":
                raise ValueError("Only Docker runtimes can be rebuilt.")
            if record.state in {
                RuntimeState.STARTING,
                RuntimeState.RUNNING,
            }:
                record = self._provisioner(record).stop(record)
            metadata = dict(record.metadata)
            metadata["docker"] = self.provisioners["docker"].validate_config(
                {},
            )
            self.registry.save(
                replace(
                    record,
                    state=RuntimeState.STOPPED,
                    desired_state=RuntimeState.RUNNING,
                    metadata=metadata,
                    last_error=None,
                ),
            )
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

    def _current_runtime_policy(
        self,
        record: RuntimeRecord,
    ) -> tuple[str, dict[str, object]]:
        """Resolve backend metadata from the current administrator policy."""
        provisioner_name = self.default_provisioner
        self.require_provisioner_available(provisioner_name)
        provisioner = self.provisioners[provisioner_name]
        metadata = dict(record.metadata)
        for name in self.provisioners:
            metadata.pop(name, None)
        normalized_config = provisioner.validate_config({})
        if normalized_config:
            metadata[provisioner_name] = normalized_config
        return provisioner_name, metadata

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
                "Unknown runtime provisioner: " f"{self.default_provisioner}",
            )

    def _configure_provisioners(self) -> None:
        """Apply current Hub settings to every registered provisioner."""
        docker_provisioner = self.provisioners.get("docker")
        if docker_provisioner is not None:
            docker_provisioner.configure(
                self.hub_config.runtime.docker.model_dump(),
            )

    @staticmethod
    def _validate_identifier(value: str, field_name: str) -> None:
        windows_basename = value.split(".", 1)[0]
        if (
            not _RUNTIME_ID_PATTERN.fullmatch(value)
            or windows_basename in _WINDOWS_RESERVED_NAMES
        ):
            raise ValueError(
                f"Invalid {field_name}: use 1-64 lowercase ASCII letters, "
                "numbers, '.', '_' or '-', without a trailing dot or "
                "Windows reserved name",
            )
