# -*- coding: utf-8 -*-
"""Zhipu service capabilities and request policy."""

from typing import ClassVar

from ..openai_provider import OpenAIProvider


class ZhipuProvider(OpenAIProvider):
    """Keep service-specific policy separate from wire protocol support."""

    cache_modes: ClassVar[frozenset[str]] = frozenset([f"implicit"])
    cache_documentation: ClassVar[
        str | None
    ] = f"https://docs.z.ai/guides/capabilities/cache"
