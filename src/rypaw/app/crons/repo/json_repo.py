# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

from .base import BaseJobRepository
from ..models import JobsFile


class JsonJobRepository(BaseJobRepository):
    """jobs.json repository (single-file storage).

    Notes:
    - Single-machine, no cross-process lock.
    - Atomic write: write tmp then replace.
    """

    def __init__(self, path: Path):
        self._path = path.expanduser()

    @property
    def path(self) -> Path:
        return self._path

    async def load(self) -> JobsFile:
        if not self._path.exists():
            return JobsFile(version=1, jobs=[])

        data = json.loads(self._path.read_text(encoding="utf-8"))
        return JobsFile.model_validate(data)

    async def save(self, jobs_file: JobsFile) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)

        tmp_path = self._path.with_suffix(self._path.suffix + ".tmp")
        payload = jobs_file.model_dump(mode="json")

        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp_path.replace(self._path)
