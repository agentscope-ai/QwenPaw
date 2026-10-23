"""Old WeChat QR business shapes through actual native worker and Session."""

import json
import os
from urllib.parse import parse_qs, urlsplit

import psutil
import pytest

from wechat_g3_native_support import g3_host_import_boundary, wechat_g3

__all__ = ["g3_host_import_boundary", "wechat_g3"]


def assert_native_clients_closed(qr):
    observations = [
        json.loads(line) for line in qr.ledger.read_text().splitlines()
    ]
    pids = {row["pid"] for row in qr.requests}
    assert len(pids) == len(qr.requests)
    assert all(
        pid != os.getpid() and not psutil.pid_exists(pid) for pid in pids
    )
    for pid in pids:
        assert [row["kind"] for row in observations if row["pid"] == pid] == [
            "request",
            "transport.closed",
        ]
    assert not any(
        lease.key.kind == "management"
        for lease in qr.loader.registry.runtime_owners.leases("wechat")
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("shape", ["missing", "null", "empty"])
async def test_native_waiting_credential_shapes_stay_waiting_and_close_client(
    wechat_g3, shape
):
    qr = wechat_g3
    fetched = await qr.sessions.fetch(qr.scope, {})
    if shape == "missing":
        qr.poll = {}
    else:
        value = None if shape == "null" else ""
        qr.poll = {"status": "waiting", "bot_token": value, "baseurl": value}
    try:
        result = await qr.sessions.poll(qr.scope, fetched.poll_token)
    finally:
        assert_native_clients_closed(qr)
    # Legacy waiting never becomes an authorization error or issued secret.
    assert result.status == "waiting"
    assert result.credentials == {}
    assert len(qr.requests) == 2
    assert parse_qs(urlsplit(qr.requests[-1]["url"]).query) == {
        "qrcode": ["native-code"]
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "image", ["https://scan.invalid/real", "encoded-image"]
)
async def test_native_fetch_url_and_encoded_image_preserve_old_scan_url(
    wechat_g3, image
):
    qr = wechat_g3
    qr.fetch = {"qrcode": "code/+?=test", "qrcode_img_content": image}
    try:
        fetched = await qr.sessions.fetch(qr.scope, {})
    finally:
        assert_native_clients_closed(qr)
    expected = (
        image
        if image.startswith("http")
        else "https://liteapp.weixin.qq.com/q/7GiQu1"
        "?qrcode=code/+?=test&bot_type=3"
    )
    assert fetched.scan_url == expected
    assert fetched.poll_token != qr.fetch["qrcode"]
    assert len(qr.requests) == 1
    assert parse_qs(urlsplit(qr.requests[0]["url"]).query) == {
        "bot_type": ["3"]
    }


@pytest.mark.asyncio
async def test_native_empty_qrcode_and_image_are_rejected_and_client_closed(
    wechat_g3,
):
    from qwenpaw.app.channels.management import ManagementError

    qr = wechat_g3
    qr.fetch = {"qrcode": "", "qrcode_img_content": ""}
    with pytest.raises(ManagementError) as caught:
        try:
            await qr.sessions.fetch(qr.scope, {})
        finally:
            assert_native_clients_closed(qr)
    assert caught.value.reason_code == "MANAGEMENT_INVALID_RESULT"
    assert len(qr.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["fetch", "poll"])
async def test_real_native_transport_error_closes_client_without_auto_retry(
    wechat_g3, operation
):
    from qwenpaw.app.channels.management import ManagementError

    qr = wechat_g3
    fetched = None
    if operation == "poll":
        fetched = await qr.sessions.fetch(qr.scope, {})
    qr.fault = operation
    with pytest.raises(ManagementError) as caught:
        try:
            if operation == "fetch":
                await qr.sessions.fetch(qr.scope, {})
            else:
                await qr.sessions.poll(qr.scope, fetched.poll_token)
        finally:
            assert_native_clients_closed(qr)
    assert caught.value.reason_code == "PLATFORM_REQUEST_FAILED"
    assert len(qr.requests) == (1 if operation == "fetch" else 2)
