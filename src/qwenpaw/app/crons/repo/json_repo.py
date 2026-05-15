# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import uuid
from pathlib import Path
from urllib.parse import quote

from .base import BaseJobRepository
from ..models import CronExecutionRecord, JobsFile

logger = logging.getLogger(__name__)


class JsonJobRepository(BaseJobRepository):
    """jobs.json repository (single-file storage).

    Notes:
    - Single-machine, no cross-process lock.
    - Atomic write: write tmp then replace.
    """

    def __init__(self, path: Path | str):
        if isinstance(path, str):
            path = Path(path)
        self._path = path.expanduser()
        self._history_dir = self._path.with_name("jobs_history")
        self._history_write_locks: dict[str, asyncio.Lock] = {}

    @property
    def path(self) -> Path:
        return self._path

    @property
    def history_dir(self) -> Path:
        return self._history_dir

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
        shutil.move(str(tmp_path), str(self._path))

    def _history_file_path(self, job_id: str) -> Path:
        encoded = quote(job_id, safe="")
        return self._history_dir / f"{encoded}.json"

    def _get_history_write_lock(self, job_id: str) -> asyncio.Lock:
        lock = self._history_write_locks.get(job_id)
        if lock is None:
            lock = asyncio.Lock()
            self._history_write_locks[job_id] = lock
        return lock

    def _write_json_atomic(self, target: Path, payload: list[dict]) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = target.with_suffix(target.suffix + ".tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        shutil.move(str(tmp_path), str(target))

    def _read_job_history(self, job_id: str) -> list[CronExecutionRecord]:
        file_path = self._history_file_path(job_id)
        if not file_path.exists():
            return []
        data = json.loads(file_path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return []
        return [CronExecutionRecord.model_validate(item) for item in data]

    async def get_history(self, job_id: str) -> list[CronExecutionRecord]:
        return self._read_job_history(job_id)

    async def append_history(
        self,
        job_id: str,
        record: CronExecutionRecord,
        *,
        limit: int = 50,
    ) -> list[CronExecutionRecord]:
        lock = self._get_history_write_lock(job_id)
        async with lock:
            records = self._read_job_history(job_id)
            records.insert(0, record)
            del records[limit:]
            payload = [r.model_dump(mode="json") for r in records]
            self._write_json_atomic(self._history_file_path(job_id), payload)
            return records

    async def delete_history(self, job_id: str) -> None:
        lock = self._get_history_write_lock(job_id)
        async with lock:
            self._history_file_path(job_id).unlink(missing_ok=True)
        self._history_write_locks.pop(job_id, None)

    async def prune_orphan_history(self, valid_job_ids: set[str]) -> None:
        if not self._history_dir.exists():
            return
        valid_filenames = {
            self._history_file_path(job_id).name for job_id in valid_job_ids
        }
        for file_path in self._history_dir.glob("*.json"):
            if file_path.name not in valid_filenames:
                file_path.unlink(missing_ok=True)


def migrate_legacy_weixin_jobs_file(jobs_path: Path | str) -> None:
    """Rewrite legacy ``weixin:`` cron dispatch session_ids to ``wechat:``.

    Without this, a fired cron would re-introduce ``weixin:`` prefixes
    into freshly created chat / session files. Idempotent; backs up the
    original file before rewrite.
    """
    path = (
        Path(jobs_path).expanduser()
        if isinstance(
            jobs_path,
            str,
        )
        else jobs_path
    )
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(data, dict):
        return

    jobs = data.get("jobs")
    if not isinstance(jobs, list):
        return

    mutated = False
    for job in jobs:
        if not isinstance(job, dict):
            continue
        target = (job.get("dispatch") or {}).get("target")
        if not isinstance(target, dict):
            continue
        sid = target.get("session_id")
        if isinstance(sid, str) and sid.startswith("weixin:"):
            target["session_id"] = "wechat:" + sid[len("weixin:") :]
            mutated = True

    if not mutated:
        return

    try:
        backup_path = path.with_suffix(
            path.suffix + f".{uuid.uuid4().hex[:8]}.weixin-migrate.bak",
        )
        shutil.copy2(path, backup_path)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        # newline="\n" prevents Windows from translating LF -> CRLF and
        # polluting the file's line endings on rewrite.
        tmp_path.write_text(
            json.dumps(
                data,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
            newline="\n",
        )
        # os.replace is the documented atomic-overwrite primitive on all
        # supported platforms (POSIX rename + Windows ReplaceFile).
        os.replace(tmp_path, path)
        logger.warning(
            "Migrated legacy 'weixin' cron dispatch targets -> 'wechat' "
            "in %s (backup: %s)",
            path,
            backup_path,
        )
    except OSError as exc:
        logger.error(
            "Failed to migrate legacy 'weixin' cron dispatch targets in "
            "%s: %s",
            path,
            exc,
        )
