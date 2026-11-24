# -*- coding: utf-8 -*-
"""iLink login, native messages, media and polling lifecycle."""

import asyncio
import base64
import hashlib
import json
import ssl
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from qwenpaw.app.channels import qrcode_sessions
from qwenpaw.app.channels.isolated_proxy import (
    ChannelDeliveryError,
    IsolatedChannelProxy,
)
from qwenpaw.app.channels.management import (
    ChannelManagementService,
    ManagementError,
)
from qwenpaw.app.channels.manager import ChannelManager
from qwenpaw.app.channels.process_supervisor import ChannelCallUnknown
from qwenpaw.app.channels.wechat_auth_custody import reserve_wechat_auth
from qwenpaw.app.routers import config as config_router
from qwenpaw.channel_protocol.errors import RpcError, RpcTimeoutError
from qwenpaw.channel_protocol.models import (
    DeliveryState,
    OutboundResult,
    SendParams,
)
from qwenpaw.config.config import (
    AgentProfileConfig,
    AgentProfileRef,
    load_agent_config,
    save_agent_config,
)
from qwenpaw.config.utils import load_config, save_config
from qwenpaw.plugins.architecture import PluginManifest, PluginRecord
from qwenpaw.plugins.channel_adapter import (
    ChannelRuntimeSettings,
    describe_channel,
)
from qwenpaw.plugins.execution_backend import BackendBinding
from qwenpaw.plugins.ownership import RuntimeKey, RuntimeStopReceipt
from qwenpaw.schemas import ImageContent
from tests.channel_support.driver import bind, module
from tests.channel_support.host import Host

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize(
    "failure,fail_chunk,recover,state,attempts",
    [
        (httpx.ConnectError, 1, True, "acknowledged", 3),
        (httpx.ConnectTimeout, 1, False, "failed", 3),
        (httpx.ConnectError, 2, False, "unknown", 4),
        (httpx.ReadTimeout, 2, False, "unknown", 2),
        (ssl.SSLCertVerificationError, 1, False, "failed", 1),
    ],
)
async def test_send_retries_only_unsent_connection_attempts(
    tmp_path,
    failure,
    fail_chunk,
    recover,
    state,
    attempts,
):
    client = module("wechat", "client").ILinkClient(
        "fake",
        "https://test.invalid",
    )
    bodies, accepted = [], []

    async def transport(request):
        body = json.loads(request.content)["msg"]
        bodies.append(body)
        chunk = body["item_list"][0]["text_item"]["text"]
        if chunk == ("first" if fail_chunk == 1 else "second"):
            if not recover or len(bodies) == 1:
                if failure is ssl.SSLCertVerificationError:
                    raise httpx.ConnectError(
                        "untrusted certificate",
                    ) from failure(1, "untrusted")
                raise failure("injected connection boundary", request=request)
        accepted.append(chunk)
        return httpx.Response(200, json={"message_id": "accepted"})

    client._client = httpx.AsyncClient(
        transport=httpx.MockTransport(transport),
    )
    driver = module("wechat").WeChatDriver()
    peer, identity = bind("wechat", driver, tmp_path)
    platform = module("wechat", "platform").WeChatPlatform(
        {"workspace_dir": str(tmp_path)},
        None,
        None,
    )
    platform._client = client
    driver._platform, driver._connected = platform, True
    opened = await peer.methods["channel.response.open"](
        {
            **identity.to_mapping(),
            "to_handle": "user",
            "meta": {"wechat_context_token": "context"},
        },
        None,
    )
    params = SendParams.from_mapping(
        {
            **identity.to_mapping(),
            "to_handle": opened["response_handle"],
            "delivery_id": "retry-test",
            "operation": "message.create",
            "content_parts": [
                {"type": "text", "text": "first"},
                {"type": "text", "text": "second"},
            ],
        },
    )
    try:
        result = await peer.methods["channel.send"](params, None)
        assert result["state"] == state
        assert len(bodies) == attempts
        assert accepted == (
            ["first", "second"]
            if recover
            else ["first"]
            if fail_chunk == 2
            else []
        )
        failed_bodies = [
            b
            for b in bodies
            if b["item_list"][0]["text_item"]["text"]
            == ("first" if fail_chunk == 1 else "second")
        ]
        assert all(body == failed_bodies[0] for body in failed_bodies)
        # Replaying the same delivery never sends either chunk again.
        assert await peer.methods["channel.send"](params, None) == result
        assert len(bodies) == attempts
    finally:
        await client.stop()


async def test_connection_retry_inherits_budget_and_propagates_cancellation():
    from qwenpaw.channel_protocol.outbound_budget import send_budget

    client = module("wechat", "client").ILinkClient(
        "fake",
        "https://test.invalid",
    )
    entered = asyncio.Event()
    attempts = []

    async def transport(request):
        if request.url.path.endswith("/getupdates"):
            await asyncio.sleep(0.02)
            return httpx.Response(200, json={"ret": 0})
        attempts.append(request)
        entered.set()
        raise httpx.ConnectError("offline", request=request)

    client._client = httpx.AsyncClient(
        transport=httpx.MockTransport(transport),
    )
    try:
        with send_budget(0.01):
            with pytest.raises(httpx.ConnectError):
                await client.send_text("user", "text", "context")
        assert len(attempts) == 1
        entered.clear()
        sending = asyncio.create_task(
            client.send_text("user", "text", "context"),
        )
        await entered.wait()
        sending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await sending
        assert len(attempts) == 2
        # A long poll retains its own timeout even if launched from a context
        # carrying a short send deadline. Only sendmessage opts into retries.
        with send_budget(0.001):
            assert await client.getupdates() == {"ret": 0}
    finally:
        await client.stop()


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
    upload, response_overrides = {}, {}

    async def transport(request):
        requests.append(request)
        path = request.url.path
        if path.endswith("/getupdates"):
            await polling.wait()
            value = {f"ret": 0, f"msgs": []}
        elif path.endswith("/get_bot_qrcode"):
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
        endpoint = path.rsplit(f"/", 1)[-1]
        return httpx.Response(
            200,
            json=response_overrides.get(endpoint, value),
        )

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
        polling=polling,
        response_overrides=response_overrides,
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


async def test_poll_and_typing_log_numeric_platform_codes(runtime, caplog):
    caplog.set_level(f"INFO")
    runtime.response_overrides.update(
        getupdates={f"ret": -14, f"errcode": 401},
        getconfig={
            f"ret": 0,
            f"errcode": 0,
            f"typing_ticket": f"ticket-value",
        },
        sendtyping={f"ret": -2, f"errcode": 404},
    )
    rt = await runtime.start()
    platform = rt.driver._platform
    platform.start_typing(f"reply", f"user-A", f"context-value")
    runtime.polling.set()
    async with asyncio.timeout(3):
        while f"WeChat sendtyping failed: status=1" not in caplog.text:
            await asyncio.sleep(0.01)
    await platform.finish_response(f"reply")
    assert f"getupdates failed: ret=-14 errcode=401" in caplog.text
    assert (
        f"getconfig response: ret=0 errcode=0 has_ticket=True" in caplog.text
    )
    for status in (1, 2):
        assert f"status={status} ret=-2 errcode=404" in caplog.text
    assert f"ticket-value" not in caplog.text
    assert f"context-value" not in caplog.text


async def test_getconfig_rejection_is_a_warning(runtime, caplog):
    runtime.response_overrides[f"getconfig"] = {
        f"ret": -14,
        f"errcode": 401,
        f"errmsg": f"private-server-response",
    }
    rt = await runtime.start()
    platform = rt.driver._platform
    platform.start_typing(f"reply", f"user-A", f"context-value")
    async with asyncio.timeout(3):
        await platform._typing_users[f"user-A"][f"task"]
    assert (
        f"WARNING",
        f"WeChat getconfig response: ret=-14 errcode=401 has_ticket=False",
    ) in [(record.levelname, record.getMessage()) for record in caplog.records]
    assert f"private-server-response" not in caplog.text


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


async def test_missing_qr_logs_failure_without_response_body(runtime, caplog):
    runtime.response_overrides[f"get_bot_qrcode"] = {
        f"errmsg": f"private-qr-response",
    }
    with pytest.raises(ValueError, match=f"QRCODE_UNAVAILABLE"):
        await runtime.start(token=f"")
    assert f"WeChat QR login failed (ValueError)" in caplog.text
    assert f"private-qr-response" not in caplog.text


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


@pytest.mark.parametrize(f"outcome", [f"timeout", f"recovered", f"rejected"])
async def test_admission_log_identifies_retained_routes(
    runtime,
    monkeypatch,
    caplog,
    outcome,
):
    rt = await runtime.start()
    host_call = rt.peer.call
    timed_out = False

    async def call(method, params):
        nonlocal timed_out
        if method == f"event.batch":
            if outcome == f"rejected":
                return {
                    f"batch_id": params[f"batch_id"],
                    f"rejected_events": [
                        {
                            f"event_id": params[f"events"][0][f"event_id"],
                            f"reason_code": f"CAPABILITY_REQUIRED",
                            f"retryable": False,
                        },
                    ],
                }
            if outcome == f"timeout" or not timed_out:
                timed_out = True
                raise RpcTimeoutError(f"private-detail")
        return await host_call(method, params)

    monkeypatch.setattr(rt.peer, f"call", call)
    if outcome == f"timeout":
        for index in range(2):
            with pytest.raises(
                RuntimeError,
                match=f"HOST_ADMISSION_EXHAUSTED",
            ):
                await rt.driver._platform._message(
                    message(index, text=f"private-message-{index}"),
                )
    else:
        await rt.driver._platform._message(message(1))

    assert len(rt.peer.batches) == (1 if outcome == f"recovered" else 0)
    retained = [log for log in caplog.messages if f"route_retained=" in log]
    assert retained == (
        [f"wechat event.batch route_retained=true reason=HOST_ACK_UNKNOWN"]
        if outcome == f"timeout"
        else []
    )
    rows = rt.peer.state[rt.driver._state_key]
    assert [row[f"kind"] for row in rows] == {
        f"timeout": [f"active", f"active"],
        f"recovered": [f"active"],
        f"rejected": [],
    }[outcome]


@pytest.fixture
def route_proxy():
    root = Path(__file__).resolve().parents[3]
    source = root / f"plugins/channel/wechat"
    manifest = PluginManifest.from_dict(
        json.loads((source / f"plugin.json").read_text(encoding=f"utf-8")),
    )
    description = describe_channel(source, manifest)
    prepared = description.prepare_proxy_config({f"enabled": True})
    return description.create_proxy(
        None,
        prepared.config,
        python_executable=sys.executable,
        support_root=root / f"src",
        instance_id=f"wechat-log-test",
        generation=1,
        qwenpaw_version=f"test",
        prepared_config=prepared,
    )


async def test_no_text_backlog_logs_routes_across_sessions(
    route_proxy,
    caplog,
):
    for index in range(34):
        assert not route_proxy._debounce_payload(
            {
                f"meta": {
                    f"debounce_key": f"private-session-{index % 2}",
                    f"response_handle": f"private-route-{index}",
                },
                f"content_parts": [ImageContent(image_url=f"private-image")],
            },
        )
    assert [
        log for log in caplog.messages if f"NO_TEXT_DEBOUNCE_BACKLOG" in log
    ] == [f"wechat NO_TEXT_DEBOUNCE_BACKLOG: waiting_routes=32"]


@pytest.mark.parametrize(
    f"reason",
    [f"TEXT_MERGE_CAPACITY", f"PLATFORM_RESULT_UNKNOWN", None],
)
async def test_finish_log_distinguishes_failure_before_rpc(
    route_proxy,
    monkeypatch,
    caplog,
    reason,
):
    meta = {f"response_handle": f"private-handle"}
    rpc = AsyncMock(side_effect=RuntimeError(f"private-rpc-error"))
    monkeypatch.setattr(route_proxy.channel_process, f"call", rpc)
    if reason == f"TEXT_MERGE_CAPACITY":
        error = meta[f"_text_merge_error"] = ValueError(reason)
    elif reason == f"PLATFORM_RESULT_UNKNOWN":
        error = ChannelDeliveryError(
            OutboundResult(f"reply", DeliveryState.UNKNOWN, f"private-detail"),
        )
        monkeypatch.setattr(
            route_proxy,
            f"_flush_response_text",
            AsyncMock(side_effect=error),
        )
    else:
        error = rpc.side_effect

    with pytest.raises(type(error)) as raised:
        await route_proxy._finish_route(meta, f"failed")
    assert raised.value is error
    warnings = [
        log for log in caplog.messages if f"RESPONSE_FINISH_SKIPPED" in log
    ]
    if reason is None:
        rpc.assert_awaited_once()
        assert not warnings
    else:
        rpc.assert_not_awaited()
        assert warnings == [
            f"wechat RESPONSE_FINISH_SKIPPED: "
            f"stage=text_merge finish_sent=false reason={reason}",
        ]


@pytest.mark.parametrize(
    f"earlier_unknown,unknown",
    [(False, False), (False, True), (True, False), (True, True)],
)
async def test_finish_diagnostic_reports_unknown_rpc_result(
    route_proxy,
    monkeypatch,
    caplog,
    earlier_unknown,
    unknown,
):
    error = (
        ChannelCallUnknown(f"channel-1-2", f"channel.response.finish", 1)
        if unknown
        else RpcError(-32603, f"private-rpc-error")
    )
    method = f"channel.response.finish"
    earlier = ChannelCallUnknown(f"channel-1-1", method, 1)
    errors = [earlier, error] if earlier_unknown else [error]
    rpc = AsyncMock(side_effect=errors)
    monkeypatch.setattr(route_proxy.channel_process, f"call", rpc)
    handles = [f"private-attachment"] if earlier_unknown else []
    meta = {
        f"response_handle": f"private-handle",
        f"_merged_response_handles": handles,
    }
    async with route_proxy._response_scope(meta):
        pass

    attempted = [
        call.args[1][f"response_handle"] for call in rpc.await_args_list
    ]
    assert attempted == [*handles, f"private-handle"]
    diagnostic = (
        f"RESPONSE_FINISH_UNKNOWN" if unknown else f"RESPONSE_FINISH_FAILED"
    )
    assert (await route_proxy.health_check())[f"last_diagnostic"] == diagnostic
    expected = [
        f"Channel diagnostic: {diagnostic}"
        + (f" rpc_result=unknown request_id=channel-1-2" if unknown else f""),
    ]
    if earlier_unknown:
        expected.insert(
            0,
            f"Channel diagnostic: RESPONSE_FINISH_UNKNOWN rpc_result=unknown "
            f"request_id=channel-1-1",
        )
    warnings = [log for log in caplog.messages if f"RESPONSE_FINISH" in log]
    assert warnings == expected


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
