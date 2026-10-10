# -*- coding: utf-8 -*-
"""Tests for environment setting validation."""

from __future__ import annotations

import pytest

from qwenpaw.envs.registry import validate_env_value


@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_stream_timeout_rejects_non_finite_values(value: str) -> None:
    """Async timeout settings must be finite."""
    with pytest.raises(ValueError, match="Invalid float value"):
        validate_env_value("QWENPAW_LLM_STREAM_IDLE_TIMEOUT", value)
