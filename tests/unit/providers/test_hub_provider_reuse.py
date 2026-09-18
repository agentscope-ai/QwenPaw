# -*- coding: utf-8 -*-
"""Hub connections reuse provider implementations and protocol defaults."""

import pytest

from qwenpaw.hub.model_service.api_models import ConnectionBody
from qwenpaw.hub.model_service.provider_setup import (
    connection_provider,
    provider_presets,
    supported_presets,
)
from qwenpaw.providers.anthropic_provider import AnthropicProvider
from qwenpaw.providers.openai_provider import OpenAIProvider
from qwenpaw.providers.openai_response_provider import OpenAIResponseProvider


@pytest.mark.parametrize(f"provider_id", list(supported_presets()))
def test_builtin_connection_preserves_provider_class_and_isolation(
    provider_id,
):
    preset = supported_presets()[provider_id]
    connection = {
        f"id": f"hub-connection",
        f"name": f"Organization connection",
        f"provider_id": provider_id,
        f"base_url": f"https://organization.example/v1",
        f"protocol": (
            f"anthropic" if preset.wire_protocol == f"chat" else f"chat"
        ),
    }
    provider = connection_provider(connection)
    assert type(provider) is type(preset)
    assert provider.wire_protocol == preset.wire_protocol
    assert provider.base_url == connection[f"base_url"]
    assert preset.base_url != provider.base_url
    provider.models.clear()
    assert provider.models is not preset.models
    validated = ConnectionBody(
        **{key: value for key, value in connection.items() if key != f"id"},
        quota_scope=f"organization",
    )
    assert validated.protocol == preset.wire_protocol


@pytest.mark.parametrize(
    (f"protocol", f"provider_class"),
    [
        (f"chat", OpenAIProvider),
        (f"responses", OpenAIResponseProvider),
        (f"anthropic", AnthropicProvider),
    ],
)
def test_custom_connection_selects_protocol(protocol, provider_class):
    provider = connection_provider(
        {
            f"id": f"custom",
            f"name": f"Custom",
            f"base_url": f"https://custom.example/v1",
            f"protocol": protocol,
        }
    )
    assert type(provider) is provider_class
    assert provider.wire_protocol == protocol


def test_presets_publish_their_implementation_protocol():
    presets = {row[f"id"]: row for row in provider_presets()}
    assert presets[f"anthropic"][f"protocol"] == f"anthropic"
    assert presets[f"minimax"][f"protocol"] == f"anthropic"
    assert presets[f"openai-response"][f"protocol"] == f"responses"
    assert presets[f"deepseek"][f"protocol"] == f"chat"


def test_unknown_builtin_does_not_fall_back_to_custom_provider():
    with pytest.raises(KeyError):
        connection_provider(
            {
                f"provider_id": f"missing-preset",
                f"protocol": f"chat",
            }
        )


def test_hub_publishes_only_modalities_supported_by_its_wire_bridge():
    from qwenpaw.hub.model_service.provider_setup import published_capabilities

    result = published_capabilities(
        {
            f"upstream_model": f"custom",
            f"supports_image": True,
            f"supports_audio": True,
            f"supports_video": True,
            f"input_token_limit": 4000,
            f"output_token_limit": 128,
        },
        {
            f"id": f"c",
            f"name": f"Custom",
            f"protocol": f"anthropic",
            f"base_url": f"https://custom.example/v1",
        },
    )
    assert result[f"supports_image"] is True
    assert result[f"supports_audio"] is False
    assert result[f"supports_video"] is False
