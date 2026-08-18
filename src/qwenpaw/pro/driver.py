# -*- coding: utf-8 -*-
"""Runtime driver contract used by the QwenPaw Pro control plane."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .models import RuntimeRecord


@dataclass(frozen=True)
class RuntimeDriverAvailability:
    """Describe whether a runtime driver can enforce its security boundary."""

    available: bool
    reason: str | None = None


class RuntimeDriverUnavailableError(RuntimeError):
    """Raised when a runtime driver cannot enforce safe execution."""


class RuntimeDriver(ABC):
    """Manage runtime lifecycle without exposing deployment internals."""

    name: str
    security_level: str

    @abstractmethod
    def preflight(self, root_dir: Path) -> RuntimeDriverAvailability:
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
        """Release all processes or connections owned by this driver."""
