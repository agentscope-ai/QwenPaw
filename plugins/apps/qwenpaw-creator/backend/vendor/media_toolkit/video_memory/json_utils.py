# -*- coding: utf-8 -*-
"""JSON extraction from LLM responses.

Vendored from Qwen-MM-Plugins commit 077aea6
(src/capabilities/video-memory/skill/script/build_memory/llm_client.py,
``extract_json`` only). License: Apache-2.0; see backend/vendor/NOTICE.md.
Modifications: the surrounding HTTP client is not vendored; the parse
failure is logged instead of printed.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger("creator.vendor.video_memory")


def extract_json(text: str) -> Any:
    """Parse JSON from a model response, tolerating ```json fences and
    surrounding prose."""
    text = text.strip()
    think_end = text.find("</think>")
    if think_end != -1:
        text = text[think_end + len("</think>") :].strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        text = m.group(1).strip()
    if not text.startswith(("{", "[")):
        for i, ch in enumerate(text):
            if ch in ("{", "["):
                text = text[i:]
                break
    bracket = "]" if text.startswith("[") else "}"
    idx = text.rfind(bracket)
    if idx != -1:
        text = text[: idx + 1]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning("JSON parse failed: %s", text[:500])
        raise
