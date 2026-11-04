# -*- coding: utf-8 -*-
# pylint: disable=missing-function-docstring
"""Write-path validation for per-model provider configuration.

``ModelInfo`` declares ``thinking_budget >= 1`` and
``max_input_length >= 1000``, but ``Provider.update_model_config`` used to
assign ``int(...)`` results directly (Pydantic does not validate plain
attribute assignment), and ``ModelConfigRequest.thinking_budget`` lacked
the ``ge`` bound its sibling fields carry. An out-of-range value was
accepted, persisted, and then failed re-validation on every read path —
after a restart the provider failed to load and silently disappeared.

``thinking_budget_range`` likewise accepted any list, while
``Provider.thinking_control`` unpacks exactly two elements.
"""

import pytest
from pydantic import ValidationError

from qwenpaw.providers.model_info import ModelInfo
from qwenpaw.providers.openai_provider import OpenAIProvider
from qwenpaw.providers.provider_model_state import migrate_provider_snapshot


def make_provider(**model_kwargs) -> OpenAIProvider:
    return OpenAIProvider(
        id="test-provider",
        name="Test provider",
        models=[ModelInfo(id="m1", name="Model 1", **model_kwargs)],
    )


@pytest.mark.parametrize("bad_budget", [-5, 0])
def test_update_model_config_rejects_thinking_budget_below_one(bad_budget):
    provider = make_provider()
    with pytest.raises(ValueError, match="thinking_budget"):
        provider.update_model_config("m1", {"thinking_budget": bad_budget})
    # The rejected value must not be stored.
    assert provider.models[0].thinking_budget is None


def test_update_model_config_rejects_max_input_length_below_minimum():
    provider = make_provider()
    original = provider.models[0].max_input_length
    with pytest.raises(ValueError, match="max_input_length"):
        provider.update_model_config("m1", {"max_input_length": 500})
    assert provider.models[0].max_input_length == original


def test_update_model_config_accepts_valid_values_roundtrip():
    provider = make_provider()
    assert provider.update_model_config("m1", {"thinking_budget": 1024})
    assert provider.resolve_model_info("m1").thinking_budget == 1024
    assert provider.update_model_config("m1", {"max_input_length": 131072})
    card = provider.resolve_model_info("m1")
    assert card.max_input_length == 131072
    # Clearing the budget with None stays allowed.
    assert provider.update_model_config("m1", {"thinking_budget": None})
    assert provider.resolve_model_info("m1").thinking_budget is None


@pytest.mark.parametrize(
    "bad_range",
    [[8000], [100, 200, 300], [9000, 100]],
)
def test_thinking_budget_range_must_be_an_ordered_pair(bad_range):
    with pytest.raises(ValidationError, match="thinking_budget_range"):
        ModelInfo(id="m1", name="Model 1", thinking_budget_range=bad_range)


def test_thinking_budget_range_ordered_pair_still_works():
    provider = make_provider(
        thinking_budget_range=[100, 9000],
        thinking_param_style="budget",
    )
    control = provider.thinking_control("m1")
    assert control.kind == "budget"
    assert control.budget_min == 100
    assert control.budget_max == 9000


@pytest.mark.parametrize("bad_range", [[0, 0], [-5, -1]])
def test_thinking_budget_range_max_must_be_at_least_one(bad_range):
    # Ordered pairs, but the normalized range is empty: thinking_control
    # clamps budget_min to >= 1, so a max below 1 can never construct a
    # valid ThinkingControl and must be rejected on the write path.
    with pytest.raises(ValidationError, match="thinking_budget_range"):
        ModelInfo(id="m1", name="Model 1", thinking_budget_range=bad_range)


def test_thinking_budget_range_zero_min_keeps_supports_off():
    provider = make_provider(
        thinking_budget_range=[0, 9000],
        thinking_param_style="budget",
    )
    control = provider.thinking_control("m1")
    assert control.kind == "budget"
    assert control.budget_min == 1
    assert control.budget_max == 9000
    assert control.supports_off is True


def make_persisted_snapshot(**model_kwargs):
    """A current-version snapshot dict, as load_provider reads from disk."""
    provider = make_provider(**model_kwargs)
    data = provider.model_dump()
    data["snapshot_schema_version"] = 2
    return data


def test_persisted_single_bound_range_is_migrated_on_load():
    # A snapshot persisted before write-path validation could carry a
    # single-bound range. Loading validates every model, so without a
    # load-time migration the provider would disappear after a restart.
    data = make_persisted_snapshot(
        thinking_budget_range=[100, 9000],
        thinking_param_style="budget",
    )
    data["models"][0]["thinking_budget_range"] = [8000]
    with pytest.raises(ValidationError):
        OpenAIProvider.model_validate(data)
    assert migrate_provider_snapshot(data) is True
    loaded = OpenAIProvider.model_validate(data)
    # The single bound is read as the cap: [8000] -> [0, 8000].
    assert loaded.models[0].thinking_budget_range == [0, 8000]
    control = loaded.thinking_control("m1")
    assert control.budget_max == 8000
    assert control.supports_off is True


@pytest.mark.parametrize("bad_range", [[0, 0], [-5, -1], [9000, 100]])
def test_persisted_unusable_range_is_dropped_on_load(bad_range):
    data = make_persisted_snapshot(thinking_budget_range=[100, 9000])
    data["models"][0]["thinking_budget_range"] = bad_range
    assert migrate_provider_snapshot(data) is True
    loaded = OpenAIProvider.model_validate(data)
    assert loaded.models[0].thinking_budget_range is None


def test_persisted_valid_range_is_left_untouched():
    data = make_persisted_snapshot(thinking_budget_range=[100, 9000])
    assert migrate_provider_snapshot(data) is False
    loaded = OpenAIProvider.model_validate(data)
    assert loaded.models[0].thinking_budget_range == [100, 9000]


def test_persisted_provider_level_range_is_migrated_on_load():
    data = make_persisted_snapshot()
    data["thinking_budget_range"] = [8000]
    assert migrate_provider_snapshot(data) is True
    assert data["thinking_budget_range"] == [0, 8000]
