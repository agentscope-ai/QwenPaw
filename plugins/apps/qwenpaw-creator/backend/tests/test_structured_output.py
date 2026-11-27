# -*- coding: utf-8 -*-
"""Unit tests for ``utils.structured_output``."""

from __future__ import annotations

import json
import pytest

from utils.structured_output import extract_json_payload

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            'Note: [see docs]\n{"a": 1, "status": "ok"}',
            {"a": 1, "status": "ok"},
        ),
        ('See [ref] for context\n{"real": 42}', {"real": 42}),
        ('Hint: [check note]\n[{"x": 1}, {"x": 2}]', [{"x": 1}, {"x": 2}]),
        ('Invalid {bad json} before {"good": 2}', {"good": 2}),
        ('```json\nInvalid [note] then {"ok": true}\n```', {"ok": True}),
        (
            '{"nested": {"items": [1, 2], "msg": "a]b{c"}}',
            {"nested": {"items": [1, 2], "msg": "a]b{c"}},
        ),
    ],
)
def test_extract_json_payload_skips_non_json_prose_brackets(
    raw: str,
    expected: object,
) -> None:
    assert extract_json_payload(raw) == expected


def test_extract_json_payload_raises_when_no_valid_json_present() -> None:
    with pytest.raises(json.JSONDecodeError):
        extract_json_payload("See [note] and {prose} only.")
