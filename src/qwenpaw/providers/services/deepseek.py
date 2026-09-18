# -*- coding: utf-8 -*-
"""DeepSeek service capabilities and request policy."""

from typing import ClassVar

from ..openai_provider import OpenAIProvider


class DeepSeekProvider(OpenAIProvider):
    """Keep service-specific policy separate from wire protocol support."""

    capture_cache_headers: ClassVar[bool] = True
    cache_modes: ClassVar[frozenset[str]] = frozenset([f"implicit"])
    cache_documentation: ClassVar[str | None] = (
        f"https://api-docs.deepseek.com/guides/kv_cache/"
    )
