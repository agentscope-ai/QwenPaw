# -*- coding: utf-8 -*-
"""Command dispatch utilities.

The main dispatch logic (``run_command_path``, ``_is_command``,
``_is_conversation_command``) has been replaced by
:class:`~copaw.app.runner.command_router.CommandRouter` and the
``CommandClassifier`` inside
:class:`~copaw.app.channels.manager.ChannelManager`.

Only ``_get_last_user_text`` is retained — it is still used by
:mod:`copaw.app.runner.runner`.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _get_last_user_text(msgs) -> str | None:
    """Extract last user message text from msgs (runtime message list)."""
    if not msgs or len(msgs) == 0:
        return None
    last = msgs[-1]
    if hasattr(last, "get_text_content"):
        return last.get_text_content()
    if isinstance(last, dict):
        content = last.get("content") or last.get("text")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    return block.get("text")
    return None
