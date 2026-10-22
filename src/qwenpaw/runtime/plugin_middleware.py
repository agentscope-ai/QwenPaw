# -*- coding: utf-8 -*-
"""Contain plugin hook faults while preserving downstream execution."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import (
    AsyncGenerator,
    AsyncIterable,
    AsyncIterator,
    Callable,
    Coroutine,
    Generator,
)
from typing import Any

from agentscope.event import ReplyEndEvent
from agentscope.middleware import MiddlewareBase

logger = logging.getLogger(__name__)
_CANCEL_TIMEOUT = 1.0


class _DeferredCall(Coroutine[Any, Any, Any]):
    """A hosted coroutine whose downstream task starts on its first await."""

    def __init__(self, run: Callable[[], Coroutine[Any, Any, Any]]) -> None:
        self.run = run
        self.task: asyncio.Task[Any] | None = None
        self.waiter: Coroutine[Any, Any, Any] | None = None
        self.closed = False

    async def result(self) -> Any:
        if self.task is None:
            if self.closed:
                return None
            self.task = asyncio.create_task(self.run())
        return await asyncio.shield(self.task)

    def __await__(self) -> Generator[Any, None, Any]:
        return (yield from self)

    def __iter__(self) -> _DeferredCall:
        return self

    def __next__(self) -> Any:
        return self.send(None)

    def send(self, value: Any) -> Any:
        if self.closed:
            raise StopIteration
        if self.waiter is None:
            self.waiter = self.result()
        return self.waiter.send(value)

    def throw(self, typ: Any, val: Any = None, tb: Any = None) -> Any:
        if self.waiter is None or self.closed:
            raise typ if isinstance(typ, BaseException) else typ(val)
        return self.waiter.throw(typ, val, tb)

    def close(self) -> None:
        self.closed = True
        if self.waiter is not None:
            self.waiter.close()


class _TrackedStream:
    """Resume only unread items if plugin iteration fails.

    Once an item is handed to the plugin, it is consumed. Plugins may
    transform, filter, or combine items, so output identity cannot establish
    delivery. An item consumed before a plugin fault is not replayed, even
    when the plugin failed before yielding it. ReplyEndEvent is an exception:
    the reply loop must receive it before the downstream iterator resumes.
    """

    def __init__(self, stream: AsyncIterable[Any], call: _HookCall) -> None:
        self.iterator = stream.__aiter__()
        self.call = call
        self.done = False
        self.pending_ends: list[ReplyEndEvent] = []

    async def relay(self) -> AsyncIterator[Any]:
        while not self.done:
            try:
                item = await anext(self.iterator)
            except StopAsyncIteration:
                self.done = True
                return
            except Exception as exc:
                self.call.downstream_errors.append(exc)
                raise
            if isinstance(item, ReplyEndEvent):
                self.pending_ends.append(item)
            yield item

    async def recover(self) -> AsyncIterator[Any]:
        # Deliver before advancing: the suspended reply loop checks whether
        # its end event escaped the middleware chain on the next pull.
        while self.pending_ends:
            yield self.pending_ends.pop(0)
        async for item in self.relay():
            self.call.delivered(item)
            yield item


class _HookCall:
    """Per-invocation downstream handles and exception provenance."""

    def __init__(self, next_handler: Callable[..., Any]) -> None:
        self.next_handler = next_handler
        self.streams: list[_TrackedStream] = []
        self.calls: list[_DeferredCall] = []
        self.downstream_errors: list[Exception] = []

    def stream_next(self, **kwargs: Any) -> AsyncIterator[Any]:
        try:
            stream = self.next_handler(**kwargs)
            tracked = _TrackedStream(stream, self)
        except Exception as exc:
            self.downstream_errors.append(exc)
            raise
        self.streams.append(tracked)
        return tracked.relay()

    def await_next(self, **kwargs: Any) -> Coroutine[Any, Any, Any]:
        """Record immediately without changing downstream execution timing."""

        async def run() -> Any:
            try:
                result = await self.next_handler(**kwargs)
                if isinstance(result, AsyncIterable):
                    tracked = _TrackedStream(result, self)
                    self.streams.append(tracked)
                    return tracked.relay()
                return result
            except Exception as exc:
                self.downstream_errors.append(exc)
                raise

        pending = _DeferredCall(run)
        self.calls.append(pending)
        return pending

    def delivered(self, item: Any) -> None:
        """Acknowledge end events, including copies made by a plugin."""
        if not isinstance(item, ReplyEndEvent):
            return
        for stream in self.streams:
            for index, pending in enumerate(stream.pending_ends):
                if (pending.session_id, pending.reply_id) == (
                    item.session_id,
                    item.reply_id,
                ):
                    stream.pending_ends.pop(index)
                    return

    def is_downstream_error(self, exc: BaseException) -> bool:
        seen: set[int] = set()
        current: BaseException | None = exc
        while current is not None and id(current) not in seen:
            if any(current is error for error in self.downstream_errors):
                return True
            seen.add(id(current))
            current = current.__cause__ or current.__context__
        return False

    async def recover_stream(
        self,
        kwargs: dict[str, Any],
    ) -> AsyncIterator[Any]:
        if not self.streams:
            self.stream_next(**kwargs)
        for stream in self.streams:
            async for item in stream.recover():
                yield item

    async def recover_result(self, kwargs: dict[str, Any]) -> Any:
        # A closed waiter can still own a completed or in-flight task.
        for entry in reversed(self.calls):
            if entry.task is not None:
                return await entry.result()
        # Retire unused calls before bypassing the faulty plugin. Hosted
        # waiters that run later must not start another downstream call.
        for entry in self.calls:
            entry.close()
        return await self.await_next(**kwargs)

    async def close_streams(self) -> None:
        for stream in self.streams:
            close = getattr(stream.iterator, "aclose", None)
            if close is not None:
                await close()


class PluginMiddlewareGuard(MiddlewareBase):
    """Protect AgentScope hooks; forward only hooks the plugin implements."""

    def __init__(self, middleware: MiddlewareBase, plugin_id: str) -> None:
        self.middleware = middleware
        self.plugin_id = plugin_id
        self._pending_cleanup: set[asyncio.Task[Any]] = set()

    def _cleanup_done(self, task: asyncio.Task[Any]) -> None:
        self._pending_cleanup.discard(task)
        if not task.cancelled():
            # Retrieve faults without misclassifying downstream failures.
            task.exception()

    async def _drain(self, tasks: set[asyncio.Task[Any]], hook: str) -> None:
        if not tasks:
            return
        self._pending_cleanup.update(tasks)
        for task in tasks:
            task.add_done_callback(self._cleanup_done)
        _, pending = await asyncio.wait(tasks, timeout=_CANCEL_TIMEOUT)
        if pending:
            self._diagnose(
                hook,
                TimeoutError("middleware cleanup did not finish in time"),
            )

    async def _cleanup(self, call: _HookCall, hook: str) -> None:
        tasks = {entry.task for entry in call.calls if entry.task is not None}
        for entry in call.calls:
            entry.close()
        for task in tasks:
            if not task.done():
                task.cancel()
        await self._drain(tasks, hook)
        if call.streams:

            async def close() -> None:
                try:
                    await call.close_streams()
                except Exception as exc:
                    self._diagnose(hook, exc)
                    raise

            closing = asyncio.create_task(close())
            await self._drain({closing}, hook)
            if closing.done() and not closing.cancelled():
                closing.result()

    def is_implemented(self, hook_name: str) -> bool:
        return self.middleware.is_implemented(hook_name)

    def _diagnose(self, hook: str, exc: Exception) -> None:
        from ..plugins.lifecycle import note_plugin_diagnostic

        logger.error(
            "Plugin '%s' middleware %s failed; bypassing",
            self.plugin_id,
            hook,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        note_plugin_diagnostic(self.plugin_id, f"middleware {hook}: {exc}")

    async def _stream_hook(
        self,
        hook: str,
        agent: Any,
        input_kwargs: dict[str, Any],
        next_handler: Callable[..., Any],
    ) -> AsyncIterator[Any]:
        call = _HookCall(next_handler)
        original_kwargs = dict(input_kwargs)
        try:
            try:
                result = getattr(self.middleware, hook)(
                    agent=agent,
                    input_kwargs=input_kwargs,
                    next_handler=call.stream_next,
                )
                if inspect.isawaitable(result):
                    result = await result
                async for item in result:
                    call.delivered(item)
                    yield item
            except Exception as exc:
                if call.is_downstream_error(exc):
                    raise
                self._diagnose(hook, exc)
                async for item in call.recover_stream(original_kwargs):
                    yield item
        finally:
            await self._cleanup(call, hook)

    async def _result_hook(
        self,
        hook: str,
        agent: Any,
        input_kwargs: dict[str, Any],
        next_handler: Callable[..., Any],
    ) -> Any:
        call = _HookCall(next_handler)
        original_kwargs = dict(input_kwargs)
        try:
            try:
                result = await getattr(self.middleware, hook)(
                    agent=agent,
                    input_kwargs=input_kwargs,
                    next_handler=call.await_next,
                )
            except Exception as exc:
                if call.is_downstream_error(exc):
                    raise
                self._diagnose(hook, exc)
                if call.streams:
                    result = call.recover_stream(original_kwargs)
                else:
                    result = await call.recover_result(original_kwargs)
            if isinstance(result, AsyncIterable):
                return self._result_stream(hook, result, call, original_kwargs)
        except BaseException:
            await self._cleanup(call, hook)
            raise
        await self._cleanup(call, hook)
        return result

    async def _result_stream(
        self,
        hook: str,
        result: AsyncIterable[Any],
        call: _HookCall,
        original_kwargs: dict[str, Any],
    ) -> AsyncIterator[Any]:
        try:
            try:
                async for item in result:
                    call.delivered(item)
                    yield item
            except Exception as exc:
                if call.is_downstream_error(exc):
                    raise
                self._diagnose(hook, exc)
                if not call.streams:
                    # Start downstream only if the plugin never called it.
                    # Otherwise reuse its completed or in-flight response.
                    recovered = await call.recover_result(original_kwargs)
                    if not isinstance(recovered, AsyncIterable):
                        if recovered is not None:
                            yield recovered
                        return
                for stream in call.streams:
                    async for item in stream.recover():
                        yield item
        finally:
            await self._cleanup(call, hook)

    async def on_reply(
        self,
        agent: Any,
        input_kwargs: dict,
        next_handler: Callable,
    ) -> AsyncGenerator[Any, None]:
        async for item in self._stream_hook(
            "on_reply",
            agent,
            input_kwargs,
            next_handler,
        ):
            yield item

    async def on_reasoning(
        self,
        agent: Any,
        input_kwargs: dict,
        next_handler: Callable,
    ) -> AsyncGenerator[Any, None]:
        async for item in self._stream_hook(
            "on_reasoning",
            agent,
            input_kwargs,
            next_handler,
        ):
            yield item

    async def on_acting(
        self,
        agent: Any,
        input_kwargs: dict,
        next_handler: Callable,
    ) -> AsyncGenerator[Any, None]:
        async for item in self._stream_hook(
            "on_acting",
            agent,
            input_kwargs,
            next_handler,
        ):
            yield item

    async def on_model_call(
        self,
        agent: Any,
        input_kwargs: dict,
        next_handler: Callable,
    ) -> Any:
        return await self._result_hook(
            "on_model_call",
            agent,
            input_kwargs,
            next_handler,
        )

    async def on_check_permission(
        self,
        agent: Any,
        input_kwargs: dict,
        next_handler: Callable,
    ) -> Any:
        return await self._result_hook(
            "on_check_permission",
            agent,
            input_kwargs,
            next_handler,
        )

    async def on_compress_context(
        self,
        agent: Any,
        input_kwargs: dict,
        next_handler: Callable,
    ) -> None:
        await self._result_hook(
            "on_compress_context",
            agent,
            input_kwargs,
            next_handler,
        )

    async def on_system_prompt(self, agent: Any, current_prompt: str) -> str:
        try:
            return await self.middleware.on_system_prompt(
                agent,
                current_prompt,
            )
        except Exception as exc:
            self._diagnose("on_system_prompt", exc)
            return current_prompt

    async def list_tools(self) -> list:
        try:
            return await self.middleware.list_tools()
        except Exception as exc:
            self._diagnose("list_tools", exc)
            return []

    async def get_middleware_key(self) -> str:
        try:
            return await self.middleware.get_middleware_key()
        except Exception as exc:
            self._diagnose("get_middleware_key", exc)
            return (
                f"plugin:{self.plugin_id}:{type(self.middleware).__qualname__}"
            )
