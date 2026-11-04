# -*- coding: utf-8 -*-
"""Tests for PowerContext-owned configuration."""

import pytest
from pydantic import ValidationError

from plugins.memory.powercontext.backend.config import PowerContextMemoryConfig


def test_defaults():
    config = PowerContextMemoryConfig()
    assert config.scope_id == ""
    assert config.auto_memory_search_config.enabled is True
    assert config.auto_memory_search_config.mode == "prepare"
    assert config.auto_memory_search_config.max_context_bytes == 12000
    assert config.context_assembly.model_dump() == {
        "format": "markdown",
        "sections": [
            {"family": "profile", "limit": 1},
            {"family": "topic-memory", "limit": 2},
            {"family": "memory", "limit": 3},
            {"family": "experience", "limit": 2},
        ],
        "show": [],
    }


def test_legacy_memory_mode_is_explicit():
    config = PowerContextMemoryConfig(
        auto_memory_search_config={"mode": "memory", "max_results": 7},
    )
    assert config.auto_memory_search_config.mode == "memory"
    assert config.auto_memory_search_config.max_results == 7


@pytest.mark.parametrize("mode", ["auto", "fallback", "", None])
def test_rejects_unknown_recall_mode(mode):
    with pytest.raises(ValidationError):
        PowerContextMemoryConfig(auto_memory_search_config={"mode": mode})


@pytest.mark.parametrize(
    "sections",
    [
        [],
        [{"family": "experience", "limit": 1}],
        [
            {"family": "memory", "limit": 8},
            {"family": "profile", "limit": 8},
            {"family": "experience", "limit": 2},
            {"family": "topic-memory", "limit": 8},
        ],
    ],
)
def test_context_assembly_preserves_section_order_and_server_budget(sections):
    config = PowerContextMemoryConfig(
        context_assembly={
            "sections": sections,
            "show": ["confidence", "recall_rank"],
        },
    )
    assert config.context_assembly.model_dump() == {
        "format": "markdown",
        "sections": sections,
        "show": ["confidence", "recall_rank"],
    }


@pytest.mark.parametrize(
    "assembly",
    [
        {"format": "json"},
        {"unknown": True},
        {"sections": [{"family": "skill", "limit": 1}]},
        {"sections": [{"family": "atomic-memory", "limit": 1}]},
        {"sections": [{"family": "memory"}]},
        {"sections": [{"family": "memory", "limit": 0}]},
        {"sections": [{"family": "memory", "limit": 9}]},
        {"sections": [{"family": "experience", "limit": 3}]},
        {"sections": [{"family": "memory", "limit": True}]},
        {"sections": [{"family": "memory", "limit": "2"}]},
        {"sections": [{"family": "memory", "limit": 2.0}]},
        {"sections": [{"family": "profile", "limit": 1, "unknown": True}]},
        {
            "sections": [
                {"family": "memory", "limit": 1},
                {"family": "memory", "limit": 2},
            ],
        },
        {"show": ["confidence", "confidence"]},
        {"show": ["score"]},
    ],
)
def test_rejects_invalid_context_assembly(assembly):
    with pytest.raises(ValidationError):
        PowerContextMemoryConfig(context_assembly=assembly)


def test_removed_fallback_backend_is_ignored():
    config = PowerContextMemoryConfig.model_validate(
        {"fallback_backend": "remelight"},
    )
    assert "fallback_backend" not in config.model_dump()


def test_rejects_more_than_fifty_auto_results():
    with pytest.raises(ValidationError, match="must be <= 50"):
        PowerContextMemoryConfig(
            auto_memory_search_config={"enabled": True, "max_results": 51},
        )


@pytest.mark.parametrize("timeout", [0.99, 60.01, float("inf"), float("nan")])
def test_rejects_out_of_range_timeout(timeout):
    with pytest.raises(ValidationError):
        PowerContextMemoryConfig(timeout=timeout)


@pytest.mark.parametrize("max_context_bytes", [1023, 32769])
def test_rejects_invalid_context_budget(max_context_bytes):
    with pytest.raises(ValidationError):
        PowerContextMemoryConfig(
            auto_memory_search_config={
                "enabled": True,
                "max_context_bytes": max_context_bytes,
            },
        )


@pytest.mark.parametrize("timeout", [1.0, 60.0])
@pytest.mark.parametrize("max_context_bytes", [1024, 32768])
def test_accepts_timeout_and_budget_boundaries(timeout, max_context_bytes):
    config = PowerContextMemoryConfig(
        timeout=timeout,
        auto_memory_search_config={"max_context_bytes": max_context_bytes},
    )

    assert config.timeout == timeout
    assert (
        config.auto_memory_search_config.max_context_bytes == max_context_bytes
    )


@pytest.mark.parametrize("scope_id", ["   ", "scope-" + "x" * 256])
def test_rejects_invalid_explicit_scope(scope_id):
    with pytest.raises(ValidationError):
        PowerContextMemoryConfig(scope_id=scope_id)
