# -*- coding: utf-8 -*-
"""Tests for provider-owned agent thinking-level mapping."""

from qwenpaw.providers.provider import agent_thinking_level
from qwenpaw.providers.provider import AGENT_THINKING_BUDGETS
from qwenpaw.providers.provider_catalog import (
    PROVIDER_ANTHROPIC,
    PROVIDER_DASHSCOPE,
    PROVIDER_GEMINI,
    PROVIDER_OPENAI,
    PROVIDER_OPENAI_RESPONSE,
)


def test_openai_maps_high_to_reasoning_effort() -> None:
    provider = PROVIDER_OPENAI.model_copy(deep=True)

    with agent_thinking_level("high"):
        kwargs = provider.get_effective_generate_kwargs(provider.models[0].id)

    assert kwargs["reasoning_effort"] == "high"


def test_dashscope_maps_medium_to_budget() -> None:
    provider = PROVIDER_DASHSCOPE.model_copy(deep=True)

    with agent_thinking_level("medium"):
        kwargs = provider.get_effective_generate_kwargs(provider.models[0].id)

    assert kwargs["thinking_enable"] is True
    assert kwargs["thinking_budget"] == 8_192


def test_dashscope_unknown_model_uses_family_thinking_support() -> None:
    provider = PROVIDER_DASHSCOPE.model_copy(deep=True)
    model_id = "newly-discovered-qwen-model"
    provider.extra_models.append(
        PROVIDER_OPENAI.models[0].model_copy(
            update={
                "id": model_id,
                "thinking_enabled": None,
                "thinking_param_style": None,
            },
        ),
    )

    with agent_thinking_level("high"):
        kwargs = provider.get_effective_generate_kwargs(model_id)

    assert kwargs["thinking_enable"] is True
    assert kwargs["thinking_budget"] == AGENT_THINKING_BUDGETS["high"]


def test_dashscope_effort_model_uses_extra_body_only() -> None:
    provider = PROVIDER_DASHSCOPE.model_copy(deep=True)
    model_id = "deepseek-v4-pro-test"
    provider.extra_models.append(
        PROVIDER_OPENAI.models[0].model_copy(
            update={
                "id": model_id,
                "thinking_enabled": True,
                "thinking_param_style": "effort",
            },
        ),
    )

    with agent_thinking_level("high"):
        kwargs = provider.get_effective_generate_kwargs(model_id)

    assert kwargs["extra_body"] == {
        "thinking": {"type": "enabled"},
        "reasoning_effort": "high",
    }
    assert "thinking_enable" not in kwargs
    assert "thinking_budget" not in kwargs


def test_dashscope_effort_model_off_disables_thinking() -> None:
    provider = PROVIDER_DASHSCOPE.model_copy(deep=True)
    model_id = "glm-5.2-test"
    provider.extra_models.append(
        PROVIDER_OPENAI.models[0].model_copy(
            update={
                "id": model_id,
                "thinking_enabled": True,
                "thinking_param_style": "effort",
            },
        ),
    )

    with agent_thinking_level("off"):
        kwargs = provider.get_effective_generate_kwargs(model_id)

    assert kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "thinking_enable" not in kwargs
    assert "thinking_budget" not in kwargs


def test_thinking_budget_levels_are_stable() -> None:
    assert AGENT_THINKING_BUDGETS == {
        "low": 2_048,
        "medium": 8_192,
        "high": 32_768,
    }


def test_anthropic_maps_low_to_budget() -> None:
    provider = PROVIDER_ANTHROPIC.model_copy(deep=True)
    provider.extra_models = []
    model_id = "claude-test"
    provider.extra_models.append(
        PROVIDER_OPENAI.models[0].model_copy(update={"id": model_id}),
    )

    with agent_thinking_level("low"):
        kwargs = provider.get_effective_generate_kwargs(model_id)

    assert kwargs["thinking_enable"] is True
    assert kwargs["thinking_budget"] == 2_048


def test_gemini_maps_off_to_zero_budget() -> None:
    provider = PROVIDER_GEMINI.model_copy(deep=True)

    with agent_thinking_level("off"):
        kwargs = provider.get_effective_generate_kwargs(provider.models[0].id)

    assert kwargs["thinking_config"] == {"thinking_budget": 0}


def test_unknown_openai_model_does_not_receive_reasoning_effort() -> None:
    provider = PROVIDER_OPENAI.model_copy(deep=True)
    model_id = "plain-chat-model"
    provider.extra_models.append(
        PROVIDER_OPENAI.models[0].model_copy(
            update={
                "id": model_id,
                "thinking_enabled": None,
                "thinking_param_style": None,
            },
        ),
    )

    with agent_thinking_level("high"):
        kwargs = provider.get_effective_generate_kwargs(model_id)

    assert "reasoning_effort" not in kwargs


def test_openai_chat_off_degrades_gpt5_to_minimal() -> None:
    """gpt-5 families without documented ``none`` must not 400 on Off."""
    provider = PROVIDER_OPENAI.model_copy(deep=True)

    with agent_thinking_level("off"):
        kwargs = provider.get_effective_generate_kwargs("gpt-5.2")

    assert kwargs["reasoning_effort"] == "minimal"
    assert "disable_thinking" not in kwargs


def test_openai_chat_off_uses_none_where_documented() -> None:
    provider = PROVIDER_OPENAI.model_copy(deep=True)
    provider.extra_models.append(
        PROVIDER_OPENAI.models[0].model_copy(update={"id": "gpt-5.5"}),
    )

    with agent_thinking_level("off"):
        kwargs = provider.get_effective_generate_kwargs("gpt-5.5")

    assert kwargs["reasoning_effort"] == "none"


def test_openai_chat_off_degrades_o_series_to_low() -> None:
    provider = PROVIDER_OPENAI.model_copy(deep=True)
    provider.extra_models.append(
        PROVIDER_OPENAI.models[0].model_copy(update={"id": "o3"}),
    )

    with agent_thinking_level("off"):
        kwargs = provider.get_effective_generate_kwargs("o3")

    assert kwargs["reasoning_effort"] == "low"


def test_openai_compat_off_uses_neutral_disable_flag() -> None:
    """Compatibility endpoints get extra_body flags, not official none."""
    provider = PROVIDER_OPENAI.model_copy(deep=True)
    provider.extra_models.append(
        PROVIDER_OPENAI.models[0].model_copy(
            update={"id": "qwen-compat", "thinking_enabled": True},
        ),
    )

    with agent_thinking_level("off"):
        kwargs = provider.get_effective_generate_kwargs("qwen-compat")

    assert kwargs["disable_thinking"] is True
    assert "reasoning_effort" not in kwargs


def test_openai_responses_off_uses_neutral_disable_flag() -> None:
    """The Responses call layer owns none-vs-strip; the mapping only
    raises the neutral flag."""
    provider = PROVIDER_OPENAI_RESPONSE.model_copy(deep=True)

    with agent_thinking_level("off"):
        kwargs = provider.get_effective_generate_kwargs(
            provider.models[0].id,
        )

    assert kwargs["disable_thinking"] is True
    assert "reasoning_effort" not in kwargs
    assert "reasoning" not in kwargs


def test_openai_responses_level_uses_reasoning_dict() -> None:
    provider = PROVIDER_OPENAI_RESPONSE.model_copy(deep=True)

    with agent_thinking_level("high"):
        kwargs = provider.get_effective_generate_kwargs(
            provider.models[0].id,
        )

    assert kwargs["reasoning"] == {"effort": "high"}
    assert "reasoning_effort" not in kwargs
