# -*- coding: utf-8 -*-
"""Unit tests for Files directory browser helpers."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from qwenpaw.app.routers.project_directory import _validate_directory_name


def test_validate_directory_name_trims_surrounding_whitespace() -> None:
    """A portable folder name is normalized before creation."""
    assert _validate_directory_name("  reports  ") == "reports"


@pytest.mark.parametrize(
    "name",
    ["", "   ", ".", "..", "child/name", "child\\name", "CON"],
)
def test_validate_directory_name_rejects_unsafe_names(name: str) -> None:
    """Traversal, separators, and non-portable names are rejected."""
    with pytest.raises(HTTPException) as exc_info:
        _validate_directory_name(name)

    assert exc_info.value.status_code == 400
