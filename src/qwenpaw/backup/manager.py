# -*- coding: utf-8 -*-
"""Application-owned lifecycle for backup creation jobs."""
from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

from ._ops.create import BackupCancelled, create_backup
from .models import (
    BackupJobPhase,
    BackupJobSnapshot,
    BackupJobStatus,
    BackupMeta,
    CreateBackupRequest,
)

logger = logging.getLogger(__name__)

_TERMINAL_STATUSES = {
    BackupJobStatus.COMPLETED,
    BackupJobStatus.FAILED,
    BackupJobStatus.CANCELLED,
}


class BackupOperationConflict(RuntimeError):
    """Raised when another mutating backup operation is already running."""

    def __init__(self, active_operation: str) -> None:
        self.active_operation = active_operation
        super().__init__(
            f"Backup operation already running: {active_operation}",
        )


@dataclass
class _BackupJob:
    request: CreateBackupRequest
    snapshot: BackupJobSnapshot
    stop_event: threading.Event = field(default_factory=threading.Event)
    subscribers: set[asyncio.Queue[BackupJobSnapshot]] = field(
        default_factory=set,
    )
    task: asyncio.Task[None] | None = None


class BackupManager:
    """Own backup jobs independently from their HTTP subscribers."""

    def __init__(self, *, max_retained_jobs: int = 20) -> None:
        self._jobs: OrderedDict[str, _BackupJob] = OrderedDict()
        self._max_retained_jobs = max_retained_jobs
        self._active_job_id: str | None = None
        self._operation: str | None = None

    def start_job(self, request: CreateBackupRequest) -> BackupJobSnapshot:
        """Start one background create job or fail if a mutation is active."""
        self._reserve_operation("create")
        meta = BackupMeta(
            name=request.name,
            description=request.description,
            scope=request.scope,
        )
        job_id = uuid.uuid4().hex
        snapshot = BackupJobSnapshot(
            job_id=job_id,
            backup_id=meta.id,
            total_agents=len(request.agents),
        )
        job = _BackupJob(request=request, snapshot=snapshot)
        self._jobs[job_id] = job
        self._active_job_id = job_id
        try:
            job.task = asyncio.create_task(self._run_job(job, meta))
        except BaseException:
            self._jobs.pop(job_id, None)
            self._active_job_id = None
            self._release_operation("create")
            raise
        self._trim_jobs()
        return self._copy_snapshot(job.snapshot)

    def get_job(self, job_id: str) -> BackupJobSnapshot | None:
        job = self._jobs.get(job_id)
        return self._copy_snapshot(job.snapshot) if job else None

    def get_active_job(self) -> BackupJobSnapshot | None:
        if self._active_job_id is None:
            return None
        return self.get_job(self._active_job_id)

    def cancel_job(self, job_id: str) -> BackupJobSnapshot | None:
        """Request cooperative cancellation; repeated calls are harmless."""
        job = self._jobs.get(job_id)
        if job is None:
            return None
        if job.snapshot.status in _TERMINAL_STATUSES:
            return self._copy_snapshot(job.snapshot)
        job.stop_event.set()
        self._update_job(job, status=BackupJobStatus.CANCEL_REQUESTED)
        return self._copy_snapshot(job.snapshot)

    def subscribe(
        self,
        job_id: str,
    ) -> asyncio.Queue[BackupJobSnapshot] | None:
        """Attach a bounded latest-snapshot subscriber to a job."""
        job = self._jobs.get(job_id)
        if job is None:
            return None
        queue: asyncio.Queue[BackupJobSnapshot] = asyncio.Queue(maxsize=1)
        job.subscribers.add(queue)
        queue.put_nowait(self._copy_snapshot(job.snapshot))
        return queue

    def unsubscribe(
        self,
        job_id: str,
        queue: asyncio.Queue[BackupJobSnapshot],
    ) -> None:
        """Detach an observer without changing the job lifecycle."""
        job = self._jobs.get(job_id)
        if job is not None:
            job.subscribers.discard(queue)

    @contextmanager
    def reserve_restore(self) -> Iterator[None]:
        """Prevent restore and background create from overlapping."""
        self._reserve_operation("restore")
        try:
            yield
        finally:
            self._release_operation("restore")

    async def shutdown(self, *, timeout: float = 5.0) -> None:
        """Request cancellation and briefly await the active worker."""
        active_id = self._active_job_id
        if active_id is None:
            return
        job = self._jobs.get(active_id)
        if job is None or job.task is None:
            return
        self.cancel_job(active_id)
        try:
            await asyncio.wait_for(asyncio.shield(job.task), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("Timed out waiting for backup job %s", active_id)

    async def _run_job(self, job: _BackupJob, meta: BackupMeta) -> None:
        loop = asyncio.get_running_loop()

        def progress(event: dict[str, Any]) -> None:
            try:
                loop.call_soon_threadsafe(
                    self._handle_progress,
                    job.snapshot.job_id,
                    event,
                )
            except RuntimeError:
                logger.debug(
                    "Event loop closed while reporting backup progress",
                )

        try:
            if job.stop_event.is_set():
                raise BackupCancelled()
            self._update_job(job, status=BackupJobStatus.RUNNING)
            result = await asyncio.to_thread(
                create_backup,
                meta,
                job.request.agents,
                progress,
                job.stop_event,
            )
        except BackupCancelled:
            self._update_job(
                job,
                status=BackupJobStatus.CANCELLED,
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.exception("Backup creation failed for %s", meta.id)
            self._update_job(
                job,
                status=BackupJobStatus.FAILED,
                error=str(exc),
            )
        else:
            self._update_job(
                job,
                status=BackupJobStatus.COMPLETED,
                phase=BackupJobPhase.FINALIZING,
                percent=100,
                result=result,
            )
        finally:
            if self._active_job_id == job.snapshot.job_id:
                self._active_job_id = None
            self._release_operation("create")

    def _handle_progress(self, job_id: str, event: dict[str, Any]) -> None:
        job = self._jobs.get(job_id)
        if job is None or job.snapshot.status in _TERMINAL_STATUSES:
            return
        status = job.snapshot.status
        if status != BackupJobStatus.CANCEL_REQUESTED:
            status = BackupJobStatus.RUNNING
        event_type = event.get("type")
        if event_type == "start":
            self._update_job(
                job,
                status=status,
                phase=BackupJobPhase.AGENTS,
                percent=int(event.get("percent", 0)),
                total_agents=int(event.get("total_agents", 0)),
            )
        elif event_type == "agent":
            self._update_job(
                job,
                status=status,
                phase=BackupJobPhase.AGENTS,
                percent=int(event.get("percent", 0)),
                current_agent=str(event.get("agent_id", "")) or None,
                agent_index=int(event.get("index", 0)),
                total_agents=int(event.get("total", 0)),
            )
        elif event_type == "saving":
            self._update_job(
                job,
                status=status,
                phase=BackupJobPhase.FINALIZING,
                percent=int(event.get("percent", 90)),
            )

    def _update_job(self, job: _BackupJob, **updates: Any) -> None:
        job.snapshot = job.snapshot.model_copy(update=updates)
        self._publish(job)

    def _publish(self, job: _BackupJob) -> None:
        snapshot = self._copy_snapshot(job.snapshot)
        for queue in tuple(job.subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(snapshot)

    def _reserve_operation(self, operation: str) -> None:
        if self._operation is not None:
            raise BackupOperationConflict(self._operation)
        self._operation = operation

    def _release_operation(self, operation: str) -> None:
        if self._operation == operation:
            self._operation = None

    def _trim_jobs(self) -> None:
        while len(self._jobs) > self._max_retained_jobs:
            for job_id, job in self._jobs.items():
                if job_id != self._active_job_id and (
                    job.snapshot.status in _TERMINAL_STATUSES
                ):
                    self._jobs.pop(job_id)
                    break
            else:
                break

    @staticmethod
    def _copy_snapshot(snapshot: BackupJobSnapshot) -> BackupJobSnapshot:
        return snapshot.model_copy(deep=True)
