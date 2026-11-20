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
            for workspace in ("one", "two"):
                await host.start_channel(
                    KEY,
                    {"public_origin": origin, "secret": "key-" + workspace},
                    workspace_id=workspace,
                )
            old = {
                workspace: binding(workspace) for workspace in ("one", "two")
            }
            assert old["one"]["pid"] != old["two"]["pid"]
            async with aiohttp.ClientSession() as client:
                for workspace in ("one", "two"):
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
                    async with client.post(url, headers=headers) as response:
                        assert response.status == 403
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
                async with client.post(
                    url,
                    headers={**signed(url, "key-one"), "Host": "evil.test"},
                ) as response:
                    assert response.status == 403
                async with client.post(url.split("?")[0]) as response:
                    assert response.status == 400
                async with client.post(
                    url.replace("/echo?", "/undeclared?"),
                ) as response:
                    assert response.status == 503
                direct = (
                    f'http://127.0.0.1:{old["one"]["port"]}'
                    + urlsplit(url).path
                )
                async with client.post(
                    direct,
                    headers=signed(url, "key-one"),
                ) as response:
                    assert response.status == 403

                oversized = b"x" * (1024 * 1024 + 1)
                async with client.post(
                    url,
                    data=oversized,
                    headers=signed(url, "key-one", oversized),
                ) as response:
                    assert response.status == 413
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
                async with client.post(
                    url,
                    headers=signed(url, "key-one"),
                ) as response:
                    assert (
                        response.status == 503
                    ), "Concurrency limit belongs to the exact owner"
                other_url = old["two"]["urls"]["echo"]
                async with client.post(
                    other_url,
                    headers=signed(other_url, "key-two"),
                ) as response:
                    assert response.status == 200
                await control("pause")
                assert (await ws.receive(timeout=3)).type in {
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.ERROR,
                }
                await ws.close()
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
                async with client.post(
                    url,
                    headers=signed(url, "key-one"),
                ) as response:
                    assert response.status == 503
                await control("resume")
                assert (storage("one") / "old-binding-invalid.json").exists()
                url = binding("one")["urls"]["echo"]
                async with client.post(
                    url,
                    headers=signed(url, "key-one"),
                ) as response:
                    assert response.status == 200
                ws_url = binding("one")["urls"]["ws"]
                closing_ws = await client.ws_connect(
                    ws_url,
                    headers=signed(ws_url, "key-one"),
                )
                await control("close")
                assert (await closing_ws.receive(timeout=3)).type in {
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.ERROR,
                }
                await closing_ws.close()
                assert alive(
                    old["one"]["pid"],
                ), "Route withdrawal alone is not listener cleanup"
                async with client.post(
                    url,
                    headers=signed(url, "key-one"),
                ) as response:
                    assert response.status == 503

                reloaded = await host.reload(KEY, new_source=ingress_plugin)
                assert reloaded.ok, reloaded
                assert all(not alive(row["pid"]) for row in old.values())
                current = {
                    workspace: binding(workspace)
                    for workspace in ("one", "two")
                }
                async with client.post(
                    url,
                    headers=signed(url, "key-one"),
                ) as response:
                    assert (
                        response.status == 503
                    ), "Old selectors must not address a new generation"
                new_url = current["one"]["urls"]["echo"]
                async with client.post(
                    new_url,
                    headers=signed(new_url, "key-one"),
                ) as response:
                    assert response.status == 200
                updated = await host.update_config(KEY, {"validation": True})
                assert updated.ok, updated
                assert all(not alive(row["pid"]) for row in current.values())
                current = {
                    workspace: binding(workspace)
                    for workspace in ("one", "two")
                }
                upgrade = tmp_path / "upgrade"
                shutil.copytree(ingress_plugin, upgrade)
                manifest = json.loads((upgrade / "plugin.json").read_text())
                manifest["version"] = "0.1.1"
                (upgrade / "plugin.json").write_text(json.dumps(manifest))
                upgraded = await host.install(upgrade, replace=True)
                assert upgraded.ok, upgraded
                assert all(not alive(row["pid"]) for row in current.values())
                current = {
                    workspace: binding(workspace)
                    for workspace in ("one", "two")
                }
                assert (
                    len(ingress._bindings) == 2
                ), "Lifecycle changes must not duplicate route owners"
                new_url = current["two"]["urls"]["echo"]
                async with client.post(
                    new_url,
                    headers=signed(new_url, "key-two"),
                ) as response:
                    assert response.status == 200
                ws_url = current["two"]["urls"]["ws"]
                disabled_ws = await client.ws_connect(
                    ws_url,
                    headers=signed(ws_url, "key-two"),
                )
                assert (await host.set_enabled(KEY, False)).quiescent
                assert (await disabled_ws.receive(timeout=3)).type in {
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.ERROR,
                }
                await disabled_ws.close()
                assert all(not alive(row["pid"]) for row in current.values())
                assert (await host.set_enabled(KEY, True)).ok
                current = {
                    workspace: binding(workspace)
                    for workspace in ("one", "two")
                }
                ws_url = current["two"]["urls"]["ws"]
                removed_ws = await client.ws_connect(
                    ws_url,
                    headers=signed(ws_url, "key-two"),
                )
                removed = await host.uninstall(KEY)
                assert (await removed_ws.receive(timeout=3)).type in {
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.ERROR,
                }
                await removed_ws.close()
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
