"""Original quote extraction; separate real HTTP/AES persistence control.

The twelve retargeted extraction units retain the original download seam.
Their deliberately invalid example keys do not establish AES/download proof.
"""

import importlib
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from qwenpaw.schemas import ContentType

ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.asyncio


@pytest.fixture
def parser(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(ROOT / "plugins/channel/wechat"))
    module = importlib.import_module("qwenpaw_channel_wechat.messages")
    return module.WeChatMessageParser(tmp_path / "media")


def _ref_msg(quoted_item):
    return {"message_item": quoted_item}


async def test_quoted_text_prepended(parser):
    text_parts, content_parts = ([], [])
    ref = _ref_msg({"type": 1, "text_item": {"text": "original"}})
    await parser._item(
        ref.get("message_item") or {},
        object(),
        text_parts,
        content_parts,
        quoted=True,
    )
    assert text_parts == ["[quoted message: original]"]
    assert content_parts == []


async def test_quoted_text_empty_ignored(parser):
    text_parts, content_parts = ([], [])
    ref = _ref_msg({"type": 1, "text_item": {"text": "   "}})
    await parser._item(
        ref.get("message_item") or {},
        object(),
        text_parts,
        content_parts,
        quoted=True,
    )
    assert text_parts == []


async def test_quoted_image_downloaded(parser, monkeypatch):
    parser.download = AsyncMock(return_value="/tmp/img.jpg")
    text_parts, content_parts = ([], [])
    ref = _ref_msg(
        {
            "type": 2,
            "image_item": {
                "aeskey": "aabb",
                "media": {"encrypt_query_param": "q=1"},
            },
        }
    )
    await parser._item(
        ref.get("message_item") or {},
        object(),
        text_parts,
        content_parts,
        quoted=True,
    )
    assert len(content_parts) == 1
    assert content_parts[0]["type"] == ContentType.IMAGE
    assert content_parts[0]["image_url"] == "/tmp/img.jpg"


async def test_quoted_image_download_failed(parser):
    parser.download = AsyncMock(return_value=None)
    text_parts, content_parts = ([], [])
    ref = _ref_msg(
        {
            "type": 2,
            "image_item": {
                "aeskey": "aabb",
                "media": {"encrypt_query_param": "q=1"},
            },
        }
    )
    await parser._item(
        ref.get("message_item") or {},
        object(),
        text_parts,
        content_parts,
        quoted=True,
    )
    assert text_parts == ["[quoted image: download failed]"]


async def test_quoted_image_no_url(parser):
    text_parts, content_parts = ([], [])
    ref = _ref_msg({"type": 2, "image_item": {"media": {}}})
    await parser._item(
        ref.get("message_item") or {},
        object(),
        text_parts,
        content_parts,
        quoted=True,
    )
    assert text_parts == ["[quoted image: no url]"]


async def test_quoted_voice_with_transcription(parser):
    text_parts, content_parts = ([], [])
    ref = _ref_msg({"type": 3, "voice_item": {"text_item": {"text": "hello"}}})
    await parser._item(
        ref.get("message_item") or {},
        object(),
        text_parts,
        content_parts,
        quoted=True,
    )
    assert text_parts == ["[quoted voice: hello]"]


async def test_quoted_voice_no_transcription(parser):
    text_parts, content_parts = ([], [])
    ref = _ref_msg({"type": 3, "voice_item": {}})
    await parser._item(
        ref.get("message_item") or {},
        object(),
        text_parts,
        content_parts,
        quoted=True,
    )
    assert text_parts == ["[quoted voice: no transcription]"]


async def test_quoted_file_downloaded(parser):
    parser.download = AsyncMock(return_value="/tmp/doc.pdf")
    text_parts, content_parts = ([], [])
    ref = _ref_msg(
        {
            "type": 4,
            "file_item": {
                "file_name": "doc.pdf",
                "media": {"encrypt_query_param": "q=1", "aes_key": "k"},
            },
        }
    )
    await parser._item(
        ref.get("message_item") or {},
        object(),
        text_parts,
        content_parts,
        quoted=True,
    )
    assert len(content_parts) == 1
    assert content_parts[0]["type"] == ContentType.FILE


async def test_quoted_file_no_url(parser):
    text_parts, content_parts = ([], [])
    ref = _ref_msg({"type": 4, "file_item": {"media": {}}})
    await parser._item(
        ref.get("message_item") or {},
        object(),
        text_parts,
        content_parts,
        quoted=True,
    )
    assert text_parts == ["[quoted file: no url]"]


async def test_quoted_video_downloaded(parser):
    parser.download = AsyncMock(return_value="/tmp/v.mp4")
    text_parts, content_parts = ([], [])
    ref = _ref_msg(
        {
            "type": 5,
            "video_item": {
                "media": {"encrypt_query_param": "q=1", "aes_key": "k"}
            },
        }
    )
    await parser._item(
        ref.get("message_item") or {},
        object(),
        text_parts,
        content_parts,
        quoted=True,
    )
    assert len(content_parts) == 1
    assert content_parts[0]["type"] == ContentType.VIDEO


async def test_empty_ref_msg(parser):
    text_parts, content_parts = ([], [])
    await parser._item(
        {}.get("message_item") or {},
        object(),
        text_parts,
        content_parts,
        quoted=True,
    )
    assert text_parts == []
    assert content_parts == []


async def test_unknown_type_noted(parser):
    text_parts, content_parts = ([], [])
    ref = _ref_msg({"type": 99})
    await parser._item(
        ref.get("message_item") or {},
        object(),
        text_parts,
        content_parts,
        quoted=True,
    )
    assert len(text_parts) == 1


async def test_real_parser_http_aes_and_persisted_image_bytes(
    parser, monkeypatch
):
    module = importlib.import_module("qwenpaw_channel_wechat.client")
    requests, transports = [], []
    actual_client = httpx.AsyncClient
    ciphertext = bytes.fromhex(
        "69c4e0d86a7b0430d8cdb78070b4c55a954f64f2e4e86e9eee82d20216684899"
    )
    plaintext = bytes.fromhex("00112233445566778899aabbccddeeff")
    image_key = "000102030405060708090a0b0c0d0e0f"
    image_ref = "quoted /+?=image"
    unused_key = "invalid-unused-secondary-key"

    async def cdn(request):
        requests.append(request)
        return httpx.Response(200, content=ciphertext)

    def local_http(**kwargs):
        client = actual_client(
            **kwargs,
            transport=httpx.MockTransport(cdn),
            trust_env=False,
        )
        transports.append(client)
        return client

    monkeypatch.setattr(module.httpx, "AsyncClient", local_http)
    client = module.ILinkClient()
    await client.start()
    try:
        parts = await parser.parse(
            {
                "item_list": [
                    {
                        "type": 1,
                        "text_item": {"text": "question"},
                        "ref_msg": {
                            "message_item": {
                                "type": 2,
                                "image_item": {
                                    "aeskey": image_key,
                                    "media": {
                                        "encrypt_query_param": image_ref,
                                        "aes_key": unused_key,
                                    },
                                },
                            }
                        },
                    }
                ]
            },
            client,
        )
    finally:
        await client.stop()
    assert parts[0] == {"type": "text", "text": "question"}
    assert len(parts) == 2 and parts[1]["type"] == "image"
    path = Path(parts[1]["image_url"])
    assert path.parent == parser.media_dir
    assert path.name.endswith("_image.jpg") and path.read_bytes() == plaintext
    assert len(requests) == 1
    assert str(requests[0].url) == (
        "https://novac2c.cdn.weixin.qq.com/c2c/download"
        "?encrypted_query_param=quoted%20%2F%2B%3F%3Dimage"
    )
    assert requests[0].extensions["timeout"]["read"] == 60.0
    assert all(transport.is_closed for transport in transports)
    assert client._client is None
