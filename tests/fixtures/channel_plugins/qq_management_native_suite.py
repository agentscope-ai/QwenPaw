"""Real HTTPS Portal and AESGCM through the fixed static manage hook."""

import asyncio
import base64
import os
from urllib.parse import parse_qs, urlsplit
import uuid

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import pytest

pytest.register_assert_rewrite("qq_native_support")

from qwenpaw.channel_protocol.management import ManagementRequest
from qwenpaw.channel_protocol.errors import ProtocolValidationError

from qq_native_support import eventually

pytest_plugins = ["qq_native_support"]


def request(operation, continuation=None):
    parameters = {"config": {"enabled": False}}
    if continuation is not None:
        parameters["continuation"] = continuation
    return ManagementRequest.from_mapping(
        {
            "request_id": str(uuid.uuid4()),
            "plugin_id": "qq",
            "workspace_id": "workspace-A",
            "channel_key": "qq",
            "instance_id": "manage-A",
            "generation": 2,
            "source_revision": "a" * 64,
            "operation": operation,
            "timeout_ms": 2000,
            "parameters": parameters,
        }
    )


async def fetch(server):
    from qwenpaw_channel_qq.driver import QQDriver

    server.queue(
        "POST",
        "/lite/create_bind_task",
        (200, {"retcode": 0, "data": {"task_id": "task-中文 /?"}}),
    )
    req = request("qrcode.fetch")
    result = await QQDriver.manage(req)
    result.validate_for(
        req,
        credential_keys={
            "app_id",
            "client_secret",
            "user_openid",
            "fail_reason",
        },
    )
    assert result.to_mapping()["outcome"] == "ok"
    payload = result.to_mapping()["result"]
    row = server.rows("/lite/create_bind_task")[0]
    assert set(row["body"]) == {"key"}
    key = base64.b64decode(row["body"]["key"], validate=True)
    assert len(key) == 32
    url = urlsplit(payload["scan_url"])
    assert url.scheme == "https" and url.path == "/qqbot/openclaw/connect.html"
    assert parse_qs(url.query) == {
        "task_id": ["task-中文 /?"],
        "_wv": ["2"],
        "source": ["QwenPaw"],
    }
    return payload["continuation"], key


async def test_static_fetch_poll_actual_https_aesgcm_and_exact_identity(
    portal,
):
    from qwenpaw_channel_qq.driver import QQDriver

    token, key = await fetch(portal)
    nonce = os.urandom(12)
    ciphertext = nonce + AESGCM(key).encrypt(
        nonce, "secret-中文".encode(), None
    )
    portal.queue(
        "POST",
        "/lite/poll_bind_result",
        (
            200,
            {
                "retcode": 0,
                "data": {
                    "status": 2,
                    "bot_appid": "app-123",
                    "bot_encrypt_secret": base64.b64encode(
                        ciphertext
                    ).decode(),
                    "user_openid": "native-user",
                },
            },
        ),
    )
    req = request("qrcode.poll", token)
    result = await QQDriver.manage(req)
    result.validate_for(
        req,
        credential_keys={
            "app_id",
            "client_secret",
            "user_openid",
            "fail_reason",
        },
    )
    actual = result.to_mapping()
    assert actual["result"] == {
        "status": "success",
        "credentials": {
            "app_id": "app-123",
            "client_secret": "secret-中文",
        },
        "metadata": {"user_openid": "native-user"},
    }
    for key in (
        "request_id",
        "plugin_id",
        "workspace_id",
        "channel_key",
        "instance_id",
        "generation",
        "source_revision",
        "operation",
    ):
        assert actual[key] == req.to_mapping()[key]
    assert portal.rows("/lite/poll_bind_result")[0]["body"] == {
        "task_id": "task-中文 /?"
    }
    assert [r["path"] for r in portal.rows()] == [
        "/lite/create_bind_task",
        "/lite/poll_bind_result",
    ]


@pytest.mark.parametrize(
    "response,want",
    [
        (
            {"retcode": 1, "msg": "rejected"},
            {"status": "fail", "credentials": {"fail_reason": "rejected"}},
        ),
        (
            {"retcode": 0, "data": {"status": 3}},
            {"status": "expired", "credentials": {}},
        ),
        (
            {"retcode": 0, "data": {"status": 1}},
            {"status": "waiting", "credentials": {}},
        ),
        (
            {"retcode": 0, "data": {"status": 2}},
            {
                "status": "fail",
                "credentials": {"fail_reason": "Missing app_id or secret"},
            },
        ),
        (
            {
                "retcode": 0,
                "data": {
                    "status": 2,
                    "bot_appid": "app",
                    "bot_encrypt_secret": "c2hvcnQ=",
                },
            },
            {
                "status": "fail",
                "credentials": {"fail_reason": "Secret decryption failed"},
            },
        ),
    ],
)
async def test_native_poll_preserves_fail_expired_waiting_missing_and_short_ciphertext(
    portal, response, want
):
    from qwenpaw_channel_qq.driver import QQDriver

    token, _ = await fetch(portal)
    portal.queue("POST", "/lite/poll_bind_result", (200, response))
    result = await QQDriver.manage(request("qrcode.poll", token))
    assert result.to_mapping()["result"] == want
    assert len(portal.rows("/lite/poll_bind_result")) == 1


async def test_wrong_aesgcm_tag_yields_failed_poll_without_credentials(portal):
    from qwenpaw_channel_qq.driver import QQDriver

    token, key = await fetch(portal)
    nonce = b"0123456789ab"
    raw = bytearray(nonce + AESGCM(key).encrypt(nonce, b"secret", None))
    raw[-1] ^= 1
    portal.queue(
        "POST",
        "/lite/poll_bind_result",
        (
            200,
            {
                "retcode": 0,
                "data": {
                    "status": 2,
                    "bot_appid": "app",
                    "bot_encrypt_secret": base64.b64encode(raw).decode(),
                },
            },
        ),
    )
    actual = (
        await QQDriver.manage(request("qrcode.poll", token))
    ).to_mapping()
    assert actual["result"] == {
        "status": "fail",
        "credentials": {"fail_reason": "Secret decryption failed"},
    }


async def test_uncertain_portal_fetch_does_not_retry(portal):
    from qwenpaw_channel_qq.driver import QQDriver

    portal.queue(
        "POST", "/lite/create_bind_task", (503, {"message": "uncertain"})
    )
    with pytest.raises(ProtocolValidationError) as caught:
        await QQDriver.manage(request("qrcode.fetch"))
    assert caught.value.reason_code == "PLATFORM_RESULT_UNKNOWN"
    assert len(portal.rows()) == 1


async def test_portal_cancel_settles_actual_body_read_and_no_second_request(
    portal,
):
    from qwenpaw_channel_qq.driver import QQDriver

    portal.queue("POST", "/lite/create_bind_task", "hold-body")
    task = asyncio.create_task(QQDriver.manage(request("qrcode.fetch")))
    await eventually(portal.body_entered.is_set)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.done() and task.cancelled()
    assert len(portal.rows()) == 1
    portal.body_release.set()
