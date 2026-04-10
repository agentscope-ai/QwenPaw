# -*- coding: utf-8 -*-
"""Track skill usage counts and outcomes for auto-evolution.

Each auto-generated skill gets a ``_meta.json`` sidecar that records
creation info, usage counts, and success/failure rates.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

logger = logging.getLogger(__name__)

_META_FILE = "_meta.json"


@dataclass(frozen=True)
class SkillUsageStats:
    """Read-only view of a skill's usage statistics."""

    created_at: str
    created_by: str
    origin: str
    use_count: int
    last_used_at: Optional[str]
    success_count: int
    failure_count: int
    revision_history: list[dict]

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.failure_count
        if total == 0:
            return 1.0
        return self.success_count / total


class SkillUsageTracker:
    """Manages ``_meta.json`` files alongside skill directories."""

    def __init__(self, skills_dir: Path) -> None:
        self._skills_dir = skills_dir

    def _meta_path(self, skill_name: str) -> Path:
        return self._skills_dir / skill_name / _META_FILE

    # -- public API --

    def init_meta(
        self,
        skill_name: str,
        *,
        origin: str = "auto",
        created_by: str = "skill_reviewer",
    ) -> None:
        """Create an initial ``_meta.json`` for a newly generated skill."""
        meta = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "created_by": created_by,
            "origin": origin,
            "use_count": 0,
            "last_used_at": None,
            "outcomes": {"success": 0, "failure": 0},
            "revision_history": [],
        }
        self._write_meta(skill_name, meta)

    def record_usage(
        self,
        skill_name: str,
        *,
        outcome: Literal["success", "failure"],
    ) -> None:
        """Record a usage event.  Atomic JSON update."""
        meta = self._read_meta(skill_name)
        if meta is None:
            return
        meta = dict(meta)  # shallow copy for immutability
        meta["use_count"] = meta.get("use_count", 0) + 1
        meta["last_used_at"] = datetime.now(timezone.utc).isoformat()
        outcomes = dict(meta.get("outcomes", {}))
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
        meta["outcomes"] = outcomes
        self._write_meta(skill_name, meta)

    def record_revision(
        self,
        skill_name: str,
        *,
        reason: str,
        revised_by: str = "skill_reviewer",
    ) -> None:
        """Append a revision entry to the skill's history."""
        meta = self._read_meta(skill_name)
        if meta is None:
            return
        meta = dict(meta)
        history = list(meta.get("revision_history", []))
        history.append(
            {
                "at": datetime.now(timezone.utc).isoformat(),
                "reason": reason,
                "by": revised_by,
            },
        )
        meta["revision_history"] = history
        self._write_meta(skill_name, meta)

    def get_stats(self, skill_name: str) -> Optional[SkillUsageStats]:
        """Return usage stats or None if no meta exists."""
        meta = self._read_meta(skill_name)
        if meta is None:
            return None
        outcomes = meta.get("outcomes", {})
        return SkillUsageStats(
            created_at=meta.get("created_at", ""),
            created_by=meta.get("created_by", ""),
            origin=meta.get("origin", "unknown"),
            use_count=meta.get("use_count", 0),
            last_used_at=meta.get("last_used_at"),
            success_count=outcomes.get("success", 0),
            failure_count=outcomes.get("failure", 0),
            revision_history=meta.get("revision_history", []),
        )

    def list_underperforming(
        self,
        *,
        min_uses: int = 3,
        max_success_rate: float = 0.5,
    ) -> list[str]:
        """Return skill names with low success rates."""
        result: list[str] = []
        if not self._skills_dir.is_dir():
            return result
        for child in self._skills_dir.iterdir():
            if not child.is_dir():
                continue
            stats = self.get_stats(child.name)
            if stats is None:
                continue
            if (
                stats.use_count >= min_uses
                and stats.success_rate <= max_success_rate
            ):
                result.append(child.name)
        return result

    # -- private helpers --

    def _read_meta(self, skill_name: str) -> Optional[dict]:
        path = self._meta_path(skill_name)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text("utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "skill_usage: failed to read %s: %s",
                path,
                exc,
            )
            return None

    def _write_meta(self, skill_name: str, meta: dict) -> None:
        path = self._meta_path(skill_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd, tmp = tempfile.mkstemp(
                dir=str(path.parent),
                suffix=".tmp",
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2, ensure_ascii=False)
                f.write("\n")
            os.replace(tmp, str(path))
        except OSError as exc:
            logger.warning(
                "skill_usage: failed to write %s: %s",
                path,
                exc,
            )
