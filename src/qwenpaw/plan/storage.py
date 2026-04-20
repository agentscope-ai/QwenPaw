# -*- coding: utf-8 -*-
"""File-based plan storage."""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
from pathlib import Path

import anyio
from agentscope.plan import PlanStorageBase, Plan

logger = logging.getLogger(__name__)

# AgentScope uses shortuuid-like ids; keep a sane bound and reject path
# segments so ``../`` cannot escape ``storage_path``.
_MAX_PLAN_ID_LEN = 128


def _assert_safe_plan_id(plan_id: str) -> None:
    """Reject path separators and traversal so files stay under ``_dir``."""
    if (
        not plan_id
        or len(plan_id) > _MAX_PLAN_ID_LEN
        or "\x00" in plan_id
        or plan_id in {".", ".."}
    ):
        raise ValueError("invalid plan id")
    parts = Path(plan_id).parts
    if len(parts) != 1 or parts[0] != plan_id:
        raise ValueError("invalid plan id")


def _write_plan_json_sync(dir_path: Path, dest: Path, data: str) -> None:
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=str(dir_path),
            suffix=".tmp",
            delete=False,
            encoding="utf-8",
        ) as fd:
            fd.write(data)
            fd.flush()
            tmp_path = Path(fd.name)
        if tmp_path is None:
            raise RuntimeError("failed to allocate temp plan file")
        tmp_path.rename(dest)
    except BaseException:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
        raise


def _read_plans_sync(dir_path: Path) -> list[Plan]:
    plans: list[Plan] = []
    for p in sorted(dir_path.glob("*.json")):
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            plans.append(Plan.model_validate(raw))
        except Exception:
            logger.warning("Skipping corrupt plan file: %s", p)
    return plans


def _read_plan_sync(path: Path) -> Plan | None:
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return Plan.model_validate(raw)
    except Exception:
        logger.warning("Failed to load plan file: %s", path)
        return None


def _unlink_plan_sync(path: Path) -> None:
    path.unlink(missing_ok=True)


class FilePlanStorage(PlanStorageBase):
    """Persist plans as JSON files under a configurable directory.

    Each plan is stored as ``{plan_id}.json``.  All file writes are
    atomic (write to a temp file, then rename) to prevent data loss.
    """

    def __init__(self, storage_path: str) -> None:
        super().__init__()
        self._dir = Path(storage_path)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    def _plan_path(self, plan_id: str) -> Path:
        _assert_safe_plan_id(plan_id)
        dest = (self._dir / f"{plan_id}.json").resolve()
        base = self._dir.resolve()
        if not dest.is_relative_to(base):
            raise ValueError("invalid plan id")
        return dest

    async def add_plan(self, plan: Plan, override: bool = True) -> None:
        async with self._lock:
            dest = self._plan_path(plan.id)
            if dest.exists() and not override:
                raise ValueError(
                    f"Plan with id {plan.id} already exists.",
                )
            data = json.dumps(
                plan.model_dump(),
                ensure_ascii=False,
                indent=2,
            )
            await anyio.to_thread.run_sync(
                _write_plan_json_sync,
                self._dir,
                dest,
                data,
            )

    async def delete_plan(self, plan_id: str) -> None:
        async with self._lock:
            path = self._plan_path(plan_id)
            await anyio.to_thread.run_sync(_unlink_plan_sync, path)

    async def get_plans(self) -> list[Plan]:
        async with self._lock:
            return await anyio.to_thread.run_sync(_read_plans_sync, self._dir)

    async def get_plan(self, plan_id: str) -> Plan | None:
        async with self._lock:
            path = self._plan_path(plan_id)
            return await anyio.to_thread.run_sync(_read_plan_sync, path)
