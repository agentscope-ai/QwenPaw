# -*- coding: utf-8 -*-
"""Safety state-machine tests using the real monitor and temporary JSON."""
# pylint: disable=protected-access,redefined-outer-name,unused-argument

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import openai
import pytest
from fastapi import FastAPI

from qwenpaw.app.routers.mail_access_control import router
from qwenpaw.config.config import AgentMailPushRule
from .test_monitor import EventRecorder, FakeImapConn, _service


@pytest.fixture
def recorder():
    events = EventRecorder()
    with patch("qwenpaw.app.mail.monitor.append_inbox_event", new=events):
        yield events


async def _scan(service, first, last):
    service._loop = asyncio.get_running_loop()
    conn = FakeImapConn(
        b" ".join(str(uid).encode() for uid in range(first, last + 1)),
    )
    await asyncio.to_thread(service._check_new_messages, conn)


async def _resume(service):
    pause = await service.get_processing_pause()
    assert pause is not None
    assert await service.resume_processing(pause["pause_id"])
    task = service._approved_replay_task
    if task is not None:
        await task
    return pause


def _approve(service, uids):
    store = service._mail_acl_store
    for uid in uids:
        store.add_pending("test-agent", "alice@example.com", uid=uid)
    store.approve_many("test-agent", [("alice@example.com", "")])


def _remaining(service):
    return [
        message["uid"]
        for entry in service._mail_acl_store.get_approved_replay("test-agent")
        for message in entry["messages"]
    ]


@pytest.mark.parametrize("baseline", [0, 500])
async def test_large_batch_restart_requires_confirmation_and_runs_once(
    tmp_path,
    recorder,
    baseline,
):
    service, workspace = _service(tmp_path, mode="agent_all")
    service._current_uidvalidity = 7
    service._commit_last_uid(baseline)
    await _scan(service, baseline + 1, baseline + 1033)
    pause = await service.get_processing_pause()
    assert pause["reason"] == "batch" and pause["count"] == 1033
    assert not workspace.queries
    assert service._last_uid == baseline
    assert recorder.types() == ["processing_paused"]

    restarted, workspace = _service(tmp_path, mode="agent_all")
    restarted._load_state()
    restarted._current_uidvalidity = 7
    restarted._reconcile_uidvalidity()
    await _scan(restarted, baseline + 1, baseline + 1033)
    assert not workspace.queries
    assert recorder.types() == ["processing_paused"]
    await _resume(restarted)
    assert not await restarted.resume_processing(pause["pause_id"])
    await _scan(restarted, baseline + 1, baseline + 1033)
    assert len(workspace.queries) == 1033
    assert restarted._last_uid == baseline + 1033
    await _scan(restarted, baseline + 1, baseline + 1033)
    assert len(workspace.queries) == 1033


async def test_empty_mailbox_first_arrival_still_processed(tmp_path, recorder):
    service, workspace = _service(tmp_path, mode="agent_all")
    await _scan(service, 1, 0)
    assert service._last_uid == 0
    await _scan(service, 1, 1)
    assert len(workspace.queries) == 1
    assert await service.get_processing_pause() is None


async def test_later_bulk_arrivals_do_not_inherit_confirmation(
    tmp_path,
    recorder,
):
    service, workspace = _service(tmp_path, mode="agent_all")
    service._last_uid = 0
    await _scan(service, 1, 51)
    first_pause = await _resume(service)
    await _scan(service, 1, 102)
    next_pause = await service.get_processing_pause()
    assert next_pause["count"] == 51
    assert not await service.resume_processing(first_pause["pause_id"])
    assert not workspace.queries
    assert service._last_uid == 0


async def test_batch_consent_does_not_bypass_sender_approval(
    tmp_path,
    recorder,
):
    service, workspace = _service(tmp_path, mode="agent_all")
    service.push.access_control_enabled = True
    service._last_uid = 0
    await _scan(service, 1, 51)
    await _resume(service)
    await _scan(service, 1, 51)
    assert not workspace.queries
    pending = service._mail_acl_store.get_acl("test-agent")["pending"]
    assert sum(len(entry["messages"]) for entry in pending) == 51
    assert service._last_uid == 51


async def test_http_controls_real_guard_without_relying_on_inbox_events(
    tmp_path,
    recorder,
):
    service, workspace = _service(tmp_path, mode="agent_all")
    service._last_uid = 500
    await _scan(service, 501, 551)
    app = FastAPI()
    app.include_router(router)
    app.state.multi_agent_manager = SimpleNamespace(
        list_loaded_agents=lambda: ["test-agent"],
        get_loaded_agent=lambda agent_id: (
            workspace if agent_id == "test-agent" else None
        ),
    )
    workspace.mail_monitor = service
    recorder.events.clear()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/mail-access-control/processing-pauses")
        assert response.status_code == 200
        pause = response.json()[0]
        assert pause["count"] == 51
        url = "/mail-access-control/processing/test-agent/resume"
        assert (
            await client.post(url, json={"pause_id": "old"})
        ).status_code == 409
        response = await client.post(url, json={"pause_id": pause["pause_id"]})
        assert response.status_code == 200
        response = await client.post(url, json={"pause_id": pause["pause_id"]})
        assert response.status_code == 409
        if service._approved_replay_task is not None:
            await service._approved_replay_task
        await _scan(service, 501, 551)
        assert len(workspace.queries) == 51
        response = await client.get("/mail-access-control/processing-pauses")
        assert response.json() == []


async def test_402_circuit_persists_and_keeps_unattempted_uids(
    tmp_path,
    recorder,
):
    service, workspace = _service(tmp_path, mode="agent_all")
    service._current_uidvalidity = 7
    service._commit_last_uid(500)
    attempts = []

    async def insufficient_balance(req):
        attempts.append(req)
        raise openai.APIStatusError(
            "Insufficient Balance",
            response=httpx.Response(
                402,
                request=httpx.Request("POST", "https://model.invalid/chat"),
            ),
            body=None,
        )
        yield  # pylint: disable=unreachable

    workspace.stream_query = insufficient_balance
    await _scan(service, 501, 610)
    await _resume(service)
    await _scan(service, 501, 610)
    assert len(attempts) == 3
    assert service._last_uid == 503
    assert service._delivery_failures == {}
    pause = await service.get_processing_pause()
    assert pause["reason"] == "failures" and pause["count"] == 3

    restarted, healthy_workspace = _service(tmp_path, mode="agent_all")
    restarted._load_state()
    restarted._current_uidvalidity = 7
    await _scan(restarted, 501, 610)
    assert not healthy_workspace.queries
    assert restarted._last_uid == 503
    await _resume(restarted)
    await _scan(restarted, 501, 610)
    assert len(healthy_workspace.queries) == 107
    assert restarted._last_uid == 610


async def test_approval_bulk_and_circuit_keep_outbox_until_success(
    tmp_path,
    recorder,
):
    service, workspace = _service(tmp_path, mode="agent_all")
    service._loop = asyncio.get_running_loop()
    _approve(service, range(1, 61))
    await service._drain_approved_replay()
    assert (await service.get_processing_pause())["count"] == 60
    assert not workspace.queries

    with patch(
        "qwenpaw.app.mail.monitor.wake_agent_for_mail",
        return_value=False,
    ) as wake:
        await _resume(service)
        assert wake.call_count == 3
    assert len(_remaining(service)) == 60
    assert (await service.get_processing_pause())["reason"] == "failures"
    await _resume(service)
    assert len(workspace.queries) == 60
    assert _remaining(service) == []


async def test_normal_and_approved_failures_share_one_counter(
    tmp_path,
    recorder,
):
    service, _ = _service(tmp_path, mode="agent_all")
    service._last_uid = 0
    with patch(
        "qwenpaw.app.mail.monitor.wake_agent_for_mail",
        return_value=False,
    ) as wake:
        await _scan(service, 1, 2)
        _approve(service, [3, 4])
        await service._drain_approved_replay()
        assert wake.call_count == 3
    assert _remaining(service) == [3, 4]
    assert (await service.get_processing_pause())["reason"] == "failures"


async def test_unexpected_wake_exception_cannot_bypass_breaker(
    tmp_path,
    recorder,
):
    service, _ = _service(tmp_path, mode="agent_all")
    service._last_uid = 0
    with patch(
        "qwenpaw.app.mail.monitor.wake_agent_for_mail",
        side_effect=RuntimeError("completion notification failed"),
    ) as wake:
        await _scan(service, 1, 10)
        assert wake.call_count == 3
    assert service._last_uid == 3
    assert (await service.get_processing_pause())["reason"] == "failures"


async def test_inflight_move_finishes_but_next_mail_never_starts(
    tmp_path,
    recorder,
):
    rule = AgentMailPushRule(
        field="from",
        contains="alice",
        action="move",
        param="Archive",
    )
    service, workspace = _service(tmp_path, mode="agent_all", rules=[rule])
    service._loop = asyncio.get_running_loop()
    service._last_uid = 0
    moves = []

    def move_then_concurrent_failure(_conn, uid, _folder):
        moves.append(uid)
        for _ in range(3):
            service._processing_guard.record_result(False)
        return {"moved": True}

    service._move_message = move_then_concurrent_failure
    await _scan(service, 1, 2)
    assert moves == [1]
    assert len(workspace.queries) == 1
    assert service._last_uid == 1
    assert await service.get_processing_pause() is not None


async def test_paused_replay_waiter_does_not_start_another_wake(
    tmp_path,
    recorder,
):
    service, _ = _service(tmp_path, mode="agent_all")
    kwargs = {
        "uid": 1,
        "sender": "alice@example.com",
        "subject": "hi",
        "date": "",
    }
    await service._agent_wake_lock.acquire()
    waiting = asyncio.create_task(service._wake_agent(param="", **kwargs))
    await asyncio.sleep(0)
    for _ in range(3):
        service._processing_guard.record_result(False)
    with patch("qwenpaw.app.mail.monitor.wake_agent_for_mail") as wake:
        service._agent_wake_lock.release()
        assert await waiting is None
        wake.assert_not_called()


async def test_notification_failure_does_not_unlock_or_lose_notice(tmp_path):
    service, _ = _service(tmp_path, mode="agent_all")
    service._processing_guard.check_batch("scan", list(range(1, 52)), 7)
    with patch(
        "qwenpaw.app.mail.monitor.append_inbox_event",
        side_effect=OSError("disk full"),
    ):
        await service._notify_processing_pause()
    pause = await service.get_processing_pause()
    assert not pause["notified"]
    events = EventRecorder()
    with patch("qwenpaw.app.mail.monitor.append_inbox_event", new=events):
        await service._notify_processing_pause()
        await service._notify_processing_pause()
    assert events.types() == ["processing_paused"]


async def test_resume_wakes_poll_sleep_without_interrupting_imap(tmp_path):
    service, _ = _service(tmp_path, mode="agent_all")
    service._loop = asyncio.get_running_loop()
    service._processing_guard.check_batch("scan", list(range(1, 52)), 7)
    sleeping = asyncio.create_task(asyncio.to_thread(service._sleep, 120))
    await asyncio.sleep(0)
    with patch.object(service, "_interrupt_active_connection") as interrupt:
        await _resume(service)
        await asyncio.wait_for(sleeping, timeout=1)
        interrupt.assert_not_called()


async def test_resume_racing_replay_exit_restarts_drain(tmp_path, recorder):
    service, workspace = _service(tmp_path, mode="agent_all")
    service._loop = asyncio.get_running_loop()
    _approve(service, [1])
    original_replay = service._replay_approved_message
    raced = False

    async def resume_during_exit(*args):
        nonlocal raced
        if not raced:
            raced = True
            for _ in range(3):
                service._processing_guard.record_result(False)
            pause = await service.get_processing_pause()
            assert await service.resume_processing(pause["pause_id"])
            return None
        return await original_replay(*args)

    service._replay_approved_message = resume_during_exit
    service.schedule_approved_replay()
    first_task = service._approved_replay_task
    await first_task
    second_task = service._approved_replay_task
    assert second_task is not None and second_task is not first_task
    await second_task
    assert len(workspace.queries) == 1
    assert _remaining(service) == []


async def test_stop_waits_for_api_resume_write_before_reload(
    tmp_path,
    recorder,
):
    service, _ = _service(tmp_path, mode="agent_all")
    service._worker = service._stop_event.wait
    service._processing_guard.check_batch("scan", list(range(1, 52)), 7)
    await service.start()
    pause = await service.get_processing_pause()
    started = threading.Event()
    release = threading.Event()
    original_resume = service._processing_guard.resume

    def blocked_resume(pause_id):
        started.set()
        assert release.wait(2)
        return original_resume(pause_id)

    with patch.object(service._processing_guard, "resume", blocked_resume):
        resuming = asyncio.create_task(
            service.resume_processing(pause["pause_id"]),
        )
        assert await asyncio.to_thread(started.wait, 1)
        stopping = asyncio.create_task(service.stop())
        await asyncio.sleep(0.02)
        assert not stopping.done()
        release.set()
        await asyncio.wait_for(stopping, timeout=1)
        await asyncio.gather(resuming, return_exceptions=True)
    assert service._approved_replay_task is None
    assert not service._submission_tasks
    restarted, _ = _service(tmp_path, mode="agent_all")
    assert restarted._processing_guard.check_batch(
        "scan",
        list(range(1, 52)),
        7,
    )
