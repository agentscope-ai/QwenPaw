# -*- coding: utf-8 -*-
"""Let users switch to local execution even if the plugin is unavailable."""

from .base import BaseControlCommandHandler, ControlContext


class ShellLocalCommandHandler(BaseControlCommandHandler):
    command_name = "/shell-local"
    description = "Use the local shell for this conversation"

    async def handle(self, context: ControlContext) -> str:
        channel = getattr(context.payload, "channel", "")
        if not (context.session_id and context.user_id and channel):
            return "Local shell selection requires an identified conversation."
        chats = context.workspace.chat_manager
        cleared = await chats.set_shell_backend(
            context.session_id,
            context.user_id,
            channel,
            None,
        )
        if not cleared:
            return "Conversation not found."
        return "This conversation now uses the local shell."
