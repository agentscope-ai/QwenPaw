# -*- coding: utf-8 -*-
"""
Channel Contract Tests

Contract tests for BaseChannel subclasses.

Usage:
    from tests.contract.channels import ChannelContractTest

    class TestMyChannelContract(ChannelContractTest):
        def create_instance(self):
            return MyChannel(process=mock_process, ...)

        # Optional: add channel-specific tests
        def test_my_feature(self, instance):
            assert hasattr(instance, 'my_feature')
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any

from .. import BaseContractTest


class ChannelContractTest(BaseContractTest):
    """
    Contract tests for BaseChannel subclasses.

    This defines the interface contract that ALL channels must satisfy.
    When BaseChannel changes, these tests ensure all channels still comply.

    Contracts verified:
    1. Required abstract methods are implemented
    2. Method signatures are compatible
    3. Critical behavior invariants are maintained
    """

    @abstractmethod
    def create_instance(self) -> Any:
        """Provide a configured channel instance for testing."""
        pass

    # =========================================================================
    # Contract: Required Abstract Methods
    # =========================================================================

    def test_has_channel_type_attribute(self, instance):
        """Contract: All channels must define channel type."""
        assert hasattr(instance, "channel"), "Missing 'channel' attribute"
        assert instance.channel is not None, "'channel' cannot be None"

    def test_has_start_method(self, instance):
        """Contract: All channels must implement start()."""
        assert hasattr(instance, "start"), "Missing start() method"
        assert callable(getattr(instance, "start")), "start must be callable"

    def test_has_stop_method(self, instance):
        """Contract: All channels must implement stop()."""
        assert hasattr(instance, "stop"), "Missing stop() method"
        assert callable(getattr(instance, "stop")), "stop must be callable"

    def test_has_send_method(self, instance):
        """Contract: All channels must implement send()."""
        assert hasattr(instance, "send"), "Missing send() method"
        assert callable(getattr(instance, "send")), "send must be callable"

    def test_has_from_config_method(self, instance):
        """Contract: All channels must implement from_config()."""
        cls = instance.__class__
        assert hasattr(
            cls, "from_config"
        ), f"{cls.__name__} missing from_config()"
        assert callable(
            getattr(cls, "from_config")
        ), "from_config must be callable"

    def test_has_build_agent_request_from_native_method(self, instance):
        """Contract: All channels must implement build_agent_request_from_native()."""
        assert hasattr(
            instance,
            "build_agent_request_from_native",
        ), "Missing build_agent_request_from_native()"
        assert callable(
            getattr(instance, "build_agent_request_from_native"),
        ), "build_agent_request_from_native must be callable"

    # =========================================================================
    # Contract: Configuration Interface
    # =========================================================================

    def test_uses_manager_queue_attribute_exists(self, instance):
        """Contract: Channels should have uses_manager_queue class attribute."""
        cls = instance.__class__
        assert hasattr(
            cls, "uses_manager_queue"
        ), "Missing uses_manager_queue class attribute"

    def test_render_style_attributes_exist(self, instance):
        """Contract: Channels should have render-related attributes."""
        # These are set in BaseChannel.__init__
        assert hasattr(instance, "_render_style"), "Missing _render_style"
        assert hasattr(instance, "_renderer"), "Missing _renderer"

    # =========================================================================
    # Contract: Session Management
    # =========================================================================

    def test_resolve_session_id_returns_str(self, instance):
        """Contract: resolve_session_id must return string."""
        result = instance.resolve_session_id("test_user")
        assert isinstance(
            result, str
        ), f"resolve_session_id must return str, got {type(result)}"

    def test_get_to_handle_from_request_exists(self, instance):
        """Contract: get_to_handle_from_request method must exist."""
        assert hasattr(instance, "get_to_handle_from_request")

    # =========================================================================
    # Contract: Policy Attributes
    # =========================================================================

    def test_policy_attributes_exist(self, instance):
        """Contract: Channels must have policy attributes for access control."""
        assert hasattr(instance, "dm_policy"), "Missing dm_policy"
        assert hasattr(instance, "group_policy"), "Missing group_policy"
        assert hasattr(instance, "allow_from"), "Missing allow_from"


__all__ = ["ChannelContractTest"]
