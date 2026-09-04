# -*- coding: utf-8 -*-
"""Persisted scan/apply jobs for the Console import workflow."""

from __future__ import annotations

import asyncio
import logging
import re
from collections import deque
from dataclasses import dataclass, field as dataclass_field
from functools import partial
from pathlib import Path
from typing import Any, AsyncIterator, Callable
from uuid import uuid4

from pydantic import BaseModel, Field

from ..utils.io_utils import read_json_async, write_json_atomic_async
from .adaptation_loop import drain_adaptation_workers, has_draining_workers
from .compatibility_safety import redact_sensitive_text
from .importer import ProviderImportService
from .models import (
    ImportAssetResult,
    ImportAssetState,
    ImportSelection,
    MigrationPlan,
)

_SUPPORTED_SOURCES = {"codex", "qoder"}
_TERMINAL = {"completed", "completed_with_issues", "failed", "interrupted"}
_CANCEL_GRACE_SECONDS = 3
_MAX_TERMINAL_JOBS = 16
_TYPE_FIELDS = {
    "memory": "memory",
    "scheduled_task": "cron",
    "skill": "skills",
    "mcp": "mcp",
    "plugin": "plugins",
}
logger = logging.getLogger(__name__)


class ImportProviderSnapshot(BaseModel):
    """One source in a UI import job."""

    source: str
    state: str = "scanning"
    plan_id: str = ""
    sessions_total: int = 0
    sessions_processed: int = 0
    sessions_imported: int = 0
    selection: ImportSelection = Field(default_factory=ImportSelection)
    assets: list[ImportAssetResult] = Field(default_factory=list)
    error: str = ""


class ImportRun(BaseModel):
    """Single durable state source for one import run."""

    job_id: str
    agent_id: str
    state: str = "scanning"
    seq: int = 0
    providers: list[ImportProviderSnapshot] = Field(default_factory=list)
    logs: list[str] = Field(default_factory=list)


@dataclass
class _LiveJob:
    workspace: Any
    snapshot: ImportRun
    plans: dict[str, MigrationPlan] = dataclass_field(default_factory=dict)
    events: deque[dict[str, Any]] = dataclass_field(
        default_factory=lambda: deque(maxlen=1),
    )
    subscribers: set[asyncio.Queue] = dataclass_field(default_factory=set)
    retry_selections: dict[str, ImportSelection] = dataclass_field(
        default_factory=dict,
    )
    asset_index: dict[
        tuple[str, str, str],
        ImportAssetResult,
    ] = dataclass_field(
        default_factory=dict,
    )
    progress_step: int = 1
    progress_updates: int = 0
    persist_lock: asyncio.Lock = dataclass_field(default_factory=asyncio.Lock)
    task: asyncio.Task | None = None
    cancel_requested: bool = False


class PortabilityImportJobManager:
    """Bridge the existing migration service to resumable UI jobs."""

    def __init__(
        self,
        *,
        service_factory: Callable[[Any], Any] = ProviderImportService,
    ) -> None:
        self._service_factory = service_factory
        self._jobs: dict[tuple[str, str], _LiveJob] = {}
        self._closing = False

    async def create(
        self,
        workspace: Any,
        sources: list[str],
    ) -> ImportRun:
        """Create a job and start source discovery in the background."""
        self._ensure_open()
        self._ensure_no_draining_workers(workspace)
        if await self.current(workspace):
            raise RuntimeError("an import is already active for this agent")
        normalized = list(dict.fromkeys(sources))
        if not normalized or any(
            item not in _SUPPORTED_SOURCES for item in normalized
        ):
            raise ValueError("sources must contain codex or qoder")
        job_id = f"import-{uuid4().hex}"
        snapshot = ImportRun(
            job_id=job_id,
            agent_id=workspace.agent_id,
            providers=[
                ImportProviderSnapshot(source=item) for item in normalized
            ],
        )
        live = _LiveJob(workspace=workspace, snapshot=snapshot)
        self._jobs[(workspace.agent_id, job_id)] = live
        await self._emit(live, persist=True)
        self._spawn(live, lambda: self._scan(live))
        return snapshot.model_copy(deep=True)

    async def start(
        self,
        workspace: Any,
        job_id: str,
        selections: dict[str, ImportSelection],
    ) -> ImportRun:
        """Apply the user selection for every successfully scanned source."""
        self._ensure_open()
        self._ensure_no_draining_workers(workspace)
        live = await self._live(workspace, job_id)
        if live.snapshot.state != "awaiting_selection":
            raise RuntimeError("import job is not awaiting selection")
        if any(
            item.snapshot.agent_id == workspace.agent_id
            and item.snapshot.state in {"running", "cancelling"}
            for item in self._jobs.values()
        ):
            raise RuntimeError("an import is already running for this agent")
        ready = {
            item.source
            for item in live.snapshot.providers
            if item.state == "ready"
        }
        if set(selections) != ready:
            raise ValueError("selection must cover every detected source")
        if not any(
            selection.sessions
            or any(
                getattr(selection, field) for field in _TYPE_FIELDS.values()
            )
            for selection in selections.values()
        ):
            raise ValueError("select at least one conversation or tool")
        for provider in live.snapshot.providers:
            if provider.source not in selections:
                continue
            provider.selection = selections[provider.source]
            provider.state = "pending"
            provider.assets = self._selected_assets(
                live.plans[provider.source],
                provider.selection,
            )
        self._prepare_progress(live)
        live.snapshot.state = "running"
        await self._emit(live, persist=True)
        self._spawn(live, lambda: self._apply(live))
        return live.snapshot.model_copy(deep=True)

    async def retry(
        self,
        workspace: Any,
        job_id: str,
        selections: dict[str, ImportSelection],
    ) -> ImportRun:
        """Retry explicitly selected failed tools in a fresh import job."""
        self._ensure_open()
        self._ensure_no_draining_workers(workspace)
        previous = await self._live(workspace, job_id)
        if previous.snapshot.state not in _TERMINAL:
            raise RuntimeError("import job has not finished")
        if any(
            item.snapshot.agent_id == workspace.agent_id
            and item.snapshot.state in {"running", "cancelling"}
            for item in self._jobs.values()
        ):
            raise RuntimeError("an import is already running for this agent")
        selected_sources = {
            source
            for source, selection in selections.items()
            if self._tool_ids(selection)
        }
        if not selected_sources or selected_sources != set(selections):
            raise ValueError("retry requires at least one selected tool")
        providers = {item.source: item for item in previous.snapshot.providers}
        if not selected_sources <= set(providers):
            raise ValueError("retry source is not part of the original import")
        for source, selection in selections.items():
            self._validate_retry_selection(providers[source], selection)
        retry_id = f"import-{uuid4().hex}"
        snapshot = previous.snapshot.model_copy(deep=True)
        snapshot = snapshot.model_copy(
            update={
                "job_id": retry_id,
                "state": "running",
                "seq": 0,
            },
        )
        for provider in snapshot.providers:
            selection = selections.get(provider.source)
            if selection is None:
                continue
            pending = {
                (item.asset_type, item.source_id): item
                for item in self._selected_assets(
                    previous.plans[provider.source],
                    selection,
                )
            }
            provider.assets = [
                pending.get((item.asset_type, item.source_id), item)
                for item in provider.assets
            ]
            provider.state = "pending"
            provider.error = ""
        live = _LiveJob(
            workspace=workspace,
            snapshot=snapshot,
            plans=dict(previous.plans),
            retry_selections=selections,
        )
        self._prepare_progress(live)
        self._jobs[(workspace.agent_id, retry_id)] = live
        await self._emit(live, persist=True)
        self._spawn(
            live,
            lambda: self._apply(live, retry_from=previous),
        )
        return snapshot.model_copy(deep=True)

    async def shutdown(self, *, drain_timeout: float = 5) -> None:
        """Stop active jobs before their workspace services close."""
        self._closing = True
        await asyncio.gather(
            *(
                self.cancel(live.workspace, live.snapshot.job_id)
                for live in tuple(self._jobs.values())
                if live.snapshot.state not in _TERMINAL
            ),
            return_exceptions=True,
        )
        await self.drain(timeout=drain_timeout)

    async def drain(self, *, timeout: float = 5) -> None:
        """Give live jobs and registered Mission workers one bounded drain."""
        tasks = [
            live.task
            for live in self._jobs.values()
            if live.task is not None and not live.task.done()
        ]
        workers = asyncio.create_task(
            drain_adaptation_workers(timeout=timeout),
        )
        _done, pending = (
            await asyncio.wait(tasks, timeout=timeout)
            if tasks
            else (set(), set())
        )
        worker_count = await workers
        if pending or worker_count:
            logger.warning(
                "Import workers still draining: jobs=%d mission=%d",
                len(pending),
                worker_count,
            )

    async def cancel(
        self,
        workspace: Any,
        job_id: str,
    ) -> ImportRun:
        """Request one active import to stop without waiting indefinitely."""
        live = await self._live(workspace, job_id)
        if live.snapshot.state in _TERMINAL:
            return live.snapshot.model_copy(deep=True)
        cancel_error = ""
        live.cancel_requested = True
        if live.snapshot.state != "cancelling":
            live.snapshot.state = "cancelling"
            self._log(live, "正在停止导入，等待当前安全操作结束。")
            await self._emit(live, persist=True)
        if live.task is not None and not live.task.done():
            live.task.cancel()
            done, _ = await asyncio.wait(
                {live.task},
                timeout=_CANCEL_GRACE_SECONDS,
            )
            if not done:
                return live.snapshot.model_copy(deep=True)
            try:
                await live.task
            except asyncio.CancelledError:
                pass
            except Exception as exc:  # pylint: disable=broad-except
                cancel_error = redact_sensitive_text(exc, limit=500)
        if live.snapshot.state not in _TERMINAL:
            if cancel_error:
                live.snapshot.state = "failed"
                self._log(live, cancel_error)
                for provider in live.snapshot.providers:
                    if provider.state == "running":
                        provider.state = "failed"
                        provider.error = cancel_error
                await self._emit(live, persist=True)
            else:
                await self._mark_interrupted(live)
        return live.snapshot.model_copy(deep=True)

    def _ensure_open(self) -> None:
        if self._closing:
            raise RuntimeError("import service is shutting down")

    @staticmethod
    def _ensure_no_draining_workers(workspace: Any) -> None:
        if has_draining_workers(workspace):
            raise RuntimeError(
                "a compatibility worker is still stopping; "
                "retry after it exits",
            )

    def _spawn(self, live: _LiveJob, operation: Callable[[], Any]) -> None:
        async def run() -> None:
            try:
                await operation()
            except asyncio.CancelledError:
                await self._mark_interrupted(live)
                raise
            except Exception as exc:  # pylint: disable=broad-except
                if live.snapshot.state not in _TERMINAL:
                    live.snapshot.state = "failed"
                    self._log(live, redact_sensitive_text(exc, limit=500))
                    for provider in live.snapshot.providers:
                        if provider.state == "running":
                            provider.state = "failed"
                            provider.error = redact_sensitive_text(
                                exc,
                                limit=500,
                            )
                    await self._emit(live, persist=True)
            else:
                if (
                    live.cancel_requested
                    and live.snapshot.state not in _TERMINAL
                ):
                    await self._mark_interrupted(live)

        live.task = asyncio.create_task(run())

    async def _mark_interrupted(self, live: _LiveJob) -> None:
        if live.snapshot.state in _TERMINAL:
            return
        live.snapshot.state = "interrupted"
        for provider in live.snapshot.providers:
            if provider.state not in {"completed", "failed"}:
                provider.state = "failed"
                provider.error = "导入已取消。"
        await self._emit(live, persist=True)

    async def snapshot(self, workspace: Any, job_id: str) -> ImportRun:
        """Return current state, restoring a persisted job when needed."""
        key = (workspace.agent_id, job_id)
        live = self._jobs.get(key)
        if live:
            return live.snapshot.model_copy(deep=True)
        try:
            value = await read_json_async(self._path(workspace, job_id))
            snapshot = ImportRun.model_validate(value)
        except (FileNotFoundError, OSError, ValueError, TypeError) as exc:
            raise ValueError("import job not found or invalid") from exc
        if snapshot.agent_id != workspace.agent_id:
            raise ValueError("import job belongs to another agent")
        if snapshot.state in {"scanning", "running", "cancelling"}:
            snapshot.state = "interrupted"
            for provider in snapshot.providers:
                if provider.state not in {"completed", "failed"}:
                    provider.state = "failed"
                    provider.error = "导入因服务重启中断，请重试。"
                for asset in provider.assets:
                    if asset.state in {
                        ImportAssetState.PENDING,
                        ImportAssetState.REPAIRING,
                        ImportAssetState.READY,
                    }:
                        asset.state = ImportAssetState.FAILED
                        asset.message = "导入因服务重启中断，请重试。"
            await self._persist(workspace, snapshot)
        live = _LiveJob(workspace=workspace, snapshot=snapshot)
        self._prepare_progress(live)
        self._jobs[key] = live
        self._trim_terminal_jobs()
        return snapshot.model_copy(deep=True)

    async def current(self, workspace: Any) -> ImportRun | None:
        """Return this agent's active or resumable import job."""
        active = [
            live
            for (agent_id, _), live in self._jobs.items()
            if agent_id == workspace.agent_id
            and live.snapshot.state not in _TERMINAL
        ]
        if active:
            return active[-1].snapshot.model_copy(deep=True)
        directory = Path(workspace.workspace_dir) / ".qwenpaw/imports/jobs"
        try:
            paths = sorted(
                directory.glob("import-*.json"),
                key=lambda path: path.stat().st_mtime_ns,
                reverse=True,
            )[:64]
        except OSError:
            return None
        for path in paths:
            try:
                value = await read_json_async(path)
                snapshot = ImportRun.model_validate(value)
            except (OSError, ValueError, TypeError):
                continue
            if (
                snapshot.agent_id == workspace.agent_id
                and snapshot.state not in _TERMINAL
            ):
                snapshot = await self.snapshot(workspace, snapshot.job_id)
                if snapshot.state not in _TERMINAL:
                    return snapshot
        return None

    async def subscribe(
        self,
        workspace: Any,
        job_id: str,
        *,
        after: int = 0,
    ) -> AsyncIterator[dict[str, Any]]:
        """Replay the latest update, then stream updates through completion."""
        live = await self._live(workspace, job_id)
        queue: asyncio.Queue = asyncio.Queue(maxsize=1)
        live.subscribers.add(queue)
        delivered = after
        try:
            event = live.events[-1] if live.events else {}
            if event.get("seq", 0) <= after:
                if live.snapshot.seq > after:
                    event = {
                        "seq": live.snapshot.seq,
                        "snapshot": live.snapshot.model_dump(mode="json"),
                    }
            if event.get("seq", 0) > delivered:
                delivered = event["seq"]
                yield event
            if live.snapshot.state in _TERMINAL:
                return
            while True:
                event = await queue.get()
                if event["seq"] <= delivered:
                    continue
                delivered = event["seq"]
                yield event
                if event["snapshot"]["state"] in _TERMINAL:
                    return
        finally:
            live.subscribers.discard(queue)

    async def _scan(self, live: _LiveJob) -> None:
        async def scan(provider: ImportProviderSnapshot) -> None:
            service = self._service_factory(live.workspace)

            async def progress(message: str) -> None:
                self._log(live, message)
                await self._emit(live)

            try:
                plan = await service.plan_from(
                    provider.source,
                    progress=progress,
                )
                live.plans[provider.source] = plan
                provider.plan_id = plan.plan_id
                provider.sessions_total = sum(
                    item.asset_type == "session" for item in plan.actions
                )
                provider.selection = self._default_selection(plan)
                provider.assets = self._selected_assets(
                    plan,
                    self._all_selection(plan),
                )
                self._prepare_progress(live)
                provider.state = "ready"
            except Exception as exc:  # pylint: disable=broad-except
                provider.state = "failed"
                provider.error = redact_sensitive_text(exc, limit=500)
            await self._emit(live, persist=True)

        await asyncio.gather(*(scan(item) for item in live.snapshot.providers))
        if live.cancel_requested:
            await self._mark_interrupted(live)
            return
        live.snapshot.state = (
            "awaiting_selection"
            if any(item.state == "ready" for item in live.snapshot.providers)
            else "failed"
        )
        await self._emit(live, persist=True)

    async def _apply(  # pylint: disable=too-many-branches
        self,
        live: _LiveJob,
        *,
        retry_from: _LiveJob | None = None,
    ) -> None:
        for provider in live.snapshot.providers:
            if live.cancel_requested:
                await self._mark_interrupted(live)
                return
            if retry_from is None and provider.source not in live.plans:
                continue
            retry_selection = live.retry_selections.get(provider.source)
            if retry_from is not None and retry_selection is None:
                continue
            provider.state = "running"
            await self._emit(live, persist=True)

            try:
                service = self._service_factory(live.workspace)
                if retry_from is None:
                    plan = live.plans[provider.source]
                    imported_sessions = await service.apply_selection(
                        provider.plan_id,
                        provider.selection,
                        progress=partial(
                            self._apply_progress,
                            live,
                            provider,
                        ),
                    )
                else:
                    plan, imported_sessions = await service.retry_selection(
                        retry_from.plans[provider.source].plan_id,
                        retry_selection,
                        progress=partial(
                            self._apply_progress,
                            live,
                            provider,
                        ),
                    )
                    live.plans[provider.source] = plan
                    provider.plan_id = plan.plan_id
                retry_keys = (
                    self._tool_ids(retry_selection)
                    if retry_selection is not None
                    else None
                )
                for asset in provider.assets:
                    key = f"{asset.asset_type}:{asset.source_id}"
                    if (
                        retry_keys is None or key in retry_keys
                    ) and asset.state in {
                        ImportAssetState.PENDING,
                        ImportAssetState.REPAIRING,
                        ImportAssetState.READY,
                    }:
                        if asset.state not in {
                            ImportAssetState.SUCCEEDED,
                            ImportAssetState.FAILED,
                        }:
                            asset.state = ImportAssetState.FAILED
                            asset.message = "未收到资产导入结果，请重试。"
                if retry_from is None:
                    provider.sessions_processed = provider.sessions_total
                    provider.sessions_imported = len(imported_sessions)
                provider.state = "completed"
            except Exception as exc:  # pylint: disable=broad-except
                provider.error = redact_sensitive_text(exc, limit=500)
                provider.state = "failed"
                retry_keys = (
                    self._tool_ids(retry_selection)
                    if retry_selection is not None
                    else None
                )
                for asset in provider.assets:
                    if (retry_keys is None) or (
                        retry_keys is not None
                        and f"{asset.asset_type}:{asset.source_id}"
                        in retry_keys
                    ):
                        if asset.state not in {
                            ImportAssetState.SUCCEEDED,
                            ImportAssetState.FAILED,
                        }:
                            asset.state = ImportAssetState.FAILED
                            asset.message = "请手动修改相关配置后重试。"
            await self._emit(live, persist=True)
        if live.cancel_requested and not any(
            item.state == "failed"
            or any(
                asset.state is ImportAssetState.FAILED for asset in item.assets
            )
            for item in live.snapshot.providers
        ):
            await self._mark_interrupted(live)
            return
        live.snapshot.state = (
            "completed_with_issues"
            if any(
                item.state == "failed"
                or any(
                    asset.state is ImportAssetState.FAILED
                    for asset in item.assets
                )
                for item in live.snapshot.providers
            )
            else "completed"
        )
        await self._emit(live, persist=True)

    async def _live(self, workspace: Any, job_id: str) -> _LiveJob:
        key = (workspace.agent_id, job_id)
        if key not in self._jobs:
            await self.snapshot(workspace, job_id)
        live = self._jobs[key]
        if not live.plans:
            service = self._service_factory(workspace)
            reader = getattr(service, "_read_plan", None)
            if reader is not None:
                for provider in live.snapshot.providers:
                    if provider.plan_id:
                        live.plans[provider.source] = await reader(
                            provider.plan_id,
                        )
        return live

    async def _emit(self, live: _LiveJob, *, persist: bool = False) -> None:
        live.snapshot.seq += 1
        event = {
            "seq": live.snapshot.seq,
            "snapshot": live.snapshot.model_dump(mode="json"),
        }
        live.events.append(event)
        for queue in live.subscribers:
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(event)
        if persist:
            async with live.persist_lock:
                await self._persist(live.workspace, live.snapshot)
        if live.snapshot.state in _TERMINAL:
            self._trim_terminal_jobs()

    async def _apply_progress(
        self,
        live: _LiveJob,
        provider: ImportProviderSnapshot,
        message: str,
    ) -> None:
        self._project_progress(
            provider,
            message,
            live.asset_index,
        )
        if not message.startswith("\x1e"):
            self._log(live, message)
            await self._emit(live)
            return
        live.progress_updates += 1
        if live.progress_updates % live.progress_step == 0:
            await self._emit(live)

    def _prepare_progress(self, live: _LiveJob) -> None:
        live.asset_index = {
            (provider.source, asset.asset_type, asset.source_id): asset
            for provider in live.snapshot.providers
            for asset in provider.assets
        }
        work_items = 0
        active_states = {
            ImportAssetState.PENDING,
            ImportAssetState.REPAIRING,
            ImportAssetState.READY,
        }
        for provider in live.snapshot.providers:
            work_items += (
                provider.sessions_total if provider.selection.sessions else 0
            )
            for asset in provider.assets:
                work_items += asset.state in active_states
        live.progress_step = max(1, work_items // 20)
        live.progress_updates = 0

    def _trim_terminal_jobs(self) -> None:
        terminal = [
            key
            for key, live in self._jobs.items()
            if live.snapshot.state in _TERMINAL
        ]
        for key in terminal[:-_MAX_TERMINAL_JOBS]:
            self._jobs.pop(key, None)

    async def _persist(
        self,
        workspace: Any,
        snapshot: ImportRun,
    ) -> None:
        path = self._path(workspace, snapshot.job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        await write_json_atomic_async(path, snapshot.model_dump(mode="json"))

    @staticmethod
    def _path(workspace: Any, job_id: str) -> Path:
        if not re.fullmatch(r"import-[0-9a-f]{32}", job_id):
            raise ValueError("invalid import job id")
        return (
            Path(workspace.workspace_dir)
            / ".qwenpaw/imports/jobs"
            / f"{job_id}.json"
        )

    @staticmethod
    def _default_selection(plan: MigrationPlan) -> ImportSelection:
        """Select non-executable assets by default."""
        selection = PortabilityImportJobManager._all_selection(plan)
        selection.plugins = []
        return selection

    @staticmethod
    def _all_selection(plan: MigrationPlan) -> ImportSelection:
        values: dict[str, Any] = {
            "sessions": any(
                item.asset_type == "session" for item in plan.actions
            ),
        }
        for action in plan.actions:
            selection_field = _TYPE_FIELDS.get(action.asset_type)
            if selection_field:
                values.setdefault(selection_field, []).append(action.source_id)
        return ImportSelection(**values)

    @staticmethod
    def _selected_assets(
        plan: MigrationPlan,
        selection: ImportSelection,
    ) -> list[ImportAssetResult]:
        selected = {
            f"{'cron' if action_type == 'scheduled_task' else action_type}:"
            f"{source_id}"
            for action_type, selection_field in _TYPE_FIELDS.items()
            for source_id in getattr(selection, selection_field)
        }
        return [
            ImportAssetResult(
                asset_type=(
                    "cron"
                    if action.asset_type == "scheduled_task"
                    else action.asset_type
                ),
                source_id=action.source_id,
                name=action.name,
                requires_sessions=action.requires_sessions,
            )
            for action in plan.actions
            if (
                (
                    "cron"
                    if action.asset_type == "scheduled_task"
                    else action.asset_type
                )
                + f":{action.source_id}"
                in selected
            )
        ]

    @staticmethod
    def _tool_ids(selection: ImportSelection) -> set[str]:
        if selection.sessions:
            raise ValueError("retry does not support sessions")
        return {
            f"{'cron' if asset_type == 'scheduled_task' else asset_type}:"
            f"{source_id}"
            for asset_type, field in _TYPE_FIELDS.items()
            for source_id in getattr(selection, field)
        }

    @classmethod
    def _validate_retry_selection(
        cls,
        provider: ImportProviderSnapshot,
        selection: ImportSelection,
    ) -> None:
        failed = {
            f"{item.asset_type}:{item.source_id}"
            for item in provider.assets
            if item.state is ImportAssetState.FAILED
        }
        requested = cls._tool_ids(selection)
        if not requested <= failed:
            raise ValueError("retry only accepts tools that previously failed")

    @staticmethod
    def _project_progress(
        provider: ImportProviderSnapshot,
        message: str,
        asset_index: (
            dict[tuple[str, str, str], ImportAssetResult] | None
        ) = None,
    ) -> None:
        result = message.split("\t")
        if len(result) == 5 and result[0] == "\x1esessions":
            (
                provider.sessions_processed,
                provider.sessions_total,
                provider.sessions_imported,
                _,
            ) = map(int, result[1:])
            return
        if len(result) == 5 and result[0] == "\x1easset":
            asset_type, state, enabled, source_id = result[1:]
            asset = (
                asset_index.get((provider.source, asset_type, source_id))
                if asset_index is not None
                else next(
                    (
                        item
                        for item in provider.assets
                        if item.asset_type == asset_type
                        and item.source_id == source_id
                    ),
                    None,
                )
            )
            if asset is not None:
                asset.state = ImportAssetState(state)
                asset.enabled = None if enabled == "-" else enabled == "1"

    @staticmethod
    def _log(live: _LiveJob, message: str) -> None:
        safe = redact_sensitive_text(message, limit=500)
        live.snapshot.logs = (live.snapshot.logs + [safe])[-50:]


__all__ = [
    "ImportRun",
    "ImportProviderSnapshot",
    "PortabilityImportJobManager",
]
