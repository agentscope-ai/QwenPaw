# -*- coding: utf-8 -*-
"""Runtime provisioner contract used by the QwenPaw Hub control plane."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .models import RuntimeRecord


@dataclass(frozen=True)
class RuntimeProvisionerAvailability:
    """Describe whether a provisioner can enforce its security boundary."""

    available: bool
    reason: str | None = None


class RuntimeProvisionerUnavailableError(RuntimeError):
    """Raised when a runtime provisioner cannot enforce safe execution."""


class RuntimeProvisioner(ABC):
    """Manage runtime lifecycle without exposing deployment internals."""

    name: str
    security_level: str

    def configure(self, config: Mapping[str, object]) -> None:
        """Apply validated backend settings without restarting the Hub."""

    def validate_config(self, value: object) -> dict[str, object]:
        """Normalize one runtime's backend-specific configuration."""
        if value not in ({}, None):
            raise ValueError(
                f"Runtime provisioner '{self.name}' has no config",
            )
        return {}

    @abstractmethod
    def preflight(self, root_dir: Path) -> RuntimeProvisionerAvailability:
        """Probe the real runtime boundary without launching QwenPaw."""

    @abstractmethod
    def start(
        self,
        record: RuntimeRecord,
        credentials: Mapping[str, str],
    ) -> RuntimeRecord:
        """Start a runtime and return its latest state."""

    @abstractmethod
    def stop(self, record: RuntimeRecord) -> RuntimeRecord:
        """Stop a runtime and return its latest state."""

    @abstractmethod
    def status(self, record: RuntimeRecord) -> RuntimeRecord:
        """Observe a runtime without changing its desired state."""

    @abstractmethod
    def close(self) -> None:
        """Release all processes or connections owned by this provisioner."""
