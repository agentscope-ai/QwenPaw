# -*- coding: utf-8 -*-
"""Async background task that asks the LLM to generate a chat title.

The console handler creates a chat with a placeholder name (truncated first
message) so the UI has something to show immediately. Once the chat exists
we spawn :func:`generate_and_update_title` as an ``asyncio`` task that asks
the active chat model for a concise title and persists it via
``ChatManager.patch_chat``. Failures are logged and swallowed so title
generation never affects the user-facing request.

The LLM call mirrors ``app/routers/skills_stream.py``: build a list of
``agentscope.message.Msg`` (2.0's ``ChatModelBase.__call__`` no longer
accepts plain dicts — the formatter is now built-in and asserts on
``Msg`` instances), await ``model(messages)`` directly, and tolerate the
same ``(ValueError, AppBaseException)`` factory failures.
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from qwenpaw.exceptions import AppBaseException
from qwenpaw.utils.model_response import consume_model_response

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
    user or a previous task) so concurrent message submissions cannot
    clobber a user-chosen name.
    """
    message = (user_message or "").strip()
    if not message:
        return

    # Check if this is a proactive session message
    is_proactive = message.startswith("[Agent proactive_helper requesting]")
    if is_proactive:
        title = "[Proactive信息]"
    else:
        if len(message) > MAX_INPUT_CHARS:
            message = message[:MAX_INPUT_CHARS]

    try:
        # Local imports keep this module's import cost low and avoid a
        # circular dependency between routers and the agents package.
        from ...agents.model_factory import create_model_and_formatter
        from ...config.config import load_agent_config

        try:
            cfg = load_agent_config(workspace.agent_id).running
        except (ValueError, AppBaseException) as exc:
            logger.debug(
                "Title generation skipped: agent config unavailable (%s)",
                exc,
            )
            return

        if not is_proactive:
            title_cfg = cfg.auto_title_config
            if not title_cfg.enabled:
                logger.debug(
                    "Title generation disabled by config for chat %s",
                    chat_id,
                )
                return
            timeout = title_cfg.timeout_seconds

            try:
                model, _ = create_model_and_formatter(
                    agent_id=workspace.agent_id,
                )
            except (ValueError, AppBaseException) as exc:
                # Same exception shape as ``skills_stream.get_model``: missing
                # or misconfigured providers raise these and are non-fatal.
                logger.debug(
                    "Title generation skipped: no model available (%s)",
                    exc,
                )
                return

            from agentscope.message import Msg, TextBlock

            messages = [
                Msg(
                    name="system",
                    role="system",
                    content=[TextBlock(type="text", text=TITLE_PROMPT)],
                ),
                Msg(
                    name="user",
                    role="user",
                    content=[TextBlock(type="text", text=message)],
                ),
            ]

            raw_title = await asyncio.wait_for(
                consume_model_response(model, messages),
                timeout=timeout,
            )
            title = _clean_title(raw_title)
            if not title:
                # Empty model output: fall back to the cleaned user message
                # (or the placeholder name) so the chat still gets a readable
                # title instead of staying on the truncated placeholder.
                title = _clean_title(message) or _clean_title(placeholder_name)
            if not title:
                logger.debug(
                    "Title generation produced empty output for %s",
                    chat_id,
                )
                return
        else:
            logger.debug("Using fixed title for proactive chat %s", chat_id)

        # Compare-and-set on the chat name in a single locked critical
        # section so a concurrent user rename cannot slip in between a
        # name check and our write. The auto-title source is recorded in
        # meta so later auto refreshes can detect a manual rename.
        updated = await workspace.chat_manager.set_auto_title(
            chat_id,
            title,
            expected_name=placeholder_name,
        )
        if updated is None:
            logger.debug(
                "Chat %s no longer has placeholder name; "
                "title update skipped",
                chat_id,
            )
            return
        logger.debug("Updated chat %s title to %r", chat_id, title)
    except Exception:
        # asyncio.CancelledError has inherited from BaseException since
        # Python 3.8 (https://docs.python.org/3/library/asyncio-exceptions
        # .html#asyncio.CancelledError) and the project requires
        # Python >= 3.10, so this ``except Exception`` deliberately does
        # not catch task cancellation. There is a regression test in
        # ``tests/unit/app/test_title_generator.py`` that asserts this
        # invariant directly.
        logger.exception("Title generation failed for chat %s", chat_id)


REFRESH_TITLE_PROMPT = (
    "You generate short titles for chat sessions. Given the recent "
    "conversation, reply with a concise title (at most 6 words, no quotes, "
    "no trailing punctuation, same language as the conversation) that "
    "captures the CURRENT topic. Reply with the title only."
)


def _messages_to_text(messages: list) -> str:
    """Serialize AgentScope messages into a compact transcript."""
    parts: list[str] = []
    for msg in messages:
        role = getattr(msg, "role", "user") or "user"
        content = getattr(msg, "content", None)
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            texts = []
            for block in content:
                block_text = getattr(block, "text", None)
                if block_text:
                    texts.append(str(block_text))
            text = "\n".join(texts)
        else:
            text = str(content) if content else ""
        text = (text or "").strip()
        if text and not text.startswith("```"):
            parts.append(f"{role}: {text}")
    joined = "\n".join(parts)
    if len(joined) > MAX_INPUT_CHARS:
        joined = joined[-MAX_INPUT_CHARS:]
    return joined


async def refresh_title_after_auto_memory(
    workspace: "Workspace",
    *,
    session_id: str,
    recent_messages: list,
) -> None:
    """Re-generate a chat title from the recent conversation slice.

    Called after each auto-memory flush (see ``MemoryMiddleware``). The
    chat is located by runtime session id, the recent messages are fed to
    the LLM for a fresh title, and the name is updated compare-and-set so
    a user-chosen name (or a title set since our last write) is never
    clobbered.

    Failures are logged and swallowed; this is a best-effort background
    nicety and must never affect the request path.

    Every exit path records its outcome into ``chat.meta["auto_title_refresh"]``
    via :meth:`ChatManager.record_auto_title_refresh` (plus an INFO log), so
    audits can verify whether the refresh succeeded without parsing debug logs.
    """
    async def _record(chat_id: str, *, ok: bool, reason: str = "", title: str = "") -> None:
        try:
            await workspace.chat_manager.record_auto_title_refresh(
                chat_id,
                ok=ok,
                reason=reason,
                title=title,
            )
        except Exception:
            # Never let bookkeeping break the request path.
            logger.exception(
                "Auto title refresh state record failed for chat %s",
                chat_id,
            )

    if not recent_messages:
        return

    from ...config.config import load_agent_config

    try:
        cfg = load_agent_config(workspace.agent_id).running
    except (ValueError, AppBaseException) as exc:
        logger.info("Auto title refresh skipped: config unavailable (%s)", exc)
        return

    title_cfg = cfg.auto_title_config
    if not title_cfg.enabled or not title_cfg.refresh_on_auto_memory:
        logger.info(
            "Auto title refresh skipped: refresh_on_auto_memory disabled "
            "(enabled=%s refresh=%s)",
            title_cfg.enabled,
            title_cfg.refresh_on_auto_memory,
        )
        return

    chat = await workspace.chat_manager.find_chat_by_session_id(session_id)
    if chat is None:
        logger.info(
            "Auto title refresh skipped: no chat for session %s",
            session_id,
        )
        return

    chat_id = chat.id

    transcript = _messages_to_text(recent_messages)
    if not transcript:
        await _record(chat_id, ok=False, reason="empty transcript")
        return

    try:
        from ...agents.model_factory import create_model_and_formatter

        try:
            model, _ = create_model_and_formatter(
                agent_id=workspace.agent_id,
            )
        except (ValueError, AppBaseException) as exc:
            logger.info(
                "Auto title refresh skipped: no model available for chat %s (%s)",
                chat_id,
                exc,
            )
            await _record(chat_id, ok=False, reason=f"no model: {exc}")
            return

        from agentscope.message import Msg, TextBlock

        messages = [
            Msg(
                name="system",
                role="system",
                content=[TextBlock(type="text", text=REFRESH_TITLE_PROMPT)],
            ),
            Msg(
                name="user",
                role="user",
                content=[TextBlock(type="text", text=transcript)],
            ),
        ]

        raw_title = await asyncio.wait_for(
            consume_model_response(model, messages),
            timeout=title_cfg.timeout_seconds,
        )
        title = _clean_title(raw_title)
        if not title:
            logger.info(
                "Auto title refresh produced empty output for chat %s",
                chat_id,
            )
            await _record(chat_id, ok=False, reason="empty LLM output")
            return
    except Exception:
        logger.exception(
            "Auto title refresh LLM failed for chat %s",
            chat_id,
        )
        await _record(chat_id, ok=False, reason="LLM failed")
        return

    # Compare-and-set: expected name is the last title we set (or the
    # current name for chats created before this feature shipped). If the
    # user renamed the chat manually, the name no longer matches and the
    # update is skipped.
    expected_name = chat.meta.get("auto_title_last") or chat.name
    updated = await workspace.chat_manager.set_auto_title(
        chat.id,
        title,
        expected_name=expected_name,
    )
    if updated is None:
        logger.info(
            "Auto title refresh skipped: chat %s renamed manually",
            chat.id,
        )
        await _record(chat_id, ok=False, reason="renamed manually")
        return
    logger.info(
        "Auto-refreshed chat %s title to %r (session %s)",
        chat.id,
        title,
        session_id,
    )
    await _record(chat_id, ok=True, reason="ok", title=title)
