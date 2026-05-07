# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
import shutil
import uuid
from pathlib import Path

from .base import BaseJobRepository
from ..models import JobsFile

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
        shutil.move(str(tmp_path), str(self._path))


def migrate_legacy_weixin_jobs_file(jobs_path: Path | str) -> None:
    """One-shot migration: rewrite legacy ``weixin:`` session_ids in jobs.json.

    Older releases used ``weixin`` as the ``session_id`` prefix for
    WeChat (iLink) cron dispatch targets. The canonical prefix is now
    ``wechat``. The ``dispatch.channel`` field has always been
    ``wechat``, so only the ``dispatch.target.session_id`` prefix needs
    to be rewritten. Original file is backed up before rewrite.
    Idempotent: a no-op when no legacy entries are present.

    Without this migration a fired cron would re-introduce ``weixin:``
    prefixes into freshly-created chat / session files, undoing the
    chats.json and sessions/ migrations done elsewhere on startup.
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
        tmp_path.write_text(
            json.dumps(
                data,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        shutil.move(str(tmp_path), str(path))
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
