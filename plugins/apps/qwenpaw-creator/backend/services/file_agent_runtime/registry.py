# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Process-level lifecycle hooks for the file-native Creator Agent driver."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import logging
from pathlib import Path
import threading
from uuid import uuid4

from services.project_files.facade import (
    CreatorFileServices,
    creator_file_services,
    release_creator_file_services,
)
from services.storage_root import member_partition

from .driver import FileCreatorAgentRuntime
from .model_client import AgentChatClient


_registry_lock = threading.RLock()
_runtimes: dict[tuple[str, str] | None, FileCreatorAgentRuntime] = {}
_MEMBER_IDLE_SECONDS = 120.0
_PROCESS_GENERATION = uuid4().hex


@dataclass
class _MemberWorkspace:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    requests: int = 0
    timer: asyncio.TimerHandle | None = None
    cleanup: asyncio.Task | None = None


_members: dict[tuple[str, str], _MemberWorkspace] = {}


def _release_idle_workers(services: CreatorFileServices) -> bool:
    from services.media.source_memory import release_idle_source_memory
    from services.media.source_observation import release_idle_source_observation
    from services.media.source_video_reader import release_idle_source_video_reader
    from services.source_analysis.service import release_idle_source_analysis
    from services.media_files.image_execution import release_idle_image_executor
    from services.media_files.r2v_execution import release_idle_video_executor

    return all(
        release(services)
        for release in (
            release_idle_source_memory,
            release_idle_source_observation,
            release_idle_source_video_reader,
            release_idle_source_analysis,
            release_idle_image_executor,
            release_idle_video_executor,
        )
    )


def _schedule_idle_check(partition, workspace, services):
    if workspace.requests or workspace.timer or workspace.cleanup:
        return

    def start_check():
        workspace.timer = None
        workspace.cleanup = asyncio.create_task(
            _retire_if_idle(partition, workspace, services)
        )

    workspace.timer = asyncio.get_running_loop().call_later(
        _MEMBER_IDLE_SECONDS, start_check
    )


async def _retire_if_idle(partition, workspace, services):
    try:
        async with workspace.lock:
            current = _runtimes.get(partition)
            if workspace.requests or _members.get(partition) is not workspace:
                return
            if current:
                if current.busy or await asyncio.to_thread(current.has_queued_work):
                    return
                if workspace.requests or current.busy:
                    return
            if not _release_idle_workers(services):
                return
            if current:
                await current.work_scheduler.save_idle_ledger(_PROCESS_GENERATION)
                if workspace.requests or current.busy:
                    return
                await current.stop()
                _runtimes.pop(partition, None)
            release_creator_file_services(services)
            if not workspace.requests:
                _members.pop(partition, None)
    except Exception:
        # Preserve a workspace whose durable state cannot be read reliably.
        logging.getLogger(__name__).exception("Creator idle workspace check failed")
    finally:
        workspace.cleanup = None
        if _members.get(partition) is workspace:
            _schedule_idle_check(partition, workspace, services)


@asynccontextmanager
async def member_project_services(root: Path):
    partition = member_partition()
    if partition is None:
        yield await asyncio.to_thread(creator_file_services, root)
        return
    workspace = _members.get(partition)
    if workspace is None:
        workspace = _members[partition] = _MemberWorkspace()
    workspace.requests += 1
    if workspace.timer:
        workspace.timer.cancel()
        workspace.timer = None
    services = None
    try:
        async with workspace.lock:
            services = await asyncio.to_thread(creator_file_services, root)
            await _ensure_member_project_runtime(partition, services)
        yield services
    finally:
        workspace.requests -= 1
        if _members.get(partition) is workspace:
            if services:
                _schedule_idle_check(partition, workspace, services)
            elif not workspace.requests:
                _members.pop(partition, None)


async def _ensure_member_project_runtime(
    partition, services: CreatorFileServices
) -> None:
    """Recover a member's own queues once, after the host has authorized access."""
    current = _runtimes.get(partition)
    if current is not None and current.started:
        return
    from services.media_files import start_file_media_execution_services
    from services.source_analysis import recover_interrupted_source_analysis
    from services.media.source_memory import recover_interrupted_source_memory
    from services.media.source_observation import (
        recover_interrupted_source_observations,
    )
    from services.media.source_video_reader import (
        recover_interrupted_source_video_reads,
    )

    await asyncio.to_thread(recover_interrupted_source_analysis, services)
    await start_file_media_execution_services(services)
    await asyncio.to_thread(recover_interrupted_source_memory, services)
    await asyncio.to_thread(recover_interrupted_source_observations, services)
    await asyncio.to_thread(recover_interrupted_source_video_reads, services)
    await start_creator_agent_runtime(services)


async def start_creator_agent_runtime(
    services: CreatorFileServices,
    *,
    model_client: AgentChatClient | None = None,
    poll_interval_seconds: float = 1.0,
) -> FileCreatorAgentRuntime:
    partition = member_partition()
    with _registry_lock:
        current = _runtimes.get(partition)
        if current is None:
            current = FileCreatorAgentRuntime(
                services,
                model_client=model_client,
                poll_interval_seconds=poll_interval_seconds,
            )
            _runtimes[partition] = current
        elif current.services.root != services.root:
            raise RuntimeError(
                "Creator Agent Runtime is already bound to another data root",
            )
        elif model_client is not None and current.model_client is not model_client:
            raise RuntimeError(
                "Creator Agent Runtime is already bound to another model client",
            )
    if not current.started:
        # Always reconcile durable messages/nodes. Only a service restart
        # gets the additional sweep that may synthesize a YOLO continuation.
        warm = partition is not None and await asyncio.to_thread(
            current.work_scheduler.restore_idle_ledger, _PROCESS_GENERATION
        )
        await current.start(resume_unattended=not warm)
    return current


async def stop_creator_agent_runtime() -> None:
    with _registry_lock:
        members = tuple(_members.values())
        _members.clear()
    for member in members:
        if member.timer:
            member.timer.cancel()
    await asyncio.gather(
        *(m.cleanup for m in members if m.cleanup), return_exceptions=True
    )
    with _registry_lock:
        runtimes = tuple(_runtimes.items())
        _runtimes.clear()
    for partition, current in runtimes:
        await current.stop()
        if partition is not None and _release_idle_workers(current.services):
            release_creator_file_services(current.services)


def get_creator_agent_runtime() -> FileCreatorAgentRuntime | None:
    with _registry_lock:
        return _runtimes.get(member_partition())


def notify_creator_agent_runtime(project_id: str) -> bool:
    current = get_creator_agent_runtime()
    if current is None:
        return False
    current.notify(project_id)
    return True


async def interrupt_creator_agent_runtime(
    project_id: str,
    *,
    superseded: bool = False,
    reason: str = "user_interrupt",
    expected_run_id: str | None = None,
) -> bool:
    current = get_creator_agent_runtime()
    if current is None:
        return False
    return await current.interrupt(
        project_id,
        superseded=superseded,
        reason=reason,
        expected_run_id=expected_run_id,
    )


def reset_creator_agent_runtime_registry_for_tests() -> None:
    """Synchronous guard for tests that already stopped the async driver."""

    with _registry_lock:
        if any(current.started for current in _runtimes.values()):
            raise RuntimeError(
                "stop Creator Agent Runtime before resetting it",
            )
        _runtimes.clear()


__all__ = [
    "get_creator_agent_runtime",
    "interrupt_creator_agent_runtime",
    "notify_creator_agent_runtime",
    "reset_creator_agent_runtime_registry_for_tests",
    "start_creator_agent_runtime",
    "stop_creator_agent_runtime",
]
