"""Independent native Azure behavior; actual Core/Agent remains separate."""

import asyncio
import base64
import json
from pathlib import Path
import time

import pytest

from qwenpaw.channel_protocol.models import SendParams, ResponseFinishParams
from qwenpaw.plugins.install_lock import InstallLockError

from azure_bot_native_support import (
    APP,
    ISSUER,
    SERVICE,
    REAL_SESSION,
    activity,
    post,
    state_module,
    azure,
    connector,
    rsa_material,
)

pytestmark = pytest.mark.asyncio


def send_params(driver, event, delivery="delivery-one", parts=None, source="direct"):
    return SendParams.from_mapping(
        {
            **driver._context.identity.to_mapping(),
            "delivery_id": delivery,
            "to_handle": event.response_handle,
            "operation": "message.create",
            "content_parts": parts or [{"type": "text", "text": "outgoing"}],
            "content_source": source,
        }
    )


@pytest.mark.parametrize(
    "failure",
    [
        "signature",
        "issuer",
        "audience",
        "expired",
        "future_nbf",
        "algorithm",
        "missing_exp",
    ],
)
async def test_invalid_jwt_is_rejected_before_reading_body(azure, connector, failure):
    async with azure() as (driver, peer):
        now = int(time.time())
        overrides = {
            "issuer": {"iss": ISSUER + "/attacker-tenant"},
            "audience": {"aud": "another-app"},
            "expired": {"exp": now - 1000},
            "future_nbf": {"nbf": now + 1000},
        }.get(failure, {})
        token = connector.token(
            overrides=overrides,
            signer=(
                connector.other
                if failure == "signature"
                else "not-a-real-rsa-key" if failure == "algorithm" else None
            ),
            algorithm="HS256" if failure == "algorithm" else "RS256",
        )
        if failure == "missing_exp":
            import jwt

            claims = {"iss": ISSUER, "aud": APP, "nbf": now - 10, "serviceurl": SERVICE}
            token = jwt.encode(
                claims, connector.key, algorithm="RS256", headers={"kid": "key-one"}
            )
        status, _ = await post(driver, connector, activity(), token=token)
        assert status == 401
        assert connector.reads == []
        assert peer.events == []
        assert driver._platform.store.refs == {}


@pytest.mark.parametrize("claim", ["lower", "camel", "both"])
async def test_connector_signature_and_service_url_bind_the_read_body(
    azure, connector, claim
):
    overrides = {"serviceUrl": SERVICE} if claim in {"camel", "both"} else {}
    if claim == "camel":
        overrides["serviceurl"] = None
    async with azure() as (driver, peer):
        status, _ = await post(
            driver, connector, activity(), token=connector.token(overrides=overrides)
        )
        assert status == 200
        assert len(connector.reads) == 1
        assert len(peer.events) == 1
        event = peer.events[0]
        assert event.acl_sender_id == "aad-user-123456"
        assert event.sender_id == "Ada#123456"
        assert event.metadata["session_id"] == "azure_msteams#ABCDEFGHIJ"
        assert event.content_parts == ({"type": "text", "text": "hello"},)
        assert (
            driver._route_attrs(event.response_handle)["bot_channel_id"] == "native-bot"
        )


@pytest.mark.parametrize(
    "change,claims",
    [
        ({"serviceUrl": SERVICE + "/different"}, {}),
        ({}, {"serviceUrl": SERVICE + "/conflict"}),
        ({"channelId": "unendorsed"}, {}),
    ],
)
async def test_valid_signature_cannot_authorize_another_service_or_channel(
    azure, connector, change, claims
):
    async with azure() as (driver, peer):
        status, _ = await post(
            driver,
            connector,
            activity(**change),
            token=connector.token(overrides=claims),
        )
        assert status == 403
        assert len(connector.reads) == 1
        assert peer.events == []
        assert driver._platform.store.refs == {}


async def test_exact_api_messages_route_and_native_nonmessage_replies(azure, connector):
    async with azure() as (driver, peer):
        assert (await post(driver, connector, activity(), path="/messages"))[0] == 404
        assert (await post(driver, connector, []))[0] == 400
        assert (await post(driver, connector, activity(type="conversationUpdate")))[
            0
        ] == 200
        assert peer.events == []
        assert len(driver._platform.store.refs) == 1
        status, text = await post(driver, connector, activity(type="invoke"))
        assert status == 200 and json.loads(text) == {"status": 200}
        assert peer.events == []
        registrations = [
            (method, params)
            for method, params in peer.calls
            if method.startswith("ingress.endpoint.")
        ]
        assert registrations[0][0] == "ingress.endpoint.register"
        assert registrations[0][1]["path"] == "/api/messages"
        assert registrations[0][1]["port"] == driver._platform.port
        assert registrations[0][1]["readiness"] == "ready"


@pytest.mark.parametrize(
    "channel,conversation,data,is_group",
    [
        ("msteams", {"conversationType": "channel"}, {}, True),
        ("msteams", {"conversationType": "groupChat"}, {}, True),
        ("webchat", {"isGroup": True}, {}, True),
        ("slack", {}, {"SlackMessage": {"event": {"channel_type": "channel"}}}, True),
        ("slack", {}, {"SlackMessage": {"event": {"channel_type": "group"}}}, True),
        ("webchat", {}, {}, False),
    ],
)
@pytest.mark.parametrize("shared", [False, True])
async def test_group_channel_session_and_real_aad_acl(
    azure, connector, channel, conversation, data, is_group, shared
):
    async with azure(share_session_in_group=shared) as (driver, peer):
        value = activity(
            channelId=channel,
            conversation={"id": "conversation-ABCDEFGHIJ", **conversation},
            channelData=data,
        )
        assert (await post(driver, connector, value))[0] == 200
        event = peer.events[0]
        assert event.conversation["type"] == ("group" if is_group else "dm")
        assert event.acl_sender_id == "aad-user-123456"
        assert event.sender_id == ("group" if is_group and shared else "Ada#123456")
        assert event.metadata["session_id"] == "azure_" + channel + "#ABCDEFGHIJ"
        assert event.metadata["user_id"] == event.sender_id


@pytest.mark.parametrize("mentioned_id", [APP, "native-bot"])
async def test_mention_gate_precedes_download_and_hidden_mention_is_removed(
    azure, connector, mentioned_id
):
    async with azure(require_mention=True) as (driver, peer):
        value = activity(
            conversation={
                "id": "conversation-ABCDEFGHIJ",
                "conversationType": "channel",
            },
            text="<at>Qwen</at> hello",
            attachments=[
                {
                    "contentType": "image/png",
                    "contentUrl": "https://media.test/download/image",
                    "name": "../unsafe.png",
                }
            ],
        )
        assert (await post(driver, connector, value))[0] == 200
        assert (
            peer.events == []
            and connector.requests == []
            and connector.token_calls == 0
        )
        value["entities"] = [
            {
                "type": "mention",
                "text": "<at>Qwen</at>",
                "mentioned": {"id": mentioned_id},
            }
        ]
        assert (await post(driver, connector, value))[0] == 200
        assert peer.events[0].content_parts[0] == {"type": "text", "text": "hello"}
        image = Path(peer.events[0].content_parts[1]["image_url"])
        assert image.is_relative_to(driver._platform.media_dir)
        assert image.read_bytes() == b"\x89PNG\r\n\x1a\nimage"
        assert connector.requests == [
            ("download", "/download/image", None)
        ]


async def test_from_id_is_acl_fallback_and_token_cache_refreshes_at_external_msal(
    azure, connector
):
    async with azure() as (driver, peer):
        value = activity(**{"from": {"id": "native-user", "name": ""}})
        assert (await post(driver, connector, value))[0] == 200
        assert peer.events[0].acl_sender_id == "native-user"
        assert peer.events[0].sender_id == "msteams#e-user"
        platform = driver._platform
        assert await platform._get_bot_token() == "access-1"
        assert await platform._get_bot_token() == "access-1"
        assert connector.token_calls == 1
        platform._token_expires = time.time() - 1
        assert await platform._get_bot_token() == "access-2"
        assert connector.token_calls == 2
        assert len(connector.token_apps) == 1
        assert (
            connector.token_apps[0][1]["authority"]
            == "https://login.microsoftonline.com/test-tenant"
        )


async def test_real_outbound_http_upload_at_180000_bytes_and_native_recipient(
    azure, connector
):
    async with azure() as (driver, peer):
        value = activity(conversation={"id": "conversation /ABCDEFGHIJ"})
        assert (await post(driver, connector, value))[0] == 200
        file = driver._platform.store.workspace / "boundary.bin"
        file.write_bytes(b"x" * 180000)
        params = send_params(
            driver,
            peer.events[0],
            parts=[{"type": "file", "file_url": str(file), "filename": "display.bin"}],
            source="media",
        )
        result = await driver._send(params, None)
        assert result["state"] == "acknowledged"
        assert len(connector.requests) == 2
        upload, sent = connector.requests
        assert upload[0] == "/v3/conversations/conversation%20%2FABCDEFGHIJ/attachments"
        assert len(base64.b64decode(upload[1]["originalBase64"])) == 180000
        assert sent[1]["from"] == {"id": "native-bot"}
        assert (
            sent[1]["attachments"][0]["contentUrl"]
            == SERVICE + "/v3/attachments/attachment%2Fid/views/original"
        )
        assert upload[2] == sent[2] == "Bearer access-1"


@pytest.mark.parametrize(
    "language,expected",
    [
        ("zh", "⚠️ 文件「large.bin」（176KB）超过附件大小限制（180KB），无法发送。"),
        (
            "en",
            '⚠️ File "large.bin" (176KB) exceeds the attachment size limit (180KB) and cannot be sent.',
        ),
        (
            "id",
            '⚠️ File "large.bin" (176KB) melebihi batas ukuran lampiran (180KB) dan tidak dapat dikirim.',
        ),
        ("ru", "⚠️ Файл «large.bin» (176KB) превышает лимит (180KB)."),
    ],
)
async def test_180001_bytes_retains_legacy_localized_notice_without_upload(
    azure, connector, language, expected
):
    async with azure(language=language) as (driver, peer):
        assert (await post(driver, connector, activity()))[0] == 200
        file = driver._platform.store.workspace / "large.bin"
        file.write_bytes(b"x" * 180001)
        result = await driver._send(
            send_params(
                driver,
                peer.events[0],
                parts=[{"type": "file", "file_url": str(file)}],
                source="media",
            ),
            None,
        )
        assert result["state"] == "acknowledged"
        assert len(connector.requests) == 1
        assert connector.requests[0][0].endswith("/activities")
        assert connector.requests[0][1]["text"] == expected


@pytest.mark.parametrize("status,body", [(500, {"error": "uncertain"}), (201, {})])
async def test_uncertain_upload_is_unknown_and_same_delivery_never_replays(
    azure, connector, status, body
):
    async with azure() as (driver, peer):
        assert (await post(driver, connector, activity()))[0] == 200
        connector.upload_status, connector.upload_body = status, body
        file = driver._platform.store.workspace / "file.bin"
        file.write_bytes(b"payload")
        params = send_params(
            driver,
            peer.events[0],
            parts=[{"type": "file", "file_url": str(file)}],
            source="media",
        )
        result = await driver._send(params, None)
        assert result["state"] == "unknown"
        assert len(connector.requests) == 1 and connector.requests[0][0].endswith(
            "/attachments"
        )
        assert await driver._send(params, None) == result
        assert len(connector.requests) == 1
        finish = ResponseFinishParams.from_mapping(
            {
                **driver._context.identity.to_mapping(),
                "response_handle": peer.events[0].response_handle,
                "outcome": "completed",
            }
        )
        await driver._finish(finish, None)
        assert len(connector.requests) == 1
        assert any(
            dict(ref.attributes).get("state") == "unknown"
            for ref in driver._routes.snapshot(params.to_handle).resource_refs
        )


async def test_definite_upload_rejection_keeps_legacy_inline_fallback(azure, connector):
    async with azure() as (driver, peer):
        assert (await post(driver, connector, activity()))[0] == 200
        connector.upload_status = 400
        file = driver._platform.store.workspace / "file.bin"
        file.write_bytes(b"payload")
        result = await driver._send(
            send_params(
                driver,
                peer.events[0],
                parts=[{"type": "file", "file_url": str(file)}],
                source="media",
            ),
            None,
        )
        assert result["state"] == "acknowledged"
        assert len(connector.requests) == 2
        assert (
            connector.requests[1][1]["attachments"][0]["contentUrl"]
            == "data:application/octet-stream;base64,cGF5bG9hZA=="
        )


async def test_legacy_refs_require_authenticated_matching_route_and_keep_original_bytes(
    azure, connector, tmp_path
):
    workspace = tmp_path / "legacy-work"
    workspace.mkdir()
    global_dir = tmp_path / "old-global"
    global_dir.mkdir()
    old = {
        "old-target": {
            "service_url": SERVICE,
            "conversation_id": "conversation-ABCDEFGHIJ",
            "bot_channel_id": "native-bot",
        }
    }
    original = json.dumps(old).encode()
    (workspace / "azure_bot_refs.json").write_bytes(original)
    (global_dir / "azure_bot_refs.json").write_bytes(
        b'{"global-only":{"service_url":"https://other.test"}}'
    )
    global_before = (global_dir / "azure_bot_refs.json").read_bytes()
    async with azure(
        workspace_dir=str(workspace), legacy_state_dir=str(global_dir)
    ) as (driver, peer):
        store = driver._platform.store
        with pytest.raises(ValueError, match="AZURE_ROUTE_UNAVAILABLE"):
            store.resolve("old-target", old["old-target"])
        assert (await post(driver, connector, activity()))[0] == 200
        assert store.resolve("old-target", {})["bot_channel_id"] == "native-bot"
        other = state_module.AzureBotStateStore(
            {
                "workspace_dir": str(workspace),
                "app_id": "another-app",
                "tenant_id": "test-tenant",
            }
        )
        other.begin()
        try:
            with pytest.raises(ValueError, match="AZURE_ROUTE_UNAVAILABLE"):
                other.resolve("old-target", old["old-target"])
        finally:
            other.close()
        assert (workspace / "azure_bot_refs.json").read_bytes() == original
        assert (global_dir / "azure_bot_refs.json").read_bytes() == global_before


async def test_stop_failure_retains_platform_claim_then_retry_releases_port(
    azure, connector, monkeypatch
):
    async with azure() as (driver, peer):
        platform = driver._platform
        port = platform.port
        owner = state_module.AzureBotStateStore(platform.config)
        with monkeypatch.context() as patch:
            original = type(platform.site).stop

            async def fails(site):
                if site is platform.site:
                    raise OSError("independent injected site failure")
                return await original(site)

            patch.setattr(type(platform.site), "stop", fails)
            with pytest.raises(OSError, match="injected site failure"):
                await driver.stop()
            assert driver._platform is platform and platform.site is not None
            with pytest.raises(InstallLockError, match="INSTALL_LOCK_UNAVAILABLE"):
                owner.begin()
        await driver.stop()
        assert driver._platform is None
        owner.begin()
        owner.close()
        server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", port)
        server.close()
        await server.wait_closed()
        assert peer.calls[-1][0] == "ingress.endpoint.unregister"


async def test_identical_idless_activities_are_distinct_platform_deliveries(
    azure, connector
):
    async with azure() as (driver, peer):
        value = activity(id="")
        assert (await post(driver, connector, value))[0] == 200
        assert (await post(driver, connector, value))[0] == 200
        assert len(peer.events) == 2
        assert peer.events[0].event_id != peer.events[1].event_id
