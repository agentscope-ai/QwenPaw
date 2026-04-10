# -*- coding: utf-8 -*-
"""Heartbeat-driven task dispatcher for multi-agent coordination.

On each tick the dispatcher:
1. Detects stuck tasks and marks them failed.
2. Picks pending tasks up to the available concurrency slots.
3. Matches each task to an agent (explicit @agent, tag-based, or default).
4. Dispatches via ``MultiAgentManager`` and tracks completion.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional, TYPE_CHECKING

from .task_board import TaskBoardManager, TaskItem

if TYPE_CHECKING:
    from ...config.config import TaskDispatcherConfig

logger = logging.getLogger(__name__)


class HeartbeatTaskDispatcher:
    """Coordinates task dispatch from the shared task board."""

    def __init__(
        self,
        *,
        config: "TaskDispatcherConfig",
        task_board: TaskBoardManager,
        multi_agent_manager: Any,
        channel_manager: Optional[Any] = None,
        agent_id: str = "default",
    ) -> None:
        self._config = config
        self._board = task_board
        self._agent_manager = multi_agent_manager
        self._channel_manager = channel_manager
        self._agent_id = agent_id
        self._semaphore = asyncio.Semaphore(
            config.max_concurrent_dispatches,
        )

    async def tick(self) -> None:
        """Called on each heartbeat interval by CronManager."""
        if not self._config.enabled:
            return

        # Check active hours
        if self._config.active_hours is not None:
            from ..crons.heartbeat import _in_active_hours

            if not _in_active_hours(self._config.active_hours):
                logger.debug(
                    "task_dispatcher: outside active hours, skipping",
                )
                return

        # Step 1: handle stuck tasks
        await self._handle_stuck_tasks()

        # Step 2: count available slots
        in_progress = self._board.list_in_progress()
        available = (
            self._config.max_concurrent_dispatches - len(in_progress)
        )

        pending = self._board.list_pending()
        logger.debug(
            "task_dispatcher: tick — %d pending,"
            " %d in_progress, %d slots available",
            len(pending),
            len(in_progress),
            max(available, 0),
        )

        if available <= 0 or not pending:
            return

        # Step 3: dispatch
        for task in pending[:available]:
            asyncio.create_task(self._dispatch_task(task))

    async def _dispatch_task(self, task: TaskItem) -> None:
        """Send a task to the matched agent."""
        async with self._semaphore:
            agent_id = self._match_agent(task)
            logger.info(
                "task_dispatcher: dispatching task '%s'"
                " to agent '%s'",
                task.id,
                agent_id,
            )

            self._board.mark_in_progress(task.id)

            try:
                workspace = await self._agent_manager.get_agent(
                    agent_id,
                )
                if workspace is None:
                    self._board.mark_failed(
                        task.id,
                        reason=f"agent '{agent_id}' not found",
                    )
                    logger.warning(
                        "task_dispatcher: agent '%s'"
                        " not found for task '%s'",
                        agent_id,
                        task.id,
                    )
                    return

                runner = workspace.runner
                req = {
                    "input": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": task.description,
                                },
                            ],
                        },
                    ],
                    "session_id": f"_task_{task.id}",
                    "user_id": "_dispatcher",
                }

                await asyncio.wait_for(
                    self._collect_response(runner, req),
                    timeout=self._config.task_timeout_minutes * 60,
                )

                self._board.mark_done(
                    task.id,
                    result_summary="completed",
                )
                logger.info(
                    "task_dispatcher: task '%s'"
                    " completed by agent '%s'",
                    task.id,
                    agent_id,
                )

                await self._notify_completion(task, "completed")

            except asyncio.TimeoutError:
                self._board.mark_failed(
                    task.id,
                    reason="timeout",
                )
                logger.warning(
                    "task_dispatcher: task '%s' timed out",
                    task.id,
                )

            except Exception as exc:  # pylint: disable=broad-except
                self._board.mark_failed(
                    task.id,
                    reason=str(exc)[:200],
                )
                logger.warning(
                    "task_dispatcher: task '%s' failed: %s",
                    task.id,
                    exc,
                )

    @staticmethod
    async def _collect_response(runner: Any, req: dict) -> str:
        """Stream all events from the runner, return concatenated text."""
        text = ""
        async for event in runner.stream_query(req):
            if isinstance(event, dict):
                content = event.get("content", "")
                if isinstance(content, str):
                    text += content
            elif isinstance(event, str):
                text += event
        return text

    def _match_agent(self, task: TaskItem) -> str:
        """Determine which agent should handle this task."""
        # Priority 1: explicit @agent
        if task.agent:
            return task.agent

        # Priority 2: fall back to this workspace's agent
        return self._agent_id

    async def _handle_stuck_tasks(self) -> None:
        """Mark tasks stuck beyond timeout as failed."""
        stuck = self._board.list_stuck(
            self._config.task_timeout_minutes,
        )
        for task in stuck:
            self._board.mark_failed(
                task.id,
                reason=(
                    f"stuck for >{self._config.task_timeout_minutes}m"
                ),
            )
            logger.warning(
                "task_dispatcher: task '%s' stuck"
                " (in_progress > %d min), marking failed",
                task.id,
                self._config.task_timeout_minutes,
            )

    async def _notify_completion(
        self,
        task: TaskItem,
        result: str,
    ) -> None:
        """Notify user of task completion."""
        notify = self._config.notify
        if notify == "main" or self._channel_manager is None:
            return

        text = (
            f"✅ Task completed: **{task.description[:100]}**"
            f"\n_{result[:200]}_"
        )
        try:
            if notify == "last":
                from ...config.config import load_agent_config

                agent_config = load_agent_config(self._agent_id)
                ld = agent_config.last_dispatch
                if ld and ld.channel:
                    await self._channel_manager.send_text(
                        channel=ld.channel,
                        user_id=ld.user_id or "",
                        session_id=ld.session_id or "main",
                        text=text,
                    )
            else:
                await self._channel_manager.send_text(
                    channel=notify,
                    user_id="",
                    session_id="main",
                    text=text,
                )
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning(
                "task_dispatcher: notification failed: %s",
                exc,
            )
