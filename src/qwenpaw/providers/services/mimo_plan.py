# -*- coding: utf-8 -*-
"""MiMoPlan service capabilities and request policy."""

from typing import ClassVar

from ..openai_provider import OpenAIProvider


class MiMoPlanProvider(OpenAIProvider):
    """Keep service-specific policy separate from wire protocol support."""

    cache_modes: ClassVar[frozenset[str]] = frozenset([])
    cache_documentation: ClassVar[
        str | None
    ] = f"https://platform.xiaomimimo.com/"
