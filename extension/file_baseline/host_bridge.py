# -*- coding: utf-8 -*-
"""Host wiring for File Baseline Protection inside the extension tree."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from functools import lru_cache
from pathlib import Path

from qwenpaw.constant import WORKING_DIR
from qwenpaw.security.integrity_protection import (
    IntegrityProtectionSettings,
    FileBaselineState as NativeFileBaselineState,
    FileBaselineDriftAlert as NativeFileBaselineDriftAlert,
)

from .constants import (
    CONFIRM_ACCEPT_PHRASE,
    CONFIRM_REESTABLISH_PHRASE,
    CONFIRM_RESTORE_PHRASE,
)
from .guardian import FileBaselineGuardian as ExtensionFileBaselineGuardian
from .guardian import FileBaselineState as ExtensionFileBaselineState
from .guardian import FileBaselineDriftAlert as ExtensionFileBaselineDriftAlert
from .service import FileBaselineService
from .sse_hub import FileBaselineSSEHub
from .agent_write import GuardedWriteOutcome
from .agent_write import try_guarded_agent_file_write as _try_guarded_agent_file_write
from .command_guard import GuardedCommandOutcome
from .command_guard import (
    try_guarded_python_code as _try_guarded_python_code,
)
from .command_guard import (
    try_guarded_shell_command as _try_guarded_shell_command,
)
from .operator_write import (
    try_guarded_operator_file_write as _try_guarded_operator_file_write,
)
from .workspace_browse import browse_workspace_protectable_files


def _wire_emitter(service: FileBaselineService) -> None:
    service.emitter.sse_publish = service.sse_hub.publish


@lru_cache(maxsize=1)
def get_file_baseline_service(working_dir: Path | None = None) -> FileBaselineService:
    root = working_dir or WORKING_DIR
    service = FileBaselineService(root)
    _wire_emitter(service)
    return service


def get_integrity_settings_projection() -> IntegrityProtectionSettings:
    base = IntegrityProtectionSettings()
    projection = get_file_baseline_service().get_integrity_projection()
    return IntegrityProtectionSettings(
        file_baseline_enabled=projection["file_baseline_enabled"],
        health_check_enabled=base.health_check_enabled,
        rule_integrity_check_passive=base.rule_integrity_check_passive,
        protected_paths=tuple(projection["protected_paths"]),
        menus=base.menus,
    )


async def run_startup_scan_if_enabled() -> dict:
    service = get_file_baseline_service()
    if not service.is_enabled():
        return {"skipped": True, "reason": "disabled"}
    return await service.run_startup_scan()


async def notify_file_saved(
    agent_id: str,
    absolute_path: str | Path,
    provenance: str,
) -> None:
    service = get_file_baseline_service()
    if not service.is_enabled():
        return
    await service.coordinator.on_file_saved(
        agent_id=agent_id,
        absolute_path=absolute_path,
        provenance=provenance,
    )


async def try_guarded_agent_file_write(
    *,
    absolute_path: str,
    content: str,
    tool_name: str,
    operation: str = "write",
    encoding: str = "utf-8",
) -> GuardedWriteOutcome:
    """Proposal → approval → atomic commit for persona-protected agent writes."""
    service = get_file_baseline_service()
    return await _try_guarded_agent_file_write(
        service,
        absolute_path=absolute_path,
        content=content,
        tool_name=tool_name,
        operation=operation,
        encoding=encoding,
    )


async def try_guarded_operator_file_write(
    *,
    absolute_path: str,
    content: str,
    agent_id: str,
    encoding: str = "utf-8",
) -> GuardedWriteOutcome:
    service = get_file_baseline_service()
    return await _try_guarded_operator_file_write(
        service,
        absolute_path=absolute_path,
        content=content,
        agent_id=agent_id,
        encoding=encoding,
    )


async def try_guarded_shell_command(
    *,
    command: str,
    cwd: Path | None,
    execute_fn,
) -> GuardedCommandOutcome:
    service = get_file_baseline_service()
    return await _try_guarded_shell_command(
        service,
        command=command,
        cwd=cwd,
        execute_fn=execute_fn,
    )


async def try_guarded_python_code(
    *,
    code: str,
    execute_fn,
) -> GuardedCommandOutcome:
    service = get_file_baseline_service()
    return await _try_guarded_python_code(
        service,
        code=code,
        execute_fn=execute_fn,
    )


async def stream_file_baseline_events(request) -> AsyncIterator[str]:
    service = get_file_baseline_service()
    if not service.is_enabled():
        yield FileBaselineSSEHub.format_sse({"type": "disabled"})
        return

    async for event in service.stream_events():
        if await request.is_disconnected():
            break
        yield FileBaselineSSEHub.format_sse(event)
        await asyncio.sleep(0)


class FileBaselineGuardian:
    """Re-export harness API while delegating to extension implementation."""

    def __init__(self, workspace_root: Path, state_dir: Path | None = None) -> None:
        del state_dir
        self._inner = ExtensionFileBaselineGuardian(workspace_root)

    def enable(self, protected_paths: tuple[str, ...]) -> NativeFileBaselineState:
        state = self._inner.enable(protected_paths)
        return _to_native_state(state)

    def scan(self) -> NativeFileBaselineState:
        return _to_native_state(self._inner.scan())

    def restore(self, relative_path: str) -> bool:
        return self._inner.restore(relative_path)

    def accept(self, relative_path: str) -> bool:
        return self._inner.accept(relative_path)


def _to_native_state(
    state: ExtensionFileBaselineState,
) -> NativeFileBaselineState:
    return NativeFileBaselineState(
        enabled=state.enabled,
        protected_paths=state.protected_paths,
        alerts=tuple(
            NativeFileBaselineDriftAlert(
                path=alert.path,
                previous_sha256=alert.previous_sha256,
                current_sha256=alert.current_sha256,
                detected_at=alert.detected_at,
            )
            for alert in state.alerts
        ),
        startup_scan_ran=state.startup_scan_ran,
    )


__all__ = [
    "CONFIRM_ACCEPT_PHRASE",
    "CONFIRM_REESTABLISH_PHRASE",
    "CONFIRM_RESTORE_PHRASE",
    "FileBaselineGuardian",
    "get_integrity_settings_projection",
    "get_file_baseline_service",
    "notify_file_saved",
    "run_startup_scan_if_enabled",
    "stream_file_baseline_events",
    "try_guarded_agent_file_write",
    "try_guarded_operator_file_write",
    "try_guarded_shell_command",
    "try_guarded_python_code",
    "GuardedWriteOutcome",
    "GuardedCommandOutcome",
    "browse_workspace_protectable_files",
]
