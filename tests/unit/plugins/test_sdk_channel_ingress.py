# -*- coding: utf-8 -*-
"""Real HTTP/WS host forwarding into SDK-only child workers."""

import asyncio
import hashlib
import hmac
import json
import shutil
import socket
from pathlib import Path
from urllib.parse import urlsplit

import aiohttp
from fastapi import FastAPI
import pytest
import uvicorn

from qwenpaw.app.channels.ingress import ChannelIngressService, IngressLimits
from qwenpaw.app.routers.channel_callbacks import channel_callbacks_router
from qwenpaw.plugins.channel_ingress import ChannelIngressRoute
from qwenpaw.plugins.channel_workers import ChannelDefinition
from qwenpaw.plugins.compliance import check_plugin
from qwenpaw.plugins.testing import PluginTestHost
from tests.channel_support.sdk import make_channel, workspace_store
from tests.channel_support.process import alive, eventually

KEY = "ingress-contract"
WORKSPACES = ("one", "two")


def definition():
    return ChannelDefinition(
        KEY,
        {"en": "Ingress contract", "zh": "回调接口测试"},
        "driver:Driver",
        {
            "type": "object",
            "properties": {
                "enabled": {"type": "boolean", "default": False},
                "public_origin": {"type": "string"},
                "secret": {"type": "string"},
            },
        },
        ("enabled", "public_origin", "secret"),
        ("channel.generic.v1", "ingress_endpoint"),
        ingress_routes=(
            ChannelIngressRoute("POST", "/echo"),
            ChannelIngressRoute("POST", "/hold"),
            ChannelIngressRoute("WEBSOCKET", "/ws"),
        ),
    )


@pytest.fixture
def ingress_plugin(tmp_path):
    driver = Path(__file__).parents[2] / "channel_support/ingress_driver.py"
    return make_channel(
        tmp_path / "ingress-plugin",
        driver.read_text(),
        definition(),
        capabilities=["channels", "resources", "storage"],
        requirements="aiohttp>=3.9\n",
    )


def test_plugin_identifiers_cannot_escape_or_alias_the_host_namespace():
    from qwenpaw.plugins._channel_ingress import ingress_path

    paths = {
        ingress_path(name, "example")
        for name in ("../victim", "victim", "中文", "plugin/one", "plugin_one")
    }
    assert len(paths) == 5
    for path in paths:
        assert path.startswith("/channel-callbacks/") and path.endswith(
            "/example",
        )
        assert path.count("/") == 3 and ".." not in path
        assert path.isascii() and "%" not in path


@pytest.mark.parametrize(
    "route",
    [
        ChannelIngressRoute("POST", "/../api/config"),
        ChannelIngressRoute("POST", "//elsewhere"),
        ChannelIngressRoute("POST", "/encoded%2fpath"),
        ChannelIngressRoute("POST", "/query?key=value"),
        ChannelIngressRoute("TRACE", "/echo"),
    ],
)
def test_static_ingress_rejects_nonlocal_routes(route):
    from dataclasses import replace

    with pytest.raises(ValueError, match="ingress route"):
        replace(definition(), ingress_routes=(route,))


def signed(url, secret, body=b""):
    return {
        "X-Platform-Signature": hmac.new(
            secret.encode(),
            url.encode() + body,
            hashlib.sha256,
        ).hexdigest(),
    }


async def assert_ws_closed(ws):
    try:
        assert (await ws.receive(timeout=3)).type in {
            aiohttp.WSMsgType.CLOSE,
            aiohttp.WSMsgType.CLOSED,
            aiohttp.WSMsgType.ERROR,
        }
    finally:
        await ws.close()


@pytest.mark.asyncio
async def test_real_ingress_two_workspaces_updates_close_and_lifecycle(
    tmp_path,
    ingress_plugin,
):
    report = check_plugin(ingress_plugin)
    assert report.ok, report.findings
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    root = tmp_path / "host"
    app = FastAPI()
    app.include_router(channel_callbacks_router)
    server = uvicorn.Server(
        uvicorn.Config(app, log_level="error", lifespan="off"),
    )
    serving = asyncio.create_task(server.serve(sockets=[listener]))
    await eventually(lambda: server.started, timeout=5)
    pending = []

    async with PluginTestHost(root, process_channels=(KEY,)) as host:
        ingress = ChannelIngressService(
            host._loader.registry,
            host_port=port,
            limits=IngressLimits(owner_concurrency=2),
        )
        app.state.channel_ingress = ingress

        def storage(workspace):
            return workspace_store(root, KEY, workspace)

        def binding(workspace):
            return json.loads(
                (storage(workspace) / "binding.json").read_text(),
            )

        def bindings():
            assert len(ingress._bindings) == len(WORKSPACES)
            return {workspace: binding(workspace) for workspace in WORKSPACES}

        def replaced(report, previous):
            assert report.ok, report
            assert all(not alive(row["pid"]) for row in previous.values())
            return bindings()

        async def control(text):
            await host.send_channel(
                KEY,
                text,
                workspace_id="one",
                user_id="operator",
                session_id="validation",
            )

        try:
            assert (await host.install(ingress_plugin)).ok
            for workspace in WORKSPACES:
                await host.start_channel(
                    KEY,
                    {"public_origin": origin, "secret": "key-" + workspace},
                    workspace_id=workspace,
                )
            old = bindings()
            assert old["one"]["pid"] != old["two"]["pid"]
            async with aiohttp.ClientSession() as client:

                async def expect_post(url, status, **kwargs):
                    async with client.post(url, **kwargs) as response:
                        assert response.status == status, (
                            url,
                            response.status,
                        )

                for workspace in WORKSPACES:
                    url = old[workspace]["urls"]["echo"]
                    async with client.post(
                        url,
                        data=b"hello",
                        headers=signed(url, "key-" + workspace, b"hello"),
                    ) as response:
                        assert response.status == 200
                        assert await response.json() == {
                            "workspace": workspace,
                            "body": "hello",
                            "original": url,
                        }

                url = old["one"]["urls"]["echo"]
                # Host forwarding is not platform authentication.
                for headers in (
                    {},
                    signed(url, "key-two"),
                    {
                        "X-Qwenpaw-Ingress-Token": "forged",
                        "X-Qwenpaw-Ingress-Original-URL": url,
                    },
                ):
                    await expect_post(url, 403, headers=headers)
                async with client.post(
                    url,
                    headers={
                        **signed(url, "key-one"),
                        "X-Forwarded-Host": "evil.test",
                        "X-Forwarded-Proto": "https",
                    },
                ) as response:
                    assert response.status == 200
                    assert (await response.json())["original"] == url
                await expect_post(
                    url,
                    403,
                    headers={**signed(url, "key-one"), "Host": "evil.test"},
                )
                await expect_post(url.split("?")[0], 400)
                await expect_post(url.replace("/echo?", "/undeclared?"), 503)
                direct = (
                    f'http://127.0.0.1:{old["one"]["port"]}'
                    + urlsplit(url).path
                )
                await expect_post(direct, 403, headers=signed(url, "key-one"))

                oversized = b"x" * (1024 * 1024 + 1)
                await expect_post(
                    url,
                    413,
                    data=oversized,
                    headers=signed(url, "key-one", oversized),
                )
                ws_url = old["one"]["urls"]["ws"]
                ws = await client.ws_connect(
                    ws_url,
                    headers=signed(ws_url, "key-one"),
                )
                await ws.send_str("ping")
                assert (await ws.receive(timeout=3)).data == "one:ping"
                hold_url = old["one"]["urls"]["hold"]
                holding = asyncio.create_task(
                    client.post(hold_url, headers=signed(hold_url, "key-one")),
                )
                pending.append(holding)
                await eventually(
                    (storage("one") / "http-open.json").exists,
                    timeout=5,
                )
                # A saturated owner must not restrict the other workspace.
                await expect_post(url, 503, headers=signed(url, "key-one"))
                other_url = old["two"]["urls"]["echo"]
                await expect_post(
                    other_url,
                    200,
                    headers=signed(other_url, "key-two"),
                )
                await control("pause")
                await assert_ws_closed(ws)
                await asyncio.wait_for(
                    asyncio.gather(holding, return_exceptions=True),
                    5,
                )
                await eventually(
                    (storage("one") / "http-closed.json").exists,
                    timeout=5,
                )
                await eventually(
                    (storage("one") / "ws-closed.json").exists,
                    timeout=5,
                )
                await expect_post(url, 503, headers=signed(url, "key-one"))
                await control("resume")
                assert (storage("one") / "old-binding-invalid.json").exists()
                url = binding("one")["urls"]["echo"]
                await expect_post(url, 200, headers=signed(url, "key-one"))
                ws_url = binding("one")["urls"]["ws"]
                closing_ws = await client.ws_connect(
                    ws_url,
                    headers=signed(ws_url, "key-one"),
                )
                await control("close")
                await assert_ws_closed(closing_ws)
                assert alive(
                    old["one"]["pid"],
                ), "Route withdrawal alone is not listener cleanup"
                await expect_post(url, 503, headers=signed(url, "key-one"))

                current = replaced(
                    await host.reload(KEY, new_source=ingress_plugin),
                    old,
                )
                # Old selectors must not address a new generation.
                await expect_post(url, 503, headers=signed(url, "key-one"))
                new_url = current["one"]["urls"]["echo"]
                await expect_post(
                    new_url,
                    200,
                    headers=signed(new_url, "key-one"),
                )
                ws_url = current["two"]["urls"]["ws"]
                disabled_ws = await client.ws_connect(
                    ws_url,
                    headers=signed(ws_url, "key-two"),
                )
                assert (await host.set_enabled(KEY, False)).quiescent
                await assert_ws_closed(disabled_ws)
                assert all(not alive(row["pid"]) for row in current.values())
                assert (await host.set_enabled(KEY, True)).ok
                current = bindings()
                ws_url = current["two"]["urls"]["ws"]
                removed_ws = await client.ws_connect(
                    ws_url,
                    headers=signed(ws_url, "key-two"),
                )
                removed = await host.uninstall(KEY)
                await assert_ws_closed(removed_ws)
                assert removed.clean and removed.quiescent, removed
                assert all(not alive(row["pid"]) for row in current.values())
                assert not ingress._bindings
                await eventually(
                    lambda: (KEY, KEY) not in ingress.routes,
                    timeout=3,
                )
        finally:
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            await ingress.aclose()
            server.should_exit = True
            await asyncio.wait_for(serving, 5)
            listener.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "config,reason",
    [
        (
            {"host": "0.0.0.0", "port": 1234, "origin": None},
            "HOST_INGRESS_LOOPBACK_REQUIRED",
        ),
        (
            {"host": "127.0.0.1", "port": 70000, "origin": None},
            "ENDPOINT_PORT_INVALID",
        ),
        (
            {
                "host": "127.0.0.1",
                "port": 1234,
                "origin": "https://user:password@example.test",
            },
            "HOST_INGRESS_PUBLIC_ORIGIN_INVALID",
        ),
    ],
)
async def test_failed_endpoint_registration_cleans_actual_worker(
    tmp_path,
    config,
    reason,
    ingress_plugin,
):
    from qwenpaw.plugins import SDKError

    source = tmp_path / "source"
    shutil.copytree(ingress_plugin, source)
    (source / "requirements.txt").write_text("")
    (source / "driver.py").write_text(
        """
import os
from qwenpaw.plugins.channel_workers import ChannelDriver, ChannelSendResult
from qwenpaw.plugins.channel_ingress import ChannelIngressSpec


class Driver(ChannelDriver):
    async def start(self, ch):
        await ch.storage.awrite_json("pid.json", os.getpid())
        try:
            await ch.ingress.register(
                ChannelIngressSpec(
                    ch.config["host"],
                    ch.config["port"],
                    public_base_url=ch.config["origin"],
                )
            )
        except Exception as exc:
            await ch.storage.awrite_json("error.json", str(exc))
            raise

    async def send(self, ch, response):
        return ChannelSendResult()
""",
    )
    root = tmp_path / "host"
    async with PluginTestHost(root, process_channels=(KEY,)) as host:
        ingress = ChannelIngressService(host._loader.registry, host_port=19090)
        try:
            assert (await host.install(source)).ok
            with pytest.raises(SDKError):
                await host.start_channel(KEY, config, workspace_id="failure")
            storage = workspace_store(root, KEY, "failure")
            assert reason in json.loads((storage / "error.json").read_text())
            assert not alive(json.loads((storage / "pid.json").read_text()))
            assert not ingress._bindings
            removed = await host.uninstall(KEY)
            assert removed.clean and removed.quiescent
        finally:
            await ingress.aclose()
