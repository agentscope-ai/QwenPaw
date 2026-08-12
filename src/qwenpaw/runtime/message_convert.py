# -*- coding: utf-8 -*-
"""Message conversion between AgentRequest and agentscope Msg."""
from __future__ import annotations

import logging
import mimetypes
from typing import Any, List
from urllib.parse import urlparse

from ..constant import (
    EXTERNAL_USER_QUERY_MESSAGE_TAG,
    QWENPAW_MESSAGE_TAG_KEY,
)
from .._compat.message import _ensure_url_scheme

logger = logging.getLogger(__name__)


def _request_message_metadata(
    role: str,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    if role != "user":
        return {}
    result = dict(metadata or {})
    result[QWENPAW_MESSAGE_TAG_KEY] = EXTERNAL_USER_QUERY_MESSAGE_TAG
    return result


def _media_type_to_block_type(media_type: str | None) -> str:
    """Map a MIME media_type to the 1.x block type the frontend expects.

    AS 2.0 uses ``"data"`` for all media; the frontend renderer still
    expects ``"image"``/``"video"``/``"audio"``.
    """
    if not media_type:
        return "data"
    major = media_type.split("/", 1)[0]
    if major in ("image", "video", "audio"):
        return major
    return "data"


def _get_last_user_text(msgs: List[Any]) -> str | None:
    """Extract the text of the last user message from a list of ``Msg``."""
    if not msgs:
        return None
    last = msgs[-1]
    if hasattr(last, "get_text_content"):
        return last.get_text_content()
    return None


# pylint: disable=too-many-branches
def _request_input_to_msgs(
    input_list: List[Any],
) -> List[Any]:
    """Convert ``AgentRequest.input`` (list of 1.x Message) to a list of
    agentscope 2.0 ``Msg`` objects.

    Handles text, image, audio, video, and file content blocks.
    """
    try:
        from agentscope.message import Msg, TextBlock, DataBlock
        from agentscope.message._block import URLSource
    except Exception:
        logger.error(
            "Failed to import agentscope.message; user input will be dropped",
            exc_info=True,
        )
        return []

    _MEDIA_TYPES = {
        "image": "image",
        "audio": "audio",
        "video": "video",
    }

    out: List[Any] = []
    for m in input_list:
        role = getattr(m, "role", None)
        if hasattr(role, "value"):
            role = role.value
        role = role or "user"
        if role == "tool":
            role = "assistant"

        blocks: list = []
        for c in getattr(m, "content", None) or []:
            ctype = getattr(c, "type", None)
            if hasattr(ctype, "value"):
                ctype = ctype.value

            if ctype == "text":
                text = getattr(c, "text", None) or ""
                if text:
                    blocks.append(TextBlock(type="text", text=text))

            elif ctype in _MEDIA_TYPES:
                url = (
                    getattr(c, "image_url", None)
                    or getattr(c, "audio_url", None)
                    or getattr(c, "video_url", None)
                    or (getattr(c, "data", None) if ctype == "audio" else None)
                    or getattr(c, "url", None)
                )
                if url:
                    url = _ensure_url_scheme(str(url))
                    url_path = urlparse(url).path
                    guessed, _ = mimetypes.guess_type(url_path)
                    if guessed and guessed.startswith(
                        f"{_MEDIA_TYPES[ctype]}/",
                    ):
                        media_type = guessed
                    else:
                        fallback_ext = "jpeg" if ctype == "image" else "mpeg"
                        media_type = f"{_MEDIA_TYPES[ctype]}/{fallback_ext}"
                    try:
                        blocks.append(
                            DataBlock(
                                source=URLSource(
                                    url=url,
                                    media_type=media_type,
                                ),
                            ),
                        )
                    except Exception:
                        logger.debug(
                            "Failed to create DataBlock for %s url=%s",
                            ctype,
                            url,
                        )

            elif ctype == "file":
                url = getattr(c, "file_url", None) or getattr(c, "url", None)
                if url:
                    url = _ensure_url_scheme(str(url))
                    try:
                        blocks.append(
                            DataBlock(
                                source=URLSource(
                                    url=url,
                                    media_type="application/octet-stream",
                                ),
                                name=getattr(c, "file_name", None),
                            ),
                        )
                    except Exception:
                        logger.debug(
                            "Failed to create DataBlock for file url=%s",
                            url,
                        )

        if not blocks:
            continue

        out.append(
            Msg(
                name=role,
                role=role,
                content=blocks,
                metadata=_request_message_metadata(
                    role,
                    getattr(m, "metadata", None),
                ),
            ),
        )
    return out
