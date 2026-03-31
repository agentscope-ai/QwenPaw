# -*- coding: utf-8 -*-
"""File-based plan storage for CoPaw."""
from __future__ import annotations

import asyncio
import json
import logging
import tempfile
from pathlib import Path

from agentscope.plan import PlanStorageBase, Plan

logger = logging.getLogger(__name__)


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
        return self._dir / f"{plan_id}.json"

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
            fd = tempfile.NamedTemporaryFile(
                mode="w",
                dir=str(self._dir),
                suffix=".tmp",
                delete=False,
                encoding="utf-8",
            )
            try:
                fd.write(data)
                fd.flush()
                fd.close()
                Path(fd.name).rename(dest)
            except BaseException:
                Path(fd.name).unlink(missing_ok=True)
                raise

    async def delete_plan(self, plan_id: str) -> None:
        async with self._lock:
            self._plan_path(plan_id).unlink(missing_ok=True)

    async def get_plans(self) -> list[Plan]:
        async with self._lock:
            plans: list[Plan] = []
            for p in sorted(self._dir.glob("*.json")):
                try:
                    raw = json.loads(p.read_text(encoding="utf-8"))
                    plans.append(Plan.model_validate(raw))
                except Exception:
                    logger.warning("Skipping corrupt plan file: %s", p)
            return plans

    async def get_plan(self, plan_id: str) -> Plan | None:
        async with self._lock:
            path = self._plan_path(plan_id)
            if not path.exists():
                return None
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                return Plan.model_validate(raw)
            except Exception:
                logger.warning("Failed to load plan file: %s", path)
                return None
