# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import threading

import pytest

from qwenpaw.backup import manager as manager_module
from qwenpaw.backup._ops.create import BackupCancelled
from qwenpaw.backup.manager import BackupManager, BackupOperationConflict
from qwenpaw.backup.models import (
    BackupJobStatus,
    BackupScope,
    CreateBackupRequest,
)


def _request() -> CreateBackupRequest:
    return CreateBackupRequest(
        name="test",
        scope=BackupScope(
            include_agents=False,
            include_global_config=False,
            include_secrets=False,
            include_skill_pool=False,
        ),
    )


async def _wait_for_status(
    manager: BackupManager,
    job_id: str,
    status: BackupJobStatus,
):
    for _ in range(200):
        snapshot = manager.get_job(job_id)
        if snapshot and snapshot.status == status:
            return snapshot
        await asyncio.sleep(0.01)
    raise AssertionError(f"job did not reach {status}")


async def test_unsubscribe_does_not_cancel_running_job(monkeypatch):
    release = threading.Event()
    observed_stop_events: list[threading.Event] = []

    def fake_create(meta, _agents, progress, stop_event):
        observed_stop_events.append(stop_event)
        progress({"type": "start", "total_agents": 0, "percent": 0})
        assert release.wait(timeout=2)
        return meta

    monkeypatch.setattr(manager_module, "create_backup", fake_create)
    manager = BackupManager()
    initial = manager.start_job(_request())
    queue = manager.subscribe(initial.job_id)
    assert queue is not None
    await queue.get()
    manager.unsubscribe(initial.job_id, queue)

    release.set()
    completed = await _wait_for_status(
        manager,
        initial.job_id,
        BackupJobStatus.COMPLETED,
    )

    assert completed.result is not None
    assert observed_stop_events[0].is_set() is False


async def test_explicit_cancel_stops_job(monkeypatch):
    def fake_create(_meta, _agents, _progress, stop_event):
        assert stop_event.wait(timeout=2)
        raise BackupCancelled()

    monkeypatch.setattr(manager_module, "create_backup", fake_create)
    manager = BackupManager()
    initial = manager.start_job(_request())

    requested = manager.cancel_job(initial.job_id)
    assert requested is not None
    assert requested.status == BackupJobStatus.CANCEL_REQUESTED
    cancelled = await _wait_for_status(
        manager,
        initial.job_id,
        BackupJobStatus.CANCELLED,
    )
    repeated = manager.cancel_job(initial.job_id)
    assert repeated is not None
    assert repeated.status == cancelled.status


async def test_create_and_restore_reservations_conflict(monkeypatch):
    release = threading.Event()

    def fake_create(meta, _agents, _progress, _stop_event):
        assert release.wait(timeout=2)
        return meta

    monkeypatch.setattr(manager_module, "create_backup", fake_create)
    manager = BackupManager()

    with manager.reserve_restore():
        with pytest.raises(BackupOperationConflict):
            manager.start_job(_request())

    initial = manager.start_job(_request())
    with pytest.raises(BackupOperationConflict):
        with manager.reserve_restore():
            pass

    release.set()
    await _wait_for_status(
        manager,
        initial.job_id,
        BackupJobStatus.COMPLETED,
    )


async def test_shutdown_requests_active_job_cancellation(monkeypatch):
    def fake_create(_meta, _agents, _progress, stop_event):
        assert stop_event.wait(timeout=2)
        raise BackupCancelled()

    monkeypatch.setattr(manager_module, "create_backup", fake_create)
    manager = BackupManager()
    initial = manager.start_job(_request())

    await manager.shutdown(timeout=1)

    snapshot = manager.get_job(initial.job_id)
    assert snapshot is not None
    assert snapshot.status == BackupJobStatus.CANCELLED
