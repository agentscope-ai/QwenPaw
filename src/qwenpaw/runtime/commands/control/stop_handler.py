# -*- coding: utf-8 -*-
"""Handler for /stop command.

The /stop command immediately terminates an ongoing agent task.
"""

from __future__ import annotations

import logging

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
            f"target_session={target_session_id[:30]} "
            f"user_id={context.user_id}",
        )

        workspace = context.workspace
        channel_id = context.channel.channel

        # Scope the lookup to the requesting user so users sharing the same
        # session_id (group members, or DM users whose conversation_id suffix
        # collides) can only stop their own task.
        chat_id = await workspace.chat_manager.get_chat_id_by_session(
            target_session_id,
            channel_id,
            user_id=context.user_id,
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
        try:
            from ....user_input.service import get_user_input_service
            from ....runtime_status.broadcast import clear_runtime_status

            user_input_service = get_user_input_service()
            cancelled_inputs = await (
                user_input_service.cancel_all_pending_by_root_session(
                    target_session_id,
                    agent_id=workspace.agent_id,
                    user_id=context.user_id,
                )
            )
            clear_runtime_status(
                workspace.agent_id, target_session_id, user_id=context.user_id,
            )
        except Exception:
            logger.debug(
                "/stop: failed to clear pending interaction state",
                exc_info=True,
            )
            cancelled_inputs = 0

        if stopped or cleared > 0 or cancelled_inputs > 0:
            logger.info(
                f"/stop: stopped={stopped} cleared={cleared} "
                f"chat_id={chat_id} session={target_session_id[:30]}",
            )
            status_parts = []
            if stopped:
                status_parts.append("running task stopped")
            if cleared > 0:
                status_parts.append(f"{cleared} queued message(s) cleared")
            if cancelled_inputs > 0:
                status_parts.append(
                    f"{cancelled_inputs} pending question(s) cancelled",
                )
            status_text = " and ".join(status_parts)
            return (
                f"**Task Stopped**\n\n"
                f"Session `{target_session_id[:40]}`: {status_text}."
            )
        else:
            logger.warning(
                f"/stop: Nothing to stop: "
                f"chat_id={chat_id} session={target_session_id[:30]}",
            )
            return (
                f"**Task Not Running**\n\n"
                f"No active task or queued messages for session "
                f"`{target_session_id[:40]}`."
            )
