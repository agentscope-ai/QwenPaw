# -*- coding: utf-8 -*-
"""Slash-command JSON argument errors provide a usable quoting example."""

import shlex

import pytest
from reme.config import parse_kwargs

from qwenpaw.agents.memory.reme_light_memory_manager import (
    _validate_reme_action_kwargs,
)


@pytest.mark.parametrize(
    ("key", "value_type", "invalid", "example"),
    [
        ("tags", "array", "[赵六]", "tags='[\"tag\"]'"),
        ("filter", "object", "{kind:decision}", 'filter=\'{"key":"value"}\''),
    ],
)
def test_invalid_json_arguments_explain_and_validate_correct_quoting(
    key,
    value_type,
    invalid,
    example,
):
    schema = {
        "properties": {key: {"type": value_type}},
        "required": [key],
    }
    with pytest.raises(ValueError) as exc_info:
        _validate_reme_action_kwargs("search", schema, {key: invalid})
    assert example in str(exc_info.value)
    corrected = parse_kwargs(*shlex.split(example))
    _validate_reme_action_kwargs("search", schema, corrected)
