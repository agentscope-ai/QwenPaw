"""Trusted budget validation and preserved transport/control contracts."""

import asyncio
import hashlib
import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest_plugins = ["extension_process_suite"]


def runtime_settings(**kwargs):
    from qwenpaw.plugins.channel_adapter import ChannelRuntimeSettings

    return ChannelRuntimeSettings(
        python_executable="python",
        support_root=Path("."),
        qwenpaw_version="test",
        **kwargs,
    )


@pytest.mark.parametrize(
    "invalid", [True, False, 0, -1, float("inf"), float("nan"), "3", None]
)
def test_nonpositive_nonfinite_and_non_numeric_budgets_rejected(invalid):
    from pydantic import ValidationError
    from qwenpaw.config.config import Config

    with pytest.raises(ValueError):
        runtime_settings(send_timeout=invalid)
    with pytest.raises(ValueError):
        runtime_settings(send_timeouts={"telegram": invalid})
    with pytest.raises(ValidationError):
        Config.model_validate({"channel_send_timeouts": {"telegram": invalid}})


def test_overrides_survive_config_and_default_resolver(tmp_path, monkeypatch):
    from qwenpaw.config.config import Config
    from qwenpaw.config.utils import save_config
    from qwenpaw.plugins.channel_bootstrap import (
        resolve_default_channel_runtime,
    )

    mapping = {"telegram": 0.35, "slack": 23, "sample_chat": 3600}
    config = Config.model_validate({"channel_send_timeouts": mapping})
    path = tmp_path / "host" / "config.json"
    monkeypatch.setattr("qwenpaw.config.utils.get_config_path", lambda: path)
    save_config(config)
    settings = resolve_default_channel_runtime()
    assert settings.send_timeouts == mapping
    for key, value in mapping.items():
        assert settings.send_timeout_for(key) == value
    assert settings.send_timeout_for("discord") == 120
    assert runtime_settings(send_timeout=18).send_timeout_for("discord") == 18


def test_old_context_and_launch_fixtures_receive_safe_default():
    from qwenpaw.app.channels.process_supervisor import LaunchSpec
    from qwenpaw.channel_protocol.shared_worker import DriverContext

    assert DriverContext(None, None).send_timeout == 120
    assert LaunchSpec.__dataclass_fields__["send_timeout"].default == 120


@pytest.mark.asyncio
async def test_outbound_rpc_reserves_receipt_margin_without_changing_controls(
    monkeypatch,
):
    from qwenpaw.app.channels.process_supervisor import ChannelProcess
    from qwenpaw.app.channels.isolated_proxy import IsolatedChannelProxy
    from qwenpaw.plugins.execution.process import PluginProcess

    observed = []

    async def transport(process, method, params=None, *, timeout=5.0):
        observed.append((method, timeout))
        return {}

    assert (
        inspect.signature(PluginProcess.call).parameters["timeout"].default
        == 5
    )
    monkeypatch.setattr(PluginProcess, "call", transport)
    process = ChannelProcess()
    process._spec = SimpleNamespace(send_timeout=17)
    for method in (
        "channel.send",
        "channel.reaction",
        "channel.response.prepare",
        "channel.response.finish",
        "channel.response.open",
    ):
        await process.call(method, {})
        assert observed[-1] == (method, 22)
    for method in ("shared.health", "shared.stop", "channel.describe"):
        await process.call(method, {})
        assert observed[-1] == (method, 5)
    await process.call("channel.send", {}, timeout=0.5)
    assert observed[-1] == ("channel.send", 0.5)

    async def settle_text(_handle):
        pass

    proxy = SimpleNamespace(
        channel_process=process,
        _identity=lambda: SimpleNamespace(to_mapping=lambda: {}),
        _cancel_response_text=settle_text,
        _flush_response_text=settle_text,
    )
    for outcome, timeout in (("completed", 22), ("cancelled", 5)):
        await IsolatedChannelProxy._finish_route(
            proxy,
            {"response_handle": "sample:reply:one"},
            outcome,
        )
        assert observed[-1] == ("channel.response.finish", timeout)


@pytest.mark.asyncio
async def test_nested_native_stages_cannot_reset_total_deadline():
    from qwenpaw.channel_protocol.outbound_budget import (
        await_send,
        remaining_send_timeout,
        retry_delay_fits,
        send_budget,
    )

    cancelled = []

    async def second_stage():
        try:
            await asyncio.sleep(0.2)
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    with send_budget(0.15):
        await await_send(asyncio.sleep(0.1))
        with send_budget(10):
            assert 0 < remaining_send_timeout() < 0.1
            assert not retry_delay_fits(0.1)
            with pytest.raises(TimeoutError):
                await await_send(second_stage())
    assert cancelled == [True]
    assert remaining_send_timeout() is None


@pytest.mark.asyncio
async def test_nonshared_worker_peer_bounds_outbound_but_preserves_control():
    from qwenpaw.channel_protocol.errors import RPC_LIFECYCLE_ERROR, RpcError
    from qwenpaw.channel_protocol.rpc import RpcPeer
    from qwenpaw.channel_protocol.shared_worker import ChannelRuntime

    class Transport:
        def __init__(self, incoming, outgoing):
            self.incoming, self.outgoing = incoming, outgoing

        async def send(self, value):
            await self.outgoing.put(value)

        async def receive(self):
            return await self.incoming.get()

        async def aclose(self):
            pass

    inbound, outbound = asyncio.Queue(), asyncio.Queue()
    runtime = ChannelRuntime()
    runtime._send_timeout = 0.04
    runtime._capabilities = ()
    host = RpcPeer(Transport(inbound, outbound))
    worker = runtime.peer(Transport(outbound, inbound))
    cancelled = []

    async def plain_driver(params, request):
        try:
            await asyncio.sleep(0.12)
        except asyncio.CancelledError:
            cancelled.append(request.method)
            raise
        return {"completed": True}

    identity = {
        "channel_key": "sample_chat",
        "instance_id": "sample",
        "generation": 1,
    }
    operations = {
        "channel.send": {
            "delivery_id": "send",
            "to_handle": "sample:reply:one",
            "operation": "message.create",
            "content_parts": [{"type": "text", "text": "bounded effect"}],
        },
        "channel.reaction": {
            "delivery_id": "reaction",
            "to_handle": "sample:reply:one",
            "target_delivery_id": "send",
            "reaction": "completed",
        },
        "channel.response.open": {"to_handle": "room-A", "meta": {}},
        "channel.response.prepare": {
            "response_handle": "sample:reply:one",
            "delivery_id": "prepare",
        },
        "channel.response.finish": {
            "response_handle": "sample:reply:one",
            "outcome": "completed",
        },
    }
    for method in (*operations, "fixture.control"):
        worker.register_method(method, plain_driver)
    await asyncio.gather(host.start(), worker.start())
    try:
        for method, params in operations.items():
            with pytest.raises(RpcError) as caught:
                await host.call(method, {**identity, **params}, timeout=1)
            assert caught.value.code == RPC_LIFECYCLE_ERROR
            assert (
                caught.value.data["reason_code"] == "PLATFORM_RESULT_UNKNOWN"
            )
            assert caught.value.data["retryable"] is False
        assert cancelled == list(operations)
        assert await host.call("fixture.control", {}, timeout=1) == {
            "completed": True
        }
    finally:
        await asyncio.gather(host.aclose(), worker.aclose())


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["prepare", "reaction"])
async def test_shared_worker_feedback_deadline_retains_unknown_receipt(
    runtime,
    method,
):
    from extension_process_suite import (
        identity,
        inspect as inspect_worker,
        open_route,
    )

    rt = await runtime(runtime_settings={"send_timeout": 0.1})
    handle = await open_route(rt, "room-A")
    target = await rt.process.call(
        "channel.send",
        {
            **identity(rt),
            "delivery_id": "target",
            "to_handle": handle,
            "operation": "message.create",
            "content_parts": [{"type": "text", "text": "target"}],
        },
    )
    assert target["state"] == "acknowledged"
    await rt.process.call("fixture.fault", {"mode": "delay"})
    if method == "prepare":
        rpc_method = "channel.response.prepare"
        params = {"response_handle": handle}
    else:
        rpc_method = "channel.reaction"
        params = {
            "to_handle": handle,
            "target_delivery_id": "target",
            "reaction": "completed",
        }
    params.update(
        identity(rt),
        delivery_id=(
            hashlib.sha256((handle + ":prepare").encode()).hexdigest()
            if method == "prepare"
            else "feedback"
        ),
    )
    result = await rt.process.call(rpc_method, params)
    assert result["state"] == "unknown"
    assert result["reason_code"] == "PLATFORM_RESULT_UNKNOWN"
    assert await rt.process.call(rpc_method, params) == result
    effects = (await inspect_worker(rt))["effects"]
    assert len([row for row in effects if row["operation"] == method]) == 1


@pytest.mark.asyncio
async def test_shared_worker_open_journal_settles_beyond_native_effect_budget(
    runtime,
):
    from extension_process_suite import open_route
    from extension_sample import sample_source

    def delayed_journal_source(*args, **kwargs):
        source = sample_source(*args, **kwargs)
        with (source / "sample_chat" / "driver.py").open("a") as stream:
            stream.write("""
_original_persist_route = Driver._persist_route
async def _delayed_persist_route(self, handle, attrs):
    await asyncio.sleep(0.12)
    return await _original_persist_route(self, handle, attrs)
Driver._persist_route = _delayed_persist_route
""")
        return source

    rt = await runtime(
        source_factory=delayed_journal_source,
        runtime_settings={"send_timeout": 0.04},
    )
    started = asyncio.get_running_loop().time()
    handle = await open_route(rt, "room-A")
    assert asyncio.get_running_loop().time() - started >= 0.12
    assert handle.startswith("sample:reply:")
    await rt.channel.send(
        "room-A", "journal committed", {"response_handle": handle}
    )
