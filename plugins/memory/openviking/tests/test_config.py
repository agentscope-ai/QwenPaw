# -*- coding: utf-8 -*-
"""Unit tests for OpenViking plugin-owned configuration."""

import pytest
from pydantic import ValidationError

from plugins.memory.openviking.backend.config import OpenVikingMemoryConfig


def test_defaults_are_safe_for_local_setup():
    config = OpenVikingMemoryConfig()

    assert config.base_url == "http://127.0.0.1:1933"
    assert config.auto_memory_search_config.enabled is True
    assert config.auto_memory_search_config.max_results == 3
    assert config.retrieval_token_budget == 2048


@pytest.mark.parametrize(
    "value",
    ["openviking:1933", "ftp://example.com", "http://"],
)
def test_base_url_requires_http_or_https(value):
    with pytest.raises(ValidationError, match="http"):
        OpenVikingMemoryConfig(base_url=value)


@pytest.mark.parametrize("timeout", [0, 301])
def test_timeout_is_bounded(timeout):
    with pytest.raises(ValidationError):
        OpenVikingMemoryConfig(request_timeout=timeout)


@pytest.mark.parametrize("budget", [63, 32001])
def test_automatic_recall_budget_is_bounded(budget):
    with pytest.raises(ValidationError):
        OpenVikingMemoryConfig(retrieval_token_budget=budget)


def test_api_key_is_normalized_without_being_defaulted():
    assert OpenVikingMemoryConfig(api_key="  test-key  ").api_key == "test-key"
