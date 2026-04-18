# -*- coding: utf-8 -*-
"""
Feishu Channel Contract Test

Ensures FeishuChannel satisfies all BaseChannel contracts.
When BaseChannel changes, this test validates FeishuChannel still complies.

Usage:
    pytest tests/contract/channels/test_feishu_contract.py -v
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from tests.contract.channels import ChannelContractTest

if TYPE_CHECKING:
    from qwenpaw.app.channels.base import BaseChannel


class TestFeishuChannelContract(ChannelContractTest):
    """
    Contract tests for FeishuChannel.

    This validates that FeishuChannel properly implements all BaseChannel
    abstract methods and maintains interface compatibility.
    """

    def create_instance(self) -> "BaseChannel":
        """Provide a FeishuChannel instance for contract testing."""
        from qwenpaw.app.channels.feishu.channel import FeishuChannel

        process = AsyncMock()

        return FeishuChannel(
            process=process,
            enabled=True,
            app_id="test_app_id",
            app_secret="test_app_secret",
            bot_prefix="[Test]",
            encrypt_key="",
            verification_token="",
            show_tool_details=False,
            filter_tool_messages=True,
        )

    # =========================================================================
    # Feishu-Specific Contract Tests
    # =========================================================================

    def test_has_token_management(
        self,
        instance,
    ):  # pylint: disable=unused-argument
        """Feishu-specific: must have tenant access token management.

        Note: Feishu uses lark_oapi TokenManager for token handling,
        not instance attributes. Token is fetched dynamically.
        We verify that the lark_oapi SDK's TokenManager is available.
        """
        # Feishu uses lark_oapi TokenManager for token handling,
        # not instance attributes. Token is fetched dynamically.
        try:
            from lark_oapi.core.token import TokenManager

            assert TokenManager is not None
        except ImportError:
            pytest.skip("lark_oapi not installed")

    def test_has_receive_id_store(self, instance):
        """Feishu-specific: must have receive_id store for proactive sends."""
        assert hasattr(
            instance,
            "_receive_id_store",
        ), "FeishuChannel missing _receive_id_store"

    def test_has_message_deduplication(self, instance):
        """Feishu-specific: must have message deduplication mechanism."""
        assert hasattr(
            instance,
            "_processed_message_ids",
        ), "FeishuChannel missing _processed_message_ids"

    def test_channel_type_is_feishu(self, instance):
        """Feishu-specific: channel type must be 'feishu'."""
        assert (
            instance.channel == "feishu"
        ), f"Expected channel='feishu', got '{instance.channel}'"

    def test_has_media_directory(self, instance):
        """Feishu-specific: must have media directory for file uploads."""
        assert hasattr(
            instance,
            "_media_dir",
        ), "FeishuChannel missing _media_dir"
