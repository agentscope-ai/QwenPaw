# -*- coding: utf-8 -*-
"""Handler for /stop command.

The /stop command immediately terminates an ongoing agent task.
"""

from __future__ import annotations

import logging

from ....plan.broadcast import plan_sse_scope
from ....plan.session_sync import (
    clear_plan_notebook_if_session_has_no_snapshot,
    persist_plan_notebook_to_session,
    reset_plan_notebook_for_session_switch,
)
from .base import BaseControlCommandHandler, ControlContext

logger = logging.getLogger(__name__)


class StopCommandHandler(BaseControlCommandHandler):
    """Handler for /stop command.

    Features:
    - Immediate response (priority level 0)
    - Stops task via TaskTracker.request_stop (native cancellation)
    - Default: stops current session
    - Optional: specify target session_id

    Usage:
        /stop                  # Stop current session
        /stop session=console:user1  # Stop specific session
    """

    command_name = "/stop"

    async def _abandon_plan_for_session(
        self,
        workspace,
        *,
        channel_id: str,
        target_session_id: str,
        user_id: str,
    ) -> bool:
        """Hydrate notebook, abandon plan for session, persist.

        Returns True if a plan was abandoned before reset. Failures are logged
        so /stop still stops the task.
        """
        nb = workspace.plan_notebook
        if nb is None or not (target_session_id or "").strip():
            return False
        runner = getattr(workspace, "runner", None)
        sess = getattr(runner, "session", None) if runner is not None else None
        if sess is None:
            return False
        try:
            with plan_sse_scope(channel_id, target_session_id):
                await clear_plan_notebook_if_session_has_no_snapshot(
                    session=sess,
                    plan_notebook=nb,
                    session_id=target_session_id,
                    user_id=user_id,
                    agent_id=workspace.agent_id,
                )
                try:
                    await sess.load_session_state(
                        session_id=target_session_id,
                        user_id=user_id,
                        plan_notebook=nb,
                    )
                except KeyError as e:
                    logger.warning(
                        "/stop plan hydrate skipped (schema mismatch): %s",
                        e,
                    )
                had_plan = getattr(nb, "current_plan", None) is not None
                if had_plan:
                    await reset_plan_notebook_for_session_switch(
                        nb,
                        agent_id=workspace.agent_id,
                        outcome="Stopped by /stop",
                    )
                await persist_plan_notebook_to_session(
                    session=sess,
                    plan_notebook=nb,
                    session_id=target_session_id,
                    user_id=user_id,
                )
                return had_plan
        except Exception:
            logger.warning(
                "/stop: plan notebook cleanup failed (task still stopped)",
                exc_info=True,
            )
            return False

    async def handle(self, context: ControlContext) -> str:
        """Handle /stop command.

        Args:
            context: Control command context

        Returns:
            Response text (success or error message)
        """
        target_session_id = context.args.get(
            "session",
            context.session_id,
        )

        logger.info(
            f"/stop command: current_session={context.session_id[:30]} "
            f"target_session={target_session_id[:30]}",
        )

        workspace = context.workspace
        channel_id = context.channel.channel

        chat_id = await workspace.chat_manager.get_chat_id_by_session(
            target_session_id,
            channel_id,
        )

        if chat_id is None:
            logger.warning(
                f"/stop: No active chat found for "
                f"session={target_session_id[:30]} channel={channel_id}",
            )
            return (
                f"**No Active Task**\n\n"
                f"No running task found for session "
                f"`{target_session_id[:40]}`."
            )

        stopped = await workspace.task_tracker.request_stop(chat_id)

        cleared = await workspace.channel_manager.clear_queue(
            channel_id,
            target_session_id,
            20,
        )

        plan_abandoned = await self._abandon_plan_for_session(
            workspace,
            channel_id=channel_id,
            target_session_id=target_session_id,
            user_id=context.user_id,
        )
        plan_suffix = (
            " Current plan abandoned for this session."
            if plan_abandoned
            else ""
        )

        if stopped or cleared > 0:
            logger.info(
                f"/stop: stopped={stopped} cleared={cleared} "
                f"chat_id={chat_id} session={target_session_id[:30]}",
            )
            status_parts = []
            if stopped:
                status_parts.append("running task stopped")
            if cleared > 0:
                status_parts.append(f"{cleared} queued message(s) cleared")
            status_text = " and ".join(status_parts)
            return (
                f"**Task Stopped**\n\n"
                f"Session `{target_session_id[:40]}`: {status_text}."
                f"{plan_suffix}"
            )
        else:
            logger.warning(
                f"/stop: Nothing to stop: "
                f"chat_id={chat_id} session={target_session_id[:30]}",
            )
            return (
                f"**Task Not Running**\n\n"
                f"No active task or queued messages for session "
                f"`{target_session_id[:40]}`.{plan_suffix}"
            )
