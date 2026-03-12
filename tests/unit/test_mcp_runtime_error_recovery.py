# -*- coding: utf-8 -*-
"""Tests for MCP RuntimeError recovery in register_mcp_clients."""
from typing import Any

import pytest
from anyio import ClosedResourceError

from copaw.agents.react_agent import _is_recoverable_mcp_error


class _FakeToolkit:
    """Fake toolkit for testing MCP client registration."""

    def __init__(
        self,
        fail_once_names: set[str] | None = None,
        always_fail_names: set[str] | None = None,
        unrecoverable_error_names: set[str] | None = None,
    ) -> None:
        self.fail_once_names = fail_once_names or set()
        self.always_fail_names = always_fail_names or set()
        self.unrecoverable_error_names = unrecoverable_error_names or set()
        self.calls: dict[str, int] = {}
        self.registered: list[str] = []

    async def register_mcp_client(
        self,
        client: Any,
        namesake_strategy: str = "skip",  # pylint: disable=unused-argument
    ) -> None:
        name = client.name
        self.calls[name] = self.calls.get(name, 0) + 1

        if name in self.always_fail_names:
            raise ClosedResourceError()

        if name in self.unrecoverable_error_names:
            # This RuntimeError is NOT recoverable (no connection keywords)
            raise RuntimeError("unexpected toolkit failure")

        if name in self.fail_once_names and self.calls[name] == 1:
            raise RuntimeError("not connected to the server")

        self.registered.append(name)


class _FakeMCPClient:
    """Fake MCP client for testing."""

    def __init__(self, name: str, connect_ok: bool = True) -> None:
        self.name = name
        self.connect_ok = connect_ok
        self.close_calls = 0
        self.connect_calls = 0

    async def close(self) -> None:
        self.close_calls += 1

    async def connect(self) -> None:
        self.connect_calls += 1
        if not self.connect_ok:
            raise RuntimeError("connect failed")


class TestIsRecoverableMcpError:
    """Tests for _is_recoverable_mcp_error helper function."""

    def test_closed_resource_error_is_recoverable(self) -> None:
        """ClosedResourceError should be recoverable."""
        assert _is_recoverable_mcp_error(ClosedResourceError()) is True

    def test_cancelled_error_is_recoverable(self) -> None:
        """CancelledError should be recoverable."""
        import asyncio

        assert _is_recoverable_mcp_error(asyncio.CancelledError()) is True

    def test_runtime_error_not_connected_is_recoverable(self) -> None:
        """RuntimeError with 'not connected' should be recoverable."""
        error = RuntimeError("The MCP client is not connected to the server")
        assert _is_recoverable_mcp_error(error) is True

    def test_runtime_error_not_established_is_recoverable(self) -> None:
        """RuntimeError with 'not established' should be recoverable."""
        error = RuntimeError("The connection is not established")
        assert _is_recoverable_mcp_error(error) is True

    def test_runtime_error_connect_method_is_recoverable(self) -> None:
        """RuntimeError with 'connect()' should be recoverable."""
        error = RuntimeError("Call connect() before using the client")
        assert _is_recoverable_mcp_error(error) is True

    def test_runtime_error_unexpected_is_not_recoverable(self) -> None:
        """Unexpected RuntimeError should not be recoverable."""
        error = RuntimeError("unexpected toolkit failure")
        assert _is_recoverable_mcp_error(error) is False

    def test_other_exception_is_not_recoverable(self) -> None:
        """Other exception types should not be recoverable."""
        assert _is_recoverable_mcp_error(ValueError("test")) is False
        assert _is_recoverable_mcp_error(KeyError("test")) is False


@pytest.mark.asyncio
async def test_register_mcp_clients_retries_on_runtime_error() -> None:
    """Should retry registration when RuntimeError indicates connection."""
    from copaw.agents.react_agent import CoPawAgent

    toolkit = _FakeToolkit(fail_once_names={"flaky"})
    flaky = _FakeMCPClient(name="flaky", connect_ok=True)
    healthy = _FakeMCPClient(name="healthy", connect_ok=True)

    agent = object.__new__(CoPawAgent)
    agent.toolkit = toolkit
    agent._mcp_clients = [flaky, healthy]  # pylint: disable=protected-access

    await CoPawAgent.register_mcp_clients(agent)

    assert toolkit.calls["flaky"] == 2
    assert flaky.connect_calls == 1
    assert toolkit.calls["healthy"] == 1
    assert toolkit.registered == ["flaky", "healthy"]


@pytest.mark.asyncio
async def test_register_mcp_clients_raises_unrecoverable_error() -> None:
    """Should raise when RuntimeError is not recoverable."""
    from copaw.agents.react_agent import CoPawAgent

    toolkit = _FakeToolkit(unrecoverable_error_names={"boom"})
    boom = _FakeMCPClient(name="boom", connect_ok=True)

    agent = object.__new__(CoPawAgent)
    agent.toolkit = toolkit
    agent._mcp_clients = [boom]  # pylint: disable=protected-access

    with pytest.raises(RuntimeError, match="unexpected toolkit failure"):
        await CoPawAgent.register_mcp_clients(agent)


@pytest.mark.asyncio
async def test_register_mcp_clients_skips_after_recovery_failure() -> None:
    """Should skip client when recovery fails after RuntimeError."""
    from copaw.agents.react_agent import CoPawAgent

    toolkit = _FakeToolkit(always_fail_names={"broken"})
    broken = _FakeMCPClient(name="broken", connect_ok=False)
    healthy = _FakeMCPClient(name="healthy", connect_ok=True)

    agent = object.__new__(CoPawAgent)
    agent.toolkit = toolkit
    agent._mcp_clients = [broken, healthy]  # pylint: disable=protected-access

    await CoPawAgent.register_mcp_clients(agent)

    assert toolkit.calls["broken"] == 1
    assert broken.connect_calls == 1
    assert "broken" not in toolkit.registered
    assert toolkit.registered == ["healthy"]
