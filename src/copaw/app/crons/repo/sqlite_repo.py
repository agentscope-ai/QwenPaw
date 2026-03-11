# -*- coding: utf-8 -*-
"""SQLite-based cron job repository."""
from __future__ import annotations

from pathlib import Path

from .base import BaseJobRepository
from ..models import CronJobSpec, JobsFile
from ...state_db import (
    connect_state_db,
    dump_model_payload,
    ensure_state_db_schema,
    load_job_from_row,
)


class SQLiteJobRepository(BaseJobRepository):
    """SQLite-backed repository for cron jobs."""

    def __init__(self, db_path: Path | str):
        if isinstance(db_path, str):
            db_path = Path(db_path)
        self._db_path = db_path.expanduser()
        ensure_state_db_schema(self._db_path)

    @property
    def path(self) -> Path:
        return self._db_path

    async def load(self) -> JobsFile:
        with connect_state_db(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT payload_json
                FROM jobs
                ORDER BY id ASC
                """,
            ).fetchall()
        return JobsFile(
            version=1,
            jobs=[load_job_from_row(row) for row in rows],
        )

    async def save(self, jobs_file: JobsFile) -> None:
        with connect_state_db(self._db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute("DELETE FROM jobs")
                conn.executemany(
                    """
                    INSERT INTO jobs (id, payload_json)
                    VALUES (?, ?)
                    """,
                    [
                        (job.id, dump_model_payload(job))
                        for job in jobs_file.jobs
                    ],
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    async def get_job(self, job_id: str) -> CronJobSpec | None:
        with connect_state_db(self._db_path) as conn:
            row = conn.execute(
                "SELECT payload_json FROM jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        return load_job_from_row(row) if row is not None else None

    async def upsert_job(self, spec: CronJobSpec) -> None:
        with connect_state_db(self._db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    """
                    INSERT INTO jobs (id, payload_json)
                    VALUES (?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        payload_json = excluded.payload_json
                    """,
                    (
                        spec.id,
                        dump_model_payload(spec),
                    ),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    async def delete_job(self, job_id: str) -> bool:
        with connect_state_db(self._db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                result = conn.execute(
                    "DELETE FROM jobs WHERE id = ?",
                    (job_id,),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return result.rowcount > 0
