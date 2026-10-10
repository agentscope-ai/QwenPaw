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
)
from typing import Any

from agentscope.event import ReplyEndEvent
from agentscope.middleware import MiddlewareBase

logger = logging.getLogger(__name__)


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
        self.tasks: list[asyncio.Task[Any]] = []
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
        """Register immediately, returning a coroutine for hosted-task APIs."""

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

        task = asyncio.create_task(run())
        self.tasks.append(task)

        async def wait() -> Any:
            return await task

        return wait()

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
        if not self.tasks:
            return await self.await_next(**kwargs)
        # Reuse even an in-flight downstream call. Never replay a tool/model.
        return await self.tasks[-1]

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

    def is_implemented(self, hook_name: str) -> bool:
        return self.middleware.is_implemented(hook_name)

    def _diagnose(self, hook: str, exc: Exception) -> None:
        from ..plugins.lifecycle import note_plugin_diagnostic

        logger.exception(
            "Plugin '%s' middleware %s failed; bypassing",
            self.plugin_id,
            hook,
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
            await call.close_streams()

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
            await call.close_streams()
            raise
        await call.close_streams()
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
            await call.close_streams()

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
