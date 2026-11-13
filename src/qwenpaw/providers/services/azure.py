# -*- coding: utf-8 -*-
"""AzureOpenAI service capabilities and request policy."""

from typing import ClassVar

from ..openai_provider import OpenAIProvider


class AzureOpenAIProvider(OpenAIProvider):
    """Keep service-specific policy separate from wire protocol support."""

    cache_modes: ClassVar[frozenset[str]] = frozenset([f"implicit"])
    cache_documentation: ClassVar[str | None] = (
        f"https://learn.microsoft.com/en-us/azure/ai-foundry/openai"
        f"/how-to/prompt-caching"
    )
