# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
from pathlib import Path

from pydantic import ValidationError

from .base import BaseJobRepository
from ..models import JobsFile
from ....utils.json_storage import (
    load_json_with_recovery,
    repair_json_file,
    save_json_atomically,
)


logger = logging.getLogger(__name__)


class JsonJobRepository(BaseJobRepository):
    """jobs.json repository (single-file storage).

    Notes:
    - Uses a sibling lock file for cross-process coordination.
    - Writes via unique temp file + atomic replace.
    """

    def __init__(self, path: Path):
        self._path = path.expanduser()

    @property
    def path(self) -> Path:
        return self._path

    async def load(self) -> JobsFile:
        default_file = JobsFile(version=1, jobs=[])
        data = load_json_with_recovery(
            self._path,
            default_payload=default_file.model_dump(mode="json"),
            storage_name="job repository",
            logger_=logger,
        )
        try:
            return JobsFile.model_validate(data)
        except ValidationError as exc:
            repair_json_file(
                self._path,
                default_payload=default_file.model_dump(mode="json"),
                storage_name="job repository",
                reason=f"schema validation failed: {exc}",
                logger_=logger,
            )
            return default_file

    async def save(self, jobs_file: JobsFile) -> None:
        payload = jobs_file.model_dump(mode="json")
        save_json_atomically(
            self._path,
            payload,
        )
