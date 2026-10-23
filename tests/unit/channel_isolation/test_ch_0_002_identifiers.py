# -*- coding: utf-8 -*-
"""Canonical Channel, Python ABI and release-platform validation."""

from __future__ import annotations

import pytest

from qwenpaw.channel_protocol import (
    DescriptorValidationError,
    current_python_abi,
    validate_channel_key,
    validate_platform_tag,
    validate_python_abi,
)

PLATFORMS = {
    "macosx_11_0_arm64",
    "manylinux_2_28_x86_64",
    "win_amd64",
}


@pytest.mark.parametrize(
    "value",
    ["", "UPPER", " leading", "trailing-", "bad.key", "a" * 65],
)
def test_channel_key_rejects_noncanonical_input(value: str) -> None:
    """V1 keys are rejected rather than trimmed or case-folded."""
    with pytest.raises(DescriptorValidationError):
        validate_channel_key(value)


@pytest.mark.parametrize(
    "value",
    ["cp311-cp311", "cp312-cp312", "cp313-cp313"],
)
def test_python_abi_matrix(value: str) -> None:
    """The required Python ABI examples are valid canonical pairs."""
    assert validate_python_abi(value) == value


def test_current_python_abi_is_canonical() -> None:
    """Runtime ABI discovery uses the first concrete sys_tags ABI."""
    assert validate_python_abi(current_python_abi()) == current_python_abi()


@pytest.mark.parametrize("value", sorted(PLATFORMS))
def test_platform_tag_registry_matrix(value: str) -> None:
    """Target-platform shapes require explicit registry membership."""
    assert (
        validate_platform_tag(
            value,
            allowed_platform_tags=PLATFORMS,
        )
        == value
    )


@pytest.mark.parametrize(
    "value",
    ["windows", "darwin", "macos", "x86_64", "linux-x86_64", "WIN_AMD64"],
)
def test_platform_tag_rejects_alias_or_noncanonical_input(value: str) -> None:
    """Product aliases and unregistered tags cannot identify environments."""
    with pytest.raises(DescriptorValidationError):
        validate_platform_tag(
            value,
            allowed_platform_tags={value, *PLATFORMS},
        )


def test_platform_tag_rejects_canonical_nonmember() -> None:
    """Canonical syntax cannot bypass release registry membership."""
    with pytest.raises(DescriptorValidationError):
        validate_platform_tag(
            "manylinux_2_17_aarch64",
            allowed_platform_tags=PLATFORMS,
        )


def test_identifier_failures_share_stable_error_code() -> None:
    """Pure identity validation exposes the descriptor_invalid code."""
    with pytest.raises(DescriptorValidationError) as raised:
        validate_channel_key("")

    assert raised.value.code == "descriptor_invalid"
