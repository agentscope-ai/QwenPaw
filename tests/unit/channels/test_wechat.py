# -*- coding: utf-8 -*-
"""iLink login, native messages, media and polling lifecycle."""
import asyncio
import base64
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from qwenpaw.app.channels import qrcode_sessions
from qwenpaw.app.channels.isolated_proxy import IsolatedChannelProxy
from qwenpaw.app.channels.management import (
    ChannelManagementService,
    ManagementError,
)
from qwenpaw.app.channels.manager import ChannelManager
from qwenpaw.app.channels.wechat_auth_custody import reserve_wechat_auth
from qwenpaw.app.routers import config as config_router
from qwenpaw.channel_protocol.models import SendParams
from qwenpaw.config.config import (
    AgentProfileConfig,
    AgentProfileRef,
    load_agent_config,
    save_agent_config,
)
from qwenpaw.config.utils import load_config, save_config
from qwenpaw.plugins.architecture import PluginManifest, PluginRecord
from qwenpaw.plugins.channel_adapter import ChannelRuntimeSettings
from qwenpaw.plugins.execution_backend import BackendBinding
from qwenpaw.plugins.ownership import RuntimeKey, RuntimeStopReceipt
from tests.channel_support.driver import bind, module
from tests.channel_support.host import Host

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

    async def start(*, token="existing-token", token_file="", workspace=None):
        driver = module("wechat").WeChatDriver()
        workspace = workspace or tmp_path
        peer, identity = bind("wechat", driver, workspace)
        drivers.append(driver)
        await driver.start(
            {
                "bot_token": token,
                "base_url": "https://ilink.test",
                "bot_token_file": str(token_file),
                "workspace_dir": str(workspace),
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


@pytest.mark.parametrize("shared_file", [False, True])
async def test_context_files_are_workspace_local(
    runtime,
    tmp_path,
    shared_file,
):
    token_file = tmp_path / f"shared-token"
    if shared_file:
        token_file.write_text(f"file-token", encoding=f"utf-8")
    for number in (1, 2):
        workspace = tmp_path / f"agent-{number}"
        configured_token = f"token-{number}"
        if shared_file and number == 2:
            configured_token = f""
        rt = await runtime.start(
            token=configured_token,
            token_file=token_file if shared_file else f"",
            workspace=workspace,
        )
        platform = rt.driver._platform
        assert platform._client.bot_token == (
            configured_token or f"file-token"
        )
        assert platform.context_token(f"user-A") == f""
        await platform._message(message(number))
        state_dir = workspace / f"wechat"
        context_file = state_dir / f"wechat_context_tokens.json"
        assert json.loads(context_file.read_text(encoding=f"utf-8")) == {
            f"user-A": f"context-{number}",
        }
        assert not (state_dir / f"wechat_bot_token").exists()
    if shared_file:
        assert token_file.read_text(encoding=f"utf-8") == f"file-token"


async def test_first_scan_transitions_from_auth_required_to_connected(
    runtime,
    tmp_path,
    monkeypatch,
):
    old_token = tmp_path / f"old-root" / f"wechat_bot_token"
    old_token.parent.mkdir()
    old_token.write_text(f"old-token", encoding=f"utf-8")
    monkeypatch.setattr(
        module(f"wechat", f"platform"),
        f"WORKING_DIR",
        old_token.parent,
        raising=False,
    )
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
    token_file = tmp_path / "wechat" / "wechat_bot_token"
    assert token_file.read_text() == "fresh-token"
    assert old_token.read_text(encoding=f"utf-8") == f"old-token"
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


@pytest.fixture
async def wechat_host(tmp_path, monkeypatch):
    host = await Host.create(tmp_path, monkeypatch)
    source = Path(__file__).resolve().parents[3] / f"plugins/channel/wechat"
    manifest = PluginManifest.from_dict(
        json.loads((source / f"plugin.json").read_text(encoding=f"utf-8")),
    )
    binding = host.loader._channel_backend.describe(source, manifest)
    host.loader._loaded_plugins[f"wechat"] = PluginRecord(
        manifest=manifest,
        source_path=source,
        enabled=True,
        backend_binding=BackendBinding(host.loader._channel_backend, binding),
    )
    host.registry.register_channel_descriptor(
        f"wechat",
        binding.payload,
        runtime_settings=ChannelRuntimeSettings(
            python_executable=sys.executable,
            support_root=source.parents[2] / f"src",
            qwenpaw_version=f"test",
            selected_channels=frozenset({f"wechat"}),
        ),
    )
    try:
        yield host
    finally:
        await host.close()


@pytest.mark.parametrize(
    "entry",
    ["config", "env", "dynamic", "cancel", "start-failure"],
)
async def test_auth_admission_only_checks_held_credentials(
    wechat_host,
    tmp_path,
    monkeypatch,
    entry,
):
    root = load_config()
    directory = tmp_path / f"default"
    idle = tmp_path / f"idle"
    for name, workspace in ((f"default", directory), (f"idle", idle)):
        workspace.mkdir()
        root.agents.profiles[name] = AgentProfileRef(
            id=name,
            workspace_dir=str(workspace),
        )
    save_config(root)
    shared_path = str(tmp_path / f"shared-token")
    values = {
        f"enabled": True,
        f"bot_token": f"shared-account",
        f"bot_token_file": shared_path,
    }
    for name in (f"default", f"idle"):
        save_agent_config(
            name,
            AgentProfileConfig.model_validate(
                {
                    f"id": f"Default" if name == f"default" else name,
                    f"name": name,
                    f"channels": {
                        f"wechat": {**values, f"enabled": name != f"idle"},
                    },
                },
            ),
        )
    owners = wechat_host.registry.runtime_owners
    baseline = owners.leases()
    managers = []
    entered, release = asyncio.Event(), asyncio.Event()
    started = []

    async def process(request):
        if False:
            yield request

    async def start(channel):
        (claim,) = channel._wechat_auth_claims
        assert owners.resource(claim) == channel._runtime_lease
        started.append(channel)
        entered.set()
        await release.wait()
        if entry == f"start-failure":
            raise RuntimeError(f"TEST_START_FAILED")

    monkeypatch.setattr(IsolatedChannelProxy, f"start", start)
    config = load_agent_config(f"default")
    if entry == f"env":
        monkeypatch.setenv(f"WECHAT_CHANNEL_ENABLED", f"1")
        monkeypatch.setenv(f"WECHAT_BOT_TOKEN", values[f"bot_token"])
        monkeypatch.setenv(f"WECHAT_BOT_TOKEN_FILE", shared_path)
        first = ChannelManager.from_env(process, workspace_dir=directory)
    else:
        first = ChannelManager.from_config(
            process,
            config,
            workspace_dir=directory,
            defer_process_channels=entry != f"config",
        )
    managers.append(first)
    pending = None
    try:
        await first.start_all()
        if entry not in {f"config", f"env"}:
            pending = asyncio.create_task(first.start_one(f"wechat", config))
        else:
            pending = asyncio.gather(*tuple(first._start_tasks))
        await asyncio.wait_for(entered.wait(), 5)
        if entry in {f"config", f"env"}:
            release.set()
            await pending
            assert first._find_channel(f"wechat") is started[0]
            return
        if entry == f"cancel":
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            assert first._find_channel(f"wechat") is None
            assert owners.leases() == baseline
            return
        if entry == f"start-failure":
            release.set()
            with pytest.raises(RuntimeError, match=f"TEST_START_FAILED"):
                await pending
            assert first._find_channel(f"wechat") is None
            assert owners.leases() == baseline
            return

        competitor = tmp_path / f"competitor"
        competitor.mkdir()
        second = ChannelManager.from_config(
            process,
            config,
            workspace_dir=competitor,
            defer_process_channels=True,
        )
        managers.append(second)
        await second.start_all()
        with pytest.raises(ManagementError, match=f"ACCOUNT_IN_USE"):
            await second.start_one(f"wechat", config)
        assert len(started) == 1

        release.set()
        await pending
        distinct = config.model_copy(deep=True)
        distinct.channels.wechat.bot_token = f"different-account"
        second_handle = await second.start_one(f"wechat", distinct)
        assert second_handle.channel._launch_spec.config[
            f"bot_token_file"
        ] == (shared_path)
        assert len(started) == 2
        first_channel = started[0]

        async def incomplete_stop():
            raise RuntimeError(f"TEST_STOP_FAILED")

        with monkeypatch.context() as patch:
            patch.setattr(first_channel, f"stop", incomplete_stop)
            assert not (await first.stop_one(f"wechat")).stopped
        await second.stop_all()
        await second.start_all()
        with pytest.raises(ManagementError, match=f"ACCOUNT_IN_USE"):
            await second.start_one(f"wechat", config)
        await first.stop_all()
        await second.start_one(f"wechat", config)
        assert len(started) == 3
    finally:
        release.set()
        if pending is not None:
            await asyncio.gather(pending, return_exceptions=True)
        for manager in managers:
            await manager.stop_all()
        assert owners.leases() == baseline


async def test_console_qr_checks_new_token_and_releases_before_reload(
    wechat_host,
    tmp_path,
    monkeypatch,
):
    workspace = tmp_path / f"default"
    workspace.mkdir()
    token_file = tmp_path / f"custom-token"
    token_file.write_text(f"old-file-token", encoding=f"utf-8")
    root = load_config()
    root.agents.profiles[f"default"] = AgentProfileRef(
        id=f"default",
        workspace_dir=str(workspace),
    )
    save_config(root)
    config = AgentProfileConfig.model_validate(
        {
            f"id": f"default",
            f"name": f"Default",
            f"channels": {
                f"wechat": {
                    f"enabled": False,
                    f"bot_token": f"occupied",
                    f"bot_token_file": str(token_file),
                    f"base_url": f"https://ilink.test",
                },
            },
        },
    )
    save_agent_config(f"default", config)
    owners = wechat_host.registry.runtime_owners
    baseline = owners.leases()
    owner = owners.reserve(
        f"wechat",
        RuntimeKey(f"channel", f"wechat", str(tmp_path / f"other")),
        tmp_path,
        instance_id=f"other",
    )
    occupied = reserve_wechat_auth(
        wechat_host.registry,
        owner=owner,
        config={
            f"bot_token": f"occupied",
            f"base_url": f"https://ilink.test:443",
        },
    )
    management = ChannelManagementService(wechat_host.loader)
    sessions = qrcode_sessions.ChannelQRCodeSessions(
        wechat_host.loader,
        management,
    )
    confirmed_token = f"occupied"
    description = wechat_host.registry.get_channel_catalog_entry(
        f"wechat",
    ).description_record

    async def execute(workspace_id, channel_key, operation, parameters, **kw):
        assert f"bot_token_file" not in parameters[f"config"]
        if operation == f"qrcode.fetch":
            payload = {
                f"scan_url": f"https://scan.test",
                f"continuation": f"scan-code",
            }
        else:
            assert operation == f"qrcode.poll"
            payload = {
                f"status": f"confirmed",
                f"credentials": {f"bot_token": confirmed_token},
            }
        return SimpleNamespace(
            plugin_id=f"wechat",
            workspace_id=workspace_id,
            channel_key=channel_key,
            source_revision=description.source_revision,
            outcome=f"ok",
            result=payload,
        )

    reloaded = []

    def reload_agent(_request, agent_id):
        assert set(owners.leases()) == {*baseline, owner, *occupied}
        reloaded.append(agent_id)

    monkeypatch.setattr(management, f"execute", execute)
    monkeypatch.setattr(config_router, f"schedule_agent_reload", reload_agent)
    app = FastAPI()
    app.include_router(config_router.router, prefix=f"/api")
    app.state.plugin_loader = wechat_host.loader
    app.state.channel_qrcode_sessions = sessions
    config_url = f"/api/config/channels/wechat"
    qr_url = f"{config_url}/qrcode"
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url=f"http://test",
            headers={f"X-Agent-Id": f"default"},
        ) as client:
            response = await client.get(qr_url)
            assert response.status_code == 200, response.text
            token = response.json()[f"poll_token"]
            response = await client.get(
                f"{qr_url}/status",
                params={f"token": token},
            )
            assert response.status_code == 409
            assert response.json() == {f"detail": f"ACCOUNT_IN_USE"}
            assert set(owners.leases()) == {*baseline, owner, *occupied}

            confirmed_token = f"new-token"
            response = await client.get(qr_url)
            assert response.status_code == 200, response.text
            token = response.json()[f"poll_token"]
            duplicate = await client.get(qr_url)
            assert duplicate.status_code == 409
            response = await client.get(
                f"{qr_url}/status",
                params={f"token": token},
            )
            assert response.status_code == 200, response.text
            wrong_origin = await client.put(
                config_url,
                headers={f"X-Channel-Auth-Session": token},
                json={
                    f"enabled": True,
                    f"bot_token": confirmed_token,
                    f"base_url": f"https://different.test",
                },
            )
            assert wrong_origin.status_code == 403
            response = await client.put(
                config_url,
                headers={f"X-Channel-Auth-Session": token},
                json={f"enabled": True, f"bot_token": confirmed_token},
            )
            assert response.status_code == 200, response.text
        saved = load_agent_config(f"default").channels.wechat
        assert saved.bot_token == confirmed_token
        assert saved.bot_token_file == str(token_file)
        assert saved.base_url == f"https://ilink.test"
        assert reloaded == [f"default"]
        assert token_file.read_text(encoding=f"utf-8") == f"old-file-token"
        assert not (workspace / f"wechat").exists()
    finally:
        await sessions.aclose()
        receipt = RuntimeStopReceipt(True, f"TEST_STOPPED")
        for claim in occupied:
            owners.release(claim, receipt)
        owners.release(owner, receipt)
        assert owners.leases() == baseline
