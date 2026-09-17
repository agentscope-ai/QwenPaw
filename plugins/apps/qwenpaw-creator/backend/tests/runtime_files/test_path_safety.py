# -*- coding: utf-8 -*-
from __future__ import annotations

import re

import pytest

from services.runtime_files import (
    RuntimeFileValidationError,
    hashed_runtime_segment,
    require_safe_runtime_segment,
)


pytestmark = pytest.mark.unit


def test_runtime_path_segment_rejects_traversal_and_control_characters() -> (
    None
):
    assert (
        require_safe_runtime_segment("review-1:decision.2")
        == "review-1:decision.2"
    )

    for unsafe in ("", ".", "..", "../round", "a/b", "a\\b", "line\nbreak"):
        with pytest.raises(RuntimeFileValidationError):
            require_safe_runtime_segment(unsafe)


def test_opaque_runtime_ids_are_hashed_into_a_stable_safe_segment() -> None:
    first = hashed_runtime_segment(
        "review-decision",
        "../../persisted-round",
        "x/../../../../escaped",
    )
    second = hashed_runtime_segment(
        "review-decision",
        "../../persisted-round",
        "x/../../../../escaped",
    )

    assert first == second
    assert re.fullmatch(r"review-decision-[0-9a-f]{64}", first)
    assert "escaped" not in first


def test_hashed_runtime_prefix_has_an_explicit_127_character_limit() -> None:
    assert len(hashed_runtime_segment("a" * 127, "opaque")) == 192

    with pytest.raises(
        RuntimeFileValidationError,
        match="must not exceed 127 characters",
    ):
        hashed_runtime_segment("a" * 128, "opaque")
