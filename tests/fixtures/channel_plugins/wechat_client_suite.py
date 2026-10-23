"""Private WeChat helpers/client against actual HTTP and crypto boundaries.

This is a pure private-source group, not Loader/worker/Agent proof. It awaits
the private source handoff; a missing import cannot establish any business case.
"""

import base64
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from qwenpaw.exceptions import ChannelError

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def private(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "plugins/channel/wechat"))
    return SimpleNamespace(
        client=importlib.import_module("qwenpaw_channel_wechat.client"),
        utils=importlib.import_module("qwenpaw_channel_wechat.utils"),
    )


@pytest.fixture
def wire(private, monkeypatch):
    requests, replies, clients = [], [], []
    actual_client = httpx.AsyncClient

    async def handle(request):
        requests.append(request)
        assert replies, "Unexpected extra platform HTTP request"
        value = replies.pop(0)
        if isinstance(value, Exception):
            raise value
        code, payload = value
        return httpx.Response(code, json=payload)

    def client(**kwargs):
        value = actual_client(
            **kwargs, transport=httpx.MockTransport(handle), trust_env=False
        )
        clients.append(value)
        return value

    monkeypatch.setattr(private.client.httpx, "AsyncClient", client)
    return SimpleNamespace(
        make=private.client.ILinkClient,
        requests=requests,
        replies=replies,
        clients=clients,
    )


@pytest.mark.parametrize("token", ["", "local-bearer"])
def test_headers_preserve_ilink_auth_and_numeric_base64_uin(private, token):
    headers = private.utils.make_headers(token)
    assert headers["Content-Type"] == "application/json"
    assert headers["AuthorizationType"] == "ilink_bot_token"
    uin = base64.b64decode(headers["X-WECHAT-UIN"], validate=True).decode()
    assert uin.isdigit() and 0 <= int(uin) < 0xFFFFFFFF
    if token:
        assert headers["Authorization"] == "Bearer local-bearer"
    else:
        assert "Authorization" not in headers


@pytest.mark.parametrize(
    "key",
    [
        "000102030405060708090a0b0c0d0e0f",
        "AAECAwQFBgcICQoLDA0ODw==",
        "MDAwMTAyMDMwNDA1MDYwNzA4MDkwYTBiMGMwZDBlMGY=",
    ],
)
def test_aes_decrypt_accepts_all_original_key_formats(private, key):
    # NIST AES first block plus a PKCS7 block, independently checked by openssl.
    ciphertext = bytes.fromhex(
        "69c4e0d86a7b0430d8cdb78070b4c55a" "954f64f2e4e86e9eee82d20216684899"
    )
    assert private.utils.aes_ecb_decrypt(ciphertext, key) == bytes.fromhex(
        "00112233445566778899aabbccddeeff"
    )


def test_aes_encrypt_keeps_original_padding_and_bytes(private):
    assert private.utils.aes_ecb_encrypt(
        bytes.fromhex("00112233445566778899aabbccddeeff"),
        "AAECAwQFBgcICQoLDA0ODw==",
    ) == bytes.fromhex(
        "69c4e0d86a7b0430d8cdb78070b4c55a" "954f64f2e4e86e9eee82d20216684899"
    )


def test_aes_rejects_bad_key_and_padding_without_returning_corrupt_media(
    private,
):
    with pytest.raises(ValueError):
        private.utils.aes_ecb_decrypt(b"\x00" * 16, "short")
    with pytest.raises(ValueError):
        private.utils.aes_ecb_decrypt(
            bytes.fromhex("69c4e0d86a7b0430d8cdb78070b4c55a"),
            "AAECAwQFBgcICQoLDA0ODw==",
        )


@pytest.mark.asyncio
async def test_qr_fetch_and_status_preserve_urls_query_auth_and_sixty_seconds(
    wire,
):
    wire.replies.extend(
        [(200, {"qrcode": "scan-A"}), (200, {"status": "scanned"})]
    )
    client = wire.make(bot_token="local-A", base_url="https://wx.test///")
    await client.start()
    try:
        assert await client.get_bot_qrcode() == {"qrcode": "scan-A"}
        assert await client.get_qrcode_status("scan /+") == {
            "status": "scanned"
        }
    finally:
        await client.stop()
    first, second = wire.requests
    assert str(first.url) == (
        "https://wx.test/ilink/bot/get_bot_qrcode?bot_type=3"
    )
    assert second.url.path == "/ilink/bot/get_qrcode_status"
    assert second.url.params["qrcode"] == "scan /+"
    assert first.headers["Authorization"] == "Bearer local-A"
    assert second.extensions["timeout"]["read"] == 60.0
    assert all(client.is_closed for client in wire.clients)


@pytest.mark.asyncio
async def test_poll_and_send_use_original_wire_body_and_independent_timeouts(
    wire,
):
    wire.replies.extend([(200, {"ret": -1}), (200, {"ret": 0})])
    client = wire.make(bot_token="local-A", base_url="https://wx.test")
    await client.start()
    try:
        assert await client.getupdates("cursor-A") == {"ret": -1}
        assert await client.send_text("user-A", "exact body", "context-A") == {
            "ret": 0
        }
    finally:
        await client.stop()
    poll, send = wire.requests
    assert poll.url.path == "/ilink/bot/getupdates"
    assert json.loads(poll.content)["get_updates_buf"] == "cursor-A"
    assert poll.extensions["timeout"]["read"] == 45.0
    body = json.loads(send.content)
    msg = body["msg"]
    assert msg["to_user_id"] == "user-A"
    assert msg["context_token"] == "context-A"
    assert msg["message_type"] == 2
    assert msg["message_state"] == 2
    assert msg["item_list"] == [
        {"type": 1, "text_item": {"text": "exact body"}}
    ]
    assert send.extensions["timeout"]["read"] == 15.0
    assert all(client.is_closed for client in wire.clients)


@pytest.mark.asyncio
async def test_login_retries_read_timeout_and_preserves_confirmed_baseurl(
    wire,
):
    wire.replies.extend(
        [
            httpx.ReadTimeout("local delayed status"),
            (200, {"status": "scanned"}),
            (
                200,
                {
                    "status": "confirmed",
                    "bot_token": "confirmed-A",
                    "baseurl": "https://assigned.test/",
                },
            ),
        ]
    )
    client = wire.make(base_url="https://wx.test")
    await client.start()
    try:
        assert await client.wait_for_login(
            "scan-A", poll_interval=0, max_wait=1
        ) == ("confirmed-A", "https://assigned.test/")
    finally:
        await client.stop()
    assert len(wire.requests) == 3
    assert all(r.url.params["qrcode"] == "scan-A" for r in wire.requests)


@pytest.mark.asyncio
async def test_expired_login_is_a_failure_and_does_not_auto_fetch_again(wire):
    wire.replies.append((200, {"status": "expired"}))
    client = wire.make(base_url="https://wx.test")
    await client.start()
    try:
        with pytest.raises(ChannelError, match="expired"):
            await client.wait_for_login("scan-A", poll_interval=0, max_wait=1)
    finally:
        await client.stop()
    assert len(wire.requests) == 1
    assert wire.requests[0].url.path == "/ilink/bot/get_qrcode_status"


@pytest.mark.asyncio
async def test_http_error_is_not_interpreted_as_a_successful_qr_payload(wire):
    wire.replies.append((503, {"qrcode": "must-not-use"}))
    client = wire.make(base_url="https://wx.test")
    await client.start()
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await client.get_bot_qrcode()
    finally:
        await client.stop()
    assert len(wire.requests) == 1
    assert all(client.is_closed for client in wire.clients)
