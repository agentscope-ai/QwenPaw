# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import copy
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Literal, Optional, Union
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.events import (
    EVENT_JOB_MAX_INSTANCES,
    EVENT_JOB_MISSED,
    JobExecutionEvent,
    JobSubmissionEvent,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from qwenpaw.exceptions import ConfigurationException

from ...config import get_heartbeat_config
from ..inbox_store import append_event as append_inbox_event

from ..console_push_store import append as push_store_append
from .contracts import ServiceCronJob
from .executor import CronExecutor
from .heartbeat import (
    is_cron_expression,
    parse_heartbeat_cron,
    parse_heartbeat_every,
    run_heartbeat_once,
)
from .models import (
    CronExecutionRecord,
    CronJobSpec,
    CronJobState,
)
from .repo.base import BaseJobRepository
from ...api_action import ManagerBase, api_action

HEARTBEAT_JOB_ID = "_heartbeat"
HEARTBEAT_MISFIRE_GRACE_SECONDS = 60
SERVICE_JOB_ID_PREFIX = "_service:"
INTERNAL_JOB_IDS = frozenset({HEARTBEAT_JOB_ID})
CRON_HISTORY_LIMIT = 50
# Periodic self-contained keepalive so the asyncio event loop keeps ticking
# even with no external traffic. APScheduler's AsyncIOScheduler processes
# due jobs via loop call_later wakeups; on some platforms (e.g. WSL2) a
# long-delay call_later does not reliably wake an otherwise-idle loop, so
# cron jobs misfire until the next HTTP request arrives (see issue #6471).
# A short, always-on keepalive task keeps loop._run_once sweeping due
# timers regardless of the heartbeat config.
CRON_KEEPALIVE_INTERVAL_SECONDS = 60

logger = logging.getLogger(__name__)


@dataclass
class _Runtime:
    sem: asyncio.Semaphore


class CronManager(ManagerBase):
    endpoint_prefix = "crons"

    def __init__(
        self,
        *,
        repo: BaseJobRepository,
        workspace: Any,
        channel_manager: Any,
        timezone: str = "UTC",  # pylint: disable=redefined-outer-name
        agent_id: Optional[str] = None,
    ):
        self._repo = repo
        self._workspace = workspace
        self._channel_manager = channel_manager
        self._agent_id = agent_id
        self._scheduler = AsyncIOScheduler(timezone=timezone)
        self._executor = CronExecutor(
            workspace=workspace,
            channel_manager=channel_manager,
        )

        self._lock = asyncio.Lock()
        self._states: Dict[str, CronJobState] = {}
        self._history: Dict[str, list[CronExecutionRecord]] = {}
        self._rt: Dict[str, _Runtime] = {}
        self._started = False
        self._keepalive_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        async with self._lock:
            if self._started:
                return
            jobs_file = await self._repo.load()
            valid_job_ids = {
                job.id for job in jobs_file.jobs if job.id is not None
            }
            await self._repo.prune_orphan_history(valid_job_ids)

            self._register_scheduler_listeners()
            self._scheduler.start()
            for job in jobs_file.jobs:
                try:
                    if self._requires_portability_review(job):
                        repaired = self.canonicalize_imported_job_for_review(
                            job,
                        )
                        if repaired != job:
                            job = repaired
                            await self._repo.upsert_job(job)
                            logger.warning(
                                "Repaired and disabled imported cron job "
                                "pending review: job_id=%s name=%s",
                                job.id,
                                job.name,
                            )
                    await self._register_or_update(job)
                except Exception as e:  # pylint: disable=broad-except
                    logger.warning(
                        "Skipping invalid cron job during startup: "
                        "job_id=%s name=%s schedule_type=%s cron=%s "
                        "run_at=%s error=%s",
                        job.id,
                        job.name,
                        job.schedule.type,
                        job.schedule.cron,
                        job.schedule.run_at,
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
                    misfire_grace_time=HEARTBEAT_MISFIRE_GRACE_SECONDS,
                    replace_existing=True,
                )
                logger.info(
                    "Heartbeat job scheduled for agent %s: every=%s",
                    self._agent_id,
                    hb.every,
                )

            self._register_memory_jobs()

            self._started = True
            self._keepalive_task = asyncio.create_task(
                self._keepalive_loop(),
                name="cron-keepalive",
            )

    async def stop(self) -> None:
        async with self._lock:
            if not self._started:
                return
            self._started = False
            keepalive = self._keepalive_task
            self._keepalive_task = None
            if keepalive is not None:
                keepalive.cancel()
                try:
                    await asyncio.wait_for(keepalive, timeout=5)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass
                except Exception as exc:  # pylint: disable=broad-except
                    logger.debug(
                        "Error cancelling cron keepalive task: %s",
                        repr(exc),
                    )
            self._scheduler.shutdown(wait=False)

    async def _keepalive_loop(self) -> None:
        """Keep the asyncio event loop ticking while cron is running.

        APScheduler's AsyncIOScheduler processes due jobs via loop
        call_later wakeups. On platforms where a long-delay call_later
        does not reliably wake an otherwise-idle event loop (e.g. WSL2,
        see issue #6471), cron jobs misfire until external I/O wakes the
        loop. This self-contained task sleeps for a short, reliable
        interval so the loop keeps sweeping due timers regardless of
        external traffic or the heartbeat config.
        """
        try:
            while self._started:
                await asyncio.sleep(CRON_KEEPALIVE_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            pass

    # ----- read/state -----

    @api_action(
        methods={"http", "cli", "slash"},
        http_method="GET",
        http_path="/crons/jobs",
        slash_command="cron-list",
    )
    async def list_jobs(self) -> list[CronJobSpec]:
        return await self._repo.list_jobs()

    async def get_job(self, job_id: str) -> Optional[CronJobSpec]:
        return await self._repo.get_job(job_id)

    def get_state(self, job_id: str) -> CronJobState:
        return self._states.get(job_id, CronJobState())

    async def get_history(self, job_id: str) -> list[CronExecutionRecord]:
        if job_id not in self._history:
            self._history[job_id] = await self._repo.get_history(job_id)
        return self._history[job_id]

    def validate_job_spec(self, spec: CronJobSpec) -> None:
        """Fully validate scheduler registration without changing state."""
        if spec.id is None:
            raise ValueError("Job must have an id before registration")
        self._build_trigger(spec)

    # ----- write/control -----

    @api_action(
        methods={"http", "cli", "slash"},
        http_method="POST",
        http_path="/crons/jobs",
        request_model=CronJobSpec,
        slash_command="cron-create",
    )
    async def create_or_replace_job(self, spec: CronJobSpec) -> None:
        async with self._lock:
            previous = await self._repo.get_job(spec.id or "")
            await self._persist_and_register(spec, previous=previous)

    async def create_job_if_absent(self, spec: CronJobSpec) -> bool:
        """Create a job without replacing a concurrent or existing import."""
        async with self._lock:
            if await self._repo.get_job(spec.id or "") is not None:
                return False
            await self._persist_and_register(spec, previous=None)
            return True

    @api_action(
        methods={"http", "cli", "slash"},
        http_method="DELETE",
        http_path="/crons/jobs/{job_id}",
        slash_command="cron-delete",
    )
    async def delete_job(self, job_id: str) -> bool:
        async with self._lock:
            if self._started and self._scheduler.get_job(job_id):
                self._scheduler.remove_job(job_id)
            self._states.pop(job_id, None)
            self._history.pop(job_id, None)
            await self._repo.delete_history(job_id)
            self._rt.pop(job_id, None)
            return await self._repo.delete_job(job_id)

    async def pause_job(self, job_id: str) -> None:
        async with self._lock:
            job = await self._repo.get_job(job_id)
            if job is None:
                raise KeyError(f"Job not found: {job_id}")
            disabled_job = job.model_copy(update={"enabled": False})
            await self._repo.upsert_job(disabled_job)
            if self._scheduler.get_job(job_id):
                self._scheduler.pause_job(job_id)

    async def resume_job(self, job_id: str) -> None:
        async with self._lock:
            job = await self._repo.get_job(job_id)
            if job is None:
                raise KeyError(f"Job not found: {job_id}")
            self._assert_review_complete(job)
            enabled_job = job.model_copy(update={"enabled": True})
            await self._persist_and_register(enabled_job, previous=job)

    async def promote_imported_job(
        self,
        job_id: str,
        *,
        actor: Optional[str] = None,
    ) -> CronJobSpec:
        """Clear an imported job's review gate without enabling it."""
        async with self._lock:
            job = await self._repo.get_job(job_id)
            if job is None:
                raise KeyError(f"Job not found: {job_id}")
            if not self._requires_portability_review(job):
                raise ValueError(f"Job does not require promotion: {job_id}")
            self._assert_promotion_workspace_is_local(job)

            promoted = self._with_portability_review(
                job,
                pending=False,
                actor=actor,
            )
            await self._persist_and_register(
                promoted,
                previous=job,
                allow_gate_clear=True,
            )
            return promoted

    async def _persist_and_register(  # pylint: disable=too-many-branches
        self,
        spec: CronJobSpec,
        *,
        previous: Optional[CronJobSpec],
        allow_gate_clear: bool = False,
    ) -> None:
        """Persist and register atomically, restoring both sides on failure."""
        self.validate_job_spec(spec)
        assert spec.id is not None
        if not allow_gate_clear:
            self._validate_review_gate_update(previous, spec)

        job_id = spec.id
        old_runtime = self._rt.get(job_id)
        old_state = self._states.get(job_id)
        await self._repo.upsert_job(spec)
        try:
            if self._started:
                await self._register_or_update(spec)
        except Exception:
            try:
                if previous is None:
                    await self._repo.delete_job(job_id)
                else:
                    await self._repo.upsert_job(previous)

                if self._started:
                    if previous is None:
                        if self._scheduler.get_job(job_id):
                            self._scheduler.remove_job(job_id)
                    else:
                        await self._register_or_update(previous)

                if old_runtime is None:
                    self._rt.pop(job_id, None)
                else:
                    self._rt[job_id] = old_runtime
                if old_state is None:
                    self._states.pop(job_id, None)
                else:
                    self._states[job_id] = old_state
            except Exception:  # pylint: disable=broad-except
                logger.exception(
                    "Failed to roll back cron job transaction: job_id=%s",
                    job_id,
                )
            raise

    @staticmethod
    def _portability_metadata(job: CronJobSpec) -> Optional[Dict[str, Any]]:
        candidates = CronManager._portability_metadata_candidates(job)
        return next(
            (
                value
                for value in candidates
                if CronManager._has_imported_provenance(value)
            ),
            candidates[0] if candidates else None,
        )

    @staticmethod
    def _portability_metadata_candidates(
        job: CronJobSpec,
    ) -> list[Dict[str, Any]]:
        candidates: list[Dict[str, Any]] = []
        for container in (job.meta, job.dispatch.meta):
            portability = container.get("portability")
            if isinstance(portability, dict) and portability not in candidates:
                candidates.append(portability)
        return candidates

    @staticmethod
    def _request_review_marker(job: CronJobSpec) -> Any:
        return CronManager._request_context(job).get(
            "portability_review_required",
        )

    @staticmethod
    def _request_context(job: CronJobSpec) -> Dict[str, Any]:
        context = getattr(job.request, "request_context", None)
        return context if isinstance(context, dict) else {}

    @staticmethod
    def _has_imported_provenance(portability: Dict[str, Any]) -> bool:
        return all(
            isinstance(value, str) and value.strip()
            for value in (
                portability.get("source"),
                portability.get("source_id"),
            )
        )

    @classmethod
    def _requires_portability_review(cls, job: CronJobSpec) -> bool:
        candidates = cls._portability_metadata_candidates(job)
        request_marker = cls._request_review_marker(job)
        if not candidates:
            return request_marker is True

        if any(
            bool(portability.get("requires_review"))
            or portability.get("safety") == "disabled_until_explicit_promotion"
            for portability in candidates
        ):
            return True

        imported = any(
            cls._has_imported_provenance(portability)
            for portability in candidates
        )
        if not imported:
            return request_marker is True

        # Imported provenance is fail-closed.  Older or partially damaged
        # records often lack the newer review fields; they are pending until
        # the dedicated promotion path writes a complete, internally
        # consistent decision to every copy of the metadata.
        explicitly_promoted = request_marker is False and all(
            portability.get("requires_review") is False
            and portability.get("safety") == "reviewed_disabled"
            and isinstance(portability.get("promoted_at"), str)
            and portability.get("promoted_at", "").strip()
            for portability in candidates
        )
        return not explicitly_promoted

    @classmethod
    def canonicalize_imported_job_for_review(
        cls,
        job: CronJobSpec,
    ) -> CronJobSpec:
        """Repair a pending imported job's duplicated review markers."""
        portability = cls._portability_metadata(job)
        if portability is None or not cls._has_imported_provenance(
            portability,
        ):
            return job
        return cls._with_portability_review(job, pending=True)

    @classmethod
    def _assert_review_complete(cls, job: CronJobSpec) -> None:
        if cls._requires_portability_review(job):
            raise PermissionError(
                "Imported cron job requires explicit promotion before "
                f"execution or enablement: {job.id}",
            )

    @classmethod
    def _assert_promotion_workspace_is_local(cls, job: CronJobSpec) -> None:
        portability = cls._portability_metadata(job) or {}
        requires_mapping = (
            portability.get("source_cwd_remote_or_unverified") is True
            or portability.get("source_cwd_binding")
            == "omitted_remote_or_unverified"
        )
        if not requires_mapping:
            return

        project_dir = cls._request_context(job).get("project_dir")
        if not isinstance(project_dir, str) or not project_dir.strip():
            raise PermissionError(
                "Remote or unverified imported cron jobs require an explicit "
                "local project_dir before promotion",
            )
        try:
            local_dir = Path(project_dir).expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise PermissionError(
                "The explicit local project_dir cannot be resolved before "
                "promotion",
            ) from exc
        if not local_dir.is_dir():
            raise PermissionError(
                "The explicit local project_dir must be an existing directory "
                "before promotion",
            )

    @classmethod
    def _validate_review_gate_update(
        cls,
        previous: Optional[CronJobSpec],
        replacement: CronJobSpec,
    ) -> None:
        if cls._requires_portability_review(replacement):
            if replacement.enabled:
                raise PermissionError(
                    "Imported cron jobs must remain disabled until explicit "
                    f"promotion: {replacement.id}",
                )
            if (
                previous is not None
                and cls._requires_portability_review(previous)
                and cls.canonicalize_imported_job_for_review(replacement)
                != replacement
            ):
                raise PermissionError(
                    "The portability review gate can only be cleared by "
                    f"promote_imported_job: {previous.id}",
                )
            return
        if previous is not None and cls._requires_portability_review(previous):
            raise PermissionError(
                "The portability review gate can only be cleared by "
                f"promote_imported_job: {previous.id}",
            )

    @classmethod
    def _with_portability_review(
        cls,
        job: CronJobSpec,
        *,
        pending: bool,
        actor: Optional[str] = None,
    ) -> CronJobSpec:
        """Write one review state to all duplicated Cron payload fields."""
        updated = job.model_copy(deep=True)
        portability = cls._portability_metadata(updated) or {}
        portability["requires_review"] = pending
        portability["safety"] = (
            "disabled_until_explicit_promotion"
            if pending
            else "reviewed_disabled"
        )
        if pending:
            portability.pop("promoted_at", None)
            portability.pop("promoted_by", None)
        else:
            portability["promoted_at"] = datetime.now(timezone.utc).isoformat()
            if actor:
                portability["promoted_by"] = actor

        updated.meta["portability"] = copy.deepcopy(portability)
        updated.dispatch.meta["portability"] = copy.deepcopy(portability)
        if updated.request is not None:
            context = cls._request_context(updated)
            context["portability_review_required"] = pending
            updated.request.request_context = context
        updated.enabled = False
        return updated

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
                    misfire_grace_time=HEARTBEAT_MISFIRE_GRACE_SECONDS,
                    replace_existing=True,
                )
                logger.info(
                    "heartbeat rescheduled: every=%s",
                    hb.every,
                )
            else:
                logger.info("heartbeat disabled, job removed")

    def _register_memory_jobs(self) -> None:
        memory_manager = getattr(self._workspace, "memory_manager", None)
        if memory_manager is None:
            declarations: list[ServiceCronJob] = []
        else:
            try:
                declarations = list(memory_manager.list_cron_jobs())
            except Exception:  # pylint: disable=broad-except
                logger.exception(
                    "Failed to load cron jobs from memory manager "
                    "for agent %s",
                    self._agent_id,
                )
                return
        self._register_service_jobs("memory", declarations)

    def _register_service_jobs(
        self,
        source: str,
        declarations: list[ServiceCronJob],
    ) -> None:
        """Register jobs declared by one workspace service."""
        declared_ids: set[str] = set()

        for declaration in declarations:
            try:
                job_id = self._service_job_id(source, declaration.key)
            except ValueError as exc:
                logger.error(
                    "Ignoring invalid %s cron job key %r: %s",
                    source,
                    declaration.key,
                    exc,
                )
                continue
            if job_id in declared_ids:
                logger.error(
                    "Ignoring duplicate %s cron job key: %s",
                    source,
                    declaration.key,
                )
                continue
            declared_ids.add(job_id)

            try:
                parts = declaration.cron.split()
                if len(parts) != 5:
                    raise ValueError("cron must have exactly 5 fields")
                minute, hour, day, month, day_of_week = parts
                trigger = CronTrigger(
                    minute=minute,
                    hour=hour,
                    day=day,
                    month=month,
                    day_of_week=day_of_week,
                    timezone=self._scheduler.timezone,
                    jitter=declaration.jitter_seconds or None,
                )
                self._scheduler.add_job(
                    self._run_service_job,
                    trigger=trigger,
                    id=job_id,
                    args=[source, declaration],
                    misfire_grace_time=declaration.misfire_grace_seconds,
                    replace_existing=True,
                )
                logger.info(
                    "%s cron job scheduled: key=%s cron=%s",
                    source,
                    declaration.key,
                    declaration.cron,
                )
            except Exception as exc:  # pylint: disable=broad-except
                logger.error(
                    "Failed to schedule %s cron job: key=%s cron=%s "
                    "error=%r",
                    source,
                    declaration.key,
                    declaration.cron,
                    exc,
                )

    @staticmethod
    def _service_job_id(source: str, key: str) -> str:
        if not source or not key or ":" in source or ":" in key:
            raise ValueError(
                "source/key must be non-empty and cannot contain ':'",
            )
        return f"{SERVICE_JOB_ID_PREFIX}{source}:{key}"

    async def run_job(self, job_id: str) -> None:
        """Trigger a job to run in the background (fire-and-forget).

        Raises KeyError if the job does not exist.
        The actual execution happens asynchronously; errors are logged
        and reflected in the job state but NOT propagated to the caller.
        """
        job = await self._repo.get_job(job_id)
        if not job:
            raise KeyError(f"Job not found: {job_id}")
        self._assert_review_complete(job)
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
            self._execute_once(
                job,
                trigger="manual",
            ),
            name=f"cron-run-{job_id}",
        )
        task.add_done_callback(lambda t: self._task_done_cb(t, job))

    # ----- callbacks -----

    def _task_done_cb(self, task: asyncio.Task, job: CronJobSpec) -> None:
        """Suppress and log exceptions from fire-and-forget tasks.

        On failure, push an error message to the console push store so
        the frontend can display it.
        """
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
                asyncio.ensure_future(
                    push_store_append(session_id, error_text),
                )

    # ----- internal -----

    def _register_scheduler_listeners(self) -> None:
        mask = EVENT_JOB_MISSED | EVENT_JOB_MAX_INSTANCES
        self._scheduler.add_listener(self._on_scheduler_event, mask=mask)

    def _on_scheduler_event(
        self,
        event: JobExecutionEvent | JobSubmissionEvent,
    ) -> None:
        if event.code == EVENT_JOB_MISSED:
            asyncio.create_task(self._handle_job_missed(event))
        elif event.code == EVENT_JOB_MAX_INSTANCES:
            asyncio.create_task(self._handle_job_max_instances(event))

    async def _handle_job_missed(self, event: JobExecutionEvent) -> None:
        job_id = event.job_id
        if self._is_internal_job(job_id):
            return

        job = await self._repo.get_job(job_id)
        if not job:
            return

        scheduled = event.scheduled_run_time
        if scheduled.tzinfo is None:
            scheduled = scheduled.replace(tzinfo=timezone.utc)
        late_seconds = max(
            0,
            int((datetime.now(timezone.utc) - scheduled).total_seconds()),
        )
        grace = job.runtime.misfire_grace_seconds
        error_msg = (
            f"missed scheduled run at {scheduled.isoformat()}: "
            f"late by {late_seconds}s, grace={grace}s"
        )
        await self._record_skipped(job, error_msg)

    async def _handle_job_max_instances(
        self,
        event: JobSubmissionEvent,
    ) -> None:
        job_id = event.job_id
        if self._is_internal_job(job_id):
            return

        job = await self._repo.get_job(job_id)
        if not job:
            return

        scheduled_times = event.scheduled_run_times or []
        if scheduled_times:
            # coalesce may queue multiple due times;
            # [-1] is the latest skipped slot.
            scheduled = scheduled_times[-1]
            if scheduled.tzinfo is None:
                scheduled = scheduled.replace(tzinfo=timezone.utc)
            scheduled_text = scheduled.isoformat()
        else:
            scheduled_text = "unknown"
        error_msg = (
            f"skipped scheduled run at {scheduled_text}: "
            f"maximum running instances reached "
            f"({job.runtime.max_concurrency})"
        )
        await self._record_skipped(job, error_msg)

    @staticmethod
    def _is_internal_job(job_id: str) -> bool:
        return job_id in INTERNAL_JOB_IDS or job_id.startswith(
            SERVICE_JOB_ID_PREFIX,
        )

    async def _record_skipped(self, job: CronJobSpec, error_msg: str) -> None:
        if job.id is None:
            logger.error(
                "cron _record_skipped: job.id is None, skipping record",
            )
            return
        logger.warning(
            "cron job skipped: job_id=%s name=%s %s",
            job.id,
            job.name,
            error_msg,
        )

        st = self._states.get(job.id, CronJobState())
        st.last_status = "skipped"
        st.last_error = error_msg
        aps_job = self._scheduler.get_job(job.id)
        st.next_run_at = aps_job.next_run_time if aps_job else st.next_run_at
        self._states[job.id] = st

        record = CronExecutionRecord(
            run_at=self._now_in_job_timezone(job),
            status="skipped",
            error=error_msg,
            trigger="scheduled",
        )
        records = await self._repo.append_history(
            job.id,
            record,
            limit=CRON_HISTORY_LIMIT,
        )
        self._history[job.id] = records

    async def _register_or_update(self, spec: CronJobSpec) -> None:
        # Validate and build trigger first. If schedule is invalid, fail fast
        # without mutating scheduler/runtime state.
        assert spec.id is not None, "Job must have an id"
        trigger = self._build_trigger(spec)

        add_job_kwargs: Dict[str, Any] = {}
        if not spec.enabled or self._requires_portability_review(spec):
            # Register directly in the paused state.  This avoids a window in
            # which a disabled imported task could become due between add_job
            # and a subsequent pause_job call.
            add_job_kwargs["next_run_time"] = None

        self._scheduler.add_job(
            self._scheduled_callback,
            trigger=trigger,
            id=spec.id,
            args=[spec.id],
            misfire_grace_time=spec.runtime.misfire_grace_seconds,
            replace_existing=True,
            **add_job_kwargs,
        )

        # Only publish new runtime state after APScheduler accepted the whole
        # registration.  add_job(replace_existing=True) preserves the old job
        # if construction/validation fails.
        self._rt[spec.id] = _Runtime(
            sem=asyncio.Semaphore(spec.runtime.max_concurrency),
        )

        # update next_run
        aps_job = self._scheduler.get_job(spec.id)
        st = self._states.get(spec.id, CronJobState())
        st.next_run_at = aps_job.next_run_time if aps_job else None
        self._states[spec.id] = st

    def _build_trigger(
        self,
        spec: CronJobSpec,
    ) -> Union[CronTrigger, DateTrigger, IntervalTrigger]:
        if spec.schedule.type == "once":
            assert spec.schedule.run_at is not None
            if spec.schedule.repeat_every_days:
                end_date: datetime | None = None
                if (
                    spec.schedule.repeat_end_type == "until"
                    and spec.schedule.repeat_until is not None
                ):
                    end_date = spec.schedule.repeat_until
                elif (
                    spec.schedule.repeat_end_type == "count"
                    and spec.schedule.repeat_count is not None
                ):
                    end_date = spec.schedule.run_at + timedelta(
                        days=spec.schedule.repeat_every_days
                        * (spec.schedule.repeat_count - 1),
                    )
                return IntervalTrigger(
                    days=spec.schedule.repeat_every_days,
                    start_date=spec.schedule.run_at,
                    end_date=end_date,
                    timezone=spec.schedule.timezone,
                )
            return DateTrigger(
                run_date=spec.schedule.run_at,
                timezone=spec.schedule.timezone,
            )

        # enforce 5 fields (no seconds)
        assert spec.schedule.cron is not None
        parts = [p for p in spec.schedule.cron.split() if p]
        if len(parts) != 5:
            raise ConfigurationException(
                config_key="cron.schedule.cron",
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
        if self._requires_portability_review(job):
            await self._record_skipped(
                job,
                "Imported cron job is awaiting explicit promotion",
            )
            return

        await self._execute_once(
            job,
            trigger="scheduled",
        )

        # refresh next_run
        aps_job = self._scheduler.get_job(job_id)
        st = self._states.get(job_id, CronJobState())
        st.next_run_at = aps_job.next_run_time if aps_job else None
        self._states[job_id] = st

    @staticmethod
    def _now_in_job_timezone(job: CronJobSpec) -> datetime:
        tz_name = job.schedule.timezone or "UTC"
        try:
            tz = ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, ValueError):
            logger.warning(
                "Invalid cron job timezone, using UTC: job_id=%s "
                "timezone=%s",
                job.id,
                tz_name,
            )
            tz = timezone.utc
        return datetime.now(tz)

    async def _heartbeat_callback(self) -> None:
        """Run one heartbeat (HEARTBEAT.md as query, optional dispatch)."""
        try:
            workspace_dir = getattr(
                self._workspace,
                "workspace_dir",
                None,
            )

            await run_heartbeat_once(
                workspace=self._workspace,
                channel_manager=self._channel_manager,
                agent_id=self._agent_id,
                workspace_dir=workspace_dir,
            )
        except asyncio.CancelledError:
            logger.info("heartbeat cancelled")
            raise
        except Exception:  # pylint: disable=broad-except
            logger.exception("heartbeat run failed")

    async def _run_service_job(
        self,
        source: str,
        declaration: ServiceCronJob,
    ) -> None:
        """Run a service-contributed job with common scheduler behavior."""
        try:
            await declaration.callback()
            logger.debug(
                "%s cron job executed successfully: %s",
                source,
                declaration.key,
            )
        except asyncio.CancelledError:
            logger.info(
                "%s cron job was cancelled: %s",
                source,
                declaration.key,
            )
            raise
        except Exception as exc:  # pylint: disable=broad-except
            logger.error(
                "Failed to execute %s cron job %s: %s",
                source,
                declaration.key,
                exc,
                exc_info=True,
            )

    # pylint: disable-next=too-many-branches,too-many-statements
    async def _execute_once(
        self,
        job: CronJobSpec,
        *,
        trigger: Literal["scheduled", "manual"] = "scheduled",
    ) -> None:
        assert job.id is not None, "Job must have an id"
        self._assert_review_complete(job)
        rt = self._rt.get(job.id)
        if not rt:
            rt = _Runtime(sem=asyncio.Semaphore(job.runtime.max_concurrency))
            self._rt[job.id] = rt

        async with rt.sem:
            st = self._states.get(job.id, CronJobState())
            st.last_status = "running"
            self._states[job.id] = st
            execution_result: dict[str, Any] = {}
            execution_succeeded = False
            delivery_failed = False

            try:
                execution_result = await self._executor.execute(job)
                execution_succeeded = True
                delivery_failed = (
                    execution_result.get("delivery_status") == "failed"
                )
                if delivery_failed:
                    st.last_status = "error"
                    delivery_error = (
                        execution_result.get("delivery_error")
                        or "delivery failed"
                    )
                    st.last_error = f"delivery failed: {delivery_error}"
                else:
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
                st.last_run_at = self._now_in_job_timezone(job)
                self._states[job.id] = st
                record = CronExecutionRecord(
                    run_at=st.last_run_at,
                    status=st.last_status or "error",
                    error=st.last_error,
                    trigger=trigger,
                )
                records = await self._repo.append_history(
                    job.id,
                    record,
                    limit=CRON_HISTORY_LIMIT,
                )
                self._history[job.id] = records
                if execution_succeeded:
                    if delivery_failed:
                        try:
                            await append_inbox_event(
                                agent_id=self._agent_id,
                                source_type="cron",
                                source_id=job.id,
                                event_type="cron_delivery_failed_fallback",
                                status="error",
                                severity="error",
                                title=f"Cron result not delivered: {job.name}",
                                body=(
                                    "Task executed successfully, "
                                    "but channel delivery failed."
                                ),
                                payload={
                                    "job_id": job.id,
                                    "job_name": job.name,
                                    "task_type": job.task_type,
                                    "trigger": trigger,
                                    "run_id": execution_result.get("run_id"),
                                    "delivery_error": execution_result.get(
                                        "delivery_error",
                                    ),
                                },
                            )
                        except Exception:  # pylint: disable=broad-except
                            logger.exception(
                                "failed to append cron fallback event",
                            )
                    elif job.save_result_to_inbox:
                        if job.task_type == "text":
                            body = (job.text or "").strip()
                        else:
                            body = "Agent cron task finished successfully."
                        try:
                            await append_inbox_event(
                                agent_id=self._agent_id,
                                source_type="cron",
                                source_id=job.id,
                                event_type="cron_result",
                                status="success",
                                severity="info",
                                title=f"Cron result: {job.name}",
                                body=body,
                                payload={
                                    "job_id": job.id,
                                    "job_name": job.name,
                                    "task_type": job.task_type,
                                    "trigger": trigger,
                                    "run_id": execution_result.get("run_id"),
                                    "save_result_to_inbox": (
                                        job.save_result_to_inbox
                                    ),
                                },
                            )
                        except Exception:  # pylint: disable=broad-except
                            logger.exception(
                                "failed to append cron result inbox event",
                            )
