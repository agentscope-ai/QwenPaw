# -*- coding: utf-8 -*-
"""MiniMax service capabilities and request policy."""

from typing import ClassVar

from ..anthropic_provider import AnthropicProvider


class MiniMaxProvider(AnthropicProvider):
    """Keep service-specific policy separate from wire protocol support."""

    cache_modes: ClassVar[frozenset[str]] = frozenset(
        [f"implicit", f"anthropic"]
    )
    cache_documentation: ClassVar[str | None] = (
        f"https://platform.minimax.io/docs/api-reference/text-prompt-caching"
    )

    def cache_capabilities(self, model_id: str) -> frozenset[str]:
        """Limit explicit cache markers to documented M2 offerings."""
        supported = {
            f"MiniMax-M2",
            f"MiniMax-M2-Stable",
            f"MiniMax-M2.1",
            f"MiniMax-M2.1-highspeed",
            f"MiniMax-M2.5",
            f"MiniMax-M2.5-highspeed",
            f"MiniMax-M2.7",
            f"MiniMax-M2.7-highspeed",
        }
        return self.cache_modes if model_id in supported else frozenset()
