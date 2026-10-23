"""Native official manage functions, real Service/worker, controlled HTTP only."""
import hashlib
import os
from urllib.parse import urlsplit

import psutil
import pytest

from g3fd_dd_native_support import g3_host_import_boundary, native_qr

__all__ = ["g3_host_import_boundary", "native_qr"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "channel,domain",
    [("dingtalk", "feishu"), ("feishu", "feishu"), ("feishu", "lark")],
)
async def test_native_fetch_poll_cookie_form_and_credentials(
    native_qr, channel, domain
):
    qr = await native_qr(channel, domain)
    fetched = await qr.sessions.fetch(qr.scope, {})
    assert fetched.scan_url.startswith("https://fixture.invalid/scan?code=abc")
    assert len(qr.requests) == 2
    init, begin = qr.requests
    assert init["pid"] == begin["pid"] != os.getpid()
    assert "cookie" not in init["headers"]
    assert begin["headers"]["cookie"] == "device_flow=fixture-cookie"
    assert not psutil.pid_exists(init["pid"])
    if channel == "dingtalk":
        assert init["fields"] == {"source": "QWENPAW"}
        assert begin["fields"] == {"nonce": "nonce"}
    else:
        assert "source=QwenPaw" in fetched.scan_url
        assert begin["fields"] == {
            "action": "begin",
            "archetype": "PersonalAgent",
            "auth_method": "client_secret",
            "request_user_info": "open_id",
        }
        assert (
            begin["headers"]["content-type"]
            == "application/x-www-form-urlencoded"
        )
        host = (
            "accounts.larksuite.com"
            if domain == "lark"
            else "accounts.feishu.cn"
        )
        assert all(
            urlsplit(row["url"]).hostname == host for row in qr.requests
        )
    result = await qr.sessions.poll(qr.scope, fetched.poll_token)
    assert result.status == "success"
    assert len(qr.requests) == 3
    poll = qr.requests[-1]
    assert poll["pid"] != init["pid"] and not psutil.pid_exists(poll["pid"])
    assert "cookie" not in poll["headers"]
    assert poll["fields"]["device_code"] == "device-123"
    if channel == "dingtalk":
        credentials = {
            "client_id": "client-123",
            "client_secret": "secret-456",
        }
        assert result.credentials == credentials
    else:
        assert urlsplit(poll["url"]).hostname == host
        credentials = {"app_id": "app-123", "app_secret": "secret-456"}
        assert result.credentials == {
            **credentials,
            "open_id": "open-789",
            "tenant_brand": domain,
        }
    again = await qr.sessions.poll(qr.scope, fetched.poll_token)
    assert again.credentials == result.credentials
    assert len(qr.requests) == 3
    async with qr.sessions.authorize_save(
        qr.scope, fetched.poll_token, credentials
    ):
        pass
    for name, expected in qr.original_functions_sha.items():
        assert (
            hashlib.sha256(
                (qr.instrumented_source / channel / name).read_bytes()
            ).hexdigest()
            == expected
        )


@pytest.mark.asyncio
async def test_invalid_query_domain_falls_back_to_saved_lark(native_qr):
    qr = await native_qr("feishu", "lark")
    fetched = await qr.sessions.fetch(
        qr.scope, {"domain": "https://open.feishu.cn"}
    )
    assert "source=QwenPaw" in fetched.scan_url
    assert len(qr.requests) == 2
    assert all(
        urlsplit(row["url"]).hostname == "accounts.larksuite.com"
        for row in qr.requests
    )
