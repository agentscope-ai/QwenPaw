# -*- coding: utf-8 -*-
"""ToolCoordinator — single owner of all in-flight tool calls."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Awaitable, Callable

from agentscope.message import TextBlock, ToolResultState
from agentscope.tool import ToolChunk, ToolResponse

from ._context import CancelReason, OffloadReason, ToolCallContext
from ._ctxvars import reset_call_context, set_call_context
from ._entry import ToolCallEntry, ToolCallStatus
from ._hint import make_offload_hint_msg
from ._hooks import ToolHookRegistry
from ._stream import ToolStream, _SENTINEL as _STREAM_SENTINEL
from ._timeout_helper import (
    MIN_BACKGROUND_WINDOW_SECS,
    OFFLOAD_TIMEOUT_RATIO,
)

logger = logging.getLogger(__name__)

# Keep finalized entries briefly so GET /output after SSE ``done`` can still
# read ``final_response`` (finalize pops from the hot table immediately).
_COMPLETED_CACHE_TTL_SECS = 60.0
_COMPLETED_CACHE_MAX = 50

CompletionHandler = Callable[[ToolCallEntry], Awaitable[None]]
OffloadedHandler = Callable[[ToolCallEntry], Awaitable[None]]
BackgroundResultProcessor = Callable[
    [ToolResponse],
    Awaitable[ToolResponse],
]


@dataclass
class _NextEvent:
    type: str  # chunk | stream_closed | cancelled | deadline_reached
    #            | kill_deadline_reached | deadline_changed
    chunk: Any = None


class ToolCoordinator:
    """Single owner of runtime state for every in-flight tool call.

    Concurrency model: all public methods are designed for single-threaded
    asyncio.  ``_entries_lock`` guards the insertion path (``execute``) to
    serialize concurrent tool launches within the same event loop tick.
    Read methods (``get``, ``list_entries``) are lock-free since CPython
    dict reads are atomic between await points.  Do NOT call these methods
    from ``asyncio.to_thread`` without external synchronization.
    """

    def __init__(
        self,
        *,
        default_timeout_secs: float | None = None,
        cancel_grace_period_secs: float = 5.0,
        offload_on_deadline: bool = False,
    ) -> None:
        self._default_timeout = default_timeout_secs
        self._cancel_grace = cancel_grace_period_secs
        self._offload_on_deadline = offload_on_deadline

        self._entries: dict[str, ToolCallEntry] = {}
        self._entries_lock = asyncio.Lock()
        # tool_call_id -> (entry, monotonic completed_at)
        self._completed_cache: OrderedDict[
            str,
            tuple[ToolCallEntry, float],
        ] = OrderedDict()
        self._pending_hints: dict[str, list[Any]] = {}
        self._hints_lock = asyncio.Lock()
        self._completion_handlers: list[CompletionHandler] = []
        self._offloaded_handlers: list[OffloadedHandler] = []

        self.hooks = ToolHookRegistry()
        self._per_agent_tool_timeouts: dict[tuple[str, str], float] = {}

    @property
    def offload_on_deadline(self) -> bool:
        return self._offload_on_deadline

    @offload_on_deadline.setter
    def offload_on_deadline(self, value: bool) -> None:
        self._offload_on_deadline = value

    # ================================================================
    # PRIMARY ENTRY
    # ================================================================
    # pylint: disable-next=too-many-statements
    async def execute(  # pylint: disable=too-many-locals,too-many-branches
        self,
        tool_call: Any,
        next_handler: Callable[..., AsyncGenerator[Any, None]],
        *,
        session_id: str,
        agent_id: str,
        root_session_id: str,
        deadline_override: float | None = None,
        background_result_processor: BackgroundResultProcessor | None = None,
    ) -> AsyncGenerator[Any, None]:
        entry = self._create_entry(
            tool_call,
            session_id,
            agent_id,
            root_session_id,
            deadline_override,
        )
        ctx = entry.ctx

        async with self._entries_lock:
            self._entries[ctx.tool_call_id] = entry

        chunk_queue: asyncio.Queue[Any] = asyncio.Queue()
        entry.stream.add_subscriber(chunk_queue)

        entry.background_task = asyncio.create_task(
            self._run_tool_with_hooks(next_handler, tool_call, entry),
            name=f"toolcall-{ctx.tool_call_id}",
        )

        terminal = "completed"
        try:
            while True:
                event = await self._await_next_event(
                    entry,
                    chunk_queue=chunk_queue,
                )
                if event.type == "chunk":
                    yield event.chunk
                elif event.type == "stream_closed":
                    break
                elif event.type == "deadline_reached":
                    if (
                        self._offload_on_deadline
                        or ctx.offload_reason == OffloadReason.USER
                    ):
                        # Offload must not create unbounded background work.
                        if not self._ensure_kill_deadline_for_offload(ctx):
                            ctx.cancel_event.set()
                            ctx.cancel_reason = CancelReason.TIMEOUT
                            await self._await_grace_or_force_cancel(entry)
                            terminal = "completed"
                            break
                        self._handle_deadline_reached(ctx)
                        terminal = "offload"
                        break
                    # keep_foreground: clear offload only when kill still
                    # bounds execution. Without kill_deadline this is the
                    # #6245 hang (clear deadline, wait forever).
                    if ctx.kill_deadline is not None:
                        ctx.offload_deadline = None
                        ctx.deadline_changed_event.set()
                    else:
                        ctx.cancel_event.set()
                        ctx.cancel_reason = CancelReason.TIMEOUT
                        await self._await_grace_or_force_cancel(entry)
                        terminal = "completed"
                        break
                elif event.type == "kill_deadline_reached":
                    ctx.cancel_event.set()
                    ctx.cancel_reason = CancelReason.TIMEOUT
                    await self._await_grace_or_force_cancel(entry)
                    terminal = "completed"
                    break
                elif event.type == "cancelled":
                    await self._await_grace_or_force_cancel(entry)
                    terminal = "completed"
                    break

            if terminal == "completed":
                await self._await_background_task(entry)
                yield await self._finalize_completed(entry)
                return

            yield await self._begin_offload(
                entry,
                background_result_processor,
            )
        except (asyncio.CancelledError, GeneratorExit):
            if entry.status == ToolCallStatus.RUNNING:
                await self._handle_parent_cancel(entry)
            raise
        finally:
            entry.stream.remove_subscriber(chunk_queue)

    @staticmethod
    def _handle_deadline_reached(ctx: ToolCallContext) -> None:
        if ctx.offload_reason is None:
            ctx.offload_reason = OffloadReason.TIMEOUT

    async def _handle_parent_cancel(self, entry: ToolCallEntry) -> None:
        """Stop and reap a tool when its parent execution is cancelled."""
        if entry.status != ToolCallStatus.RUNNING:
            return
        ctx = entry.ctx
        if ctx.cancel_reason is None:
            ctx.cancel_reason = CancelReason.USER
        ctx.cancel_event.set()
        await self._await_grace_or_force_cancel(entry)
        if entry.background_task is not None:
            await asyncio.gather(
                entry.background_task,
                return_exceptions=True,
            )
        entry.final_response = ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=self._cancel_message_for_llm(ctx),
                ),
            ],
            id=ctx.tool_call_id,
            state=ToolResultState.INTERRUPTED,
        )
        entry.end_state = "interrupted"
        await self._finalize_completed(entry)

    def _create_entry(
        self,
        tool_call: Any,
        session_id: str,
        agent_id: str,
        root_session_id: str,
        deadline_override: float | None,
    ) -> ToolCallEntry:
        loop = asyncio.get_running_loop()
        now = loop.time()
        timeout = self._resolve_timeout(
            agent_id,
            tool_call.name,
            deadline_override,
        )
        offload_deadline = None
        if timeout is not None:
            # Reserve the second half of the timeout for background execution
            # so equal hook/tool budgets do not let kill win over offload.
            offload_secs = max(0.0, timeout * OFFLOAD_TIMEOUT_RATIO)
            offload_deadline = now + offload_secs
        ctx = ToolCallContext(
            tool_call_id=tool_call.id,
            tool_name=tool_call.name,
            session_id=session_id,
            agent_id=agent_id,
            root_session_id=root_session_id,
            started_at=now,
            offload_deadline=offload_deadline,
            cancel_event=asyncio.Event(),
        )
        return ToolCallEntry(
            ctx=ctx,
            stream=ToolStream(
                tool_call_id=tool_call.id,
                session_id=session_id,
            ),
            final_response=ToolResponse(id=tool_call.id),
        )

    async def _begin_offload(
        self,
        entry: ToolCallEntry,
        background_result_processor: BackgroundResultProcessor | None,
    ) -> ToolResponse:
        ctx = entry.ctx
        entry.status = ToolCallStatus.OFFLOADED
        ctx.offload_deadline = None

        asyncio.create_task(
            self._supervise(entry, background_result_processor),
            name=f"toolcall-supervise-{ctx.tool_call_id}",
        )

        for handler in list(self._offloaded_handlers):
            try:
                await handler(entry)
            except Exception as exc:
                logger.warning(
                    "on_offloaded handler failed: %s",
                    exc,
                    exc_info=True,
                )

        bg_task_name = (
            entry.background_task.get_name() if entry.background_task else ""
        )
        reason = ctx.offload_reason.value if ctx.offload_reason else "unknown"
        if ctx.offload_reason == OffloadReason.USER:
            text = (
                f"The user moved tool `{ctx.tool_name}` to the background "
                f"(task={bg_task_name}, reason=user). Continue other work; "
                f"do not re-run the same tool. You will be notified when "
                f"it finishes."
            )
        else:
            text = (
                f"Tool `{ctx.tool_name}` was automatically moved to the "
                f"background (task={bg_task_name}, reason={reason}). "
                f"Continue other work; do not re-run the same tool. "
                f"You will be notified when it finishes."
            )
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=text,
                ),
            ],
            id=ctx.tool_call_id,
            state=ToolResultState.SUCCESS,
            metadata={
                "offloaded": True,
                "background_task_id": bg_task_name,
                "offload_reason": reason,
                "tool_name": ctx.tool_name,
            },
        )

    # ================================================================
    # INDEX / QUERY
    # ================================================================
    def get(self, tool_call_id: str) -> ToolCallEntry | None:
        entry = self._entries.get(tool_call_id)
        if entry is not None:
            return entry
        return self._get_completed(tool_call_id)

    def list_entries(
        self,
        session_id: str | None = None,
    ) -> list[ToolCallEntry]:
        entries = list(self._entries.values())
        if session_id is not None:
            entries = [e for e in entries if e.ctx.session_id == session_id]
        return entries

    def _get_completed(self, tool_call_id: str) -> ToolCallEntry | None:
        self._purge_completed_cache()
        cached = self._completed_cache.get(tool_call_id)
        if cached is None:
            return None
        entry, _completed_at = cached
        return entry

    def _store_completed(self, entry: ToolCallEntry) -> None:
        self._purge_completed_cache()
        tcid = entry.ctx.tool_call_id
        self._completed_cache.pop(tcid, None)
        self._completed_cache[tcid] = (entry, time.monotonic())
        while len(self._completed_cache) > _COMPLETED_CACHE_MAX:
            self._completed_cache.popitem(last=False)

    def _purge_completed_cache(self) -> None:
        now = time.monotonic()
        expired = [
            tcid
            for tcid, (_entry, completed_at) in self._completed_cache.items()
            if now - completed_at > _COMPLETED_CACHE_TTL_SECS
        ]
        for tcid in expired:
            self._completed_cache.pop(tcid, None)

    # ================================================================
    # PER-AGENT PER-TOOL TIMEOUT CONFIGURATION
    # ================================================================
    def set_agent_tool_timeout(
        self,
        agent_id: str,
        tool_name: str,
        timeout_secs: float | None,
    ) -> bool:
        if timeout_secs is None:
            self._per_agent_tool_timeouts.pop(
                (agent_id, tool_name),
                None,
            )
            return True
        if timeout_secs <= 0:
            return False
        hook = self.hooks.get(tool_name)
        if (
            hook.max_internal_timeout_secs is not None
            and timeout_secs > hook.max_internal_timeout_secs
        ):
            return False
        self._per_agent_tool_timeouts[(agent_id, tool_name)] = float(
            timeout_secs,
        )
        return True

    def clear_agent_tool_timeouts(self, agent_id: str) -> None:
        keys = [k for k in self._per_agent_tool_timeouts if k[0] == agent_id]
        for k in keys:
            self._per_agent_tool_timeouts.pop(k, None)

    # ================================================================
    # INTERVENTION API
    # ================================================================
    async def request_offload(
        self,
        tool_call_id: str,
        *,
        reason: OffloadReason = OffloadReason.USER,
    ) -> bool:
        entry = self._entries.get(tool_call_id)
        if entry is None or entry.status != ToolCallStatus.RUNNING:
            return False
        # Refuse unbounded background: require an existing or seedable kill.
        if not self._ensure_kill_deadline_for_offload(entry.ctx):
            return False
        entry.ctx.offload_reason = reason
        entry.ctx.offload_deadline = asyncio.get_running_loop().time()
        entry.ctx.deadline_changed_event.set()
        return True

    async def cancel(
        self,
        tool_call_id: str,
        *,
        reason: CancelReason = CancelReason.USER,
        force: bool = False,
    ) -> bool:
        entry = self._entries.get(tool_call_id)
        if entry is None:
            return False
        entry.ctx.cancel_reason = reason
        if force:
            # Always signal cancel_event before task.cancel() so platforms
            # that bridge cancel → process kill (e.g. Windows host shell)
            # can stop the subprocess even when sync_timeout is None.
            await self._apply_force_cancel(entry)
            return True
        entry.ctx.cancel_event.set()
        return True

    async def extend_offload_deadline(
        self,
        tool_call_id: str,
        *,
        seconds: float | None = None,
        no_deadline: bool = False,
    ) -> bool:
        """Extend foreground wait time (postpone offload). No effect on
        kill_deadline.

        Kept async (despite no await) for interface consistency with
        cancel() and other coordinator methods that callers await."""
        entry = self._entries.get(tool_call_id)
        if entry is None or entry.status != ToolCallStatus.RUNNING:
            return False

        if no_deadline:
            entry.ctx.offload_deadline = None
            entry.ctx.deadline_changed_event.set()
            return True

        if seconds is None or seconds <= 0:
            return False

        loop = asyncio.get_running_loop()
        base = entry.ctx.offload_deadline or loop.time()
        entry.ctx.offload_deadline = base + seconds
        entry.ctx.deadline_changed_event.set()
        return True

    async def extend_kill_deadline(
        self,
        tool_call_id: str,
        *,
        seconds: float | None = None,
        no_deadline: bool = False,
    ) -> bool:
        """Extend maximum execution time. Works in both foreground and
        background phases.

        Kept async for interface consistency with cancel()."""
        entry = self._entries.get(tool_call_id)
        if entry is None:
            return False

        hook = self.hooks.get(entry.ctx.tool_name)
        cap = hook.max_internal_timeout_secs

        if no_deadline:
            # Cap or OFFLOADED: refuse clearing the last hard execution bound.
            if cap is not None or entry.status == ToolCallStatus.OFFLOADED:
                return False
            entry.ctx.kill_deadline = None
            entry.ctx.deadline_changed_event.set()
            return True

        if seconds is None or seconds <= 0:
            return False

        loop = asyncio.get_running_loop()
        base = entry.ctx.kill_deadline or loop.time()
        new_deadline = base + seconds
        if cap is not None and new_deadline > entry.ctx.started_at + cap:
            return False
        entry.ctx.kill_deadline = new_deadline
        entry.ctx.deadline_changed_event.set()
        return True

    async def extend_deadline(
        self,
        tool_call_id: str,
        *,
        seconds: float | None = None,
        no_deadline: bool = False,
    ) -> bool:
        """Backward-compatible entry point. Extends offload deadline."""
        return await self.extend_offload_deadline(
            tool_call_id,
            seconds=seconds,
            no_deadline=no_deadline,
        )

    # ================================================================
    # HINT INJECTION + CALLBACKS
    # ================================================================
    async def pop_pending_hints(
        self,
        session_id: str,
    ) -> list[Any]:
        async with self._hints_lock:
            return self._pending_hints.pop(session_id, [])

    def on_completion(self, handler: CompletionHandler) -> None:
        self._completion_handlers.append(handler)

    def on_offloaded(self, handler: OffloadedHandler) -> None:
        self._offloaded_handlers.append(handler)

    # ================================================================
    # LLM CANCEL TOOL
    # ================================================================
    def as_cancel_tool(self) -> Callable[..., Any]:
        coordinator = self

        async def TaskStop(tool_call_id: str) -> ToolResponse:
            """Stop a still-running tool call by its id.

            Args:
                tool_call_id: id from previous offload notifications.
            """
            ok = await coordinator.cancel(
                tool_call_id,
                reason=CancelReason.AGENT,
            )
            text = (
                f"OK — sent cooperative stop signal to {tool_call_id}"
                if ok
                else f"No active tool call found with id {tool_call_id}"
            )
            return ToolResponse(
                content=[TextBlock(type="text", text=text)],
            )

        return TaskStop

    # ================================================================
    # SHUTDOWN
    # ================================================================
    async def shutdown(self) -> None:
        entries = list(self._entries.values())
        for entry in entries:
            entry.ctx.cancel_event.set()
            entry.ctx.cancel_reason = CancelReason.SHUTDOWN
        for entry in entries:
            if entry.background_task and not entry.background_task.done():
                try:
                    await asyncio.wait_for(
                        asyncio.shield(entry.background_task),
                        timeout=self._cancel_grace,
                    )
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    entry.background_task.cancel()

    # ================================================================
    # INTERNAL
    # ================================================================
    async def _await_next_event(
        self,
        entry: ToolCallEntry,
        *,
        chunk_queue: asyncio.Queue[Any] | None,
    ) -> _NextEvent:
        loop = asyncio.get_running_loop()
        now = loop.time()
        ctx = entry.ctx

        remaining_offload = (
            (ctx.offload_deadline - now)
            if ctx.offload_deadline is not None
            else None
        )
        remaining_kill = (
            (ctx.kill_deadline - now)
            if ctx.kill_deadline is not None
            else None
        )

        # kill takes priority — execution limit supersedes offload
        if remaining_kill is not None and remaining_kill <= 0:
            return _NextEvent(type="kill_deadline_reached")
        if remaining_offload is not None and remaining_offload <= 0:
            return _NextEvent(type="deadline_reached")

        candidates = [
            r for r in (remaining_offload, remaining_kill) if r is not None
        ]
        remaining = min(candidates) if candidates else None

        waiters: dict[str, asyncio.Task[Any]] = {}
        if chunk_queue is not None:
            waiters["chunk"] = asyncio.create_task(chunk_queue.get())
        waiters["cancel"] = asyncio.create_task(
            ctx.cancel_event.wait(),
        )
        waiters["dl_changed"] = asyncio.create_task(
            ctx.deadline_changed_event.wait(),
        )

        try:
            done, pending = await asyncio.wait(
                set(waiters.values()),
                timeout=remaining,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if pending:
                for t in pending:
                    t.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
        except asyncio.CancelledError:
            for t in waiters.values():
                if not t.done():
                    t.cancel()
            await asyncio.gather(
                *waiters.values(),
                return_exceptions=True,
            )
            raise

        if "chunk" in waiters and waiters["chunk"] in done:
            item = waiters["chunk"].result()
            event_type = (
                "stream_closed" if item is _STREAM_SENTINEL else "chunk"
            )
            return _NextEvent(
                type=event_type,
                chunk=item if event_type == "chunk" else None,
            )

        if waiters["cancel"] in done:
            return _NextEvent(type="cancelled")

        if waiters["dl_changed"] in done:
            ctx.deadline_changed_event.clear()
            return _NextEvent(type="deadline_changed")

        # timeout expired — determine which deadline fired
        now2 = loop.time()
        deadline_type = (
            "kill_deadline_reached"
            if ctx.kill_deadline is not None and now2 >= ctx.kill_deadline
            else "deadline_reached"
        )
        return _NextEvent(type=deadline_type)

    async def _drain(
        self,
        next_handler: Callable[..., AsyncGenerator[Any, None]],
        tool_call: Any,
        entry: ToolCallEntry,
    ) -> None:
        try:
            async for item in next_handler(tool_call=tool_call):
                if isinstance(item, ToolResponse):
                    entry.final_response = item
                    await entry.stream.close()
                    return

                if isinstance(item, ToolChunk):
                    entry.final_response.append_chunk(item)
                    await entry.stream.append(item)

                    if item.state in (
                        ToolResultState.ERROR,
                        ToolResultState.INTERRUPTED,
                    ):
                        entry.end_state = (
                            "error"
                            if item.state == ToolResultState.ERROR
                            else "interrupted"
                        )
                        await entry.stream.close()
                        return

        except asyncio.CancelledError:
            entry.final_response = ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=self._cancel_message_for_llm(entry.ctx),
                    ),
                ],
                id=entry.ctx.tool_call_id,
                state=ToolResultState.INTERRUPTED,
            )
            entry.end_state = "interrupted"
        except Exception as exc:
            entry.final_response = ToolResponse(
                content=[
                    TextBlock(type="text", text=f"Tool error: {exc}"),
                ],
                id=entry.ctx.tool_call_id,
                state=ToolResultState.ERROR,
            )
            entry.end_state = "error"
        finally:
            await entry.stream.close()

    async def _run_tool_with_hooks(
        self,
        next_handler: Callable[..., AsyncGenerator[Any, None]],
        tool_call: Any,
        entry: ToolCallEntry,
    ) -> None:
        hooks = self.hooks.get(entry.ctx.tool_name)
        token = set_call_context(entry.ctx)
        try:
            if hooks.before:
                try:
                    modified = await hooks.before(
                        _parse_tool_input(tool_call),
                        entry.ctx,
                    )
                    if modified is not None:
                        _update_tool_input(tool_call, modified)
                except Exception as exc:
                    logger.warning(
                        "before_call failed: %s",
                        exc,
                        exc_info=True,
                    )
                    entry.final_response = ToolResponse(
                        content=[
                            TextBlock(
                                type="text",
                                text=f"before_call failed: {exc}",
                            ),
                        ],
                        id=entry.ctx.tool_call_id,
                        state=ToolResultState.ERROR,
                    )
                    await entry.stream.close()
                    return

            if entry.ctx.is_cancelled:
                entry.final_response = ToolResponse(
                    content=[
                        TextBlock(
                            type="text",
                            text=self._cancel_message_for_llm(entry.ctx),
                        ),
                    ],
                    id=entry.ctx.tool_call_id,
                    state=ToolResultState.INTERRUPTED,
                )
                await entry.stream.close()
                return

            await self._drain(next_handler, tool_call, entry)

            if hooks.after:
                try:
                    resp = await asyncio.shield(
                        hooks.after(entry.final_response, entry.ctx),
                    )
                    if resp is not None:
                        entry.final_response = resp
                except asyncio.CancelledError:
                    pass
                except Exception as exc:
                    logger.warning(
                        "after_call failed: %s",
                        exc,
                        exc_info=True,
                    )
        finally:
            reset_call_context(token)

    async def _supervise(
        self,
        entry: ToolCallEntry,
        background_result_processor: BackgroundResultProcessor | None,
    ) -> None:
        bg = entry.background_task
        if bg is None:
            return

        await self._supervise_loop(entry, bg)

        await self._await_background_task(entry)

        await self._finalize_completed(entry)

        if background_result_processor is not None:
            try:
                entry.final_response = await background_result_processor(
                    entry.final_response,
                )
            except Exception:
                logger.exception("background result processor failed")

        hint = make_offload_hint_msg(entry)
        async with self._hints_lock:
            self._pending_hints.setdefault(
                entry.ctx.session_id,
                [],
            ).append(hint)

        for handler in list(self._completion_handlers):
            try:
                await handler(entry)
            except Exception as exc:
                logger.warning(
                    "completion handler failed: %s",
                    exc,
                    exc_info=True,
                )

    async def _supervise_loop(
        self,
        entry: ToolCallEntry,
        bg: asyncio.Task[Any],
    ) -> None:
        while not bg.done():
            event_task = asyncio.ensure_future(
                self._await_next_event(entry, chunk_queue=None),
            )
            done, _ = await asyncio.wait(
                {event_task, bg},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if event_task not in done:
                event_task.cancel()
                try:
                    await event_task
                except asyncio.CancelledError:
                    pass
                break

            event = event_task.result()
            if event.type in (
                "deadline_changed",
                "deadline_reached",
            ):
                continue
            if event.type == "cancelled":
                # Non-cooperative tools ignore cancel_event; without grace
                # + force this busy-loops on cancelled forever.
                await self._await_grace_or_force_cancel(entry)
                break
            if event.type in (
                "kill_deadline_reached",
                "stream_closed",
            ):
                if (
                    event.type != "stream_closed"
                    and not entry.ctx.cancel_event.is_set()
                ):
                    entry.ctx.cancel_event.set()
                    entry.ctx.cancel_reason = CancelReason.TIMEOUT
                if event.type != "stream_closed":
                    await self._await_grace_or_force_cancel(entry)
                break

    async def _await_grace_or_force_cancel(
        self,
        entry: ToolCallEntry,
    ) -> None:
        """Wait briefly for cooperative stop, then cancel the bg task."""
        bg = entry.background_task
        if bg is None or bg.done():
            return
        try:
            await asyncio.wait_for(
                asyncio.shield(bg),
                timeout=self._cancel_grace,
            )
        except asyncio.TimeoutError:
            await self._apply_force_cancel(entry)

    async def _apply_force_cancel(self, entry: ToolCallEntry) -> None:
        # Signal cooperative stop first. Windows host shell (and similar
        # bridges) rely on cancel_event → stop_event to kill the process
        # tree; task.cancel() alone leaves sync_timeout=None workers running.
        if entry.ctx.cancel_reason is None:
            entry.ctx.cancel_reason = CancelReason.USER
        entry.ctx.cancel_event.set()
        if entry.background_task is None or entry.background_task.done():
            return
        entry.force_cancelled = True
        entry.background_task.cancel()

    @staticmethod
    async def _await_background_task(entry: ToolCallEntry) -> None:
        bg = entry.background_task
        if bg is None:
            return
        try:
            await asyncio.shield(bg)
        except asyncio.CancelledError:
            # Distinguish: bg task cancelled vs caller task cancelled.
            current = asyncio.current_task()
            if current is not None and current.cancelling():
                raise

    async def _finalize_completed(self, entry: ToolCallEntry) -> ToolResponse:
        if entry.final_response is None:
            entry.final_response = ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text="tool produced no response",
                    ),
                ],
                id=entry.ctx.tool_call_id,
                state=ToolResultState.ERROR,
            )
        entry.status = ToolCallStatus.COMPLETED
        if entry.end_state is None:
            entry.end_state = (
                "interrupted" if entry.ctx.cancel_event.is_set() else "success"
            )
        self._entries.pop(entry.ctx.tool_call_id, None)
        self._store_completed(entry)
        return entry.final_response

    @staticmethod
    def _cancel_message_for_llm(ctx: ToolCallContext) -> str:
        """LLM-facing text for a cancelled tool call."""
        if ctx.cancel_reason == CancelReason.USER:
            return (
                f"Tool `{ctx.tool_name}` was cancelled by the user. "
                "Do not retry this tool call unless the user explicitly asks."
            )
        if ctx.cancel_reason == CancelReason.TIMEOUT:
            return (
                f"Tool `{ctx.tool_name}` was cancelled due to timeout. "
                "Do not retry with the same timeout unless the user asks; "
                "consider a longer timeout or a different approach."
            )
        reason = ctx.cancel_reason.value if ctx.cancel_reason else "unknown"
        return (
            f"Tool `{ctx.tool_name}` was cancelled (reason={reason}). "
            "Do not retry unless appropriate for the new situation."
        )

    def _ensure_kill_deadline_for_offload(
        self,
        ctx: ToolCallContext,
    ) -> bool:
        """Ensure background offload has a usable hard kill bound.

        Returns True when ``kill_deadline`` already has enough remaining
        budget, or was seeded/topped up from the tool/coordinator timeout.
        Returns False when no bound is available (caller should refuse
        offload / cancel instead).

        Note: topping up to ``MIN_BACKGROUND_WINDOW_SECS`` can make a short
        tool's total lifetime exceed its original timeout (e.g. 15s grep
        offloads at ~7.5s then may run up to +30s in background). This is
        intentional so offloaded work keeps a usable bounded window.
        """
        loop = asyncio.get_running_loop()
        now = loop.time()
        bound = self._resolve_timeout(ctx.agent_id, ctx.tool_name, None)

        if ctx.kill_deadline is not None:
            remaining = ctx.kill_deadline - now
            if remaining >= MIN_BACKGROUND_WINDOW_SECS:
                return True
            # No seedable Coordinator bound: refuse near-zero windows so
            # UI cannot claim "backgrounded" right before an immediate kill.
            if bound is None or bound <= 0:
                return False
            seed = max(MIN_BACKGROUND_WINDOW_SECS, bound)
            ctx.kill_deadline = now + seed
            ctx.deadline_changed_event.set()
            logger.info(
                "Topped up kill_deadline (+%.1fs) for offload of %s/%s "
                "(was %.1fs remaining)",
                seed,
                ctx.tool_name,
                ctx.tool_call_id,
                remaining,
            )
            return True

        if bound is None or bound <= 0:
            return False
        seed = max(MIN_BACKGROUND_WINDOW_SECS, bound)
        ctx.kill_deadline = now + seed
        ctx.deadline_changed_event.set()
        logger.info(
            "Seeded kill_deadline (+%.1fs) for offload of %s/%s",
            seed,
            ctx.tool_name,
            ctx.tool_call_id,
        )
        return True

    def _resolve_timeout(
        self,
        agent_id: str,
        tool_name: str,
        deadline_override: float | None,
    ) -> float | None:
        """Four-tier: override > per-agent > hook default > global."""
        if deadline_override is not None:
            return deadline_override
        per_agent = self._per_agent_tool_timeouts.get(
            (agent_id, tool_name),
        )
        if per_agent is not None:
            return per_agent
        hook = self.hooks.get(tool_name)
        if hook.default_timeout_secs is not None:
            return hook.default_timeout_secs
        return self._default_timeout


def _parse_tool_input(tool_call: Any) -> dict[str, Any]:
    raw = getattr(tool_call, "input", None)
    if isinstance(raw, dict):
        return dict(raw)
    return {}


def _update_tool_input(tool_call: Any, modified: dict[str, Any]) -> None:
    if hasattr(tool_call, "input") and isinstance(tool_call.input, dict):
        tool_call.input.update(modified)
