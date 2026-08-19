# -*- coding: utf-8 -*-
"""Benign trailing closers execute the lossless prefix instead of failing.

Reproduces the 2026-08 production case: a 4.4KB streamed tool-call
argument ended with exactly one surplus ``}`` after a complete JSON
object, forcing a repair-and-retry turn even though dropping the tail
was provably lossless.
"""
from __future__ import annotations

import json

import pytest

from services.file_agent_runtime.model_client import _parse_tool_arguments


pytestmark = pytest.mark.unit


def test_single_surplus_closing_brace_is_accepted_as_strict():
    payload = {"projectId": "p-1", "program": ".", "jsonArgs": {"a": 1}}
    raw = json.dumps(payload) + "}"

    arguments, parse_error, repaired, strict_error = _parse_tool_arguments(
        raw,
    )

    assert arguments == payload
    assert parse_error is None
    assert repaired is False
    assert strict_error is None


def test_surplus_closers_with_whitespace_are_accepted():
    payload = {"projectId": "p-1", "program": "."}
    raw = json.dumps(payload) + " \n]} \t"

    arguments, parse_error, repaired, strict_error = _parse_tool_arguments(
        raw,
    )

    assert arguments == payload
    assert repaired is False
    assert strict_error is None
    assert parse_error is None


def test_trailing_real_content_still_goes_through_repair():
    # The tail carries information (a truncated sibling key): accepting the
    # prefix would silently drop it, so the repair path must stay in charge.
    payload = {"projectId": "p-1", "jsonArgs": {"a": 1}}
    raw = json.dumps(payload) + ', "program": "."}'

    arguments, parse_error, repaired, strict_error = _parse_tool_arguments(
        raw,
    )

    assert strict_error is not None
    assert repaired or parse_error is not None
    assert arguments != payload or repaired


def test_plain_valid_json_is_untouched():
    payload = {"projectId": "p-1", "program": "."}

    arguments, parse_error, repaired, strict_error = _parse_tool_arguments(
        json.dumps(payload),
    )

    assert arguments == payload
    assert parse_error is None
    assert repaired is False
    assert strict_error is None
