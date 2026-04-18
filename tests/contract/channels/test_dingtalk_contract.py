# -*- coding: utf-8 -*-
"""
DingTalk Channel Contract Test

Ensures DingTalkChannel satisfies all BaseChannel contracts.
When BaseChannel changes, this test validates DingTalkChannel still complies.

Run:
    pytest tests/contract/channels/test_dingtalk_contract.py -v
    pytest tests/contract/channels/ -v  # Run all channel contract tests
"""
# pylint: disable=protected-access

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from tests.contract.channels import ChannelContractTest

if TYPE_CHECKING:
    from qwenpaw.app.channels.base import BaseChannel


class TestDingTalkChannelContract(ChannelContractTest):
    """
    Contract tests for DingTalkChannel.

    This validates that DingTalkChannel properly implements all BaseChannel
    abstract methods and maintains interface compatibility.

    Key contracts verified:
    - Required abstract methods: start(), stop(), send(), from_config(), etc.
    - Session management: resolve_session_id returns string
    - Configuration: proper initialization with config attributes
    - Policy attributes: dm_policy, group_policy, allow_from
    """

    @pytest.fixture(autouse=True)
    def _setup_dingtalk_env(self, temp_copaw_home):
        """Setup isolated environment for DingTalk tests."""
        self._media_dir = temp_copaw_home / ".copaw" / "media"
        self._media_dir.mkdir(parents=True, exist_ok=True)

    def create_instance(self) -> "BaseChannel":
        """
        Create a DingTalkChannel instance for contract testing.

        Uses mocks to avoid requiring real DingTalk credentials.
        """
        from qwenpaw.app.channels.dingtalk.channel import DingTalkChannel

        process = AsyncMock()

        return DingTalkChannel(
            process=process,
            enabled=True,
            client_id="test_client_id",
            client_secret="test_client_secret",
            bot_prefix="[Test]",
            media_dir=str(self._media_dir),
            show_tool_details=False,
            filter_tool_messages=True,
        )

    # =========================================================================
    # DingTalk-Specific Contract Tests
    # =========================================================================

    def test_has_dingtalk_specific_attributes(self, instance):
        """DingTalk-specific: must have session webhook store."""
        assert hasattr(
            instance,
            "_session_webhook_store",
        ), "DingTalkChannel missing _session_webhook_store"
        assert isinstance(
            instance._session_webhook_store,
            dict,
        ), "_session_webhook_store must be a dict"

    def test_has_token_caching_attributes(self, instance):
        """DingTalk-specific: must have token caching mechanism."""
        assert hasattr(
            instance,
            "_token_value",
        ), "DingTalkChannel missing _token_value"
        assert hasattr(
            instance,
            "_token_expires_at",
        ), "DingTalkChannel missing _token_expires_at"

    def test_has_media_directory_attribute(self, instance):
        """DingTalk-specific: must have media directory for file uploads."""
        assert hasattr(
            instance,
            "_media_dir",
        ), "DingTalkChannel missing _media_dir"

    def test_channel_type_is_dingtalk(self, instance):
        """DingTalk-specific: channel type must be 'dingtalk'."""
        assert (
            instance.channel == "dingtalk"
        ), f"Expected channel='dingtalk', got '{instance.channel}'"

    def test_has_file_upload_capability(self, instance):
        """DingTalk-specific: must support file upload methods."""
        assert hasattr(
            instance,
            "send_media",
        ), "DingTalkChannel should have send_media for file uploads"

    @pytest.mark.asyncio
    async def test_resolve_session_id_with_conversation_id(self, instance):
        """DingTalk-specific: resolve_session_id handles conversation IDs."""
        result1 = instance.resolve_session_id("user123")
        assert isinstance(result1, str)
        assert "user123" in result1

        result2 = instance.resolve_session_id(
            "user456",
            {"conversation_id": "conv_abc_123"},
        )
        assert isinstance(result2, str)

    # =========================================================================
    # Critical DingTalk Behavior Contracts
    # =========================================================================

    @pytest.mark.asyncio
    async def test_session_webhook_storage_contract(self, instance):
        """
        Critical: session webhook storage must be thread-safe.

        Session webhooks are shared between incoming message handling
        and proactive (cron) sends.
        """
        assert hasattr(
            instance,
            "_session_webhook_lock",
        ), "Missing _session_webhook_lock for thread safety"
        assert isinstance(
            instance._session_webhook_lock,
            asyncio.Lock,
        ), "_session_webhook_lock must be asyncio.Lock"

    def test_dedup_mechanism_exists(self, instance):
        """
        Critical: message deduplication to prevent double-processing.

        DingTalk can deliver the same message multiple times.
        """
        assert hasattr(
            instance,
            "_processing_message_ids",
        ), "Missing _processing_message_ids for deduplication"
        assert hasattr(
            instance,
            "_processing_message_ids_lock",
        ), "Missing _processing_message_ids_lock for thread safety"
        # threading.Lock() returns a lock object, check by type name
        lock_type = type(instance._processing_message_ids_lock).__name__
        assert (
            "lock" in lock_type.lower()
        ), f"_processing_message_ids_lock must be a Lock, got {lock_type}"


# =============================================================================
# Regression Prevention Example
# =============================================================================
# Scenario: Developer fixes DingTalk file upload by modifying BaseChannel
#
# Before contract tests:
#   - Dev modifies BaseChannel.send_media() signature
#   - DingTalk tests pass (dev tested locally)
#   - Feishu, Telegram, Discord tests fail in production!
#
# With contract tests:
#   - Dev modifies BaseChannel.send_media() signature
#   - Run: pytest tests/contract/channels/ -v
#   - TestConsoleChannelContract::test_has_send_method PASSES
#   - TestDingTalkChannelContract::test_has_file_upload_capability PASSES
#   - TestFeishuChannelContract (not yet added) would FAIL
#   - Dev realizes the breaking change and fixes it before merge
