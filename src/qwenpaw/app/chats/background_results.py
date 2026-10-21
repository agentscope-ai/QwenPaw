"""Chat-owned result delivery; execution stays with the original tool.

Only a server-created CallResultRoute may issue a one-use child-task ticket.
The ticket crosses the existing local HTTP boundary without trusting model IDs.
All state transitions run on the parent event loop. There is no polling worker,
second Agent executor or durable task database here.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Callable
from uuid import uuid4

from agentscope.message import Msg

from ...runtime.reply_cycle import InternalResultInput

logger = logging.getLogger(__name__)
_tickets: dict[str, tuple["BackgroundWork", str]] = {}
_MAX_PENDING = 128
_MAX_FINISHED = 256


@dataclass
class BackgroundWork:
    owner: "ChatBackgroundResults"
    call_id: str
    input_ids: tuple[str, ...]
    source_run_id: str
    tool_name: str
    task_id: str = ""
    work_id: str = field(default_factory=lambda: uuid4().hex)
    ready: bool = False
    status: str = "running"
    delivery: str = "pending"
    message: Msg | None = None
    error: str = ""
    attempt: int = 0
    consumer_run: str = ""
    cancel: Callable[[], Any] | None = None
    submit_task: asyncio.Task | None = None

    def complete(self, status: str, message: Msg) -> None:
        if self.status != "running" or self.delivery == "cancelled":
            return
        self.status, self.message = status, message
        self.owner.schedule(self)


def consume_result_ticket(
    token: str, agent_id: str, *, consume: bool = True
) -> BackgroundWork:
    """Validate the destination before consuming a dispatch capability."""
    item = _tickets.get(token)
    if item is None or item[1] != agent_id:
        raise ValueError("Invalid background result ticket")
    work, _ = item
    if work.delivery == "cancelled":
        raise ValueError("The originating input was cancelled")
    if consume:
        _tickets.pop(token)
    return work


class CallResultRoute:
    """Call ownership and the ready barrier for its returned receipt."""

    def __init__(
        self, owner: "ChatBackgroundResults", snapshot: Any, call: Any
    ):
        self.owner, self.snapshot, self.call = owner, snapshot, call
        self.works: list[BackgroundWork] = []
        self._ready = False
        self.reported_results: set[str] = set()

    def record_polled_result(self, task_id: str) -> None:
        """The current tool returned this work's actual terminal result."""
        for work in self.owner.works.values():
            if work.task_id == task_id and work.delivery not in {
                "cancelled",
                "delivered",
            }:
                self.reported_results.add(work.work_id)

    def register(self) -> BackgroundWork:
        work = self.owner.register(self.snapshot, self.call)
        work.ready = self._ready
        self.works.append(work)
        return work

    def issue_ticket(self, agent_id: str) -> str:
        """Called by the existing synchronous HTTP tool on a worker thread."""

        async def issue() -> str:
            work = self.register()
            token = uuid4().hex
            _tickets[token] = (work, agent_id)
            return token

        return asyncio.run_coroutine_threadsafe(
            issue(), self.owner.loop
        ).result()

    def finish_receipt(self) -> None:
        # AgentScope has saved the yielded ToolResponse at this boundary.
        self._ready = True
        for work in self.works:
            work.ready = True
            self.owner.schedule(work)
        for token, (work, _) in tuple(_tickets.items()):
            if work in self.works:
                # Unconsumed tickets did not launch a child. The ordinary tool
                # error is already the result; do not inject a second failure.
                _tickets.pop(token, None)
                self.owner.works.pop(work.work_id, None)


class ChatBackgroundResults:
    """Result ownership and acknowledgement for one ordinary Chat."""

    def __init__(self, tracker: Any, chat_id: str):
        self.tracker, self.chat_id = tracker, chat_id
        self.loop = asyncio.get_running_loop()
        self.works: dict[str, BackgroundWork] = {}
        self.input_runs: dict[str, str] = {}
        self.cancelled_inputs: set[str] = set()
        self.source_saves: dict[str, str] = {}
        self.payload: dict[str, Any] = {}
        self.stream_fn: Any = None
        self.workspace: Any = None
        self.reserve_order: Any = None
        self.closed = False

    async def refresh_runtime(self) -> None:
        """Resolve the current workspace after a configuration hot reload."""
        manager = getattr(self.workspace, "_manager", None)
        if manager is None:
            return
        current = await manager.get_agent(self.workspace.agent_id)
        if current is self.workspace:
            return
        if current.task_tracker is not self.tracker:
            raise RuntimeError("The originating Chat runtime is unavailable")
        channel = await current.channel_manager.get_channel("console")
        if channel is None:
            raise RuntimeError("The Console channel is unavailable")
        self.workspace, self.stream_fn = current, channel.stream_one

    def bind_call(self, snapshot: Any, call: Any) -> CallResultRoute:
        return CallResultRoute(self, snapshot, call)

    def register(self, snapshot: Any, call: Any) -> BackgroundWork:
        if self.closed:
            raise RuntimeError("The originating Chat was closed")
        self._prune()
        if (
            sum(
                w.delivery not in {"delivered", "cancelled"}
                for w in self.works.values()
            )
            >= _MAX_PENDING
        ):
            raise OverflowError("Too many outstanding background results")
        ids = snapshot.responds_to_input_ids
        if self.cancelled_inputs.intersection(ids):
            raise RuntimeError("The originating input was cancelled")
        work = BackgroundWork(self, call.id, ids, snapshot.run_id, call.name)
        self.works[work.work_id] = work
        return work

    def pending(self, input_id: str) -> bool:
        return any(
            input_id in w.input_ids
            and w.delivery not in {"delivered", "cancelled"}
            for w in self.works.values()
        )

    def is_cancelled(self, work_id: str) -> bool:
        work = self.works.get(work_id)
        return work is None or work.delivery == "cancelled"

    def schedule(self, work: BackgroundWork) -> None:
        if (
            self.closed
            or not work.ready
            or work.message is None
            or work.delivery not in {"pending", "failed"}
            or (work.submit_task is not None and not work.submit_task.done())
        ):
            return
        work.submit_task = asyncio.create_task(self._deliver(work))

    async def _deliver(self, work: BackgroundWork) -> None:
        try:
            await self.tracker.submit_result(self.chat_id, work)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            work.delivery, work.error = "failed", str(exc)
            logger.exception(
                "Background result delivery failed: %s", work.work_id
            )

    def observed(self, work_id: str, run_id: str) -> None:
        work = self.works[work_id]
        if work.delivery != "cancelled":
            work.delivery, work.consumer_run = "observed", run_id

    def replied(self, work_id: str, run_id: str) -> None:
        work = self.works[work_id]
        if work.delivery != "cancelled":
            work.delivery, work.consumer_run = "replied", run_id

    def finish_run(self, run_id: str, persistence: str, error: str) -> None:
        self.source_saves[run_id] = persistence
        for work in self.works.values():
            if work.consumer_run != run_id or work.delivery == "cancelled":
                continue
            if work.delivery == "replied" and persistence == "saved":
                work.delivery, work.error = "delivered", ""
            else:
                work.delivery = "failed"
                work.error = error or "The parent response was not saved"
        self._prune()

    def settled_inputs(self, run_id: str) -> tuple[str, ...]:
        return tuple(
            {
                i
                for w in self.works.values()
                if w.consumer_run == run_id and w.delivery == "delivered"
                for i in w.input_ids
                if not self.pending(i)
            }
        )

    def retry_pending(self) -> None:
        # Called on a new ordinary Chat interaction, never re-executes tools.
        for work in tuple(self.works.values()):
            self.schedule(work)

    def cancel_inputs(self, input_ids: tuple[str, ...]) -> None:
        self.cancelled_inputs.update(input_ids)
        for work in self.works.values():
            if set(work.input_ids).intersection(
                input_ids
            ) and work.delivery not in {"delivered", "cancelled"}:
                work.delivery = "cancelled"
                if work.cancel is not None:
                    work.cancel()
                if work.submit_task is not None:
                    work.submit_task.cancel()

    async def close(self) -> None:
        self.closed = True
        self.cancel_inputs(
            tuple({i for work in self.works.values() for i in work.input_ids})
        )
        for token, (work, _) in tuple(_tickets.items()):
            if work.owner is self:
                _tickets.pop(token, None)
        await asyncio.gather(
            *(w.submit_task for w in self.works.values() if w.submit_task),
            return_exceptions=True,
        )

    def _prune(self) -> None:
        finished = [
            key
            for key, w in self.works.items()
            if w.delivery in {"delivered", "cancelled"}
        ]
        for key in finished[:-_MAX_FINISHED]:
            self.works.pop(key, None)

    def facts(self, input_ids: set[str]) -> tuple[dict[str, Any], ...]:
        return tuple(
            {
                "work_id": w.work_id,
                "execution": w.status,
                "delivery": w.delivery,
                "error": w.error,
            }
            for w in self.works.values()
            if input_ids.intersection(w.input_ids)
        )

    def make_input(self, work: BackgroundWork) -> InternalResultInput:
        work.attempt += 1
        return InternalResultInput(
            work.work_id,
            work.input_ids,
            work.message,
            work.attempt,
        )
