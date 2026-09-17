# -*- coding: utf-8 -*-
"""模型热路径与 PostgreSQL 用量 Repository 之间的异步队列。"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from uuid import UUID

from .buffer import _UsageEvent
from .usage_repository import PostgresUsageRepository, UsageEvent

logger = logging.getLogger(__name__)


class PostgresUsageBuffer:
    def __init__(self, *, repository: PostgresUsageRepository) -> None:
        self._repository = repository
        self._queue: asyncio.Queue[_UsageEvent] = asyncio.Queue()
        self._consumer_task: asyncio.Task | None = None

    def start(self) -> None:
        if self._consumer_task is None:
            self._consumer_task = asyncio.create_task(
                self._consume(), name="postgres-usage-consumer"
            )

    def enqueue(self, event: _UsageEvent) -> None:
        self._queue.put_nowait(event)

    async def stop(self) -> None:
        if self._consumer_task is None:
            return
        await self._queue.join()
        self._consumer_task.cancel()
        try:
            await self._consumer_task
        except asyncio.CancelledError:
            pass
        self._consumer_task = None

    async def _consume(self) -> None:
        while True:
            event = await self._queue.get()
            try:
                await self._persist(event)
            except Exception:  # noqa: BLE001 - background accounting must not fail calls
                logger.exception("token_usage: PostgreSQL usage event rejected")
            finally:
                self._queue.task_done()

    async def _persist(self, event: _UsageEvent) -> bool:
        if not event.user_id or not event.agent_key:
            logger.warning("token_usage: missing trusted user or agent attribution")
            return False
        try:
            user_id = UUID(event.user_id)
        except ValueError:
            logger.warning("token_usage: invalid trusted user attribution")
            return False
        return await self._repository.append(
            UsageEvent(
                occurred_at=datetime.fromisoformat(event.now_iso),
                user_id=user_id,
                actor_type=event.actor_type,
                agent_key=event.agent_key,
                provider_key=event.provider_id,
                model_key=event.model_name,
                prompt_tokens=event.prompt_tokens,
                completion_tokens=event.completion_tokens,
                conversation_id=event.conversation_id,
                run_id=event.run_id,
                automation_schedule_id=event.automation_schedule_id,
            )
        )


__all__ = ["PostgresUsageBuffer"]
