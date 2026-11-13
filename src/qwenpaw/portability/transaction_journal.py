# -*- coding: utf-8 -*-
"""Crash marker for import plans.

Stores write atomically, so recovery only resets an interrupted plan and never
restores a snapshot over data changed by another agent.
"""

from __future__ import annotations

import logging
import os
import re
import secrets
import stat
from datetime import datetime, timezone
from pathlib import Path

from ..utils.io_utils import (
    read_json_async,
    run_sync_io,
    unlink_async,
    write_json_atomic_async,
)
from .models import MigrationPlan

logger = logging.getLogger(__name__)

_PLAN_ID_PATTERN = re.compile(r"plan-[0-9a-f]{32}")
_MAX_JOURNAL_BYTES = 4 * 1024


def _journal_path(workspace: Path, plan_id: str) -> Path:
    return workspace / ".qwenpaw/imports/transactions" / f"{plan_id}.json"


class ImportTransactionJournal:
    """Durable in-flight marker; no whole-store snapshots are taken."""

    def __init__(self, workspace: Path, plan_id: str) -> None:
        if not _PLAN_ID_PATTERN.fullmatch(plan_id):
            raise ValueError("invalid import plan id")
        self.path = _journal_path(workspace.resolve(), plan_id)
        self.plan_id = plan_id

    async def begin(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        await write_json_atomic_async(
            self.path,
            {"plan_id": self.plan_id, "state": "applying"},
            sort_keys=True,
            new_file_mode=0o600,
        )

    async def discard(self) -> None:
        await unlink_async(self.path, missing_ok=True)


def _validate_journal_file(path: Path) -> None:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("journal is not a regular file")
    if info.st_size > _MAX_JOURNAL_BYTES:
        raise ValueError("journal exceeds the size limit")


def _quarantine_path(path: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = path.with_name(
        f"{path.name}.corrupt-{timestamp}-{secrets.token_hex(4)}",
    )
    os.replace(path, target)
    os.chmod(target, 0o600)
    return target


async def _quarantine(path: Path, exc: Exception) -> None:
    try:
        target = await run_sync_io(_quarantine_path, path)
    except OSError:
        logger.exception("Failed to quarantine import journal %s", path)
    else:
        logger.warning(
            "Quarantined invalid import journal %s: %s",
            target,
            exc,
        )


async def _read_recovery_plan(workspace: Path, path: Path) -> tuple[str, dict]:
    await run_sync_io(_validate_journal_file, path)
    plan_id = path.stem
    if not _PLAN_ID_PATTERN.fullmatch(plan_id):
        raise ValueError("invalid import plan id")
    value = await read_json_async(path)
    if (
        not isinstance(value, dict)
        or value.get("plan_id") != plan_id
        or value.get("state") != "applying"
    ):
        raise ValueError("invalid journal payload")
    plan_path = workspace / ".qwenpaw/imports/plans" / f"{plan_id}.json"
    plan_value = await read_json_async(plan_path)
    if (
        not isinstance(plan_value, dict)
        or plan_value.get("plan_id") != plan_id
        or plan_value.get("state") not in {"ready", "applying", "applied"}
    ):
        raise ValueError("invalid import plan")
    plan = MigrationPlan.model_validate(plan_value)
    states = {"ready", "applying", "applied"}
    if plan.plan_id != plan_id or plan.state not in states:
        raise ValueError("invalid import plan")
    return plan_id, plan_value


async def recover_import_transactions(workspaces: list[Path]) -> list[str]:
    """Reset interrupted plans without touching live asset stores."""
    recovered: list[str] = []
    for workspace in workspaces:
        root = workspace / ".qwenpaw/imports/transactions"
        try:
            journals = sorted(root.glob("*.json"))
        except OSError:
            continue
        for path in journals:
            try:
                recovery = await _read_recovery_plan(workspace, path)
                plan_id, plan_value = recovery
            except (FileNotFoundError, TypeError, ValueError) as exc:
                await _quarantine(path, exc)
                continue
            except OSError:
                logger.exception("Failed to read import journal %s", path)
                continue
            try:
                if plan_value["state"] == "applying":
                    plan_value["state"] = "ready"
                    plans_root = workspace / ".qwenpaw/imports/plans"
                    plan = plans_root / f"{plan_id}.json"
                    await write_json_atomic_async(
                        plan,
                        plan_value,
                        sort_keys=True,
                        new_file_mode=0o600,
                    )
                    recovered.append(plan_id)
                await unlink_async(path, missing_ok=True)
            except OSError:
                logger.exception("Failed to recover import journal %s", path)
    return recovered


__all__ = ["ImportTransactionJournal", "recover_import_transactions"]
