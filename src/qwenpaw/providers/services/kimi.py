# -*- coding: utf-8 -*-
"""Kimi service capabilities and request policy."""

from typing import ClassVar

from ..openai_provider import OpenAIProvider


class KimiProvider(OpenAIProvider):
    """Keep service-specific policy separate from wire protocol support."""

    cache_modes: ClassVar[frozenset[str]] = frozenset()
    cache_documentation: ClassVar[
        str | None
    ] = f"https://platform.moonshot.ai/docs/guide/automatic-context-caching"
