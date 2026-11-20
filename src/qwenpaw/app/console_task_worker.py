"""Run durable Console work with an expiring, fenced database claim."""

import asyncio
import logging
import math
from contextlib import suppress
from uuid import UUID

from fastapi import HTTPException, Request

from ..access.actor import actor_from_request
from ..identity.runtime import get_identity_runtime
from ..persistence.console_tasks import ConsoleTaskRepository, TaskClaim
from .agent_context import reset_current_agent_id, set_current_agent_id
from .console_delegation import ConsoleDelegation

logger = logging.getLogger(__name__)
INTERRUPTED = {
    "status": "failed",
    "error": {
        "code": "task_execution_interrupted",
        "message": "任务执行期间工作进程中断。请先核对已生成的文件及外部操作，确认后再重新提交。",
    },
}


def task_timeout_seconds(value) -> float | None:
    if value is None:
        return None
    try:
        seconds = float(value)
        if not math.isfinite(seconds):
            raise ValueError
    except (TypeError, ValueError, OverflowError) as exc:
        raise HTTPException(422, detail="invalid_task_timeout") from exc
    return seconds if seconds > 0 else None


def task_envelope(request: Request, payload: dict) -> dict:
    """Persist business input and opaque device identity, never HTTP credentials."""
    authenticated = request.state.authenticated_session
    parent = request.scope.get("qwenpaw.subtask")
    fields = (
        "input",
        "channel",
        "session_id",
        "conversation_id",
        "request_context",
        "requested_model",
        "timeout",
    )
    envelope = {
        "session_id": str(authenticated.session.id),
        "payload": {name: payload[name] for name in fields if name in payload},
    }
    if parent is not None:
        envelope["delegation"] = {
            "tools": parent.tools,
            "skills": parent.skills,
            "model": parent.model,
            "target_agent_id": parent.target_agent_id,
            "is_subtask": parent.is_subtask,
            "root_session_id": parent.root_session_id,
            "session_handle": parent.session_handle,
        }
    return envelope


async def execute_console_task(app, claim: TaskClaim, row: dict) -> dict:
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "app": app,
            "path": "/api/console/chat/task",
            "scheme": "http",
            "query_string": b"",
            "headers": [],
            "state": {"agent_id": row["agent_id"], "task_execution_started": False},
        }
    )
    deadline = asyncio.timeout(task_timeout_seconds(row["envelope"]["payload"].get("timeout")))
    try:
        async with deadline:
            result = await _restore_and_execute(request, claim, row)
    except TimeoutError:
        # An unrelated provider or database timeout has its own failure path.
        if not deadline.expired():
            raise
    else:
        # A protected finalizer may complete a commit after the deadline.
        # Keep its authoritative success; inner model streams can absorb cancellation.
        if not deadline.expired() or result.get("status") == "completed":
            return result
    if request.state.task_execution_started:
        code = "task_execution_timeout"
        message = "任务执行已超时。请先核对已生成的文件及外部操作，确认后再重新提交。"
    else:
        code = "task_admission_timeout"
        message = "任务在等待执行时超时，尚未开始运行。可重新提交。"
    return {"status": "failed", "error": {"code": code, "message": message}}


async def _restore_and_execute(request: Request, claim: TaskClaim, row: dict) -> dict:
    from .routers.console import _submit_console_chat_task

    envelope = row["envelope"]
    session_id = UUID(envelope["session_id"])
    authenticated = await get_identity_runtime().sessions.active_parent_session(
        session_id, claim.owner_id
    )
    if authenticated is None:
        raise HTTPException(401, detail="device_session_revoked")
    request.state.authenticated_session = authenticated
    request.state.actor = actor_from_request(request, multi_user=True)
    delegated = envelope.get("delegation")
    if delegated is not None:
        request.scope["qwenpaw.subtask"] = ConsoleDelegation(
            request.app,
            session_id,
            claim.owner_id,
            row["parent_agent_id"],
            str(row["parent_conversation_id"]),
            **delegated,
        )
    token = set_current_agent_id(row["agent_id"])
    try:
        return await _submit_console_chat_task(envelope["payload"], request, claimed=row)
    finally:
        reset_current_agent_id(token)


class ConsoleTaskWorker:
    def __init__(self, repo: ConsoleTaskRepository, execute, *, concurrency=16, poll_seconds=2):
        self.repo = repo
        self.execute = execute
        self.concurrency = concurrency
        self.poll_seconds = poll_seconds
        self.wake = asyncio.Event()
        self.active: set[asyncio.Task] = set()

    async def _execute_claim(self, claim):
        row = await self.repo.begin(claim)
        if row is None:
            return
        work = asyncio.create_task(self.execute(claim, row))
        try:
            while True:
                done, _ = await asyncio.wait({work}, timeout=self.repo.lease_seconds / 3)
                if done:
                    break
                if not await self.repo.renew(claim):
                    return
            try:
                result = work.result()
            except HTTPException as exc:
                message = (
                    "账号、设备或资源授权已失效。" if exc.status_code in {401, 403, 404} else "后台任务无法启动，请核对任务配置。"
                )
                result = {
                    "status": "failed",
                    "error": {"code": f"task_http_{exc.status_code}", "message": message},
                }
            except Exception as exc:
                logger.warning("Console task failed (error_type=%s)", type(exc).__name__)
                result = {"status": "failed", "error": {"message": "task_execution_failed"}}
            await self.repo.finish(claim, result)
        finally:
            if not work.done():
                work.cancel()
            await asyncio.gather(work, return_exceptions=True)

    def _completed(self, task):
        self.active.discard(task)
        self.wake.set()
        if not task.cancelled() and task.exception() is not None:
            logger.warning(
                "Console task dispatch failed (error_type=%s)", type(task.exception()).__name__
            )

    async def serve(self, ready=None):
        if ready is not None:
            await ready.wait()
        next_sweep = 0.0
        loop = asyncio.get_running_loop()
        try:
            while True:
                self.wake.clear()
                try:
                    if loop.time() >= next_sweep:
                        await self.repo.maintain()
                        next_sweep = loop.time() + min(self.repo.lease_seconds / 3, 10)
                    while len(self.active) < self.concurrency:
                        claim = await self.repo.claim()
                        if claim is None:
                            break
                        task = asyncio.create_task(self._execute_claim(claim))
                        self.active.add(task)
                        task.add_done_callback(self._completed)
                except Exception as exc:
                    logger.warning("Console queue unavailable (error_type=%s)", type(exc).__name__)
                with suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self.wake.wait(), self.poll_seconds)
        finally:
            tasks = list(self.active)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
