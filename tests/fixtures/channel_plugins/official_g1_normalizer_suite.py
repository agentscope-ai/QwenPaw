"""Release model gate: neutral normalization cannot bypass real constraints."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path

from pydantic import Field, field_validator
import pytest

ROOT = Path(__file__).resolve().parents[3]


def gate():
    spec = importlib.util.spec_from_file_location(
        "g1_normalizer_release_gate",
        ROOT / "scripts/pack/validate_channel_contracts.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def matrix_schema():
    return json.loads(
        (ROOT / "plugins/channel/matrix/channel.json").read_text()
    )["config_schema"]


def test_actual_official_preflight_accepts_matrix_neutral_normalization():
    from qwenpaw.config.config import MatrixConfig

    assert MatrixConfig(homeserver="https://matrix.invalid///").homeserver == (
        "https://matrix.invalid"
    )
    # This is normalization, not a restriction to URLs or slash-free input.
    assert MatrixConfig(homeserver="arbitrary///").homeserver == "arbitrary"
    assert MatrixConfig(homeserver="").homeserver == ""
    gate().validate_official_channel_contracts(ROOT)


@pytest.mark.parametrize("kind", ["undeclared", "forged_marker", "same_name"])
def test_unregistered_validator_cannot_borrow_matrix_normalizer_marker(kind):
    from qwenpaw.config.config import MatrixConfig

    original = deepcopy(
        MatrixConfig.model_fields["homeserver"].json_schema_extra
    )
    annotation = original if isinstance(original, dict) else {}
    if kind == "forged_marker":
        # An arbitrary JSON annotation must never authorize Python behavior.
        annotation["x-qwenpaw-normalizer"] = "matrix.homeserver.rstrip-slash"

    class Unregistered(MatrixConfig):
        homeserver: str = Field(default="", json_schema_extra=annotation)

        @field_validator("homeserver")
        @classmethod
        def strip_trailing_slash(cls, value):
            if kind == "same_name":
                return value.rstrip("/")
            if value == "forbidden":
                raise ValueError("additional undeclared restriction")
            return value

    release = gate()
    # Establish that this release gate actually understands the registered
    # normalizer, so rejection cannot hide behind the original Matrix defect.
    release._validate_model_contract(MatrixConfig, "matrix", matrix_schema())
    schema = Unregistered.model_json_schema()
    for name, value in Unregistered().model_dump(mode="json").items():
        schema["properties"][name]["default"] = value
    with pytest.raises(ValueError, match="(?i)validator|normaliz"):
        release._validate_model_contract(Unregistered, "matrix", schema)


@pytest.mark.parametrize(
    "change", ["default", "constraint", "field", "schema_type"]
)
def test_recognized_normalizer_does_not_hide_schema_contract_drift(change):
    from qwenpaw.config.config import MatrixConfig

    release = gate()
    schema = matrix_schema()
    release._validate_model_contract(MatrixConfig, "matrix", schema)
    mutated = deepcopy(schema)
    if change == "default":
        mutated["properties"]["homeserver"]["default"] = "other-default"
    elif change == "constraint":
        mutated["properties"]["sync_timeout_ms"]["minimum"] = 1
    elif change == "field":
        del mutated["properties"]["access_token"]
    else:
        mutated["properties"]["homeserver"]["type"] = "integer"
    with pytest.raises(ValueError, match="differs from retained host model"):
        release._validate_model_contract(MatrixConfig, "matrix", mutated)
