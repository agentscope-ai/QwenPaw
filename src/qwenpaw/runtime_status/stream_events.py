# -*- coding: utf-8 -*-
"""Runtime-status transitions for streamed agent responses."""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterable, Callable
from typing import Any


def emit_stream_event_status(
    emit_status: Callable[..., None],
    *,
    session_id: str,
    root_session_id: str,
    chat_id: str | None,
    seen_first_event: bool,
    last: bool,
) -> bool:
    """Emit status changes before the stream event is yielded to consumers.

    A consumer may stop iterating as soon as it receives ``last=True``.  The
    terminal status must therefore be emitted before that event is yielded,
    otherwise the cached running status can remain visible indefinitely.
    """
    if not seen_first_event:
        emit_status(
            session_id=session_id,
            root_session_id=root_session_id,
            chat_id=chat_id,
            stage="model_streaming",
            message="模型已开始响应。",
        )

    if last:
        emit_status(
            session_id=session_id,
            root_session_id=root_session_id,
            chat_id=chat_id,
            stage="completed",
            status="completed",
            message="任务已完成。",
        )

    return True


async def stream_with_runtime_status(
    stream: AsyncIterable[tuple[Any, bool]],
    emit_status: Callable[..., None],
    *,
    session_id: str,
    root_session_id: str,
    chat_id: str | None,
) -> AsyncGenerator[tuple[Any, bool], None]:
    """Forward a response stream while guaranteeing terminal status cleanup."""
    seen_first_event = False
    terminal_emitted = False
    try:
        async for msg, last in stream:
            seen_first_event = emit_stream_event_status(
                emit_status,
                session_id=session_id,
                root_session_id=root_session_id,
                chat_id=chat_id,
                seen_first_event=seen_first_event,
                last=last,
            )
            terminal_emitted = terminal_emitted or last
            yield msg, last
    finally:
        if not terminal_emitted:
            emit_status(
                session_id=session_id,
                root_session_id=root_session_id,
                chat_id=chat_id,
                stage="completed",
                status="completed",
                message="任务已完成。",
            )


def emit_runtime_final_status(
    emit_status: Callable[..., None],
    *,
    session_id: str,
    root_session_id: str,
    chat_id: str | None,
    error: BaseException | None,
) -> None:
    """Finish the runtime-status lifecycle for the current request."""
    if error is None:
        emit_status(
            session_id=session_id,
            root_session_id=root_session_id,
            chat_id=chat_id,
            stage="completed",
            status="completed",
            message="任务已完成。",
        )
        return

    cancelled = isinstance(error, (asyncio.CancelledError, KeyboardInterrupt))
    emit_status(
        session_id=session_id,
        root_session_id=root_session_id,
        chat_id=chat_id,
        stage="cancelled" if cancelled else "failed",
        status="failed",
        message="任务已取消。" if cancelled else str(error)[:180],
    )
