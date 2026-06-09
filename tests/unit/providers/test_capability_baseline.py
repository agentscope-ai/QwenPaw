# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
from __future__ import annotations

import pytest

from qwenpaw.providers.capability_baseline import (
    ExpectedCapability,
    ExpectedCapabilityRegistry,
    compare_probe_result,
    generate_summary,
)

# ---------------------------------------------------------------------------
# ExpectedCapabilityRegistry
# ---------------------------------------------------------------------------


@pytest.fixture()
def registry() -> ExpectedCapabilityRegistry:
    return ExpectedCapabilityRegistry()


def test_registry_loads_baseline() -> None:
    """Baseline file should load and contain at least one entry."""
    reg = ExpectedCapabilityRegistry()
    assert reg._data, "baseline file appears empty or failed to parse"


def test_registry_get_expected_found() -> None:
    reg = ExpectedCapabilityRegistry()
    cap = ExpectedCapability(
        provider_id="synth_provider",
        model_id="synth_model",
        expected_image=True,
        expected_video=False,
    )
    reg._register(cap)
    result = reg.get_expected("synth_provider", "synth_model")
    assert result is not None
    assert result.provider_id == "synth_provider"
    assert result.model_id == "synth_model"


def test_registry_get_expected_not_found(
    registry: ExpectedCapabilityRegistry,
) -> None:
    assert registry.get_expected("nonexistent", "model") is None


def test_registry_get_all_for_provider_empty(
    registry: ExpectedCapabilityRegistry,
) -> None:
    assert not registry.get_all_for_provider("no_such_provider")


def test_registry_get_all_for_provider_filters() -> None:
    reg = ExpectedCapabilityRegistry()
    cap1 = ExpectedCapability(
        provider_id="synth_prov",
        model_id="m1",
        expected_image=True,
        expected_video=False,
    )
    cap2 = ExpectedCapability(
        provider_id="synth_prov",
        model_id="m2",
        expected_image=False,
        expected_video=True,
    )
    cap_other = ExpectedCapability(
        provider_id="other_prov",
        model_id="m3",
        expected_image=True,
        expected_video=True,
    )
    reg._register(cap1)
    reg._register(cap2)
    reg._register(cap_other)
    caps = reg.get_all_for_provider("synth_prov")
    assert len(caps) >= 2
    assert all(c.provider_id == "synth_prov" for c in caps)


def test_registry_register_overwrites() -> None:
    reg = ExpectedCapabilityRegistry()
    cap = ExpectedCapability(
        provider_id="test",
        model_id="model",
        expected_image=True,
        expected_video=False,
    )
    reg._register(cap)
    assert reg.get_expected("test", "model") is cap
    cap2 = ExpectedCapability(
        provider_id="test",
        model_id="model",
        expected_image=False,
        expected_video=True,
    )
    reg._register(cap2)
    assert reg.get_expected("test", "model") is cap2


# ---------------------------------------------------------------------------
# compare_probe_result
# ---------------------------------------------------------------------------


def test_compare_no_discrepancy() -> None:
    cap = ExpectedCapability(
        "p",
        "m",
        expected_image=True,
        expected_video=False,
    )
    logs = compare_probe_result(cap, actual_image=True, actual_video=False)
    assert not logs


def test_compare_false_negative() -> None:
    cap = ExpectedCapability(
        "p",
        "m",
        expected_image=True,
        expected_video=None,
    )
    logs = compare_probe_result(cap, actual_image=False, actual_video=False)
    assert len(logs) == 1
    assert logs[0].field == "image"
    assert logs[0].discrepancy_type == "false_negative"
    assert logs[0].expected is True
    assert logs[0].actual is False


def test_compare_false_positive() -> None:
    cap = ExpectedCapability(
        "p",
        "m",
        expected_image=False,
        expected_video=None,
    )
    logs = compare_probe_result(cap, actual_image=True, actual_video=True)
    assert len(logs) == 1
    assert logs[0].field == "image"
    assert logs[0].discrepancy_type == "false_positive"


def test_compare_none_expected_skips() -> None:
    cap = ExpectedCapability(
        "p",
        "m",
        expected_image=None,
        expected_video=None,
    )
    logs = compare_probe_result(cap, actual_image=True, actual_video=True)
    assert not logs


def test_compare_both_fields_discrepant() -> None:
    cap = ExpectedCapability(
        "p",
        "m",
        expected_image=True,
        expected_video=True,
    )
    logs = compare_probe_result(cap, actual_image=False, actual_video=False)
    assert len(logs) == 2
    fields = {log.field for log in logs}
    assert fields == {"image", "video"}


# ---------------------------------------------------------------------------
# generate_summary
# ---------------------------------------------------------------------------


def test_generate_summary_counts() -> None:
    cap = ExpectedCapability(
        "p",
        "m",
        expected_image=True,
        expected_video=None,
    )
    results = [
        (cap, True, False, "ok"),
        (cap, False, False, "discrepancy"),
        (cap, True, True, "failure"),
    ]
    summary = generate_summary(results)
    assert summary.total_models == 3
    assert summary.passed == 1
    assert summary.discrepancies == 1
    assert summary.failures == 1


def test_generate_summary_empty() -> None:
    summary = generate_summary([])
    assert summary.total_models == 0
    assert summary.passed == 0
    assert not summary.details


def test_generate_summary_details_populated() -> None:
    cap = ExpectedCapability(
        "p",
        "m",
        expected_image=True,
        expected_video=None,
    )
    results = [
        (cap, False, False, "discrepancy"),
    ]
    summary = generate_summary(results)
    assert len(summary.details) == 1
    assert summary.details[0].field == "image"
