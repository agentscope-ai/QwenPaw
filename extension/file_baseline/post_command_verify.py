# -*- coding: utf-8
"""Fail-closed baseline verification after agent shell/python commands."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from .drift_gate import path_status_from_adapter, sha256_file
from .os_readonly import apply_os_readonly_for_paths, temporary_os_writable
from .write_context import file_baseline_maintenance_context, is_file_baseline_maintenance

if TYPE_CHECKING:
    from .service import FileBaselineService

logger = logging.getLogger(__name__)


def _file_matches_approved(*, approved_sha256: str, absolute: Path) -> bool:
    if not approved_sha256:
        return False
    if not absolute.is_file():
        return False
    try:
        return sha256_file(absolute) == approved_sha256
    except OSError:
        return False


async def verify_protected_baselines_after_command(
    service: "FileBaselineService",
    *,
    agent_id: str,
) -> list[str]:
    """Restore drifted/missing protected files; return affected relative paths."""
    if is_file_baseline_maintenance() or not service.is_enabled():
        return []

    settings = service.settings_store.load()
    rel_paths = service.settings_store.effective_paths(settings, agent_id)
    if not rel_paths:
        return []

    workspace = service.settings_store.resolve_workspace(agent_id)
    state_dir = service.settings_store.agent_state(agent_id)
    restored: list[str] = []

    for rel_path in rel_paths:
        target = workspace / rel_path
        approved_sha, _adapter_current = path_status_from_adapter(
            service.adapter,
            workspace_root=workspace,
            state_dir=state_dir,
            rel_path=rel_path,
        )
        if not approved_sha:
            continue

        if _file_matches_approved(approved_sha256=approved_sha, absolute=target):
            continue

        try:
            drift_sha = sha256_file(target) if target.is_file() else ""
        except OSError:
            drift_sha = ""

        logger.warning(
            "file_baseline_post_command_drift agent_id=%s path=%s "
            "approved_sha=%s drift_sha=%s exists=%s",
            agent_id,
            rel_path,
            approved_sha[:12],
            drift_sha[:12],
            target.is_file(),
        )

        with file_baseline_maintenance_context():
            writable = [target] if target.is_file() else []
            with temporary_os_writable(writable):
                await asyncio.to_thread(
                    service.adapter.restore_file,
                    workspace_root=workspace,
                    state_dir=state_dir,
                    relative_path=rel_path,
                    working_dir=service.working_dir,
                    agent_id=agent_id,
                )

        apply_os_readonly_for_paths(workspace, [rel_path])

        try:
            current_sha = sha256_file(target) if target.is_file() else ""
        except OSError:
            current_sha = ""
        service.watch_service.suppress.register(
            agent_id=agent_id,
            path=rel_path,
            sha256=current_sha,
            ttl_seconds=2.0,
        )
        if drift_sha and drift_sha != approved_sha:
            await service.emitter.emit_drift(
                agent_id=agent_id,
                path=rel_path,
                approved_sha256=approved_sha,
                current_sha256=drift_sha,
                provenance="post_command_restore",
            )
        restored.append(rel_path)
        logger.info(
            "file_baseline_post_command_restored agent_id=%s path=%s sha256=%s",
            agent_id,
            rel_path,
            current_sha[:12],
        )

    return restored
