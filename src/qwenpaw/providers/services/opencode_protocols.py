# -*- coding: utf-8 -*-
"""OpenCode service policies composed with native protocol implementations."""

from ..anthropic_provider import AnthropicProvider
from ..openai_provider import OpenCodeProvider
from ..openai_response_provider import OpenAIResponseProvider


class OpenCodeResponsesProvider(OpenAIResponseProvider, OpenCodeProvider):
    """Reuse Responses requests and OpenCode session affinity."""


class OpenCodeAnthropicProvider(AnthropicProvider, OpenCodeProvider):
    """Reuse Messages requests and OpenCode session affinity."""

    def cache_capabilities(self, model_id: str) -> frozenset[str]:
        """OpenCode's Messages route accepts Anthropic cache controls."""
        return frozenset({f"anthropic"})


def protocol_provider(provider, protocol: str):
    """Keep API credentials, model overrides and session affinity intact."""
    if protocol == f"chat":
        return provider
    classes = {
        f"responses": OpenCodeResponsesProvider,
        f"anthropic": OpenCodeAnthropicProvider,
    }
    if protocol not in classes:
        raise ValueError(f"Unsupported OpenCode model protocol: {protocol}")
    result = classes[protocol].model_validate(provider.model_dump())
    result._request_session = provider._request_session
    return result
