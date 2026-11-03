# -*- coding: utf-8 -*-
"""AliyunPlan service capabilities and request policy."""

from typing import ClassVar

from ..openai_provider import OpenAIProvider


class AliyunPlanProvider(OpenAIProvider):
    """Keep service-specific policy separate from wire protocol support."""

    cache_modes: ClassVar[frozenset[str]] = frozenset([f"implicit"])
    cache_documentation: ClassVar[str | None] = (
        f"https://docs.modelstudio.console.alibabacloud.com"
        f"/en/model-studio/context-cache"
    )
