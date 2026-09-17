# -*- coding: utf-8 -*-
"""WorkflowState — state directory and file management for OMP modes."""

from __future__ import annotations

import json
import logging
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class WorkflowState:
    """Manage per-instance state directory and files.

    Path convention:
        {workspace_dir}/.qwenpaw/omp_workflows/{mode_name}-{timestamp}/

    Writers should prefer :meth:`update_state` so concurrent agent
    updates to other keys are preserved (read-merge-write + atomic
    replace).
    """

    def __init__(self, workspace_dir: Path, mode_name: str) -> None:
        self.workspace_dir = workspace_dir
        self.mode_name = mode_name
        self._instance_dir: Path | None = None

    def create_instance(self) -> Path:
        """Create a timestamped instance directory."""
        ts = time.strftime("%Y%m%d-%H%M%S")
        suffix = uuid.uuid4().hex[:6]
        base = self.workspace_dir / ".qwenpaw" / "omp_workflows"
        self._instance_dir = base / f"{self.mode_name}-{ts}-{suffix}"
        self._instance_dir.mkdir(parents=True, exist_ok=True)
        self.append_log(f"[{self.mode_name}] instance created")
        return self._instance_dir

    @property
    def instance_dir(self) -> Path | None:
        return self._instance_dir

    @classmethod
    def from_existing(
        cls,
        workspace_dir: Path,
        mode_name: str,
        instance_dir: Path,
    ) -> WorkflowState:
        """Attach to an already-created instance directory."""
        wf = cls(workspace_dir, mode_name)
        wf._instance_dir = instance_dir
        return wf

    def read_state(self) -> dict[str, Any]:
        """Read state.json, returning empty dict if absent."""
        if not self._instance_dir:
            return {}
        p = self._instance_dir / "state.json"
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Failed to read %s", p, exc_info=True)
            return {}

    def write_state(self, data: dict[str, Any]) -> None:
        """Atomically replace state.json with *data*."""
        if not self._instance_dir:
            return
        self._atomic_write_json(
            self._instance_dir / "state.json",
            data,
        )

    def update_state(self, patch: dict[str, Any]) -> dict[str, Any]:
        """Merge *patch* into state.json and write atomically.

        Returns the merged document.  Prefer this over
        :meth:`write_state` when the gate only owns some keys.
        """
        data = self.read_state()
        data.update(patch)
        self.write_state(data)
        return data

    def read_prd(self) -> dict[str, Any]:
        """Read prd.json, returning empty dict if absent."""
        if not self._instance_dir:
            return {}
        p = self._instance_dir / "prd.json"
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Failed to read %s", p, exc_info=True)
            return {}

    def append_log(self, entry: str) -> None:
        """Append a line to progress.txt (survives :meth:`cleanup`)."""
        if not self._instance_dir:
            return
        p = self._instance_dir / "progress.txt"
        with p.open("a", encoding="utf-8") as f:
            f.write(entry + "\n")

    def cleanup(self) -> None:
        """Remove temporary control files; keep audit artifacts.

        Deletes ``state.json`` / ``prd.json`` (and ``*.tmp`` sidecars)
        only.  Specs, plans, handoffs, worker results, and
        ``progress.txt`` are retained for post-run inspection.
        """
        if not self._instance_dir or not self._instance_dir.exists():
            return
        remove_names = {"state.json", "prd.json"}
        for child in list(self._instance_dir.iterdir()):
            should_remove = child.name in remove_names or (
                child.is_file() and child.name.endswith(".tmp")
            )
            if not should_remove:
                continue
            try:
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
            except OSError:
                logger.warning(
                    "Failed to remove %s during cleanup",
                    child,
                    exc_info=True,
                )
        self.append_log(f"[{self.mode_name}] cleanup complete")
        logger.info("Cleaned up control files in %s", self._instance_dir)

    @staticmethod
    def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
        """Write JSON via temp file + replace."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        tmp.replace(path)
