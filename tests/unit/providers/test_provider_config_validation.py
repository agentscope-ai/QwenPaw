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

import json

import pytest
from pydantic import ValidationError

from qwenpaw.providers.context_windows import DEFAULT_CONTEXT_WINDOW
from qwenpaw.providers.model_info import ModelInfo
from qwenpaw.providers.openai_provider import OpenAIProvider
from qwenpaw.providers.provider_manager import ProviderManager
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


def test_persisted_provider_level_unusable_range_is_removed():
    # ProviderInfo.thinking_budget_range is a non-optional List[int], so
    # an unusable provider-level value cannot fall back to None; the key
    # is removed so the field default applies instead.
    data = make_persisted_snapshot()
    data["thinking_budget_range"] = [9000, 100]
    assert migrate_provider_snapshot(data) is True
    assert "thinking_budget_range" not in data


def load_snapshot_with_provider_range(range_value):
    """Write a snapshot carrying *range_value* and load it for real."""
    data = make_persisted_snapshot()
    data["is_custom"] = True
    data["thinking_budget_range"] = range_value
    manager = ProviderManager()
    path = manager.custom_path / "test-provider.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return manager.load_provider("test-provider")


@pytest.mark.parametrize(
    "bad_range",
    [[9000, 100], [0, 0], [-5, -1], [1, 2, 3], "garbage"],
)
def test_load_provider_survives_unusable_provider_level_range(bad_range):
    loaded = load_snapshot_with_provider_range(bad_range)
    assert loaded is not None
    # The key was removed during load, so the field default applies.
    assert loaded.thinking_budget_range == [1, 81920]


def test_load_provider_migrates_single_bound_provider_level_range():
    loaded = load_snapshot_with_provider_range([8000])
    assert loaded is not None
    assert loaded.thinking_budget_range == [0, 8000]


def test_persisted_string_range_is_preserved_on_load():
    # Pydantic itself accepts numeric strings for List[int] fields and
    # coerces them; the migration must not mistake a coercible range for
    # an invalid one and discard a perfectly usable persisted override.
    data = make_persisted_snapshot(thinking_budget_range=[100, 9000])
    data["models"][0]["thinking_budget_range"] = ["100", "9000"]
    assert migrate_provider_snapshot(data) is False
    loaded = OpenAIProvider.model_validate(data)
    assert loaded.models[0].thinking_budget_range == [100, 9000]


def test_persisted_provider_level_string_range_is_preserved_on_load():
    data = make_persisted_snapshot()
    data["thinking_budget_range"] = ["100", "9000"]
    assert migrate_provider_snapshot(data) is False
    loaded = OpenAIProvider.model_validate(data)
    assert loaded.thinking_budget_range == [100, 9000]


def test_persisted_single_bound_string_range_is_migrated_on_load():
    data = make_persisted_snapshot(thinking_budget_range=[100, 9000])
    data["models"][0]["thinking_budget_range"] = ["8000"]
    assert migrate_provider_snapshot(data) is True
    loaded = OpenAIProvider.model_validate(data)
    assert loaded.models[0].thinking_budget_range == [0, 8000]


@pytest.mark.parametrize(
    "field,bad_value",
    [
        ("thinking_budget", 0),
        ("thinking_budget", -5),
        ("max_output_length", 0),
        ("max_input_length_auto_detected", 500),
        ("input_token_limit", 0),
    ],
)
def test_persisted_invalid_optional_scalar_is_reset_on_load(
    field,
    bad_value,
):
    # ModelInfo bounds these optional scalars from below (ge=1 or
    # ge=1000). A snapshot persisted before write-path validation could
    # carry a value below the bound; without a load-time migration the
    # whole provider fails validation and disappears after a restart.
    data = make_persisted_snapshot()
    data["models"][0][field] = bad_value
    with pytest.raises(ValidationError):
        OpenAIProvider.model_validate(data)
    assert migrate_provider_snapshot(data) is True
    loaded = OpenAIProvider.model_validate(data)
    assert getattr(loaded.models[0], field) is None


def test_persisted_invalid_max_input_length_restores_default_on_load():
    # max_input_length is non-optional (ge=1000), so an unusable
    # persisted value cannot fall back to None; the key is removed and
    # the field default applies instead.
    data = make_persisted_snapshot()
    data["models"][0]["max_input_length"] = 500
    with pytest.raises(ValidationError):
        OpenAIProvider.model_validate(data)
    assert migrate_provider_snapshot(data) is True
    assert "max_input_length" not in data["models"][0]
    loaded = OpenAIProvider.model_validate(data)
    assert loaded.models[0].max_input_length == DEFAULT_CONTEXT_WINDOW


def test_persisted_coercible_string_scalars_are_left_untouched():
    # Pydantic coerces numeric strings for int fields on load, so a
    # persisted "1024" is a valid value, not a legacy violation.
    data = make_persisted_snapshot()
    data["models"][0]["thinking_budget"] = "1024"
    data["models"][0]["max_input_length"] = "131072"
    assert migrate_provider_snapshot(data) is False
    loaded = OpenAIProvider.model_validate(data)
    assert loaded.models[0].thinking_budget == 1024
    assert loaded.models[0].max_input_length == 131072


def load_snapshot_data(data):
    """Write *data* as a custom provider snapshot and load it for real."""
    data["is_custom"] = True
    manager = ProviderManager()
    path = manager.custom_path / "test-provider.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return manager.load_provider("test-provider")


def test_load_provider_survives_invalid_persisted_scalars():
    data = make_persisted_snapshot()
    data["models"][0]["thinking_budget"] = 0
    data["models"][0]["max_input_length"] = 500
    loaded = load_snapshot_data(data)
    assert loaded is not None
    assert loaded.models[0].thinking_budget is None
    assert loaded.models[0].max_input_length == DEFAULT_CONTEXT_WINDOW


def test_persisted_invalid_max_input_length_clears_configured_flag():
    # Resetting the value is not enough on its own: the snapshot also
    # carries the explicit-override markers (the configured flag and the
    # config_overrides entries). Left in place, the restored default
    # would still be treated as an explicit user override and take
    # precedence over auto-detected values. The write path's clear
    # operation removes exactly these markers; the migration mirrors it.
    data = make_persisted_snapshot()
    model = data["models"][0]
    model["max_input_length"] = 500
    model["max_input_length_configured"] = True
    model["config_overrides"] = [
        "max_input_length",
        "max_input_length_configured",
        "thinking_budget",
    ]
    assert migrate_provider_snapshot(data) is True
    assert "max_input_length" not in model
    assert model["max_input_length_configured"] is False
    assert model["config_overrides"] == ["thinking_budget"]
    loaded = OpenAIProvider.model_validate(data)
    assert loaded.models[0].max_input_length == DEFAULT_CONTEXT_WINDOW
    assert loaded.models[0].max_input_length_configured is False
    assert loaded.models[0].config_overrides == ["thinking_budget"]


def test_persisted_bool_thinking_budget_follows_pydantic_coercion():
    # Pydantic coerces True to 1 for int fields, so a persisted True is
    # a previously valid value (1 >= 1); the migration must not clear
    # it as if it were a non-numeric legacy value.
    data = make_persisted_snapshot()
    data["models"][0]["thinking_budget"] = True
    assert migrate_provider_snapshot(data) is False
    loaded = OpenAIProvider.model_validate(data)
    assert loaded.models[0].thinking_budget == 1


def test_persisted_bool_range_is_preserved_on_load():
    # Same alignment at both levels: [True, 1000] coerces to the valid
    # range [1, 1000] under Pydantic and must survive migration.
    data = make_persisted_snapshot(thinking_budget_range=[100, 9000])
    data["models"][0]["thinking_budget_range"] = [True, 1000]
    data["thinking_budget_range"] = [True, 1000]
    assert migrate_provider_snapshot(data) is False
    loaded = OpenAIProvider.model_validate(data)
    assert loaded.models[0].thinking_budget_range == [1, 1000]
    assert loaded.thinking_budget_range == [1, 1000]


def test_persisted_false_thinking_budget_is_reset_on_load():
    # False coerces to 0, which is below the ge=1 bound, so it is
    # treated like any other out-of-bound legacy value and reset.
    data = make_persisted_snapshot()
    data["models"][0]["thinking_budget"] = False
    assert migrate_provider_snapshot(data) is True
    loaded = OpenAIProvider.model_validate(data)
    assert loaded.models[0].thinking_budget is None


@pytest.mark.parametrize("bad_string", ["1.", "1000.", "1.0e3"])
def test_persisted_non_pydantic_numeric_string_scalar_is_reset(bad_string):
    # Strings such as "1." parse as floats in Python, but Pydantic
    # rejects them for int fields. The migration used to accept them
    # via float(), keep the value, and the provider then still failed
    # validation on load.
    data = make_persisted_snapshot()
    data["models"][0]["thinking_budget"] = bad_string
    with pytest.raises(ValidationError):
        OpenAIProvider.model_validate(data)
    assert migrate_provider_snapshot(data) is True
    loaded = OpenAIProvider.model_validate(data)
    assert loaded.models[0].thinking_budget is None


def test_persisted_trailing_dot_max_input_length_restores_default():
    data = make_persisted_snapshot()
    data["models"][0]["max_input_length"] = "1000."
    with pytest.raises(ValidationError):
        OpenAIProvider.model_validate(data)
    assert migrate_provider_snapshot(data) is True
    assert "max_input_length" not in data["models"][0]
    loaded = OpenAIProvider.model_validate(data)
    assert loaded.models[0].max_input_length == DEFAULT_CONTEXT_WINDOW


@pytest.mark.parametrize(
    "bad_range",
    [["1.", "9000"], ["1000.", 9000], ["1e3", "9000"], ["1.0e3", 9000]],
)
def test_persisted_non_pydantic_string_range_is_dropped_on_load(bad_range):
    data = make_persisted_snapshot(thinking_budget_range=[100, 9000])
    data["models"][0]["thinking_budget_range"] = bad_range
    with pytest.raises(ValidationError):
        OpenAIProvider.model_validate(data)
    assert migrate_provider_snapshot(data) is True
    loaded = OpenAIProvider.model_validate(data)
    assert loaded.models[0].thinking_budget_range is None


def test_persisted_decimal_string_values_are_preserved_on_load():
    # "100.0" is accepted by Pydantic for int fields, so the
    # tightened coercion must keep accepting it.
    data = make_persisted_snapshot(thinking_budget_range=[100, 9000])
    data["models"][0]["thinking_budget"] = "100.0"
    data["models"][0]["thinking_budget_range"] = ["100.0", "9000.0"]
    assert migrate_provider_snapshot(data) is False
    loaded = OpenAIProvider.model_validate(data)
    assert loaded.models[0].thinking_budget == 100
    assert loaded.models[0].thinking_budget_range == [100, 9000]


def test_update_model_config_atomic_when_thinking_budget_invalid():
    # The reviewer's example: a valid max_input_length in the same
    # call as an invalid thinking_budget must not be applied when
    # the call raises.
    provider = make_provider()
    model = provider.models[0]
    original_max = model.max_input_length
    with pytest.raises(ValueError, match="thinking_budget"):
        provider.update_model_config(
            "m1",
            {"max_input_length": 64000, "thinking_budget": 0},
        )
    assert model.max_input_length == original_max
    assert model.max_input_length_configured is False
    assert model.config_overrides == []
    assert model.thinking_budget is None


def test_update_model_config_atomic_when_max_input_length_invalid():
    provider = make_provider()
    model = provider.models[0]
    with pytest.raises(ValueError, match="max_input_length"):
        provider.update_model_config(
            "m1",
            {
                "model_type": "decision",
                "supports_image": True,
                "template_id": "tpl-1",
                "generate_kwargs": {"temperature": 0.1},
                "max_input_length": 500,
            },
        )
    assert model.model_type == "chat"
    assert model.supports_image is None
    assert model.template_id is None
    assert model.generate_kwargs == {}
    assert model.config_overrides == []


def test_update_model_config_atomic_when_bool_field_invalid():
    provider = make_provider()
    model = provider.models[0]
    with pytest.raises(ValueError, match="supports_image"):
        provider.update_model_config(
            "m1",
            {"model_type": "decision", "supports_image": "yes"},
        )
    assert model.model_type == "chat"
    assert model.supports_image is None
    assert model.config_overrides == []


def test_update_model_config_atomic_when_thinking_control_invalid():
    provider = make_provider()
    model = provider.models[0]
    with pytest.raises(ValidationError):
        provider.update_model_config(
            "m1",
            {
                "model_type": "decision",
                # A budget control without its range is invalid.
                "thinking_control": {"kind": "budget"},
            },
        )
    assert model.model_type == "chat"
    assert model.thinking_control is None
    assert model.config_overrides == []
