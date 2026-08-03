# -*- coding: utf-8 -*-
"""Tests for AgentBuilder._build_request_context metadata merge + hardening.

Covers:
- AgentRequest.metadata merged first (user-owned fields)
- ``_``-prefixed internal keys blocked
- security-critical fields set last (cannot be overwritten by metadata)
- ``user_id`` precedence (metadata wins, request fallback)
- channel_meta user_name merge
- request_context payload merge (setdefault)
- metadata JSON size limit
"""

from __future__ import annotations

# Tests target request-scope helpers directly.
# pylint: disable=protected-access

from types import SimpleNamespace

import pytest

from qwenpaw.runtime.builder import AgentBuilder


def _ctx(
    *,
    metadata=None,
    channel_meta=None,
    payload_ctx=None,
    channel="console",
    user_id="req-user",
    session_id="sess-1",
    agent_id="default",
    root_session_id="root-1",
    root_agent_id="root-agent",
    workspace_dir="/tmp/ws",
):
    request = SimpleNamespace(
        metadata=metadata,
        channel_meta=channel_meta,
        request_context=payload_ctx,
        channel=channel,
        user_id=user_id,
        channel_instance=object(),
    )
    return SimpleNamespace(
        request=request,
        session_id=session_id,
        agent_id=agent_id,
        root_session_id=root_session_id,
        root_agent_id=root_agent_id,
        workspace_dir=workspace_dir,
        app_services=None,
    )


def test_metadata_merged_first():
    rc = AgentBuilder._build_request_context(
        _ctx(metadata={"tenant": "acme", "user_name": "bob", "level": 3}),
    )
    assert rc["tenant"] == "acme"
    assert rc["user_name"] == "bob"
    assert rc["level"] == 3


def test_underscore_prefixed_metadata_blocked():
    rc = AgentBuilder._build_request_context(
        _ctx(metadata={"_internal": "x", "tenant": "acme"}),
    )
    assert "_internal" not in rc
    assert rc["tenant"] == "acme"


def test_security_fields_not_overwritten_by_metadata():
    rc = AgentBuilder._build_request_context(
        _ctx(
            metadata={
                "session_id": "evil",
                "agent_id": "evil",
                "root_session_id": "evil",
                "root_agent_id": "evil",
                "channel": "evil",
            },
        ),
    )
    assert rc["session_id"] == "sess-1"
    assert rc["agent_id"] == "default"
    assert rc["root_session_id"] == "root-1"
    assert rc["root_agent_id"] == "root-agent"
    assert rc["channel"] == "console"


def test_metadata_user_id_wins_over_request_fallback():
    rc = AgentBuilder._build_request_context(
        _ctx(metadata={"user_id": "meta-user"}),
    )
    assert rc["user_id"] == "meta-user"


def test_request_user_id_fallback_when_metadata_absent():
    rc = AgentBuilder._build_request_context(_ctx())
    assert rc["user_id"] == "req-user"


def test_channel_meta_user_name_merged():
    channel_meta = {"user_name": "Alice", "org": "acme"}
    rc = AgentBuilder._build_request_context(_ctx(channel_meta=channel_meta))
    assert rc["user_name"] == "Alice"
    assert rc["channel_meta"] == channel_meta


def test_request_context_payload_merged_but_security_wins():
    rc = AgentBuilder._build_request_context(
        _ctx(payload_ctx={"approval_level": "high", "session_id": "evil"}),
    )
    assert rc["approval_level"] == "high"
    assert rc["session_id"] == "sess-1"


def test_workspace_dir_set_from_ctx():
    rc = AgentBuilder._build_request_context(_ctx(workspace_dir="/data/ws"))
    assert rc["workspace_dir"] == "/data/ws"


def test_metadata_size_limit_rejected():
    with pytest.raises(ValueError, match="too large"):
        AgentBuilder._build_request_context(
            _ctx(metadata={"padding": "x" * (64 * 1024 + 1)}),
        )


def test_non_json_serializable_metadata_rejected():
    with pytest.raises(ValueError, match="not JSON-serializable"):
        AgentBuilder._build_request_context(_ctx(metadata={(1, 2): "x"}))
