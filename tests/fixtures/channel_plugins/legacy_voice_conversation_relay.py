# -*- coding: utf-8 -*-
"""Exact historical Voice method excerpts for AST-only compatibility oracles.

Never import this fixture as a runtime implementation.
"""

from typing import Any

from qwenpaw.schemas import ContentType


class ConversationRelayBaseline:
    @staticmethod
    def _extract_text_from_event(event: Any) -> str:
        """Extract plain text from a completed message event."""
        content = getattr(event, "content", None)
        if not content:
            return ""

        parts: list[str] = []
        for c in content:
            ct = getattr(c, "type", None)
            if ct == ContentType.TEXT:
                text = getattr(c, "text", None)
                if text:
                    parts.append(text.strip())
            elif ct == ContentType.REFUSAL:
                refusal = getattr(c, "refusal", None)
                if refusal:
                    parts.append(refusal.strip())
        return " ".join(parts)
