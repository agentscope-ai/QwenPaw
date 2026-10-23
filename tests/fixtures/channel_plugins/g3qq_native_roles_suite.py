"""Exact internal role change; reuse the original native TLS/AES fixtures."""

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import pytest

from qq_management_native_suite import fetch, request

pytest_plugins = ["qq_native_support"]


@pytest.mark.asyncio
@pytest.mark.parametrize("corrupt_tag", [False, True])
async def test_native_qq_success_metadata_and_decryption_failure_shape(
    portal, corrupt_tag
):
    from qwenpaw_channel_qq.driver import QQDriver

    token, key = await fetch(portal)
    nonce = os.urandom(12)
    ciphertext = bytearray(
        nonce + AESGCM(key).encrypt(nonce, "secret-中文".encode(), None)
    )
    if corrupt_tag:
        ciphertext[-1] ^= 1
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
        credential_keys={"app_id", "client_secret", "fail_reason"},
    )
    actual = result.to_mapping()
    assert actual["result"] == (
        {
            "status": "fail",
            "credentials": {"fail_reason": "Secret decryption failed"},
        }
        if corrupt_tag
        else {
            "status": "success",
            "credentials": {
                "app_id": "app-123",
                "client_secret": "secret-中文",
            },
            "metadata": {"user_openid": "native-user"},
        }
    )
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
    assert [row["path"] for row in portal.rows()] == [
        "/lite/create_bind_task",
        "/lite/poll_bind_result",
    ]
