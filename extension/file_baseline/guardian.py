# -*- coding: utf-8 -*-
"""Harness-facing guardian wrapper delegating to FileBaselineService."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .service import FileBaselineService


@dataclass(frozen=True)
class FileBaselineDriftAlert:
    path: str
    previous_sha256: str
    current_sha256: str
    detected_at: str


@dataclass(frozen=True)
class FileBaselineState:
    enabled: bool
    protected_paths: tuple[str, ...]
    alerts: tuple[FileBaselineDriftAlert, ...] = ()
    startup_scan_ran: bool = False


class FileBaselineGuardian:
    """Single-workspace guardian used by integration harness."""

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root
        self._service = FileBaselineService(workspace_root)

    def enable(self, protected_paths: tuple[str, ...]) -> FileBaselineState:
        self._service.enable_local(protected_paths)
        return self.scan()

    def scan(self) -> FileBaselineState:
        state = self._service.scan_local()
        alerts = tuple(
            FileBaselineDriftAlert(
                path=str(item.get("path") or ""),
                previous_sha256=str(item.get("approved_sha256") or ""),
                current_sha256=str(item.get("current_sha256") or ""),
                detected_at=str(item.get("detected_at") or ""),
            )
            for item in state.alerts
        )
        return FileBaselineState(
            enabled=state.enabled,
            protected_paths=state.protected_paths,
            alerts=alerts,
            startup_scan_ran=state.startup_scan_ran,
        )

    def restore(self, relative_path: str) -> bool:
        return self._service.restore_local(relative_path)

    def accept(self, relative_path: str) -> bool:
        return self._service.accept_local(relative_path)
