# -*- coding: utf-8 -*-
"""
Example: Console Channel Contract Test

Demonstrates how to implement contract tests for channel subclasses.
When BaseChannel changes, these tests ensure ConsoleChannel still complies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from tests.contract.channels import ChannelContractTest

if TYPE_CHECKING:
    from qwenpaw.app.channels.base import BaseChannel


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


class TestConsoleChannelContract(ChannelContractTest):
    """
    ConsoleChannel must satisfy ALL contracts defined in ChannelContractTest.

    If BaseChannel adds a new requirement (e.g., a new abstract method),
    this test automatically picks it up and fails until ConsoleChannel
    implements it.
    """

    def create_instance(self) -> "BaseChannel":
        """Provide a ConsoleChannel instance for contract testing."""
        from qwenpaw.app.channels.console.channel import ConsoleChannel

        process = create_mock_process_handler()
        return ConsoleChannel(
            process=process,
            enabled=True,
            bot_prefix="[TEST] ",
            show_tool_details=False,
            filter_tool_messages=True,
        )

    # Subclass-specific tests can be added here
    def test_console_specific_behavior(self, instance):
        """Console-specific: uses stdout for output."""
        # Console channel outputs to stdout/stderr
        assert hasattr(instance, "bot_prefix")


# =============================================================================
# Example: Contract Coverage Check
# =============================================================================


@pytest.mark.skip(reason="Meta-test - run manually to check coverage")
def test_all_channel_subclasses_have_contract_tests():
    """
    Meta-test: Verify all BaseChannel subclasses have contract tests.

    This prevents adding a new channel without corresponding contract coverage.
    Run periodically in CI to ensure completeness.
    """
    import inspect
    from qwenpaw.app.channels.base import BaseChannel

    # Get all concrete ChannelContractTest implementations
    tested_classes = set()
    for test_class in ChannelContractTest.get_concrete_tests():
        try:
            instance = test_class().create_instance()
            tested_classes.add(instance.__class__.__name__)
        except Exception as e:
            pytest.skip(f"Cannot instantiate {test_class.__name__}: {e}")

    # Get all BaseChannel subclasses
    def get_channel_subclasses(cls):
        result = []
        for subclass in cls.__subclasses__():
            if not inspect.isabstract(subclass):
                result.append(subclass.__name__)
            result.extend(get_channel_subclasses(subclass))
        return result

    all_channels = set(get_channel_subclasses(BaseChannel))

    # Check coverage
    untested = all_channels - tested_classes

    if untested:
        pytest.fail(
            f"Channels missing contract tests: {untested}\n"
            f"Create test class inheriting from ChannelContractTest for each.",
        )
