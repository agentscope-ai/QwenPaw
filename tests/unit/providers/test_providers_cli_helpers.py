# -*- coding: utf-8 -*-
"""Tests for CLI provider helpers (_mask_header_value, _parse_header_pairs)."""

from __future__ import annotations

import click
import pytest

from copaw.cli.providers_cmd import _mask_header_value, _parse_header_pairs
from copaw.providers.provider import Provider


# ------------------------------------------------------------------
# _mask_header_value  (delegates to Provider.mask_header_value)
# ------------------------------------------------------------------


def test_mask_header_value_short():
    assert _mask_header_value("ab") == "**"
    assert _mask_header_value("abcd") == "****"


def test_mask_header_value_long():
    result = _mask_header_value("Bearer sk-secret-key-12345")
    assert result.startswith("Be")
    assert result.endswith("45")
    assert "***" in result


def test_mask_header_value_empty():
    assert _mask_header_value("") == ""


def test_mask_header_value_delegates_to_provider():
    """Ensure the CLI wrapper delegates to Provider.mask_header_value."""
    assert _mask_header_value("secret") == Provider.mask_header_value("secret")


# ------------------------------------------------------------------
# _parse_header_pairs
# ------------------------------------------------------------------


def test_parse_header_pairs_valid():
    result = _parse_header_pairs(
        ("X-Custom=value", "Authorization=Bearer tok"),
    )
    assert result == {"X-Custom": "value", "Authorization": "Bearer tok"}


def test_parse_header_pairs_strips_whitespace():
    result = _parse_header_pairs(("  Key  =  Value  ",))
    assert result == {"Key": "Value"}


def test_parse_header_pairs_empty_tuple():
    assert not _parse_header_pairs(())


def test_parse_header_pairs_value_with_equals():
    result = _parse_header_pairs(("Key=val=ue",))
    assert result == {"Key": "val=ue"}


def test_parse_header_pairs_invalid_format():
    with pytest.raises(click.BadParameter, match="KEY=VALUE"):
        _parse_header_pairs(("NoEqualsSign",))
