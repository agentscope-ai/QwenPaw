# -*- coding: utf-8 -*-
"""iLink login, native messages, media and polling lifecycle."""
import asyncio
import base64
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio

from qwenpaw.channel_protocol.models import SendParams
from tests.channel_support.driver import bind, module

pytestmark = pytest.mark.asyncio


def message(number, *, group="", text="hello"):
    return {
        "message_type": 1,
        "from_user_id": "user-A",
        "to_user_id": "bot",
        "context_token": f"context-{number}",
        "msg_id": str(number),
        "group_id": group,
        "item_list": [{"type": 1, "text_item": {"text": text}}],
    }


@pytest_asyncio.fixture
async def runtime(tmp_path, monkeypatch):
    requests, clients = [], []
    real_client = httpx.AsyncClient
    polling, qr_release = asyncio.Event(), asyncio.Event()
    upload = {}

    async def transport(request):
        requests.append(request)
        path = request.url.path
        if path.endswith("/getupdates"):
            await polling.wait()
            return httpx.Response(200, json={"ret": 0, "msgs": []})
        if path.endswith("/get_bot_qrcode"):
            value = {
                "qrcode": "scan-code",
                "qrcode_img_content": "https://login.test/scan",
            }
        elif path.endswith("/get_qrcode_status"):
            await qr_release.wait()
            value = {
                "status": "confirmed",
                "bot_token": "fresh-token",
                "baseurl": "https://assigned.test",
            }
        elif path.endswith("/getuploadurl"):
            upload.update(json.loads(request.content))
            value = {"upload_full_url": "https://cdn.test/upload"}
        elif path == "/upload":
            return httpx.Response(
                200,
                headers={"x-encrypted-param": "uploaded-image"},
            )
        elif path == "/image":
            return httpx.Response(200, content=b"image-download")
        elif path.endswith("/getconfig"):
            value = {"typing_ticket": "ticket"}
        else:
            assert path.endswith(("/sendmessage", "/sendtyping")), path
            value = {"ret": 0}
        return httpx.Response(200, json=value)

    def external_client(**kwargs):
        client = real_client(
            **kwargs,
            transport=httpx.MockTransport(transport),
            trust_env=False,
        )
        clients.append(client)
        return client

    monkeypatch.setattr(
        module("wechat", "client").httpx,
        "AsyncClient",
        external_client,
    )
    drivers = []

    async def start(*, token="existing-token"):
        driver = module("wechat").WeChatDriver()
        peer, identity = bind("wechat", driver, tmp_path)
        drivers.append(driver)
        await driver.start(
            {
                "bot_token": token,
                "base_url": "https://ilink.test",
                "bot_token_file": str(tmp_path / "token"),
                "workspace_dir": str(tmp_path),
            },
        )
        return SimpleNamespace(
            driver=driver,
            peer=peer,
            identity=identity.to_mapping(),
        )

    yield SimpleNamespace(
        start=start,
        requests=requests,
        qr_release=qr_release,
        upload=upload,
    )
    qr_release.set()
    for driver in drivers:
        await driver.stop()
    assert all(client.is_closed for client in clients)


def sent(runtime):
    return [
        json.loads(r.content)["msg"]
        for r in runtime.requests
        if r.url.path.endswith("/sendmessage")
    ]


async def send(rt, handle, parts):
    return await rt.peer.methods["channel.send"](
        SendParams.from_mapping(
            {
                **rt.identity,
                "to_handle": handle,
                "delivery_id": "reply",
                "operation": "message.create",
                "content_parts": parts,
            },
        ),
        None,
    )


async def test_existing_login_connects_without_qr(runtime):
    rt = await runtime.start()
    assert rt.driver._connected
    assert rt.driver._platform._client.bot_token == "existing-token"
    assert not any("qrcode" in r.url.path for r in runtime.requests)


async def test_first_scan_transitions_from_auth_required_to_connected(
    runtime,
    tmp_path,
):
    starting = asyncio.create_task(runtime.start(token=""))
    async with asyncio.timeout(2):
        while not any(
            r.url.path.endswith("/get_qrcode_status") for r in runtime.requests
        ):
            await asyncio.sleep(0.005)
    assert not starting.done()
    runtime.qr_release.set()
    rt = await starting
    assert rt.driver._connected
    assert (tmp_path / "token").read_text() == "fresh-token"
    assert rt.driver._platform._client.base_url == "https://assigned.test"
    notices = [
        params
        for name, params in rt.peer.notifications
        if name == "channel.auth.required"
    ]
    assert notices[0]["scan_url"] == "https://login.test/scan"


@pytest.mark.parametrize(
    "group,session,kind",
    [
        ("", "wechat:user-A", "dm"),
        ("group-A", "wechat:group:group-A", "group"),
    ],
)
async def test_native_dm_and_group_routes_send_with_context(
    runtime,
    group,
    session,
    kind,
):
    rt = await runtime.start()
    await rt.driver._platform._message(message(1, group=group))
    event = rt.peer.batches[0]["events"][0]
    assert event["sender_id"] == event["acl_sender_id"] == "user-A"
    assert event["metadata"]["session_id"] == session
    assert event["conversation"]["type"] == kind
    assert event["content_parts"] == [{"type": "text", "text": "hello"}]
    assert (
        await send(
            rt,
            event["response_handle"],
            [{"type": "text", "text": "answer"}],
        )
    )["state"] == "acknowledged"
    assert sent(runtime)[-1]["to_user_id"] == "user-A"
    assert sent(runtime)[-1]["context_token"] == "context-1"
    assert sent(runtime)[-1]["item_list"] == [
        {"type": 1, "text_item": {"text": "answer"}},
    ]


async def test_outbound_image_encrypts_and_sends_native_media(
    runtime,
    tmp_path,
):
    rt = await runtime.start()
    await rt.driver._platform._message(message(2))
    event = rt.peer.batches[0]["events"][0]
    path = tmp_path / "picture.png"
    raw = b"\x89PNG\r\n\x1a\nimage-body"
    path.write_bytes(raw)
    result = await send(
        rt,
        event["response_handle"],
        [{"type": "image", "image_url": str(path)}],
    )
    assert result["state"] == "acknowledged"
    upload_request = next(
        r for r in runtime.requests if r.url.path == "/upload"
    )
    key = base64.b64encode(bytes.fromhex(runtime.upload["aeskey"])).decode()
    assert (
        module("wechat", "utils").aes_ecb_decrypt(upload_request.content, key)
        == raw
    )
    assert runtime.upload["rawfilemd5"] == hashlib.md5(raw).hexdigest()
    item = sent(runtime)[-1]["item_list"][0]
    assert item["type"] == 2
    assert (
        item["image_item"]["media"]["encrypt_query_param"] == "uploaded-image"
    )


async def test_stop_cancels_poll_and_closes_clients(runtime):
    rt = await runtime.start()
    platform = rt.driver._platform
    poll = platform._poll_task
    await rt.driver.stop()
    assert poll.done()
    assert platform._client is platform._poll_client is None
    assert rt.driver._platform is None and not rt.driver._connected


@pytest.mark.parametrize(
    "entry",
    ["config", "env", "dynamic", "cancel", "stale"],
)
async def test_auth_admission_scans_off_loop_and_releases_claims(
    tmp_path,
    monkeypatch,
    entry,
):
    import threading
    import sys
    from types import SimpleNamespace

    from qwenpaw.app.channels import wechat_auth_custody as custody
    from qwenpaw.app.channels.isolated_proxy import IsolatedChannelProxy
    from qwenpaw.app.channels.manager import ChannelManager
    from qwenpaw.config.config import (
        Config,
        AgentProfileConfig,
        AgentProfileRef,
        save_agent_config,
    )
    from qwenpaw.config.utils import load_config, save_config
    from qwenpaw.plugins.architecture import PluginManifest
    from qwenpaw.plugins.channel_adapter import (
        ChannelRuntimeSettings,
        describe_channel,
    )
    from tests.channel_support.host import Host

    case = await Host.create(tmp_path, monkeypatch)
    root = load_config()
    for name in ("other-one", "other-two"):
        directory = tmp_path / name
        directory.mkdir()
        root.agents.profiles[name] = AgentProfileRef(
            id=name,
            workspace_dir=str(directory),
        )
        save_config(root)
        save_agent_config(name, AgentProfileConfig(id=name, name=name))
    save_config(root)
    managers = []
    entered, release = threading.Event(), threading.Event()
    dynamic = entry in {"dynamic", "cancel", "stale"}
    loop_thread = threading.get_ident()
    scan = custody._read_wechat_auth_evidence
    scans = []
    started = []

    def read(*args):
        scans.append(threading.get_ident())
        entered.set()
        assert release.wait(5), "auth scan blocked the event loop"
        return scan(*args)

    async def start(channel):
        assert channel._wechat_auth_claims
        started.append(channel)

    monkeypatch.setattr(custody, "_read_wechat_auth_evidence", read)
    monkeypatch.setattr(IsolatedChannelProxy, "start", start)
    source = Path(__file__).resolve().parents[3] / "plugins/channel/wechat"
    description = describe_channel(
        source,
        PluginManifest.from_dict(
            json.loads((source / "plugin.json").read_text()),
        ),
    )
    case.registry.register_channel_descriptor(
        "wechat",
        description,
        runtime_settings=ChannelRuntimeSettings(
            python_executable=sys.executable,
            support_root=source.parents[2] / "src",
            qwenpaw_version="test",
            selected_channels=frozenset({"wechat"}),
        ),
    )

    async def process(request):
        if False:
            yield request

    async def build(name):
        directory = tmp_path / name
        directory.mkdir()
        values = {
            "enabled": True,
            "bot_token": "shared-account",
            "bot_token_file": str(directory / "token"),
        }
        config = Config.model_validate({"channels": {"wechat": values}})
        if entry == "env":
            monkeypatch.setenv("WECHAT_CHANNEL_ENABLED", "1")
            monkeypatch.setenv("WECHAT_BOT_TOKEN", values["bot_token"])
            monkeypatch.setenv(
                "WECHAT_BOT_TOKEN_FILE",
                values["bot_token_file"],
            )
            manager = ChannelManager.from_env(process, workspace_dir=directory)
        else:
            manager = ChannelManager.from_config(
                process,
                config,
                workspace_dir=directory,
                defer_process_channels=dynamic,
            )
        manager.set_workspace(
            SimpleNamespace(workspace_dir=directory, agent_id=name),
        )
        managers.append(manager)
        return manager, config

    async def launch(manager, config):
        await manager.start_all()
        if dynamic:
            return await manager.start_one("wechat", config)
        await asyncio.gather(*tuple(manager._start_tasks))

    try:
        baseline = len(case.registry.runtime_owners.leases())
        first, config = await build("first")
        pending = asyncio.create_task(launch(first, config))
        async with asyncio.timeout(5):
            while not entered.is_set() and not pending.done():
                await asyncio.sleep(0.001)
        if pending.done():
            await pending
        assert entered.is_set()
        assert not pending.done()
        if entry in {"cancel", "stale"}:
            if entry == "cancel":
                pending.cancel()
                await asyncio.sleep(0)
                assert not pending.done()
            else:
                config.channels.wechat.bot_token = "changed-account"
            release.set()
            expected = (
                pytest.raises(asyncio.CancelledError)
                if entry == "cancel"
                else pytest.raises(
                    RuntimeError,
                    match="CHANNEL_PREPARATION_STALE",
                )
            )
            with expected:
                await pending
            assert not started and first._find_channel("wechat") is None
            assert len(case.registry.runtime_owners.leases()) == baseline
            return
        if dynamic:
            second, second_config = await build("second")
            competing = asyncio.create_task(launch(second, second_config))
            async with asyncio.timeout(5):
                while len(scans) < 2 and not competing.done():
                    await asyncio.sleep(0.001)
            assert len(scans) >= 2
            release.set()
            results = await asyncio.gather(
                pending,
                competing,
                return_exceptions=True,
            )
            failures = [r for r in results if isinstance(r, BaseException)]
            assert len(failures) == 1
            assert "ACCOUNT_IN_USE" in str(failures[0])
        else:
            release.set()
            await pending
            second, second_config = await build("second")
            await launch(second, second_config)
        assert scans and loop_thread not in scans
        claims = started[0]._wechat_auth_claims
        assert claims
        assert len(started) == 1
        assert all(
            claim in case.registry.runtime_owners.leases()
            and case.registry.runtime_owners.resource(claim).owner
            == started[0]._runtime_lease
            for claim in claims
        )
        if dynamic:
            owner = next(m for m in managers if started[0] in m.channels)
            with pytest.raises(RuntimeError, match="CHANNEL_ALREADY_OWNED"):
                await owner.replace_channel(started[0])
            assert owner._find_channel("wechat") is started[0]
            assert all(
                claim in case.registry.runtime_owners.leases()
                for claim in claims
            )
        for manager in managers:
            await manager.stop_all()
        assert not any(
            lease.key.kind == "wechat_auth"
            for lease in case.registry.runtime_owners.leases()
        )
    finally:
        release.set()
        for manager in managers:
            await manager.stop_all()
        await case.close()
    assert len(case.registry.runtime_owners.leases()) == baseline
