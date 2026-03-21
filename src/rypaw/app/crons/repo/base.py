# -*- coding: utf-8 -*-
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from ..models import CronJobSpec, JobsFile


class BaseJobRepository(ABC):
    """Abstract repository for cron job specs persistence."""

    @abstractmethod
    async def load(self) -> JobsFile:
        """Load all jobs from storage."""
        raise NotImplementedError

    @abstractmethod
    async def save(self, jobs_file: JobsFile) -> None:
        """Persist all jobs to storage (should be atomic if possible)."""
        raise NotImplementedError

    # ---- Optional but commonly needed convenience ops ----

    async def list_jobs(self) -> list[CronJobSpec]:
        jf = await self.load()
        return jf.jobs

    async def get_job(self, job_id: str) -> Optional[CronJobSpec]:
        jf = await self.load()
        for job in jf.jobs:
            if job.id == job_id:
                return job
        return None

    async def upsert_job(self, spec: CronJobSpec) -> None:
        jf = await self.load()
        for i, j in enumerate(jf.jobs):
            if j.id == spec.id:
                jf.jobs[i] = spec
                break
        else:
            jf.jobs.append(spec)
        await self.save(jf)

    async def delete_job(self, job_id: str) -> bool:
        jf = await self.load()
        before = len(jf.jobs)
        jf.jobs = [j for j in jf.jobs if j.id != job_id]
        if len(jf.jobs) == before:
            return False
        await self.save(jf)
        return True
