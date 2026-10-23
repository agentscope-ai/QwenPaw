"""Mechanical import retarget of complete frozen Yuanbao pure business oracles."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch
import nturl2path
import pytest

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "plugins/channel/yuanbao"))

from qwenpaw_channel_yuanbao import media as yuanbao_media
from qwenpaw.app.channels import utils as channel_utils

@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (r"C:\media\report.pdf", r"C:\media\report.pdf"),
        ("file:///C:/media/report.pdf", r"C:\media\report.pdf"),
        ("file://C:/media/report.pdf", r"C:\media\report.pdf"),
        ("file:///C:/media/my%20report.pdf", r"C:\media\my report.pdf"),
        (r"\\server\share\report.pdf", r"\\server\share\report.pdf"),
        ("file://server/share/report.pdf", r"\\server\share\report.pdf"),
    ],
)
def test_resolve_windows_media_paths(source, expected):
    """Yuanbao uses Windows drive and UNC conversion on every test host."""
    with (
        patch.object(channel_utils, "os", SimpleNamespace(name="nt")),
        patch.object(channel_utils, "url2pathname", nturl2path.url2pathname),
    ):
        assert yuanbao_media._resolve_local_path(source) == expected


@pytest.mark.parametrize("source_type", ["data", "path", "file_url"])
async def test_media_source_reaches_cos_upload(tmp_path, source_type):
    """Data URLs and existing local references reach the same upload flow."""
    local_file = tmp_path / "report.pdf"
    local_file.write_bytes(b"pdf-data")
    sources = {
        "data": "data:application/pdf;base64,cGRmLWRhdGE=",
        "path": str(local_file),
        "file_url": local_file.as_uri(),
    }
    session = MagicMock()
    config = MagicMock()
    with (
        patch.object(
            yuanbao_media,
            "get_upload_info",
            new=AsyncMock(return_value=config),
        ) as get_info,
        patch.object(
            yuanbao_media,
            "upload_to_cos",
            new=AsyncMock(return_value="https://cdn.example.com/file.pdf"),
        ) as upload,
    ):
        result = await yuanbao_media.download_and_upload_media(
            sources[source_type],
            session,
            "yuanbao.tencent.com",
            {},
        )

    expected_name = "file.pdf" if source_type == "data" else "report.pdf"
    get_info.assert_awaited_once_with(
        session,
        "yuanbao.tencent.com",
        {},
        expected_name,
    )
    upload.assert_awaited_once_with(
        session,
        config,
        b"pdf-data",
        "application/pdf",
    )
    assert result.filename == expected_name
    assert result.size == 8
    assert result.mime_type == "application/pdf"
    assert local_file.read_bytes() == b"pdf-data"


@pytest.fixture
def sample_upload_result():
    """Create a sample UploadResult."""
    from qwenpaw_channel_yuanbao.media import UploadResult

    return UploadResult(
        url="https://cdn.example.com/image.jpg",
        filename="image.jpg",
        size=12345,
        mime_type="image/jpeg",
        uuid_hex="abc123def456",
        width=800,
        height=600,
    )




class TestMediaMsgBody:
    """P1: TIMImageElem / TIMFileElem message body building."""

    def test_build_image_msg_body(self, sample_upload_result):
        from qwenpaw_channel_yuanbao.media import build_image_msg_body

        body = build_image_msg_body(sample_upload_result)

        assert len(body) == 1
        assert body[0]["msg_type"] == "TIMImageElem"
        content = body[0]["msg_content"]
        assert content["uuid"] == "abc123def456"
        assert content["image_format"] == 255
        images = content["image_info_array"]
        assert len(images) == 1
        assert images[0]["url"] == "https://cdn.example.com/image.jpg"
        assert images[0]["width"] == 800
        assert images[0]["height"] == 600
        assert images[0]["size"] == 12345



class TestNormalizeInbound:
    """P1: _normalize_inbound tests."""

    def test_normalize_text_message(self):
        from qwenpaw_channel_yuanbao.platform import YuanbaoPlatform

        data = {
            "callback_command": "C2C.CallbackAfterSendMsg",
            "from_account": "sender123",
            "msg_body": [
                {"msg_type": "TIMTextElem", "msg_content": {"text": "你好"}},
            ],
        }
        result = YuanbaoPlatform._normalize_inbound(data)
        assert result["msg_body"][0]["msg_content"]["text"] == "你好"

    def test_normalize_string_content(self):
        from qwenpaw_channel_yuanbao.platform import YuanbaoPlatform

        data = {
            "msg_body": [
                {"msg_type": "TIMTextElem", "msg_content": '{"text": "hi"}'},
            ],
        }
        result = YuanbaoPlatform._normalize_inbound(data)
        assert result["msg_body"][0]["msg_content"] == {"text": "hi"}

    def test_normalize_invalid_json_string_content(self):
        from qwenpaw_channel_yuanbao.platform import YuanbaoPlatform

        data = {
            "msg_body": [
                {"msg_type": "TIMTextElem", "msg_content": "plain text"},
            ],
        }
        result = YuanbaoPlatform._normalize_inbound(data)
        assert result["msg_body"][0]["msg_content"] == {"text": "plain text"}

    def test_parses_cloud_custom_data_quote(self):
        from qwenpaw_channel_yuanbao.platform import YuanbaoPlatform

        raw = {
            "msg_body": [],
            "cloud_custom_data": (
                '{"quote":{"id":"abc","seq":1,"type":1,"desc":"hi"}}'
            ),
        }
        out = YuanbaoPlatform._normalize_inbound(raw)
        ccd = out["cloud_custom_data"]
        assert isinstance(ccd, dict)
        quote = ccd.get("quote")
        assert isinstance(quote, dict)
        assert quote.get("desc") == "hi"

    def test_cloud_custom_data_empty_string_becomes_empty_dict(self):
        from qwenpaw_channel_yuanbao.platform import YuanbaoPlatform

        out = YuanbaoPlatform._normalize_inbound(
            {"msg_body": [], "cloud_custom_data": ""},
        )
        assert not out["cloud_custom_data"]

    def test_cloud_custom_data_invalid_json_becomes_empty_dict(self):
        from qwenpaw_channel_yuanbao.platform import YuanbaoPlatform

        out = YuanbaoPlatform._normalize_inbound(
            {"msg_body": [], "cloud_custom_data": "{not json"},
        )
        assert not out["cloud_custom_data"]

    def test_cloud_custom_data_missing_field_becomes_empty_dict(self):
        from qwenpaw_channel_yuanbao.platform import YuanbaoPlatform

        out = YuanbaoPlatform._normalize_inbound({"msg_body": []})
        assert out["cloud_custom_data"] == {}




class TestBuildSafeFilename:
    """``_build_safe_filename`` should preserve the original name."""

    def test_preserves_cjk_when_no_conflict(self, tmp_path):
        from qwenpaw_channel_yuanbao.utils import _build_safe_filename

        assert _build_safe_filename("陈灵威.txt", ".txt", tmp_path) == "陈灵威.txt"

    def test_strips_whitespace_keeps_parens(self, tmp_path):
        from qwenpaw_channel_yuanbao.utils import _build_safe_filename

        assert (
            _build_safe_filename("test 副本(1).mp3", ".mp3", tmp_path)
            == "test副本(1).mp3"
        )

    def test_appends_uid_only_on_conflict(self, tmp_path):
        from qwenpaw_channel_yuanbao.utils import _build_safe_filename

        existing = tmp_path / "陈灵威.txt"
        existing.write_text("seed")
        result = _build_safe_filename("陈灵威.txt", ".txt", tmp_path)
        assert result.startswith("陈灵威_")
        assert result.endswith(".txt")
        assert result != "陈灵威.txt"

    def test_blank_filename_uses_yuanbao_prefix(self, tmp_path):
        from qwenpaw_channel_yuanbao.utils import _build_safe_filename

        result = _build_safe_filename("", ".bin", tmp_path)
        assert result.startswith("yuanbao_")
        assert result.endswith(".bin")

    def test_all_whitespace_falls_back_to_file(self, tmp_path):
        from qwenpaw_channel_yuanbao.utils import _build_safe_filename

        # "  " (only whitespace) -> stripped to empty -> "file"
        assert _build_safe_filename("   .txt", ".txt", tmp_path) == "file.txt"
