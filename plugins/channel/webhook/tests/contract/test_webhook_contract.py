# -*- coding: utf-8 -*-
"""Webhook Channel Contract Test.

Ensures WebhookChannel satisfies the BaseChannel contract. This is
intentionally a thin, self-contained reimplementation (not a copy of
``tests/contract/channels/__init__.py``) so that plugin tests can
run in isolation from the main ``tests/`` tree without depending on
the build-time test infrastructure.
"""

from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock

import pytest

if TYPE_CHECKING:
    from qwenpaw.app.channels.base import BaseChannel


class ChannelContractTest(ABC):
    """
    Minimal contract surface used by every channel.

    Mirrors ``tests.contract.channels.ChannelContractTest`` for the
    assertions the webhook channel cares about, so this plugin can be
    tested without a hard dependency on the main test tree.
    """

    @abstractmethod
    def create_instance(self) -> Any:
        """Return a configured channel instance."""

    # ---- fixtures ----

    @pytest.fixture
    def instance(self) -> Any:
        return self.create_instance()

    # ---- contract checks ----

    def test_no_abstract_methods_remaining(self, instance):
        cls = instance.__class__
        abstracts = getattr(cls, "__abstractmethods__", set())
        if abstracts:
            pytest.fail(
                f"{cls.__name__} has unimplemented abstract methods: "
                f"{', '.join(sorted(abstracts))}",
            )

    def test_has_channel_type_attribute(self, instance):
        assert hasattr(instance, "channel"), "Missing 'channel' attribute"
        assert isinstance(instance.channel, str), "'channel' must be a string"

    def test_has_start_method(self, instance):
        assert callable(getattr(instance, "start", None))

    def test_has_stop_method(self, instance):
        assert callable(getattr(instance, "stop", None))

    def test_has_send_method(self, instance):
        assert callable(getattr(instance, "send", None))

    def test_has_from_config_classmethod(self, instance):
        cls = instance.__class__
        assert callable(
            getattr(cls, "from_config", None),
        ), f"{cls.__name__} missing from_config()"

    def test_has_build_agent_request_from_native(self, instance):
        assert callable(
            getattr(instance, "build_agent_request_from_native", None),
        )

    def test_start_method_accepts_no_required_args(self, instance):
        params = list(inspect.signature(instance.start).parameters.values())
        for p in params:
            if p.name in ("self", "cls"):
                continue
            if p.default is inspect.Parameter.empty and p.kind in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            ):
                pytest.fail(
                    f"{instance.__class__.__name__}.start() has required "
                    f"parameter '{p.name}'",
                )

    def test_stop_method_accepts_no_required_args(self, instance):
        params = list(inspect.signature(instance.stop).parameters.values())
        for p in params:
            if p.name in ("self", "cls"):
                continue
            if p.default is inspect.Parameter.empty and p.kind in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            ):
                pytest.fail(
                    f"{instance.__class__.__name__}.stop() has required "
                    f"parameter '{p.name}'",
                )


def create_mock_process_handler():
    """Create a mock process handler for channel testing."""
    mock = AsyncMock()

    async def mock_process(*_args, **_kwargs):
        from unittest.mock import MagicMock

        mock_event = MagicMock()
        mock_event.object = "message"
        mock_event.status = "completed"
        yield mock_event

    mock.side_effect = mock_process
    return mock


class TestWebhookChannelContract(ChannelContractTest):
    """WebhookChannel must satisfy ALL contracts."""

    def create_instance(self) -> "BaseChannel":
        """Provide a WebhookChannel instance for contract testing."""
        from plugins.channel.webhook.channel import WebhookChannel

        process = create_mock_process_handler()
        return WebhookChannel(
            process=process,
            enabled=True,
            channel_id="default",
            outbound_url=None,
            secret=None,
        )

    def test_webhook_channel_attribute(self, instance):
        """Webhook-specific: channel is 'webhook'."""
        assert instance.channel == "webhook"

    def test_webhook_config_attribute(self, instance):
        """Webhook-specific: has config with channel_id."""
        assert hasattr(instance, "config")
        assert instance.config.channel_id == "default"

    def test_webhook_resolve_session_id_uses_channel_id(self, instance):
        """Webhook-specific: session id derived from channel_id."""
        result = instance.resolve_session_id("any_sender")
        assert result == "webhook:default"

    def test_webhook_resolve_session_id_honors_meta(self, instance):
        """Explicit session_id in meta wins over channel_id."""
        result = instance.resolve_session_id(
            "any_sender",
            {"session_id": "abc"},
        )
        assert result == "webhook:abc"
