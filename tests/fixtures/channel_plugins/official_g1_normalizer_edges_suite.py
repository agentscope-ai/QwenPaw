"""Actual descriptor/model parity and closed neutral-normalizer admission."""

from copy import deepcopy

from pydantic import BaseModel, Field, ValidationError, field_validator
import pytest

from official_g1_normalizer_suite import gate, matrix_schema


@pytest.mark.parametrize(
    "homeserver", ["https://matrix.invalid///", "anything///", ""]
)
def test_descriptor_only_normalizes_like_real_model_without_mutating_inputs(
    homeserver,
):
    from qwenpaw.config.config import MatrixConfig
    from qwenpaw.plugins.channel_config import validate_channel_config

    schema = matrix_schema()
    values = {"homeserver": homeserver, "groups": {"room": {"tags": ["one"]}}}
    original_schema, original_values = deepcopy(schema), deepcopy(values)
    output = validate_channel_config(schema, values)
    assert output == MatrixConfig.model_validate(values).model_dump(
        mode="json"
    )
    assert schema == original_schema and values == original_values
    output["groups"]["room"]["tags"].append("new")
    assert values == original_values


@pytest.mark.parametrize("invalid", [True, 17, None, [], {}])
def test_normalizer_does_not_coerce_invalid_descriptor_input(invalid):
    from qwenpaw.config.config import MatrixConfig
    from qwenpaw.plugins.channel_config import validate_channel_config

    with pytest.raises(ValidationError):
        MatrixConfig(homeserver=invalid)
    with pytest.raises(ValueError, match="homeserver"):
        validate_channel_config(matrix_schema(), {"homeserver": invalid})


@pytest.mark.parametrize(
    "marker", ["unknown", "__import__('os').system('false')", True, 1]
)
def test_unknown_normalizer_marker_is_data_and_cannot_authorize_execution(
    marker,
):
    from qwenpaw.plugins.channel_config import validate_channel_config_schema

    schema = matrix_schema()
    schema["properties"]["homeserver"]["x-qwenpaw-normalizer"] = marker
    with pytest.raises(ValueError, match="Unknown channel field normalizer"):
        validate_channel_config_schema(schema)


@pytest.mark.parametrize("mode", ["unbound", "before"])
def test_known_normalizer_declaration_requires_exact_after_binding(mode):
    from qwenpaw.config.channel_normalizers import strip_trailing_slash

    class Settings(BaseModel):
        homeserver: str = Field(
            default="",
            json_schema_extra={
                "x-qwenpaw-normalizer": "strip_trailing_slash",
            },
        )

        if mode == "before":
            normalize = field_validator("homeserver", mode="before")(
                strip_trailing_slash,
            )

    with pytest.raises(ValueError, match="normalizer.*(validator|after mode)"):
        gate()._validate_model_contract(
            Settings, "marked_settings", Settings.model_json_schema()
        )
