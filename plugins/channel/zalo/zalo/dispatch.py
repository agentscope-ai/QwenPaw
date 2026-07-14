# -*- coding: utf-8 -*-
"""Outbound dispatch helpers for :class:`ZaloChannel`.

This module knows how to take a string of text + the channel instance,
extract any rich-content :class:`~custom_channels.zalo.routing.Action`
objects, and call the right Zalo API method on the channel's client.

Public helpers:

- :func:`_dispatch_local_file` — handles ``[FILE: ...]`` markers. The
  Zalo Bot API does not support raw file upload (it needs a public URL),
  so for now we send a small text report with the file's metadata.
- :func:`_dispatch_text_actions` — main entry point: sends the leftover
  text first, then each extracted action via the matching API method.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from .routing import _extract_actions

if TYPE_CHECKING:
    from .channel import ZaloChannel


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Local file dispatcher
# ---------------------------------------------------------------------------

async def _dispatch_local_file(
    ch: "ZaloChannel",
    real_chat_id: str,
    path_str: str,
) -> None:
    """Send a textual report for a local file referenced in the LLM text.

    Zalo Bot API doesn't support raw file upload without a public URL,
    so for now we report file metadata. A future iteration could tunnel
    files via S3 / object storage and send the resulting URL.
    """
    try:
        path = Path(path_str).expanduser().resolve()
    except Exception:
        await ch._client.send_message(
            chat_id=real_chat_id,
            text=f"❌ Cannot resolve path: {path_str}",
        )
        return

    if not path.exists():
        await ch._client.send_message(
            chat_id=real_chat_id,
            text=f"❌ File not found: {path}",
        )
        return

    size_kb = path.stat().st_size / 1024
    await ch._client.send_message(
        chat_id=real_chat_id,
        text=f"📎 File: {path.name} ({size_kb:.1f} KB)\n📍 {path}",
    )


# ---------------------------------------------------------------------------
# Smart text dispatcher
# ---------------------------------------------------------------------------

async def _dispatch_text_actions(
    ch: "ZaloChannel",
    real_chat_id: str,
    initial_text: str,
    *,
    is_group: bool = False,
) -> None:
    """Send *initial_text* with smart extraction of rich content.

    Order:

    1. Extract :class:`Action` objects (image / sticker / voice / file).
    2. Send the leftover plain text first (``send_message``).
    3. Send each action via its dedicated API method.

    Errors on individual sends are logged and swallowed so a single
    failed image upload doesn't break the rest of the reply stream.
    """
    actions, leftover = _extract_actions(initial_text)
    if not actions and not leftover:
        return

    # 1. Leftover plain text first.
    if leftover:
        try:
            await ch._client.send_message(
                chat_id=real_chat_id,
                text=leftover,
            )
            ch._safe_on_reply(real_chat_id, is_group=is_group)
        except Exception:
            logger.exception(
                "Zalo send_message failed chat_id=%s text=%r",
                real_chat_id, leftover[:80],
            )

    # 2. Each extracted action.
    for action in actions:
        try:
            if action.kind == "photo":
                await ch._client.send_photo(
                    chat_id=real_chat_id,
                    photo=action.payload,
                )
            elif action.kind == "local_file":
                await _dispatch_local_file(ch, real_chat_id, action.payload)
                continue
            elif action.kind == "sticker":
                await ch._client.send_sticker(
                    chat_id=real_chat_id,
                    sticker=action.payload,
                )
            elif action.kind == "voice":
                await ch._client.send_voice(
                    chat_id=real_chat_id,
                    voice_url=action.payload,
                )
            ch._safe_on_reply(real_chat_id, is_group=is_group)
        except Exception:
            logger.exception(
                "Zalo send_%s failed chat_id=%s payload=%s",
                action.kind, real_chat_id, action.payload,
            )
