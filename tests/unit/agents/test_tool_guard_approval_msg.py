"""Test that tool guard approval messages use the approval_request block format."""
import pytest


def test_approval_msg_contains_approval_request_block():
    """The denied_text Msg must include an approval_request block
    so the stream adapter can convert it to MCP_APPROVAL_REQUEST."""
    from copaw.agents.tool_guard_mixin import build_approval_blocks

    tool_call = {
        "id": "call_123",
        "name": "shell",
        "input": {"cmd": "rm -rf /tmp/test"},
    }
    tool_name = "shell"

    class FakeGuardResult:
        max_severity = type("S", (), {"value": "critical"})()
        findings_count = 2
        findings = []

    blocks = build_approval_blocks(tool_call, tool_name, FakeGuardResult())

    # Should have a text block with risk info and an approval_request block
    types = [b["type"] for b in blocks]
    assert "text" in types
    assert "approval_request" in types

    approval_block = next(b for b in blocks if b["type"] == "approval_request")
    assert approval_block["id"] == "call_123"
    assert approval_block["name"] == "shell"
    assert "cmd" in str(approval_block["arguments"])


def test_approval_msg_text_block_has_risk_info():
    """The text block should contain severity and findings info."""
    from copaw.agents.tool_guard_mixin import build_approval_blocks

    tool_call = {
        "id": "call_456",
        "name": "browser",
        "input": {"url": "http://evil.com"},
    }

    class FakeGuardResult:
        max_severity = type("S", (), {"value": "high"})()
        findings_count = 1
        findings = []

    blocks = build_approval_blocks(tool_call, "browser", FakeGuardResult())
    text_block = next(b for b in blocks if b["type"] == "text")
    assert "high" in text_block["text"].lower()
    assert "browser" in text_block["text"]
