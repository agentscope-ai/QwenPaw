# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
import asyncio
import threading
from pathlib import Path

import pytest

from copaw.app.channels.dingtalk.channel import DingTalkChannel
from copaw.app.channels.dingtalk.handler import DingTalkChannelHandler


class _FakeRichFileMessage:
    robot_code = "robot-1"

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def to_dict(self) -> dict:
        return self._payload


class _FakeDownloadResponse:
    def __init__(
        self,
        data: bytes,
        *,
        content_type: str = "application/octet-stream",
        disposition: str = "",
    ) -> None:
        self.status = 200
        self.headers = {
            "Content-Type": content_type,
            "Content-Disposition": disposition,
        }
        self._data = data

    async def read(self) -> bytes:
        return self._data

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _FakeHTTPClient:
    def __init__(self, response: _FakeDownloadResponse) -> None:
        self._response = response

    def get(self, _url: str) -> _FakeDownloadResponse:
        return self._response


@pytest.fixture
def dingtalk_handler_loop():
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    try:
        yield loop
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=3)
        loop.close()


def test_parse_rich_content_preserves_item_filename(
    dingtalk_handler_loop: asyncio.AbstractEventLoop,
) -> None:
    captured: list[dict] = []

    async def fake_fetcher(**kwargs):
        captured.append(kwargs)
        return "/tmp/report.pdf"

    handler = DingTalkChannelHandler(
        dingtalk_handler_loop,
        None,
        "[BOT]",
        fake_fetcher,
    )
    message = _FakeRichFileMessage(
        {
            "content": {
                "richText": [
                    {
                        "type": "file",
                        "downloadCode": "dl-1",
                        "fileName": "报告.pdf",
                    },
                ],
            },
        },
    )

    content = handler._parse_rich_content(message)

    assert captured == [
        {
            "download_code": "dl-1",
            "robot_code": "robot-1",
            "filename": "报告.pdf",
            "filename_hint": "报告.pdf",
        },
    ]
    assert len(content) == 1
    assert content[0].file_url == "/tmp/report.pdf"
    assert content[0].filename == "报告.pdf"


def test_parse_single_download_code_preserves_top_level_filename(
    dingtalk_handler_loop: asyncio.AbstractEventLoop,
) -> None:
    captured: list[dict] = []

    async def fake_fetcher(**kwargs):
        captured.append(kwargs)
        return "/tmp/contract.pdf"

    handler = DingTalkChannelHandler(
        dingtalk_handler_loop,
        None,
        "[BOT]",
        fake_fetcher,
    )
    message = _FakeRichFileMessage(
        {
            "msgtype": "file",
            "content": {
                "downloadCode": "dl-2",
                "fileName": "合同.pdf",
            },
        },
    )

    content = handler._parse_rich_content(message)

    assert captured == [
        {
            "download_code": "dl-2",
            "robot_code": "robot-1",
            "filename": "合同.pdf",
            "filename_hint": "合同.pdf",
        },
    ]
    assert len(content) == 1
    assert content[0].file_url == "/tmp/contract.pdf"
    assert content[0].filename == "合同.pdf"


@pytest.mark.asyncio
async def test_download_media_to_local_preserves_filename_and_sanitizes_path(
    tmp_path: Path,
) -> None:
    channel = DingTalkChannel(
        lambda *args, **kwargs: None,
        True,
        "client-id",
        "client-secret",
        "[BOT]",
        media_dir=str(tmp_path),
    )
    channel._http = _FakeHTTPClient(
        _FakeDownloadResponse(b"%PDF-1.4\npayload"),
    )

    local_path = await channel._download_media_to_local(
        "https://example.com/report",
        "abc123",
        filename="../报表?.pdf",
        filename_hint="file.bin",
    )

    assert local_path is not None
    saved = Path(local_path)
    assert saved.name == "报表_.pdf"
    assert saved.read_bytes() == b"%PDF-1.4\npayload"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["报表_.pdf"]


@pytest.mark.asyncio
async def test_download_media_to_local_uses_magic_suffix_without_temp_file(
    tmp_path: Path,
) -> None:
    channel = DingTalkChannel(
        lambda *args, **kwargs: None,
        True,
        "client-id",
        "client-secret",
        "[BOT]",
        media_dir=str(tmp_path),
    )
    channel._http = _FakeHTTPClient(
        _FakeDownloadResponse(b"%PDF-1.4\npayload"),
    )

    local_path = await channel._download_media_to_local(
        "https://example.com/file",
        "safe456",
        filename_hint="file.bin",
    )

    assert local_path is not None
    saved = Path(local_path)
    assert saved.name == "file.pdf"
    assert saved.read_bytes() == b"%PDF-1.4\npayload"
    assert sorted(p.suffix for p in tmp_path.iterdir()) == [".pdf"]


@pytest.mark.asyncio
async def test_download_media_to_local_appends_short_hash_only_on_collision(
    tmp_path: Path,
) -> None:
    channel = DingTalkChannel(
        lambda *args, **kwargs: None,
        True,
        "client-id",
        "client-secret",
        "[BOT]",
        media_dir=str(tmp_path),
    )
    channel._http = _FakeHTTPClient(
        _FakeDownloadResponse(b"%PDF-1.4\nnew"),
    )
    (tmp_path / "报告.pdf").write_bytes(b"%PDF-1.4\nold")

    local_path = await channel._download_media_to_local(
        "https://example.com/file",
        "deadbeef1234",
        filename="报告.pdf",
        filename_hint="file.bin",
    )

    assert local_path is not None
    saved = Path(local_path)
    assert saved.name == "报告_deadbeef.pdf"
    assert saved.read_bytes() == b"%PDF-1.4\nnew"
