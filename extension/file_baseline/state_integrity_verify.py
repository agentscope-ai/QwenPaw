# -*- coding: utf-8
"""Detect and repair Agent tampering of integrity-protection state after commands."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .frozen_store import (
    detect_state_hash_drift,
    repair_mutable_state_from_frozen,
    snapshot_state_hashes,
)
from .write_context import file_baseline_maintenance_context, is_file_baseline_maintenance

if TYPE_CHECKING:
    from .service import FileBaselineService

logger = logging.getLogger(__name__)


def capture_state_hashes_for_agent(
    service: "FileBaselineService",
    agent_id: str,
) -> dict[str, str]:
    if not service.is_enabled():
        return {}
    settings = service.settings_store.load()
    rel_paths = service.settings_store.effective_paths(settings, agent_id)
    if not rel_paths:
        return {}
    return snapshot_state_hashes(service.working_dir, agent_id, rel_paths)


async def verify_integrity_state_after_command(
    service: "FileBaselineService",
    agent_id: str,
    *,
    before_hashes: dict[str, str] | None,
) -> list[str]:
    """Repair mutable state when Agent changed integrity-protection files mid-command."""
    if is_file_baseline_maintenance() or not service.is_enabled() or not before_hashes:
        return []

    settings = service.settings_store.load()
    rel_paths = service.settings_store.effective_paths(settings, agent_id)
    if not rel_paths:
        return []

    after_hashes = snapshot_state_hashes(service.working_dir, agent_id, rel_paths)
    drifted_keys = detect_state_hash_drift(before_hashes, after_hashes)
    if not drifted_keys:
        return []

    logger.warning(
        "file_baseline_state_tamper agent_id=%s drifted_keys=%s",
        agent_id,
        drifted_keys,
    )

    state_dir = service.settings_store.agent_state(agent_id)
    with file_baseline_maintenance_context():
        repair_mutable_state_from_frozen(
            service.working_dir,
            agent_id,
            state_dir=state_dir,
            rel_paths=rel_paths,
        )

    for rel_path in rel_paths:
        await service._emit_drift_for_path(
            settings,
            agent_id,
            rel_path,
            provenance="state_tamper",
        )

    return drifted_keys
