# -*- coding: utf-8 -*-
"""Unit tests for :mod:`qwenpaw.app.approvals.models`.

The module is tiny but it ships the data contract that every approval
source (ToolGuard, driver policy, IM channels, …) feeds into the central
``ApprovalService``.  We pin field names, defaults and immutability so a
downstream refactor cannot silently break the contract.
"""

from __future__ import annotations

# pylint: disable=use-implicit-booleaness-not-comparison,unused-argument

import dataclasses

import pytest

from qwenpaw.app.approvals.models import ApprovalRequestSummary

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


def test_required_fields_are_source_type_and_name():
    """source_type and name have no default — callers must supply them."""
    summary = ApprovalRequestSummary(
        source_type="driver_policy",
        name="driver:http:Bash",
    )
    assert summary.source_type == "driver_policy"
    assert summary.name == "driver:http:Bash"


def test_defaults_match_contract():
    """severity/findings_count/result_summary/payload default per spec."""
    summary = ApprovalRequestSummary(
        source_type="driver_policy",
        name="bash-driver",
    )
    assert summary.severity == "medium"
    assert summary.findings_count == 1
    assert summary.result_summary == ""
    assert summary.payload == {}


def test_payload_default_factory_is_per_instance():
    """Each new summary gets its own dict (no shared mutable default)."""
    a = ApprovalRequestSummary(source_type="x", name="a")
    b = ApprovalRequestSummary(source_type="x", name="b")
    a.payload["k"] = "v"
    assert b.payload == {}, "payload default leaked across instances"


# ---------------------------------------------------------------------------
# Mutability / shape
# ---------------------------------------------------------------------------


def test_summary_is_frozen():
    """ApprovalRequestSummary is a frozen dataclass — fields cannot be
    reassigned after construction (prevents accidental in-place tampering
    by approval sources)."""
    summary = ApprovalRequestSummary(
        source_type="driver_policy",
        name="bash",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        summary.severity = "high"  # type: ignore[misc]


def test_payload_contents_are_preserved():
    """Arbitrary JSON-ish payload survives the round-trip intact, including
    nested dicts/lists used by driver_policy / IM channel sources."""
    payload = {
        "display": {"tool_name": "Bash", "tool_source": "driver:http"},
        "driver": {"name": "Bash", "protocol": "http", "operation": "invoke"},
        "tool_call": {"id": "tc-1", "name": "Bash", "input": {"cmd": "ls"}},
    }
    summary = ApprovalRequestSummary(
        source_type="driver_policy",
        name="driver:http:Bash",
        severity="high",
        findings_count=3,
        result_summary="requires approval for invoke.",
        payload=payload,
    )
    assert summary.payload == payload
    assert summary.severity == "high"
    assert summary.findings_count == 3
    assert summary.result_summary.startswith("requires")


def test_field_set_matches_contract():
    """New fields cannot be added implicitly and the documented set is the
    full surface area."""
    fields = {f.name for f in dataclasses.fields(ApprovalRequestSummary)}
    assert fields == {
        "source_type",
        "name",
        "severity",
        "findings_count",
        "result_summary",
        "payload",
    }
