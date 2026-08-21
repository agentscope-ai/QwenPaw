# -*- coding: utf-8 -*-
"""Pluggable web search providers for the ``web_search`` tool.

The active provider and any provider API key are selected per-agent via
Console tool configuration (``BuiltinToolConfig.config`` for
``web_search``), not environment variables.
"""

from .anysearch import (
    AnySearchProvider,
    _current_agent_anysearch_key,
    _parse_auto_registered_credentials,
)
from .base import SearchProvider, format_search_results
from .factory import get_search_provider
from .tavily import TavilyProvider

__all__ = [
    "SearchProvider",
    "TavilyProvider",
    "AnySearchProvider",
    "get_search_provider",
    "format_search_results",
    "_current_agent_anysearch_key",
    "_parse_auto_registered_credentials",
]
