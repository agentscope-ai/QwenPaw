"""Remaining ordinary parser/download duties; only HTTP transport replaced."""

import importlib
from pathlib import Path

import httpx
import pytest

from wechat_closeout_driver_suite import private

__all__ = ["private"]
pytestmark = pytest.mark.asyncio


@pytest.fixture
def download_wire(private, monkeypatch):
    requests, replies, clients = [], [], []
    actual_client = httpx.AsyncClient

    async def handle(request):
        requests.append(request)
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        code, body = reply
        return httpx.Response(code, content=body)

    def client(**kwargs):
        value = actual_client(
            **kwargs, transport=httpx.MockTransport(handle), trust_env=False
        )
        clients.append(value)
        return value

    monkeypatch.setattr(private.client.httpx, "AsyncClient", client)
    return requests, replies, clients


async def test_direct_download_name_and_http_failure(
    private, download_wire, tmp_path
):
    requests, replies, clients = download_wire
    replies.extend([(200, b"data"), (503, b"unavailable")])
    parser = importlib.import_module(
        "qwenpaw_channel_wechat.messages"
    ).WeChatMessageParser(tmp_path / "media")
    client = private.client.ILinkClient()
    await client.start()
    try:
        path = await parser.download(
            client,
            "https://cdn.fixture/image.jpg",
            filename="file<name>with:invalid|chars*.jpg",
        )
        assert path is not None and "wechat_" in path
        assert "<" not in path and ">" not in path
        assert Path(path).read_bytes() == b"data"
        assert (
            await parser.download(
                client,
                "https://cdn.fixture/failure.jpg",
                filename="failure.jpg",
            )
            is None
        )
        assert list((tmp_path / "media").iterdir()) == [Path(path)]
    finally:
        await client.stop()
    assert [str(request.url) for request in requests] == [
        "https://cdn.fixture/image.jpg",
        "https://cdn.fixture/failure.jpg",
    ]
    assert all(client.is_closed for client in clients)


async def test_ordinary_parse_and_legacy_targets(
    private, download_wire, tmp_path
):
    requests, replies, clients = download_wire
    for handle, expected in (
        ("wechat:user123", "user123"),
        ("wechat:group:group456", "group456"),
        ("plain_user_id", "plain_user_id"),
    ):
        target = private.driver.WeChatDriver._target(handle, {})
        assert target["wechat_from_user_id"] == expected
    with pytest.raises(ValueError, match="OUTBOUND_TARGET_UNKNOWN"):
        private.driver.WeChatDriver._target("", {})
    replies.append((200, b"native-image-bytes"))
    parser = importlib.import_module(
        "qwenpaw_channel_wechat.messages"
    ).WeChatMessageParser(tmp_path / "media")
    client = private.client.ILinkClient()
    await client.start()
    try:
        parts = await parser.parse(
            {
                "item_list": [
                    {"type": 1, "text_item": {"text": "document.pdf"}},
                    {
                        "type": 3,
                        "voice_item": {
                            "text_item": {"text": "Voice transcription"}
                        },
                    },
                    {
                        "type": 2,
                        "image_item": {
                            "media": {
                                "encrypt_query_param": "actual-encoded-image"
                            }
                        },
                    },
                ]
            },
            client,
        )
        assert parts[0] == {"type": "text", "text": "Voice transcription"}
        assert len(parts) == 2 and parts[1]["type"] == "image"
        image = Path(parts[1]["image_url"])
        assert image.parent == tmp_path / "media"
        assert image.read_bytes() == b"native-image-bytes"
    finally:
        await client.stop()
    assert len(requests) == 1
    assert (
        requests[0].url.params["encrypted_query_param"]
        == "actual-encoded-image"
    )
    assert all(client.is_closed for client in clients)
