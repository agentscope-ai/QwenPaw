# -*- coding: utf-8 -*-
"""Deployment-neutral runtime models for QwenPaw Hub."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class RuntimeState(str, Enum):
    """Observed lifecycle state of a managed runtime."""

    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    STOPPED = "stopped"
    FAILED = "failed"


class RuntimeStartPolicy(str, Enum):
    """Define who may start an intentionally stopped runtime."""

    OWNER_ALLOWED = "owner_allowed"
    ADMIN_ONLY = "admin_only"


@dataclass(frozen=True)
class RuntimeSpec:
    """Logical runtime request independent of its deployment provisioner."""

    runtime_id: str
    tenant_id: str
    owner_user_id: str
    provisioner: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimeRecord:
    """Persisted configuration and latest observed runtime state."""

    runtime_id: str
    tenant_id: str
    owner_user_id: str
    provisioner: str
    host: str
    port: int
    state: RuntimeState
    working_dir: Path
    secret_dir: Path
    backup_dir: Path
    log_file: Path
    pid: int | None = None
    desired_state: RuntimeState = RuntimeState.CREATED
    start_policy: RuntimeStartPolicy = RuntimeStartPolicy.OWNER_ALLOWED
    runtime_type: str = "qwenpaw"
    revision: int = 1
    created_at: str = ""
    updated_at: str = ""
    observed_at: str = ""
    last_error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""
        data = asdict(self)
        data["state"] = self.state.value
        data["desired_state"] = self.desired_state.value
        data["start_policy"] = self.start_policy.value
        for key in ("working_dir", "secret_dir", "backup_dir", "log_file"):
            data[key] = str(data[key])
        return data
