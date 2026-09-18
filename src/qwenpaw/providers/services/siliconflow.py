# -*- coding: utf-8 -*-
"""SiliconFlow service capabilities and request policy."""

from typing import ClassVar

from ..openai_provider import OpenAIProvider


class SiliconFlowProvider(OpenAIProvider):
    """Keep service-specific policy separate from wire protocol support."""

    cache_modes: ClassVar[frozenset[str]] = frozenset([f"implicit"])
    cache_documentation: ClassVar[str | None] = (
        f"https://docs.siliconflow.cn/docs/api/chat-completions-post"
    )
