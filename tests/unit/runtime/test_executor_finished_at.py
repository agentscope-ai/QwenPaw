# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for the REPLY_END ``finished_at`` backfill in AgentExecutor.

Regression tests for issue #6826: assistant messages persisted via
``_save_to_context`` never received a ``finished_at`` stamp, so history
rebuilt from the API displayed ``created_at`` (the first-segment save
time) as the assistant completion time — under-reporting turns with
long tool calls.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, AsyncGenerator

import pytest
from agentscope.event import EventType

from qwenpaw.runtime.executor import AgentExecutor


def _msg(
    msg_id: str = "reply-1",
    role: str = "assistant",
    finished_at: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(id=msg_id, role=role, finished_at=finished_at)


def _agent(context: list[Any] | None) -> SimpleNamespace:
    if context is None:
        return SimpleNamespace(state=SimpleNamespace(context=[]))
    return SimpleNamespace(state=SimpleNamespace(context=context))


def _reply_end(
    reply_id: str = "reply-1",
    created_at: str = "2026-08-12T17:00:00.000000",
) -> SimpleNamespace:
    return SimpleNamespace(
        type=EventType.REPLY_END.value,
        reply_id=reply_id,
        created_at=created_at,
    )


class TestMaybeStampFinishedAt:
    def test_stamps_last_assistant_message_by_reply_id(self) -> None:
        target = _msg("reply-1")
        agent = _agent([_msg("user-0", role="user"), target])
        executor = AgentExecutor(agent, envelope=None)

        executor._maybe_stamp_finished_at(_reply_end("reply-1"))

        assert target.finished_at == "2026-08-12T17:00:00.000000"

    def test_prefers_reply_id_match_over_positional_last(self) -> None:
        target = _msg("reply-1")
        trailing = _msg("observed-later")
        agent = _agent([target, trailing])
        executor = AgentExecutor(agent, envelope=None)

        executor._maybe_stamp_finished_at(_reply_end("reply-1"))

        assert target.finished_at == "2026-08-12T17:00:00.000000"
        assert trailing.finished_at is None

    def test_falls_back_to_last_assistant_without_reply_id(self) -> None:
        target = _msg("reply-1")
        agent = _agent([_msg("user-0", role="user"), target])
        executor = AgentExecutor(agent, envelope=None)

        event = _reply_end("unknown-reply")
        executor._maybe_stamp_finished_at(event)

        assert target.finished_at == "2026-08-12T17:00:00.000000"

    def test_does_not_overwrite_existing_finished_at(self) -> None:
        target = _msg("reply-1", finished_at="2026-08-12T16:00:00.000000")
        agent = _agent([target])
        executor = AgentExecutor(agent, envelope=None)

        executor._maybe_stamp_finished_at(_reply_end("reply-1"))

        assert target.finished_at == "2026-08-12T16:00:00.000000"

    def test_skips_when_last_message_is_not_assistant(self) -> None:
        user_msg = _msg("user-9", role="user")
        agent = _agent([user_msg])
        executor = AgentExecutor(agent, envelope=None)

        executor._maybe_stamp_finished_at(_reply_end("unknown-reply"))

        assert user_msg.finished_at is None

    def test_ignores_non_reply_end_events(self) -> None:
        target = _msg("reply-1")
        agent = _agent([target])
        executor = AgentExecutor(agent, envelope=None)

        event = SimpleNamespace(
            type=EventType.TEXT_BLOCK_END.value,
            reply_id="reply-1",
            created_at="2026-08-12T17:00:00.000000",
        )
        executor._maybe_stamp_finished_at(event)

        assert target.finished_at is None

    def test_empty_context_is_noop(self) -> None:
        executor = AgentExecutor(_agent(None), envelope=None)
        executor._maybe_stamp_finished_at(_reply_end())

    def test_agent_without_state_is_noop(self) -> None:
        executor = AgentExecutor(SimpleNamespace(), envelope=None)
        executor._maybe_stamp_finished_at(_reply_end())

    def test_missing_created_at_falls_back_to_now(self) -> None:
        target = _msg("reply-1")
        agent = _agent([target])
        executor = AgentExecutor(agent, envelope=None)

        event = SimpleNamespace(
            type=EventType.REPLY_END.value,
            reply_id="reply-1",
            created_at=None,
        )
        executor._maybe_stamp_finished_at(event)

        assert target.finished_at  # stamped with datetime.now()


@pytest.mark.asyncio
async def test_run_stamps_finished_at_on_reply_end() -> None:
    """The stamp happens while driving the reply stream (issue #6826)."""
    target = _msg("reply-1")
    agent = _agent([_msg("user-0", role="user"), target])

    async def reply_stream(inputs: Any) -> AsyncGenerator[Any, None]:
        del inputs
        yield _reply_end("reply-1")

    agent.reply_stream = reply_stream

    class _SilentEnvelope:
        async def heartbeat(self) -> AsyncGenerator[Any, None]:
            return
            yield  # pragma: no cover

        async def translate_event(
            self,
            event: Any,
        ) -> AsyncGenerator[Any, None]:
            del event
            return
            yield  # pragma: no cover

    executor = AgentExecutor(agent, _SilentEnvelope())
    async for _ in executor.run([]):
        pass

    assert target.finished_at == "2026-08-12T17:00:00.000000"
