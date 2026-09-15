# -*- coding: utf-8 -*-
"""Runtime provisioner contract used by the QwenPaw Hub control plane."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import httpx

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

    def model_endpoint(self, port: int) -> str:
        """Resolve the Hub model listener from this runtime's network."""
        if not port:
            raise RuntimeError("Hub model listener is not running")
        return f"http://127.0.0.1:{port}"

    @staticmethod
    def verify_model_connection(
        record: RuntimeRecord,
        credentials: Mapping[str, str],
    ) -> None:
        """Require an authenticated round trip from the launched runtime."""
        if not credentials.get("QWENPAW_HUB_MODEL_TOKEN"):
            return
        try:
            with httpx.Client(timeout=15, trust_env=False) as client:
                response = client.get(
                    f"http://{record.host}:{record.port}"
                    f"/api/models/hub-status",
                    headers={
                        "X-QwenPaw-Runtime-Token": credentials[
                            "QWENPAW_RUNTIME_INTERNAL_TOKEN"
                        ],
                    },
                )
                response.raise_for_status()
                if response.json().get("connected") is not True:
                    raise ValueError("Model connection was not verified")
        except (httpx.HTTPError, ValueError) as exc:
            raise RuntimeError(
                "Runtime could not reach the Hub model service. "
                "Check the runtime image and host network access.",
            ) from exc

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
