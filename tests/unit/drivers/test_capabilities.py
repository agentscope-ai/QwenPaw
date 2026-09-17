# -*- coding: utf-8 -*-
"""Tests for Driver capability-id encoding/decoding contracts."""
from __future__ import annotations

import pytest

from qwenpaw.drivers.capabilities import (
    CapabilityExposure,
    DriverCapability,
    DriverInvocation,
    DriverInvocationResult,
    DriverRuntimeInfo,
    format_capability_id,
    parse_capability_id,
)


class TestCapabilityIdRoundTrip:
    """format/parse must be lossless.

    Intent: capability_id is a stable wire contract — encoding then
    parsing must recover the original fields exactly, including unsafe
    characters that would otherwise corrupt the URL structure.
    """

    @pytest.mark.parametrize(
        ("protocol", "driver_name", "kind", "action", "name"),
        [
            ("mcp", "github", "tool", "create_issue", "issues"),
            ("mcp", "fs", "tool", "read", "read_file"),
            ("acp", "db", "tool", "query", "sql"),
        ],
    )
    def test_roundtrip_plain(self, protocol, driver_name, kind, action, name):
        cid = format_capability_id(protocol, driver_name, kind, action, name)
        assert parse_capability_id(cid) == (
            protocol,
            driver_name,
            kind,
            action,
            name,
        )

    def test_roundtrip_unsafe_characters(self):
        # '/', '#', ' ' would break urlsplit if not quoted by _encode_part.
        cid = format_capability_id(
            "m cp",
            "git/hub",
            "tool",
            "act#ion",
            "na me?",
        )
        assert parse_capability_id(cid) == (
            "m cp",
            "git/hub",
            "tool",
            "act#ion",
            "na me?",
        )

    def test_tool_kind_round_trips_via_tools_segment(self):
        # 'tool' is encoded as path segment 'tools' and decoded back to
        # 'tool' — the kind↔segment mapping must be invisible to callers.
        cid = format_capability_id("mcp", "d", "tool", "a", "n")
        assert "/tools/" in cid
        _, _, kind, _, _ = parse_capability_id(cid)
        assert kind == "tool"


class TestParseCapabilityIdValidation:
    """parse_capability_id rejects malformed ids at the boundary."""

    @pytest.mark.parametrize(
        "bad_id",
        [
            "http://github/tool/a#n",  # wrong scheme
            "driver:///tool/a#n",  # missing netloc (protocol)
            "driver://proto/d/a#n",  # only 2 path parts
            "driver://proto/d/tool/a/n#n",  # 4 path parts
            "driver://proto/d/tool/a",  # missing fragment (action)
            "",  # empty
        ],
    )
    def test_invalid_ids_raise(self, bad_id):
        with pytest.raises(ValueError):
            parse_capability_id(bad_id)


class TestCapabilityDataclasses:
    """Defaults and frozen-ness protect the capability contract."""

    def test_driver_capability_defaults(self):
        cap = DriverCapability(
            capability_id="id",
            driver_name="d",
            protocol="mcp",
            kind="tool",
            action="a",
            name="n",
        )
        assert cap.description == ""
        assert not cap.input_schema
        assert not cap.output_schema
        assert cap.exposure == CapabilityExposure()
        assert not cap.metadata
        with pytest.raises(AttributeError):  # frozen dataclass
            cap.name = "x"

    def test_invocation_result_defaults(self):
        r = DriverInvocationResult(ok=True)
        assert r.value is None
        assert r.error_type == ""
        assert r.message == ""
        assert not r.metadata

    def test_runtime_info_defaults(self):
        info = DriverRuntimeInfo(
            name="d",
            protocol="mcp",
            enabled=True,
            status="ok",
        )
        assert info.display_name == ""
        assert info.error == ""

    def test_invocation_request_context_isolated_per_instance(self):
        # default_factory must give a fresh dict per instance — no shared
        # mutable default across DriverInvocation instances.
        inv1 = DriverInvocation(capability_id="id", payload={})
        inv2 = DriverInvocation(capability_id="id", payload={})
        inv1.request_context["x"] = 1
        assert "x" not in inv2.request_context
