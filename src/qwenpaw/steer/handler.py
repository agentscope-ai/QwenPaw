# -*- coding: utf-8 -*-
"""Steer command handler.

``/steer`` lets the user inject guidance that the agent picks up on its
next turn. Real mid-execution steering would need invasive changes to the
reply loop; instead the guidance is handed off through a per-session
buffer that :class:`~qwenpaw.steer.hook.SteerInjectionHook` drains once.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .store import put_guidance

if TYPE_CHECKING:
    from agentscope.message import Msg

logger = logging.getLogger(__name__)

_USAGE = (
    "**Steer Mode**\n\n"
    "- Usage: `/steer <guidance>`\n"
    "- Example: `/steer Focus on the error handling first`\n"
    "- The agent picks the guidance up on its next turn, then forgets it"
)


def make_steer_command_spec() -> Any:
    """Create a CommandSpec for the /steer command."""
    from ..runtime.slash_command_registry import CommandSpec

    async def _handler(ctx: Any, args: str) -> "Msg | None":
        from agentscope.message import Msg, TextBlock

        guidance = args.strip()
        if not guidance:
            return Msg(
                name="assistant",
                role="assistant",
                content=[TextBlock(type="text", text=_USAGE)],
            )

        session_id = str(getattr(ctx, "session_id", "") or "")
        if not session_id:
            return Msg(
                name="assistant",
                role="assistant",
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            "**Steer Mode unavailable**\n\n"
                            "This session has no id, so the guidance cannot "
                            "be handed to the next turn."
                        ),
                    ),
                ],
            )

        put_guidance(session_id, guidance)
        logger.info("[STEER] Recorded guidance (session=%s)", session_id)

        return Msg(
            name="assistant",
            role="assistant",
            content=[
                TextBlock(
                    type="text",
                    text=(
                        "**Steer Mode Activated**\n\n"
                        f"> {guidance}\n\n"
                        "- Noted; it will be applied on the next turn "
                        "and then cleared."
                    ),
                ),
            ],
        )

    return CommandSpec(
        name="steer",
        handler=_handler,
        category="conversation",
        help_text=(
            "Steer the agent's behaviour on the next turn "
            "(`/steer <guidance>`)"
        ),
    )
