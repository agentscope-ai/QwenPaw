# -*- coding: utf-8 -*-
"""Runtime orchestration service for QwenPaw Pro."""

from __future__ import annotations

import re
import threading
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path

from .driver import RuntimeDriver
from .models import RuntimeRecord, RuntimeSpec, RuntimeState
from .registry import RuntimeRegistry

_RUNTIME_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$")


class RuntimeService:
    """Coordinate persistent metadata with deployment-specific drivers."""

    def __init__(
        self,
        *,
        root_dir: Path,
        registry: RuntimeRegistry,
        drivers: dict[str, RuntimeDriver],
        credential_provider: Callable[[RuntimeRecord], Mapping[str, str]],
    ) -> None:
        self.root_dir = root_dir.resolve()
        self.registry = registry
        self.drivers = dict(drivers)
        self.credential_provider = credential_provider
        self._lock_registry = threading.Lock()
        self._runtime_locks: dict[str, threading.RLock] = {}

    def create(self, spec: RuntimeSpec) -> RuntimeRecord:
        """Register a runtime and prepare its isolated data directories."""
        with self._lock_registry:
            return self._create_locked(spec)

    def _create_locked(self, spec: RuntimeSpec) -> RuntimeRecord:
        """Create a runtime while the lifecycle lock is held."""
        self._validate_identifier(spec.runtime_id, "runtime_id")
        self._validate_identifier(spec.tenant_id, "tenant_id")
        if spec.driver not in self.drivers:
            raise ValueError(f"Unknown runtime driver: {spec.driver}")
        if self.registry.get(spec.runtime_id) is not None:
            raise ValueError(f"Runtime already exists: {spec.runtime_id}")

        runtime_root = self._runtime_root(spec.runtime_id)
        record = RuntimeRecord(
            runtime_id=spec.runtime_id,
            tenant_id=spec.tenant_id,
            owner_user_id=spec.owner_user_id,
            driver=spec.driver,
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

    def get(self, runtime_id: str) -> RuntimeRecord:
        """Return a runtime or raise KeyError."""
        record = self.registry.get(runtime_id)
        if record is None:
            raise KeyError(runtime_id)
        return record

    def start(self, runtime_id: str) -> RuntimeRecord:
        """Start a runtime and persist either success or failure."""
        with self._runtime_lock(runtime_id):
            return self._start_locked(runtime_id)

    def _start_locked(self, runtime_id: str) -> RuntimeRecord:
        """Start a runtime while the lifecycle lock is held."""
        record = self.get(runtime_id)
        driver = self._driver(record)
        starting = self.registry.save(
            replace(record, state=RuntimeState.STARTING, last_error=None),
        )
        try:
            credentials = self.credential_provider(starting)
            running = driver.start(starting, credentials)
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
        """Stop a runtime through its configured driver."""
        with self._runtime_lock(runtime_id):
            record = self.get(runtime_id)
            stopped = self._driver(record).stop(record)
            return self.registry.save(stopped)

    def status(self, runtime_id: str) -> RuntimeRecord:
        """Refresh one runtime's observed state."""
        with self._runtime_lock(runtime_id):
            record = self.get(runtime_id)
            observed = self._driver(record).status(record)
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
        """Close all drivers and persist the resulting stopped states."""
        for driver in self.drivers.values():
            driver.close()
        for record in self.registry.list():
            if record.state in {
                RuntimeState.RUNNING,
                RuntimeState.STARTING,
            }:
                self.registry.save(
                    replace(record, state=RuntimeState.STOPPED, pid=None),
                )

    def security_level(self, driver_name: str) -> str:
        """Expose the security contract of a registered driver."""
        driver = self.drivers.get(driver_name)
        if driver is None:
            raise ValueError(f"Unknown runtime driver: {driver_name}")
        return driver.security_level

    def _driver(self, record: RuntimeRecord) -> RuntimeDriver:
        driver = self.drivers.get(record.driver)
        if driver is None:
            raise ValueError(f"Unknown runtime driver: {record.driver}")
        return driver

    def _runtime_root(self, runtime_id: str) -> Path:
        candidate = (self.root_dir / "runtimes" / runtime_id).resolve()
        expected_parent = (self.root_dir / "runtimes").resolve()
        if candidate.parent != expected_parent:
            raise ValueError(f"Runtime path escapes Pro root: {runtime_id}")
        return candidate

    def _runtime_lock(self, runtime_id: str) -> threading.RLock:
        with self._lock_registry:
            return self._runtime_locks.setdefault(
                runtime_id,
                threading.RLock(),
            )

    @staticmethod
    def _validate_identifier(value: str, field_name: str) -> None:
        if not _RUNTIME_ID_PATTERN.fullmatch(value):
            raise ValueError(
                f"Invalid {field_name}: use 1-64 letters, numbers, '.', "
                f"'_' or '-'",
            )
