# -*- coding: utf-8 -*-
# pylint: disable=protected-access,unused-argument
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from anyio import ClosedResourceError

import copaw.app.runner.runner as runner_module
from copaw.agents.react_agent import CoPawAgent
from copaw.app.mcp.manager import MCPClientManager
from copaw.app.runner.runner import AgentRunner
from copaw.config.config import MCPClientConfig


class _FakeToolkit:
    def __init__(
        self,
        fail_once_names: set[str] | None = None,
        always_fail_names: set[str] | None = None,
        runtime_fail_names: set[str] | None = None,
    ) -> None:
        self.fail_once_names = fail_once_names or set()
        self.always_fail_names = always_fail_names or set()
        self.runtime_fail_names = runtime_fail_names or set()
        self.calls: dict[str, int] = {}
        self.registered: list[str] = []
        self.cancel_once_names: set[str] = set()

    async def register_mcp_client(
        self,
        client,
        namesake_strategy: str = "skip",  # noqa: ARG002
    ) -> None:
        name = client.name
        self.calls[name] = self.calls.get(name, 0) + 1

        if name in self.always_fail_names:
            raise ClosedResourceError()

        if name in self.runtime_fail_names:
            raise RuntimeError("unexpected toolkit failure")

        if name in self.cancel_once_names and self.calls[name] == 1:
            raise asyncio.CancelledError()

        if name in self.fail_once_names and self.calls[name] == 1:
            raise ClosedResourceError()

        self.registered.append(name)


class _FakeMCPClient:
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


def test_build_client_attaches_rebuild_info(tmp_path: Path) -> None:
    cfg = MCPClientConfig(
        name="mcp_everything",
        enabled=True,
        transport="stdio",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-everything"],
        env={"A": "1"},
        cwd=str(tmp_path),
    )

    client = MCPClientManager._build_client(cfg)
    rebuild_info = getattr(client, "_copaw_rebuild_info", None)

    assert isinstance(rebuild_info, dict)
    assert rebuild_info["transport"] == "stdio"
    assert rebuild_info["command"] == "npx"
    assert rebuild_info["args"] == [
        "-y",
        "@modelcontextprotocol/server-everything",
    ]
    assert rebuild_info["env"] == {"A": "1"}
    assert rebuild_info["cwd"] == str(tmp_path)


@pytest.mark.asyncio
async def test_register_mcp_clients_retries_once_on_closed_resource() -> None:
    toolkit = _FakeToolkit(fail_once_names={"flaky"})
    flaky = _FakeMCPClient(name="flaky", connect_ok=True)
    healthy = _FakeMCPClient(name="healthy", connect_ok=True)

    agent = object.__new__(CoPawAgent)
    agent.toolkit = toolkit
    agent._mcp_clients = [flaky, healthy]

    await CoPawAgent.register_mcp_clients(agent)

    assert toolkit.calls["flaky"] == 2
    assert flaky.connect_calls == 1
    assert toolkit.calls["healthy"] == 1
    assert toolkit.registered == ["flaky", "healthy"]


@pytest.mark.asyncio
async def test_register_mcp_clients_skips_unrecoverable_client() -> None:
    toolkit = _FakeToolkit(always_fail_names={"broken"})
    broken = _FakeMCPClient(name="broken", connect_ok=False)
    healthy = _FakeMCPClient(name="healthy", connect_ok=True)

    agent = object.__new__(CoPawAgent)
    agent.toolkit = toolkit
    agent._mcp_clients = [broken, healthy]

    await CoPawAgent.register_mcp_clients(agent)

    assert toolkit.calls["broken"] == 1
    assert broken.connect_calls == 1
    assert "broken" not in toolkit.registered
    assert toolkit.registered == ["healthy"]


@pytest.mark.asyncio
async def test_register_mcp_clients_handles_cancelled_error() -> None:
    toolkit = _FakeToolkit()
    toolkit.cancel_once_names = {"flaky"}
    flaky = _FakeMCPClient(name="flaky", connect_ok=True)

    agent = object.__new__(CoPawAgent)
    agent.toolkit = toolkit
    agent._mcp_clients = [flaky]

    await CoPawAgent.register_mcp_clients(agent)

    assert toolkit.calls["flaky"] == 2
    assert flaky.connect_calls == 1
    assert toolkit.registered == ["flaky"]


@pytest.mark.asyncio
async def test_register_mcp_clients_reraises_unexpected_error() -> None:
    toolkit = _FakeToolkit(runtime_fail_names={"boom"})
    boom = _FakeMCPClient(name="boom", connect_ok=True)

    agent = object.__new__(CoPawAgent)
    agent.toolkit = toolkit
    agent._mcp_clients = [boom]

    with pytest.raises(RuntimeError, match="unexpected toolkit failure"):
        await CoPawAgent.register_mcp_clients(agent)


@pytest.mark.asyncio
async def test_register_mcp_clients_rebuilds_client_when_reconnect_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    toolkit = _FakeToolkit(always_fail_names={"broken"})
    broken = _FakeMCPClient(name="broken", connect_ok=False)
    rebuilt = _FakeMCPClient(name="rebuilt", connect_ok=True)

    monkeypatch.setattr(
        CoPawAgent,
        "_rebuild_mcp_client",
        staticmethod(lambda client: rebuilt),  # noqa: ARG005
    )

    agent = object.__new__(CoPawAgent)
    agent.toolkit = toolkit
    agent._mcp_clients = [broken]

    await CoPawAgent.register_mcp_clients(agent)

    assert broken.connect_calls == 1
    assert rebuilt.connect_calls == 1
    assert toolkit.registered == ["rebuilt"]
    assert agent._mcp_clients[0] is broken
    assert agent._mcp_clients[0].name == "rebuilt"


@pytest.mark.asyncio
async def test_reconnect_mcp_client_respects_timeout() -> None:
    class _SlowClient:
        async def close(self) -> None:
            return

        async def connect(self) -> None:
            await asyncio.sleep(0.1)

    ok = await CoPawAgent._reconnect_mcp_client(
        _SlowClient(),
        timeout=0.01,
    )
    assert ok is False


@pytest.mark.asyncio
async def test_query_handler_skips_session_save_when_load_not_reached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeAgent:
        def __init__(self, *args, **kwargs) -> None:  # noqa: ARG002
            pass

        async def register_mcp_clients(self) -> None:
            raise ClosedResourceError()

        def set_console_output_enabled(
            self,
            enabled: bool,
        ) -> None:  # noqa: ARG002
            return

    class _FakeSession:
        def __init__(self) -> None:
            self.load_calls = 0
            self.save_calls = 0

        async def load_session_state(self, **kwargs) -> None:  # noqa: ARG002
            self.load_calls += 1

        async def save_session_state(self, **kwargs) -> None:  # noqa: ARG002
            self.save_calls += 1

    class _DummyInputMsg:
        def get_text_content(self) -> str:
            return "你好"

    cfg = SimpleNamespace(
        agents=SimpleNamespace(
            running=SimpleNamespace(max_iters=1, max_input_length=2048),
        ),
    )

    monkeypatch.setattr(runner_module, "CoPawAgent", _FakeAgent)
    monkeypatch.setattr(runner_module, "load_config", lambda: cfg)
    monkeypatch.setattr(
        runner_module,
        "build_env_context",
        lambda **kwargs: "env",
    )
    monkeypatch.setattr(
        runner_module,
        "write_query_error_dump",
        lambda **kwargs: None,
    )

    runner = AgentRunner()
    fake_session = _FakeSession()
    runner.session = fake_session

    request = SimpleNamespace(
        session_id="s1",
        user_id="u1",
        channel="console",
    )

    with pytest.raises(ClosedResourceError):
        async for _ in runner.query_handler(
            [_DummyInputMsg()],
            request=request,
        ):
            pass

    assert fake_session.load_calls == 0
    assert fake_session.save_calls == 0
