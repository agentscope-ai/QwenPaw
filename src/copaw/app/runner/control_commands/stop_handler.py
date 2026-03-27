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
    - Stops task via /console/stop HTTP endpoint
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
        # Get target session ID (default: current session)
        target_session_id = context.args.get(
            "session",
            context.session_id,
        )

        # Get target user_id (default: current user)
        target_user_id = context.args.get(
            "user",
            context.user_id,
        )

        logger.info(
            f"/stop command: current_session={context.session_id[:30]} "
            f"target_session={target_session_id[:30]} "
            f"target_user={target_user_id[:30]}",
        )

        # Call /api/agents/{agentId}/agent/stop HTTP endpoint
        # This goes through workspace middleware and agent_app's InterruptMixin
        import aiohttp
        from ....config.utils import read_last_api

        workspace = context.workspace
        agent_id = workspace.agent_id

        # Get service host/port
        api_info = read_last_api()
        if api_info:
            host, port = api_info
        else:
            host, port = "127.0.0.1", 8088

        # Construct request payload (AgentRequest format)
        payload = {
            "input": [],
            "user_id": target_user_id,
            "session_id": target_session_id,
        }

        url = f"http://{host}:{port}/api/agents/{agent_id}/agent/stop"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if resp.status == 200:
                        logger.info(
                            f"/stop: Interrupt signal sent for "
                            f"session={target_session_id[:30]}",
                        )
                        return (
                            f"**Task Stop Requested**\n\n"
                            f"Interrupt signal sent to session "
                            f"`{target_session_id[:40]}`.\n"
                            f"The task should stop shortly."
                        )
                    else:
                        error_text = await resp.text()
                        logger.error(
                            f"/stop: HTTP {resp.status}: {error_text}",
                        )
                        return (
                            f"**Stop Failed**\n\n"
                            f"HTTP {resp.status}: {error_text}"
                        )
        except Exception as e:
            logger.exception(
                f"/stop: Failed to send interrupt signal: {e}",
            )
            return (
                f"**Stop Failed**\n\n"
                f"Failed to send interrupt signal: {str(e)}"
            )
