# -*- coding: utf-8 -*-
"""
Channel Contract Tests

Contract tests for BaseChannel subclasses.

When BaseChannel changes, these tests ensure ALL channels still comply.
This prevents "fix Console, break DingTalk" regressions.

Usage:
    from tests.contract.channels import ChannelContractTest

    class TestMyChannelContract(ChannelContractTest):
        def create_instance(self):
            return MyChannel(process=mock_process, ...)
"""

from __future__ import annotations

import inspect
from abc import abstractmethod
from typing import Any

import pytest

from .. import BaseContractTest


class ChannelContractTest(BaseContractTest):
    """
    Contract tests for BaseChannel subclasses.

    This defines the interface contract that ALL channels must satisfy.
    When BaseChannel changes, these tests ensure all channels still comply.

    Contracts verify compatible signatures, session behavior and policy types.
    Concrete channel tests exercise lifecycle, configuration and delivery.
    """

    @pytest.fixture(autouse=True)
    def _isolate_channel_config(self, monkeypatch):
        """Prevent contract construction from reading user configuration."""
        from qwenpaw.config.config import Config

        monkeypatch.setattr(
            "qwenpaw.app.channels.base.load_config",
            Config,
        )

    @abstractmethod
    def create_instance(self) -> Any:
        """Provide a configured channel instance for testing."""
        return None  # pragma: no cover

    def test_has_channel_type_attribute(self, instance):
        """Contract: All channels must define channel type."""
        assert instance.channel is not None, "'channel' cannot be None"
        assert isinstance(instance.channel, str), "'channel' must be a string"

    # =========================================================================
    # Contract: Method Signature Compatibility
    # =========================================================================

    def test_resolve_session_id_signature_compatible(self, instance):
        """
        Contract: resolve_session_id() must accept sender_id and optional meta.
        """
        sig = inspect.signature(instance.resolve_session_id)
        params = list(sig.parameters.values())
        param_names = [p.name for p in params if p.name not in ("self", "cls")]

        assert "sender_id" in param_names, (
            f"{instance.__class__.__name__}.resolve_session_id() missing "
            f"required 'sender_id' parameter"
        )

    # =========================================================================
    # Contract: Configuration Interface
    # =========================================================================

    def test_uses_manager_queue_is_boolean(self, instance):
        """Channels explicitly select whether the manager owns their queue."""
        assert isinstance(instance.uses_manager_queue, bool)

    # =========================================================================
    # Contract: Policy Attributes
    # =========================================================================

    def test_policy_attributes_types(self, instance):
        """Contract: Policy attributes must have correct types."""
        assert isinstance(instance.dm_policy, str), "dm_policy must be str"
        assert isinstance(
            instance.group_policy,
            str,
        ), "group_policy must be str"
        assert isinstance(
            instance.allow_from,
            (set, list),
        ), "allow_from must be set or list"


__all__ = ["ChannelContractTest"]
