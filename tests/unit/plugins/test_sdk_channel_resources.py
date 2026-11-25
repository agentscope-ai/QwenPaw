# -*- coding: utf-8 -*-
"""Declarative identity claims through real installation and worker cleanup."""

import asyncio
import json

import pytest

from qwenpaw.plugins import SDKError
from qwenpaw.plugins.channel_workers import (
    ChannelDefinition,
    ChannelExclusiveResource,
)
from qwenpaw.plugins.channel_config import channel_resource_claims
from qwenpaw.plugins.testing import PluginTestHost
from tests.channel_support.sdk import make_channel
from tests.channel_support.process import alive, eventually


def definition(key="sdk-owner", resources=None):
    return ChannelDefinition(
        key,
        {"en": "Resource owner", "zh": "资源占用验证"},
        "driver:Driver",
        {
            "type": "object",
            "properties": {
                "server": {"type": "string"},
                "account": {"type": "string"},
                "port": {"type": "integer"},
                "marker": {"type": "string"},
            },
        },
        ("server", "account", "port", "marker"),
        ("channel.generic.v1",),
        exclusive_resources=(
            (
                ChannelExclusiveResource(
                    "example.account",
                    ("server", "account"),
                ),
            )
            if resources is None
            else resources
        ),
    )


@pytest.mark.parametrize(
    "resources",
    [
        (ChannelExclusiveResource("", ("account",)),),
        (ChannelExclusiveResource("bad name", ("account",)),),
        (ChannelExclusiveResource("account", ()),),
        (ChannelExclusiveResource("account", ("missing",)),),
        (ChannelExclusiveResource("account", ("account",), ()),),
        (ChannelExclusiveResource("account", ("account",), ("run", "run")),),
        (ChannelExclusiveResource("account", ("account",), ("all",)),),
        (ChannelExclusiveResource("account", ("account", "account")),),
        (
            ChannelExclusiveResource("account", ("account",)),
            ChannelExclusiveResource("account", ("server",)),
        ),
    ],
)
def test_invalid_resource_declarations(resources):
    with pytest.raises(ValueError, match="exclusive resource"):
        definition(resources=resources)


def test_composite_identity_is_opaque_and_roundtrips(tmp_path):
    declared = definition()
    path = tmp_path / "channel.json"
    path.write_text(json.dumps(declared.to_dict()))
    assert ChannelDefinition.load(path) == declared
    schema = declared.config_schema
    claim = channel_resource_claims(
        schema,
        {"server": "a", "account": "secret"},
    )
    assert "secret" not in repr(claim)
    assert claim != channel_resource_claims(
        schema,
        {"server": "b", "account": "secret"},
    )
    assert claim != channel_resource_claims(
        schema,
        {"server": "a", "account": "other"},
    )
    with pytest.raises(ValueError, match="CHANNEL_RESOURCE_IDENTITY_MISSING"):
        channel_resource_claims(schema, {"server": "a", "account": " "})
    assert channel_resource_claims(schema, {}, "qrcode.fetch") == ()


SOURCE = """
import os
import asyncio
import threading
import time
from pathlib import Path
from qwenpaw.plugins.channel_workers import ChannelDriver, ChannelDeliveryError
from qwenpaw.plugins.channel_management import ChannelQRCode

class Driver(ChannelDriver):
    async def start(self, ch):
        marker = Path(ch.config["marker"])
        marker.write_text(str(os.getpid()))
        stop = threading.Event()
        def run():
            stop.wait()
            marker.with_suffix(".waiting").touch()
            while not marker.with_suffix(".release").exists():
                time.sleep(0.01)
            marker.with_suffix(".exited").touch()
        ch.resources.thread(run, stop=stop)
        await ch.report_status("connected")

    async def send(self, ch, response):
        raise ChannelDeliveryError("VALIDATION_HAS_NO_TRANSPORT", side_effect_possible=False)

    @staticmethod
    async def manage(request):
        marker = Path(request.config["marker"])
        marker.write_text(str(os.getpid()))
        async def cleanup():
            marker.with_suffix(".waiting").touch()
            while not marker.with_suffix(".release").exists():
                await asyncio.sleep(0.01)
            marker.with_suffix(".exited").touch()
        request.resources.defer(cleanup)
        return ChannelQRCode("https://example.test/scan", "opaque")
"""


@pytest.mark.asyncio
async def test_actual_host_retains_claim_until_worker_thread_exits(tmp_path):
    keys = ("sdk-owner", "sdk-other-owner")
    sources = []
    for key in keys:
        source = tmp_path / key
        make_channel(
            source,
            SOURCE,
            definition(key),
            capabilities=["channels", "resources"],
        )
        sources.append(source)

    markers = [tmp_path / name for name in ("one.pid", "two.pid", "three.pid")]
    stopping = None
    async with PluginTestHost(
        tmp_path / "host",
        process_channels=keys,
    ) as host:
        try:
            for source in sources:
                result = await host.install(source)
                assert result.ok, result

            def settings(marker, server="server-a"):
                return {
                    "server": server,
                    "account": "shared-secret",
                    "marker": str(marker),
                }

            await host.start_channel(
                keys[0],
                settings(markers[0]),
                workspace_id="one",
            )
            pid = int(markers[0].read_text())
            assert alive(pid)
            # A different plugin and workspace cannot take the same resource.
            with pytest.raises(
                SDKError,
                match="RUNTIME_IDENTITY_ALREADY_OWNED",
            ) as error:
                await host.start_channel(
                    keys[1],
                    settings(markers[1]),
                    workspace_id="two",
                )
            assert "shared-secret" not in str(error.value)
            assert not markers[
                1
            ].exists(), "Conflicts must fail before driver startup"
            # Same account name on a different server is not a collision.
            await host.start_channel(
                keys[1],
                settings(markers[2], "server-b"),
                workspace_id="three",
            )
            other_pid = int(markers[2].read_text())
            assert alive(other_pid)
            stopping = asyncio.create_task(
                host.stop_channel(keys[0], workspace_id="one"),
            )
            await eventually(
                lambda: markers[0].with_suffix(".waiting").exists(),
                timeout=5,
            )
            assert alive(pid) and not stopping.done()
            with pytest.raises(
                SDKError,
                match="RUNTIME_IDENTITY_ALREADY_OWNED",
            ):
                await host.start_channel(
                    keys[1],
                    settings(markers[1]),
                    workspace_id="two",
                )
            assert not markers[1].exists()
            markers[0].with_suffix(".release").touch()
            await stopping
            assert markers[0].with_suffix(".exited").exists()
            assert not alive(pid)
            await host.start_channel(
                keys[1],
                settings(markers[1]),
                workspace_id="two",
            )
            new_pid = int(markers[1].read_text())
            assert alive(new_pid)
            for marker in markers:
                marker.with_suffix(".release").touch()
            result = await host.uninstall(keys[1])
            assert result.clean and result.quiescent, result
            assert not alive(new_pid) and not alive(other_pid)
        finally:
            for marker in markers:
                marker.with_suffix(".release").touch()
            if stopping is not None:
                await stopping


@pytest.mark.asyncio
async def test_management_claim_retained_during_cancelled_cleanup(tmp_path):
    from dataclasses import replace
    from qwenpaw.app.channels.management import (
        ChannelManagementService,
        ManagementError,
        ManagementCancelled,
    )

    key = "sdk-owner"
    source = tmp_path / "source"
    declared = replace(
        definition(
            resources=(
                ChannelExclusiveResource(
                    "example.account",
                    ("server", "account"),
                    ("run", "qrcode.fetch"),
                ),
            ),
        ),
        capabilities=("channel.generic.v1", "channel.management.qrcode.v1"),
    )
    make_channel(
        source,
        SOURCE,
        declared,
        capabilities=["channels", "resources"],
    )
    first, second = tmp_path / "first.pid", tmp_path / "second.pid"
    task = None
    async with PluginTestHost(
        tmp_path / "host",
        process_channels=(key,),
    ) as host:
        service = ChannelManagementService(host._loader)
        try:
            assert (await host.install(source)).ok

            def parameters(marker):
                return {
                    "config": {
                        "server": "server-a",
                        "account": "shared-secret",
                        "marker": str(marker),
                    },
                }

            task = asyncio.create_task(
                service.execute(
                    "one",
                    key,
                    "qrcode.fetch",
                    parameters(first),
                    timeout=10,
                ),
            )
            await eventually(first.exists, timeout=5)
            pid = int(first.read_text())
            assert alive(pid)
            with pytest.raises(ManagementError, match="MANAGEMENT_BUSY"):
                await service.execute(
                    "two",
                    key,
                    "qrcode.fetch",
                    parameters(second),
                    timeout=10,
                )
            assert not second.exists()
            with pytest.raises(
                SDKError,
                match="RUNTIME_IDENTITY_ALREADY_OWNED",
            ):
                await host.start_channel(
                    key,
                    parameters(second)["config"],
                    workspace_id="two",
                )
            await eventually(first.with_suffix(".waiting").exists, timeout=5)
            assert alive(pid) and not task.done()
            with pytest.raises(ManagementError, match="MANAGEMENT_BUSY"):
                await service.execute(
                    "two",
                    key,
                    "qrcode.fetch",
                    parameters(second),
                    timeout=10,
                )
            process = next(iter(service._work.values())).process
            task.cancel()
            with pytest.raises(ManagementCancelled):
                await task
            assert not alive(pid)
            assert (
                process.last_cleanup.exited
                and not process.last_cleanup.residual
            )
            second.with_suffix(".release").touch()
            result = await service.execute(
                "two",
                key,
                "qrcode.fetch",
                parameters(second),
                timeout=10,
            )
            assert result.outcome == "ok"
            assert second.with_suffix(".exited").exists()
            assert not alive(int(second.read_text()))
        finally:
            first.with_suffix(".release").touch()
            second.with_suffix(".release").touch()
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await service.aclose()
