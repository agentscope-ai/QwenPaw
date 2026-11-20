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


@pytest.mark.parametrize(
    "timeout, budget, max_results",
    [(1.0, 64, 1), (300.0, 32000, 20)],
)
def test_accepts_configuration_boundaries(timeout, budget, max_results):
    config = OpenVikingMemoryConfig(
        request_timeout=timeout,
        retrieval_token_budget=budget,
        auto_memory_search_config={"max_results": max_results},
    )

    assert config.request_timeout == timeout
    assert config.retrieval_token_budget == budget
    assert config.auto_memory_search_config.max_results == max_results


@pytest.mark.parametrize(
    "timeout",
    [float("nan"), float("inf"), -float("inf")],
)
def test_rejects_nonfinite_timeout(timeout):
    with pytest.raises(ValidationError):
        OpenVikingMemoryConfig(request_timeout=timeout)


@pytest.mark.parametrize("max_results", [0, 21])
def test_rejects_out_of_range_auto_search_limit(max_results):
    with pytest.raises(ValidationError):
        OpenVikingMemoryConfig(
            auto_memory_search_config={"max_results": max_results},
        )


def test_rejects_unknown_commit_policy():
    with pytest.raises(ValidationError):
        OpenVikingMemoryConfig(commit_policy="unknown")


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_normalizes_endpoint_without_losing_base_path(scheme):
    config = OpenVikingMemoryConfig(
        base_url=f"  {scheme}://openviking.test/service///  ",
    )

    assert config.base_url == f"{scheme}://openviking.test/service"
