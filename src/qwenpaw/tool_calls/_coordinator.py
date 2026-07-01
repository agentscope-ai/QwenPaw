# -*- coding: utf-8 -*-
"""ToolCoordinator — single owner of all in-flight tool calls."""

from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Awaitable, Callable

from agentscope.message import TextBlock, ToolResultState
from agentscope.tool import ToolChunk, ToolResponse

from ._context import CancelReason, OffloadReason, ToolCallContext
from ._ctxvars import reset_call_context, set_call_context
from ._entry import ResultFinalizer, ToolCallEntry, ToolCallStatus
from ._hint import make_offload_hint_msg
from ._hooks import ToolHookRegistry
from ._stream import ToolStream, _SENTINEL as _STREAM_SENTINEL

logger = logging.getLogger(__name__)

CompletionHandler = Callable[[ToolCallEntry], Awaitable[None]]
OffloadedHandler = Callable[[ToolCallEntry], Awaitable[None]]


@dataclass
class _NextEvent:
    type: str  # chunk | stream_closed | cancelled | deadline_reached
    #            | deadline_changed
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
    ) -> None:
        self._default_timeout = default_timeout_secs
        self._cancel_grace = cancel_grace_period_secs

        self._entries: dict[str, ToolCallEntry] = {}
        self._entries_lock = asyncio.Lock()
        self._pending_hints: dict[str, list[Any]] = {}
        self._hints_lock = asyncio.Lock()
        self._completion_handlers: list[CompletionHandler] = []
        self._offloaded_handlers: list[OffloadedHandler] = []

        self.hooks = ToolHookRegistry()
        self._per_agent_tool_timeouts: dict[tuple[str, str], float] = {}

    # ================================================================
    # PRIMARY ENTRY
    # ================================================================
    async def execute(  # pylint: disable=too-many-locals
        self,
        tool_call: Any,
        next_handler: Callable[..., AsyncGenerator[Any, None]],
        *,
        session_id: str,
        agent_id: str,
        root_session_id: str,
        deadline_override: float | None = None,
        result_finalizer: ResultFinalizer | None = None,
    ) -> AsyncGenerator[Any, None]:
        entry = self._create_entry(
            tool_call,
            session_id,
            agent_id,
            root_session_id,
            deadline_override,
            result_finalizer,
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
                    self._handle_deadline_reached(ctx)
                    terminal = "offload"
                    break
        finally:
            entry.stream.remove_subscriber(chunk_queue)

        if terminal == "completed":
            await self._await_background_task(entry)
            yield await self._finalize_completed(entry)
            return

        yield await self._begin_offload(entry)

    @staticmethod
    def _handle_deadline_reached(ctx: ToolCallContext) -> None:
        if ctx.offload_reason is None:
            ctx.offload_reason = OffloadReason.TIMEOUT
            ctx.cancel_event.set()
            if ctx.cancel_reason is None:
                ctx.cancel_reason = CancelReason.TIMEOUT

    def _create_entry(
        self,
        tool_call: Any,
        session_id: str,
        agent_id: str,
        root_session_id: str,
        deadline_override: float | None,
        result_finalizer: ResultFinalizer | None,
    ) -> ToolCallEntry:
        loop = asyncio.get_running_loop()
        now = loop.time()
        timeout = self._resolve_timeout(
            agent_id,
            tool_call.name,
            deadline_override,
        )
        ctx = ToolCallContext(
            tool_call_id=tool_call.id,
            tool_name=tool_call.name,
            session_id=session_id,
            agent_id=agent_id,
            root_session_id=root_session_id,
            started_at=now,
            deadline=now + timeout if timeout is not None else None,
            cancel_event=asyncio.Event(),
        )
        return ToolCallEntry(
            ctx=ctx,
            stream=ToolStream(
                tool_call_id=tool_call.id,
                session_id=session_id,
            ),
            final_response=ToolResponse(id=tool_call.id),
            result_finalizer=result_finalizer,
        )

    async def _begin_offload(
        self,
        entry: ToolCallEntry,
    ) -> ToolResponse:
        ctx = entry.ctx
        entry.status = ToolCallStatus.OFFLOADED
        ctx.deadline = None

        asyncio.create_task(
            self._supervise(entry),
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
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=(
                        f"Tool `{ctx.tool_name}` has been offloaded"
                        f" to background (task={bg_task_name},"
                        f" reason={reason}). You may continue."
                    ),
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
        return self._entries.get(tool_call_id)

    def list_entries(
        self,
        session_id: str | None = None,
    ) -> list[ToolCallEntry]:
        entries = list(self._entries.values())
        if session_id is not None:
            entries = [e for e in entries if e.ctx.session_id == session_id]
        return entries

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
        entry.ctx.offload_reason = reason
        entry.ctx.deadline = asyncio.get_running_loop().time()
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
        if force:
            await self._apply_force_cancel(entry)
            return True
        entry.ctx.cancel_event.set()
        entry.ctx.cancel_reason = reason
        return True

    async def extend_deadline(
        self,
        tool_call_id: str,
        *,
        seconds: float | None = None,
        no_deadline: bool = False,
    ) -> bool:
        entry = self._entries.get(tool_call_id)
        if entry is None:
            return False

        hook = self.hooks.get(entry.ctx.tool_name)
        cap = hook.max_internal_timeout_secs

        if no_deadline:
            if cap is not None:
                return False
            entry.ctx.deadline = None
            entry.ctx.deadline_changed_event.set()
            return True

        if seconds is None or seconds <= 0:
            return False

        loop = asyncio.get_running_loop()
        base = entry.ctx.deadline if entry.ctx.deadline else loop.time()
        new_deadline = base + seconds

        if cap is not None:
            max_allowed = entry.ctx.started_at + cap
            if new_deadline > max_allowed:
                return False

        entry.ctx.deadline = new_deadline
        entry.ctx.deadline_changed_event.set()
        return True

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
        remaining = (
            entry.ctx.deadline - loop.time()
            if entry.ctx.deadline is not None
            else None
        )

        if remaining is not None and remaining <= 0:
            return _NextEvent(type="deadline_reached")

        waiters: dict[str, asyncio.Task[Any]] = {}
        if chunk_queue is not None:
            waiters["chunk"] = asyncio.create_task(chunk_queue.get())
        waiters["cancel"] = asyncio.create_task(
            entry.ctx.cancel_event.wait(),
        )
        waiters["dl_changed"] = asyncio.create_task(
            entry.ctx.deadline_changed_event.wait(),
        )

        try:
            done, pending = await asyncio.wait(
                set(waiters.values()),
                timeout=remaining,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
        except asyncio.CancelledError:
            for t in waiters.values():
                t.cancel()
            raise

        if "chunk" in waiters and waiters["chunk"] in done:
            item = waiters["chunk"].result()
            if item is _STREAM_SENTINEL:
                return _NextEvent(type="stream_closed")
            return _NextEvent(type="chunk", chunk=item)

        if waiters["cancel"] in done:
            return _NextEvent(type="cancelled")

        if waiters["dl_changed"] in done:
            # Clear before returning so the next _await_next_event blocks.
            # A concurrent set() between wait() and clear() is benign:
            # the caller always re-reads entry.ctx.deadline for the true
            # value, so a "lost" notification just triggers one extra loop.
            entry.ctx.deadline_changed_event.clear()
            return _NextEvent(type="deadline_changed")

        return _NextEvent(type="deadline_reached")

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
                        text="Tool cancelled by manager",
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
                            text="Cancelled before execution",
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

    async def _supervise(self, entry: ToolCallEntry) -> None:
        bg = entry.background_task
        if bg is None:
            return

        while not bg.done():
            event = await self._await_next_event(
                entry,
                chunk_queue=None,
            )

            if event.type in ("cancelled", "deadline_changed"):
                continue

            if event.type == "deadline_reached":
                entry.ctx.cancel_event.set()
                entry.ctx.cancel_reason = CancelReason.TIMEOUT
                try:
                    await asyncio.wait_for(
                        asyncio.shield(bg),
                        timeout=self._cancel_grace,
                    )
                except asyncio.TimeoutError:
                    await self._apply_force_cancel(entry)
                break

            if event.type == "stream_closed":
                break

        await self._await_background_task(entry)

        await self._finalize_completed(entry)

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

    async def _apply_force_cancel(self, entry: ToolCallEntry) -> None:
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
        if entry.result_finalizer is not None and not entry.result_finalized:
            finalized = entry.result_finalizer(
                entry.final_response,
                entry.ctx,
            )
            if inspect.isawaitable(finalized):
                finalized = await finalized
            entry.final_response = finalized
            entry.result_finalized = True
        entry.status = ToolCallStatus.COMPLETED
        if entry.end_state is None:
            entry.end_state = (
                "interrupted" if entry.ctx.cancel_event.is_set() else "success"
            )
        self._entries.pop(entry.ctx.tool_call_id, None)
        return entry.final_response

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
