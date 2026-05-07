# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Union

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from agentscope_runtime.engine.schemas.exception import ConfigurationException

from ...config import get_heartbeat_config, get_dream_cron

from ..console_push_store import append as push_store_append
from .executor import CronExecutor
from .heartbeat import (
    is_cron_expression,
    parse_heartbeat_cron,
    parse_heartbeat_every,
    run_heartbeat_once,
)
from .models import CronJobSpec, CronJobState
from .repo.base import BaseJobRepository

HEARTBEAT_JOB_ID = "_heartbeat"
DREAM_JOB_ID = "_dream"

logger = logging.getLogger(__name__)


@dataclass
class _Runtime:
    sem: asyncio.Semaphore


class CronManager:
    def __init__(
        self,
        *,
        repo: BaseJobRepository,
        runner: Any,
        channel_manager: Any,
        timezone: str = "UTC",  # pylint: disable=redefined-outer-name
        agent_id: Optional[str] = None,
    ):
        self._repo = repo
        self._runner = runner
        self._channel_manager = channel_manager
        self._agent_id = agent_id
        self._scheduler = AsyncIOScheduler(timezone=timezone)
        self._executor = CronExecutor(
            runner=runner,
            channel_manager=channel_manager,
        )

        self._lock = asyncio.Lock()
        self._states: Dict[str, CronJobState] = {}
        self._rt: Dict[str, _Runtime] = {}
        # Track fire-and-forget background tasks so we can cancel them
        # during stop() and avoid the "Task was destroyed while pending"
        # warning caused by losing the task reference.
        self._run_tasks: set[asyncio.Task] = set()
        # Per-job set of running tasks, used by delete_job to cancel
        # in-flight executions and prevent state resurrection.
        self._job_tasks: Dict[str, set[asyncio.Task]] = {}
        self._started = False

    async def start(self) -> None:
        async with self._lock:
            if self._started:
                return
            jobs_file = await self._repo.load()

            self._scheduler.start()
            for job in jobs_file.jobs:
                try:
                    await self._register_or_update(job)
                except Exception as e:  # pylint: disable=broad-except
                    logger.warning(
                        "Skipping invalid cron job during startup: "
                        "job_id=%s name=%s cron=%s error=%s",
                        job.id,
                        job.name,
                        job.schedule.cron,
                        repr(e),
                    )
                    if job.enabled:
                        disabled_job = job.model_copy(
                            update={"enabled": False},
                        )
                        await self._repo.upsert_job(disabled_job)
                        logger.warning(
                            "Auto-disabled invalid cron job: "
                            "job_id=%s name=%s",
                            job.id,
                            job.name,
                        )

            # Heartbeat: scheduled job when enabled in config
            hb = get_heartbeat_config(self._agent_id)
            if getattr(hb, "enabled", False):
                trigger = self._build_heartbeat_trigger(hb.every)
                self._scheduler.add_job(
                    self._heartbeat_callback,
                    trigger=trigger,
                    id=HEARTBEAT_JOB_ID,
                    replace_existing=True,
                )
                logger.info(
                    "Heartbeat job scheduled for agent %s: every=%s",
                    self._agent_id,
                    hb.every,
                )

            # Dream-based memory optimization: cron job from config
            dream_cron = get_dream_cron(self._agent_id)
            if dream_cron:
                try:
                    trigger = CronTrigger.from_crontab(
                        dream_cron,
                        timezone=self._scheduler.timezone,
                    )
                    self._scheduler.add_job(
                        self._dream_callback,
                        trigger=trigger,
                        id=DREAM_JOB_ID,
                        replace_existing=True,
                    )
                    logger.info(
                        f"Dream-based memory optimization job scheduled for "
                        f"agent {self._agent_id}: cron={dream_cron}",
                    )
                except Exception as e:  # pylint: disable=broad-except
                    logger.error(
                        f"Failed to schedule dream-based memory optimization"
                        f"for  agent {self._agent_id}: error={repr(e)}",
                    )

            self._started = True

    async def stop(self) -> None:
        async with self._lock:
            if not self._started:
                return
            self._scheduler.shutdown(wait=False)
            self._started = False

            # Cancel all in-flight fire-and-forget tasks to prevent them
            # from writing into the state dicts after we have cleared them.
            pending = [t for t in self._run_tasks if not t.done()]
            for task in pending:
                task.cancel()

            # Wait for cancellations to settle outside the lock so that the
            # done callbacks (which remove tasks from the tracking set) can
            # run without deadlocking on our lock.
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

        async with self._lock:
            # Clear all per-run state to avoid leaking it to the next
            # start() cycle (e.g. stale last_status / last_error).
            self._states.clear()
            self._rt.clear()
            self._run_tasks.clear()
            self._job_tasks.clear()

    # ----- read/state -----

    async def list_jobs(self) -> list[CronJobSpec]:
        return await self._repo.list_jobs()

    async def get_job(self, job_id: str) -> Optional[CronJobSpec]:
        return await self._repo.get_job(job_id)

    def get_state(self, job_id: str) -> CronJobState:
        return self._states.get(job_id, CronJobState())

    # ----- write/control -----

    async def create_or_replace_job(self, spec: CronJobSpec) -> None:
        async with self._lock:
            await self._repo.upsert_job(spec)
            if self._started:
                await self._register_or_update(spec)

    async def delete_job(self, job_id: str) -> bool:
        async with self._lock:
            if self._started and self._scheduler.get_job(job_id):
                self._scheduler.remove_job(job_id)
            self._states.pop(job_id, None)
            self._rt.pop(job_id, None)
            # Cancel any in-flight executions for this job so they cannot
            # recreate runtime/state entries after deletion.
            running = self._job_tasks.pop(job_id, set())
            for task in running:
                if not task.done():
                    task.cancel()
            deleted = await self._repo.delete_job(job_id)

            # Wait outside the lock to let _task_done_cb run and remove the
            # cancelled tasks from the tracking set.
        if running:
            await asyncio.gather(*running, return_exceptions=True)
        return deleted

    async def pause_job(self, job_id: str) -> None:
        async with self._lock:
            self._scheduler.pause_job(job_id)

    async def resume_job(self, job_id: str) -> None:
        async with self._lock:
            self._scheduler.resume_job(job_id)

    async def reschedule_heartbeat(self) -> None:
        """Reload heartbeat config and update or remove the heartbeat job.

        Note: CronManager should always be started during workspace
        initialization, so this method assumes self._started is True.
        """
        async with self._lock:
            if not self._started:
                logger.warning(
                    f"CronManager not started for agent {self._agent_id}, "
                    f"cannot reschedule heartbeat. This should not happen.",
                )
                return

            hb = get_heartbeat_config(self._agent_id)

            # Remove existing heartbeat job if present
            if self._scheduler.get_job(HEARTBEAT_JOB_ID):
                self._scheduler.remove_job(HEARTBEAT_JOB_ID)

            # Add heartbeat job if enabled
            if getattr(hb, "enabled", False):
                trigger = self._build_heartbeat_trigger(hb.every)
                self._scheduler.add_job(
                    self._heartbeat_callback,
                    trigger=trigger,
                    id=HEARTBEAT_JOB_ID,
                    replace_existing=True,
                )
                logger.info(
                    "heartbeat rescheduled: every=%s",
                    hb.every,
                )
            else:
                logger.info("heartbeat disabled, job removed")

    async def reschedule_dream(self) -> None:
        """Reschedule the dream-based memory optimization job based on
        configuration.

        Note: CronManager should always be started during workspace
        initialization, so this method assumes self._started is True.
        """
        async with self._lock:
            if not self._started:
                logger.warning(
                    f"CronManager not started for agent {self._agent_id}, "
                    "cannot reschedule dream-based memory optimization."
                    "This should not happen.",
                )
                return

            # Check if dream-based memory optimization is enabled in config
            dream_cron = get_dream_cron(self._agent_id)

            # Remove existing job if any
            if self._scheduler.get_job(DREAM_JOB_ID):
                self._scheduler.remove_job(DREAM_JOB_ID)
                logger.info(
                    "Dream-based memory optimization job removed for "
                    f"agent {self._agent_id}",
                )

            # Add new job if cron expression is valid
            if dream_cron:
                try:
                    trigger = CronTrigger.from_crontab(
                        dream_cron,
                        timezone=self._scheduler.timezone,
                    )
                    self._scheduler.add_job(
                        self._dream_callback,
                        trigger=trigger,
                        id=DREAM_JOB_ID,
                        replace_existing=True,
                    )
                    logger.info(
                        "Dream-based memory optimization job rescheduled"
                        f"for agent {self._agent_id}: cron={dream_cron}",
                    )
                except Exception as e:  # pylint: disable=broad-except
                    logger.error(
                        "Failed to reschedule dream-based memory  "
                        f"optimization for agent {self._agent_id}: "
                        f"error={repr(e)}",
                    )
            else:
                logger.info(
                    "dream-based memory optimization disabled, job removed",
                )

    async def run_job(self, job_id: str) -> None:
        """Trigger a job to run in the background (fire-and-forget).

        Raises KeyError if the job does not exist.
        The actual execution happens asynchronously; errors are logged
        and reflected in the job state but NOT propagated to the caller.
        """
        job = await self._repo.get_job(job_id)
        if not job:
            raise KeyError(f"Job not found: {job_id}")
        logger.info(
            "cron run_job (async): job_id=%s channel=%s task_type=%s "
            "target_user_id=%s target_session_id=%s",
            job_id,
            job.dispatch.channel,
            job.task_type,
            (job.dispatch.target.user_id or "")[:40],
            (job.dispatch.target.session_id or "")[:40],
        )
        task = asyncio.create_task(
            self._execute_once(job),
            name=f"cron-run-{job_id}",
        )
        self._track_job_task(job_id, task)
        task.add_done_callback(lambda t: self._task_done_cb(t, job))

    # ----- callbacks -----

    def _track_job_task(self, job_id: str, task: asyncio.Task) -> None:
        """Register a fire-and-forget task for lifecycle management."""
        self._run_tasks.add(task)
        self._job_tasks.setdefault(job_id, set()).add(task)

    def _untrack_job_task(self, job_id: str, task: asyncio.Task) -> None:
        """Remove a tracked fire-and-forget task when it completes."""
        self._run_tasks.discard(task)
        job_set = self._job_tasks.get(job_id)
        if job_set is not None:
            job_set.discard(task)
            if not job_set:
                self._job_tasks.pop(job_id, None)

    def _task_done_cb(self, task: asyncio.Task, job: CronJobSpec) -> None:
        """Suppress and log exceptions from fire-and-forget tasks.

        On failure, push an error message to the console push store so
        the frontend can display it.
        """
        # Always drop the task from the tracking sets first so that a
        # later stop()/delete_job() does not try to cancel a completed
        # task (which is harmless but also leaks memory until next gc).
        assert job.id is not None
        self._untrack_job_task(job.id, task)

        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error(
                "cron background task %s failed: %s",
                task.get_name(),
                repr(exc),
            )
            # Push error to the console for the frontend to display
            session_id = job.dispatch.target.session_id
            if session_id:
                error_text = f"❌ Cron job [{job.name}] failed: {exc}"
                push_task = asyncio.create_task(
                    push_store_append(session_id, error_text),
                    name=f"cron-push-err-{job.id}",
                )
                # Track so shutdown does not lose the reference.
                self._run_tasks.add(push_task)
                push_task.add_done_callback(self._run_tasks.discard)

    # ----- internal -----

    async def _register_or_update(self, spec: CronJobSpec) -> None:
        # Validate and build trigger first. If cron is invalid, fail fast
        # without mutating scheduler/runtime state.
        assert spec.id is not None, "Job must have an id"
        trigger = self._build_trigger(spec)

        # per-job concurrency semaphore
        # Reuse the existing semaphore if one is already in place: blindly
        # replacing it would orphan in-flight tasks holding permits on the
        # old semaphore and silently double the effective max_concurrency
        # until those tasks finish. Changes to max_concurrency therefore
        # take effect only when no task is currently waiting on the sem.
        existing = self._rt.get(spec.id)
        if existing is None:
            self._rt[spec.id] = _Runtime(
                sem=asyncio.Semaphore(spec.runtime.max_concurrency),
            )
        else:
            # Keep the existing _Runtime so in-flight executions see a
            # consistent semaphore. If the limit actually changed, log it
            # so operators know the new value applies to future runs only.
            current_limit = getattr(existing.sem, "_value", None)
            if (
                current_limit is not None
                and current_limit != spec.runtime.max_concurrency
            ):
                logger.info(
                    "cron job_id=%s max_concurrency change (%s -> %s) "
                    "will apply after current runs settle",
                    spec.id,
                    current_limit,
                    spec.runtime.max_concurrency,
                )

        # replace existing
        if self._scheduler.get_job(spec.id):
            self._scheduler.remove_job(spec.id)

        self._scheduler.add_job(
            self._scheduled_callback,
            trigger=trigger,
            id=spec.id,
            args=[spec.id],
            misfire_grace_time=spec.runtime.misfire_grace_seconds,
            replace_existing=True,
        )

        if not spec.enabled:
            self._scheduler.pause_job(spec.id)

        # update next_run
        aps_job = self._scheduler.get_job(spec.id)
        st = self._states.get(spec.id, CronJobState())
        st.next_run_at = aps_job.next_run_time if aps_job else None
        self._states[spec.id] = st

    def _build_trigger(self, spec: CronJobSpec) -> CronTrigger:
        # enforce 5 fields (no seconds)
        parts = [p for p in spec.schedule.cron.split() if p]
        if len(parts) != 5:
            raise ConfigurationException(
                message=(
                    f"cron must have 5 fields, "
                    f"got {len(parts)}: {spec.schedule.cron}"
                ),
            )

        minute, hour, day, month, day_of_week = parts
        return CronTrigger(
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=day_of_week,
            timezone=spec.schedule.timezone,
        )

    def _build_heartbeat_trigger(
        self,
        every: str,
    ) -> Union[CronTrigger, IntervalTrigger]:
        """Build a trigger from the heartbeat *every* value.

        Returns CronTrigger for cron expressions,
        IntervalTrigger for interval strings.
        """
        if is_cron_expression(every):
            minute, hour, day, month, day_of_week = parse_heartbeat_cron(every)
            return CronTrigger(
                minute=minute,
                hour=hour,
                day=day,
                month=month,
                day_of_week=day_of_week,
            )
        interval_seconds = parse_heartbeat_every(every)
        return IntervalTrigger(seconds=interval_seconds)

    async def _scheduled_callback(self, job_id: str) -> None:
        job = await self._repo.get_job(job_id)
        if not job:
            return

        # Track the scheduled execution as well so stop()/delete_job()
        # can cancel it and we do not leak state writes after shutdown.
        current = asyncio.current_task()
        if current is not None:
            self._track_job_task(job_id, current)
        try:
            try:
                await self._execute_once(job)
            except Exception:  # pylint: disable=broad-except
                # _execute_once already logged and persisted error status.
                # Swallow here so that APScheduler does not double-report
                # and so we still refresh next_run_at below.
                # Note: asyncio.CancelledError is BaseException in Python
                # 3.8+ and is not caught here, so cancellation still
                # propagates up correctly.
                pass

            # Refresh next_run_at, but only if the job still exists.
            # Otherwise a concurrent delete_job() would get its state
            # resurrected by this write.
            if (
                job_id not in self._states
                and (await self._repo.get_job(job_id)) is None
            ):
                return
            aps_job = self._scheduler.get_job(job_id)
            st = self._states.get(job_id, CronJobState()).model_copy()
            st.next_run_at = aps_job.next_run_time if aps_job else None
            if job_id in self._states or aps_job is not None:
                self._states[job_id] = st
        finally:
            if current is not None:
                self._untrack_job_task(job_id, current)

    async def _heartbeat_callback(self) -> None:
        """Run one heartbeat (HEARTBEAT.md as query, optional dispatch)."""
        try:
            # Get workspace_dir from runner if available
            workspace_dir = None
            if hasattr(self._runner, "workspace_dir"):
                workspace_dir = self._runner.workspace_dir

            await run_heartbeat_once(
                runner=self._runner,
                channel_manager=self._channel_manager,
                agent_id=self._agent_id,
                workspace_dir=workspace_dir,
            )
        except asyncio.CancelledError:
            logger.info("heartbeat cancelled")
            raise
        except Exception:  # pylint: disable=broad-except
            logger.exception("heartbeat run failed")

    async def _dream_callback(self) -> None:
        """Run one dream-based memory optimization task."""
        try:
            # Run dream task
            await self._runner.memory_manager.dream()
            logger.debug("Dream task executed successfully")
        except asyncio.CancelledError:
            logger.info("Dream task was cancelled")
            raise
        except Exception as e:  # pylint: disable=broad-except
            logger.error(f"Failed to execute dream task: {e}", exc_info=True)

    async def _execute_once(self, job: CronJobSpec) -> None:
        assert job.id is not None, "Job must have an id"
        rt = self._rt.get(job.id)
        if rt is None:
            # The job is no longer managed (likely deleted while this
            # execution was pending). Do NOT recreate the _Runtime here:
            # that would resurrect runtime state for a deleted job, which
            # is exactly the concurrency state leak we are fixing. Abort
            # silently instead.
            logger.info(
                "cron _execute_once skipped: job_id=%s runtime missing "
                "(job likely deleted)",
                job.id,
            )
            return

        async with rt.sem:
            # Work on a *local* CronJobState so that parallel executions
            # for the same job (max_concurrency > 1) and for different
            # jobs do not share a mutable instance. Without this, one
            # run's fields (e.g. last_error) leak into another run's
            # final state.
            st = self._states.get(job.id, CronJobState()).model_copy()
            st.last_status = "running"
            self._publish_state(job.id, st)

            try:
                await self._executor.execute(job)
                st.last_status = "success"
                st.last_error = None
                logger.info(
                    "cron _execute_once: job_id=%s status=success",
                    job.id,
                )
            except asyncio.CancelledError:
                st.last_status = "cancelled"
                st.last_error = "Job was cancelled"
                logger.info(
                    "cron _execute_once: job_id=%s status=cancelled",
                    job.id,
                )
                raise
            except Exception as e:  # pylint: disable=broad-except
                st.last_status = "error"
                st.last_error = repr(e)
                logger.warning(
                    "cron _execute_once: job_id=%s status=error error=%s",
                    job.id,
                    repr(e),
                )
                raise
            finally:
                st.last_run_at = datetime.now(timezone.utc)
                self._publish_state(job.id, st)

    def _publish_state(self, job_id: str, state: CronJobState) -> None:
        """Publish a per-run state snapshot back to the shared dict.

        The write is skipped if the job has been deleted (its runtime
        entry is gone) so that in-flight executions cannot resurrect
        state for a removed job.
        """
        if job_id not in self._rt:
            return
        # Preserve next_run_at that may have been set by the scheduler
        # callback (the execution path never owns this field).
        existing = self._states.get(job_id)
        if existing is not None and existing.next_run_at is not None:
            state = state.model_copy(
                update={"next_run_at": existing.next_run_at},
            )
        self._states[job_id] = state
