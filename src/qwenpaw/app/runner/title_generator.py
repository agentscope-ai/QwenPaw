# -*- coding: utf-8 -*-
"""Async background task that asks the LLM to generate a chat title.

The console handler creates a chat with a placeholder name (truncated first
message) so the UI has something to show immediately. Once the chat exists
we spawn :func:`generate_and_update_title` as an ``asyncio`` task that asks
the active chat model for a concise title and persists it via
``ChatManager.patch_chat``. Failures are logged and swallowed so title
generation never affects the user-facing request.
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from .models import ChatUpdate

if TYPE_CHECKING:
    from ..workspace import Workspace

logger = logging.getLogger(__name__)


TITLE_PROMPT = (
    "You generate short titles for chat sessions. Given the first user "
    "message, reply with a concise title (at most 6 words, no quotes, no "
    "trailing punctuation, same language as the message) that captures the "
    "topic. Reply with the title only."
)

MAX_INPUT_CHARS = 500
MAX_TITLE_CHARS = 60
TITLE_TIMEOUT_SECONDS = 30.0


def _extract_text(response: Any) -> str:
    """Best-effort extraction of plain text from a ChatResponse-like object."""
    if response is None:
        return ""
    if isinstance(response, str):
        return response
    text = getattr(response, "text", None)
    if isinstance(text, str) and text:
        return text
    content = getattr(response, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                value = item.get("text")
                if isinstance(value, str):
                    parts.append(value)
            else:
                value = getattr(item, "text", None)
                if isinstance(value, str):
                    parts.append(value)
        if parts:
            return "".join(parts)
    return ""


def _clean_title(raw: str) -> str:
    """Normalize model output into a single-line title."""
    title = raw.strip().splitlines()[0] if raw.strip() else ""
    title = title.strip().strip("\"'`“”‘’")
    while title and title[-1] in ".,;:!?":
        title = title[:-1].rstrip()
    if len(title) > MAX_TITLE_CHARS:
        title = title[:MAX_TITLE_CHARS].rstrip()
    return title


async def generate_and_update_title(
    workspace: "Workspace",
    chat_id: str,
    user_message: str,
    placeholder_name: str,
) -> None:
    """Generate a chat title via the active LLM and persist it.

    Skips the update if the chat has already been renamed (either by the
    user or a previous task) so concurrent message submissions cannot clobber
    a user-chosen name.
    """
    message = (user_message or "").strip()
    if not message:
        return
    if len(message) > MAX_INPUT_CHARS:
        message = message[:MAX_INPUT_CHARS]

    try:
        from ...agents.model_factory import create_model_and_formatter

        try:
            model, _ = create_model_and_formatter(agent_id=workspace.agent_id)
        except Exception as exc:
            logger.debug("Title generation skipped: no model available (%s)", exc)
            return

        messages = [
            {"role": "system", "content": TITLE_PROMPT},
            {"role": "user", "content": message},
        ]

        response = await asyncio.wait_for(
            model(messages),
            timeout=TITLE_TIMEOUT_SECONDS,
        )
        title = _clean_title(_extract_text(response))
        if not title:
            logger.debug("Title generation produced empty output for %s", chat_id)
            return

        current = await workspace.chat_manager.get_chat(chat_id)
        if current is None:
            return
        if current.name != placeholder_name:
            # User or another task already renamed it; leave it alone.
            return

        await workspace.chat_manager.patch_chat(
            chat_id,
            ChatUpdate(name=title),
        )
        logger.debug("Updated chat %s title to %r", chat_id, title)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Title generation failed for chat %s", chat_id)
