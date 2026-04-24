# -*- coding: utf-8 -*-
"""XiaoYi Channel Contract Test

Ensures XiaoYiChannel satisfies all BaseChannel contracts.
When BaseChannel changes, this validates XiaoYiChannel still complies.

Run:
    pytest tests/contract/channels/test_xiaoyi_contract.py -v
    pytest tests/contract/channels/ -v  # Run all channel contract tests
"""
# pylint: disable=protected-access

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from tests.contract.channels import ChannelContractTest

if TYPE_CHECKING:
    from qwenpaw.app.channels.base import BaseChannel


class TestXiaoYiChannelContract(ChannelContractTest):
    """Contract tests for XiaoYiChannel.

    This validates that XiaoYiChannel properly implements all BaseChannel
    abstract methods and maintains interface compatibility.

    Key contracts verified:
    - Required abstract methods: start(), stop(), send(), from_config(), etc.
    - Session management: resolve_session_id returns string
    - Configuration: proper initialization with config attributes
    - Policy attributes: dm_policy, group_policy, allow_from
    - XiaoYi-specific: dual WebSocket connections, A2A protocol support
    """

    @pytest.fixture(autouse=True)
    def _setup_xiaoyi_env(self, tmp_path):
        """Setup isolated environment for XiaoYi tests."""
        self._media_dir = tmp_path / "media" / "xiaoyi"
        self._media_dir.mkdir(parents=True, exist_ok=True)

    def create_instance(self) -> "BaseChannel":
        """Create a XiaoYiChannel instance for contract testing.

        Uses mocks to avoid requiring real XiaoYi credentials.
        """
        from qwenpaw.app.channels.xiaoyi.channel import XiaoYiChannel

        process = AsyncMock()

        return XiaoYiChannel(
            process=process,
            enabled=True,
            ak="test_ak",
            sk="test_sk",
            agent_id="test_agent_id",
            ws_url="wss://test.example.com/ws",
            ws_url_backup="wss://116.63.174.231/ws",
            show_tool_details=False,
            filter_tool_messages=True,
            bot_prefix="[Test]",
            media_dir=str(self._media_dir),
        )

    # =====================================================================
    # XiaoYi-Specific Contract Tests
    # =====================================================================

    def test_channel_type_is_xiaoyi(self, instance):
        """XiaoYi-specific: channel type must be 'xiaoyi'."""
        assert instance.channel == "xiaoyi", (
            f"Expected channel='xiaoyi', got '{instance.channel}'"
        )

    def test_has_uses_manager_queue(self, instance):
        """XiaoYi-specific: must use manager queue for long-running channel."""
        from qwenpaw.app.channels.xiaoyi.channel import XiaoYiChannel

        assert hasattr(
            XiaoYiChannel,
            "uses_manager_queue",
        ), "Missing uses_manager_queue class attribute"
        assert (
            XiaoYiChannel.uses_manager_queue is True
        ), "uses_manager_queue must be True for WebSocket channel"

    def test_has_media_directory_attribute(self, instance):
        """XiaoYi-specific: must have media directory for file downloads."""
        assert hasattr(
            instance,
            "_media_dir",
        ), "XiaoYiChannel missing _media_dir"
        assert isinstance(
            instance._media_dir,
            Path,
        ), "_media_dir must be a Path"

    def test_has_session_task_map(self, instance):
        """XiaoYi-specific: must have session->task mapping for A2A replies."""
        assert hasattr(
            instance,
            "_session_task_map",
        ), "XiaoYiChannel missing _session_task_map"
        assert isinstance(
            instance._session_task_map,
            dict,
        ), "_session_task_map must be a dict"

    def test_has_session_server_map(self, instance):
        """XiaoYi-specific: must have session->server mapping for reply routing."""
        assert hasattr(
            instance,
            "_session_server_map",
        ), "XiaoYiChannel missing _session_server_map"
        assert isinstance(
            instance._session_server_map,
            dict,
        ), "_session_server_map must be a dict"

    def test_has_dual_connection_attributes(self, instance):
        """XiaoYi-specific: must have dual WebSocket connection attributes."""
        assert hasattr(
            instance,
            "_conn1",
        ), "XiaoYiChannel missing _conn1"
        assert hasattr(
            instance,
            "_conn2",
        ), "XiaoYiChannel missing _conn2"

    def test_has_connected_attribute(self, instance):
        """XiaoYi-specific: must have connection state tracking."""
        assert hasattr(
            instance,
            "_connected",
        ), "XiaoYiChannel missing _connected"
        assert isinstance(
            instance._connected,
            bool,
        ), "_connected must be a bool"

    def test_has_reconnect_attributes(self, instance):
        """XiaoYi-specific: must have reconnection state tracking."""
        assert hasattr(
            instance,
            "_reconnect_attempts",
        ), "XiaoYiChannel missing _reconnect_attempts"
        assert hasattr(
            instance,
            "_stopping",
        ), "XiaoYiChannel missing _stopping"

    def test_has_heartbeat_attributes(self, instance):
        """XiaoYi-specific: must have heartbeat timeout detection attributes."""
        assert hasattr(
            instance,
            "_drain_task",
        ), "XiaoYiChannel missing _drain_task"

    def test_has_buffer_attributes(self, instance):
        """XiaoYi-specific: must have message buffer for race condition protection."""
        assert hasattr(
            instance,
            "_message_buffer",
        ), "XiaoYiChannel missing _message_buffer"
        assert isinstance(
            instance._message_buffer,
            list,
        ), "_message_buffer must be a list"
        assert hasattr(
            instance,
            "_buffer_lock",
        ), "XiaoYiChannel missing _buffer_lock"

    def test_has_send_media_method(self, instance):
        """XiaoYi-specific: must support media send for file/image messages."""
        assert hasattr(
            instance,
            "send_media",
        ), "XiaoYiChannel should have send_media for file uploads"

    def test_has_send_final_message_method(self, instance):
        """XiaoYi-specific: must have send_final_message for A2A stream completion."""
        assert hasattr(
            instance,
            "send_final_message",
        ), "XiaoYiChannel missing send_final_message"

    def test_has_send_status_update_method(self, instance):
        """XiaoYi-specific: must have send_status_update for A2A status signaling."""
        assert hasattr(
            instance,
            "send_status_update",
        ), "XiaoYiChannel missing send_status_update"

    def test_has_build_artifact_msg_method(self, instance):
        """XiaoYi-specific: must have _build_artifact_msg for A2A protocol."""
        assert hasattr(
            instance,
            "_build_artifact_msg",
        ), "XiaoYiChannel missing _build_artifact_msg"

    def test_has_extract_xiaoyi_parts_method(self, instance):
        """XiaoYi-specific: must have _extract_xiaoyi_parts for message formatting."""
        assert hasattr(
            instance,
            "_extract_xiaoyi_parts",
        ), "XiaoYiChannel missing _extract_xiaoyi_parts"

    def test_has_send_xiaoyi_parts_method(self, instance):
        """XiaoYi-specific: must have send_xiaoyi_parts for formatted sending."""
        assert hasattr(
            instance,
            "send_xiaoyi_parts",
        ), "XiaoYiChannel missing send_xiaoyi_parts"

    # =====================================================================
    # Critical XiaoYi Behavior Contracts
    # =====================================================================

    def test_config_validation(self, instance):
        """Critical: config validation must check required fields."""
        assert hasattr(
            instance,
            "_validate_config",
        ), "XiaoYiChannel missing _validate_config"

        # With valid config, should not raise
        instance.ak = "test_ak"
        instance.sk = "test_sk"
        instance.agent_id = "test_agent_id"
        instance._validate_config()

        # With missing config, should raise
        instance.ak = ""
        with pytest.raises(ValueError, match="AK"):
            instance._validate_config()

    def test_ws_url_attributes(self, instance):
        """Critical: must have primary and backup WebSocket URLs."""
        assert hasattr(
            instance,
            "ws_url",
        ), "XiaoYiChannel missing ws_url"
        assert hasattr(
            instance,
            "ws_url_backup",
        ), "XiaoYiChannel missing ws_url_backup"
        assert isinstance(
            instance.ws_url,
            str,
        ), "ws_url must be a string"
        assert isinstance(
            instance.ws_url_backup,
            str,
        ), "ws_url_backup must be a string"

    @pytest.mark.asyncio
    async def test_resolve_session_id_with_meta(self, instance):
        """XiaoYi-specific: resolve_session_id handles A2A session IDs."""
        result1 = instance.resolve_session_id("user123")
        assert isinstance(result1, str)
        assert "user123" in result1

        result2 = instance.resolve_session_id(
            "user456",
            {"session_id": "sess_abc_123"},
        )
        assert isinstance(result2, str)

    def test_from_env_factory(self, instance):
        """Critical: must support from_env factory method."""
        from qwenpaw.app.channels.xiaoyi.channel import XiaoYiChannel

        assert hasattr(
            XiaoYiChannel,
            "from_env",
        ), "XiaoYiChannel missing from_env factory"
        assert callable(
            getattr(XiaoYiChannel, "from_env"),
        ), "from_env must be callable"

    def test_from_config_factory(self, instance):
        """Critical: must support from_config factory method."""
        from qwenpaw.app.channels.xiaoyi.channel import XiaoYiChannel

        assert hasattr(
            XiaoYiChannel,
            "from_config",
        ), "XiaoYiChannel missing from_config factory"
        assert callable(
            getattr(XiaoYiChannel, "from_config"),
        ), "from_config must be callable"

    def test_build_artifact_msg_produces_valid_a2a(self, instance):
        """Critical: _build_artifact_msg must produce valid A2A artifact-update."""
        import json

        msg = instance._build_artifact_msg(
            session_id="test_session",
            task_id="test_task",
            message_id="test_msg_id",
            parts=[{"kind": "text", "text": "hello"}],
            append=True,
            final=False,
        )

        # Must be a dict
        assert isinstance(msg, dict)

        # Must have required A2A envelope fields
        assert msg.get("msgType") == "agent_response"
        assert msg.get("agentId") == "test_agent_id"
        assert msg.get("sessionId") == "test_session"
        assert msg.get("taskId") == "test_task"
        assert "msgDetail" in msg

        # msgDetail must be valid JSON with artifact-update
        detail = json.loads(msg["msgDetail"])
        assert detail.get("jsonrpc") == "2.0"
        assert detail.get("id") == "test_msg_id"

        result = detail.get("result", {})
        assert result.get("kind") == "artifact-update"
        assert result.get("append") is True
        assert result.get("lastChunk") is True  # Always true per A2A spec
        assert result.get("final") is False

        artifact = result.get("artifact", {})
        assert "artifactId" in artifact
        assert artifact.get("parts") == [{"kind": "text", "text": "hello"}]

    def test_build_artifact_msg_final_message(self, instance):
        """Critical: final message must have append=False and final=True."""
        msg = instance._build_artifact_msg(
            session_id="test_session",
            task_id="test_task",
            message_id="test_msg_id",
            parts=[{"kind": "text", "text": ""}],
            append=False,
            final=True,
        )

        import json
        detail = json.loads(msg["msgDetail"])
        result = detail.get("result", {})

        assert result.get("append") is False
        assert result.get("final") is True
        assert result.get("lastChunk") is True

    def test_health_check_returns_dict(self, instance):
        """Critical: health_check must return a dict with status info."""
        import asyncio

        result = asyncio.get_event_loop().run_until_complete(
            instance.health_check(),
        )
        assert isinstance(result, dict)
        assert "channel" in result
        assert "status" in result

    @pytest.mark.asyncio
    async def test_send_status_update_is_callable(self, instance):
        """Critical: send_status_update must be an async callable."""
        assert callable(instance.send_status_update), (
            "send_status_update must be callable"
        )
        import inspect
        assert inspect.iscoroutinefunction(
            instance.send_status_update,
        ), "send_status_update must be async"

    def test_send_final_message_is_callable(self, instance):
        """Critical: send_final_message must be an async callable."""
        assert callable(instance.send_final_message), (
            "send_final_message must be callable"
        )
        import inspect
        assert inspect.iscoroutinefunction(
            instance.send_final_message,
        ), "send_final_message must be async"


# =============================================================================
# Regression Prevention
# =============================================================================
# Scenario: Developer modifies BaseChannel._on_process_completed signature
#
# Before contract tests:
#   - Dev changes BaseChannel._on_process_completed parameters
#   - Console, DingTalk tests pass (dev tested locally)
#   - XiaoYi final message stops sending in production!
#
# With contract tests:
#   - Dev changes BaseChannel._on_process_completed signature
#   - Run: pytest tests/contract/channels/test_xiaoyi_contract.py -v
#   - TestXiaoYiChannelContract::test_has_on_process_completed PASSES
#   - But XiaoYi-specific behavior tests may FAIL
#   - Dev realizes the breaking change and fixes it before merge