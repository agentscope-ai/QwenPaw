# -*- coding: utf-8 -*-
"""AgentScope Platform's OpenAI-compatible model service."""

from ..openai_provider import OpenAIProvider


class AgentScopePlatformProvider(OpenAIProvider):
    """Discover account models without depending on a bundled model card."""
