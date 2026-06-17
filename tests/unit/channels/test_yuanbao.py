# -*- coding: utf-8 -*-
"""
Yuanbao Channel Unit Tests

Tests cover: initialization, factory methods, codec, auth, media upload,
message sending, session routing.

Run:
    pytest tests/unit/channels/test_yuanbao.py -v
"""
# pylint: disable=redefined-outer-name,protected-access,unused-argument
from __future__ import annotations

import struct
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_process():
    """Create mock process handler."""

    async def mock_handler(*_args, **_kwargs):
        mock_event = MagicMock()
        mock_event.object = "message"
        mock_event.status = "completed"
        mock_event.type = "text"
        yield mock_event

    return AsyncMock(side_effect=mock_handler)


@pytest.fixture
def yuanbao_channel(mock_process, tmp_path):
    """Create YuanbaoChannel instance for testing."""
    from qwenpaw.app.channels.yuanbao.channel import YuanbaoChannel

    channel = YuanbaoChannel(
        process=mock_process,
        enabled=True,
        app_id="test_app_key_123",
        app_secret="test_app_secret_456",
        api_domain="yuanbao.tencent.com",
        bot_prefix="[Bot] ",
        media_dir=str(tmp_path / "media"),
    )
    return channel


@pytest.fixture
def connected_channel(yuanbao_channel):
    """Channel with mocked connected state."""
    yuanbao_channel._connected = True
    yuanbao_channel._bot_id = "test_bot_id"
    yuanbao_channel._ws = MagicMock()
    yuanbao_channel._ws.send_bytes = AsyncMock()
    yuanbao_channel._ws.close = AsyncMock()
    yuanbao_channel._session = MagicMock()
    yuanbao_channel._session.closed = False
    yuanbao_channel._token_manager = MagicMock()
    yuanbao_channel._token_manager.get_auth_headers = AsyncMock(
        return_value={"X-ID": "bot_id", "X-Token": "tok", "X-Source": "bot"},
    )
    return yuanbao_channel


@pytest.fixture
def sample_upload_result():
    """Create a sample UploadResult."""
    from qwenpaw.app.channels.yuanbao.media import UploadResult

    return UploadResult(
        url="https://cdn.example.com/image.jpg",
        filename="image.jpg",
        size=12345,
        mime_type="image/jpeg",
        uuid_hex="abc123def456",
        width=800,
        height=600,
    )


# =============================================================================
# P0: Initialization Tests
# =============================================================================


class TestYuanbaoChannelInit:
    """P0: YuanbaoChannel initialization tests."""

    def test_init_stores_basic_config(self, mock_process, tmp_path):
        from qwenpaw.app.channels.yuanbao.channel import YuanbaoChannel

        channel = YuanbaoChannel(
            process=mock_process,
            enabled=True,
            app_id="key_abc",
            app_secret="secret_xyz",
            api_domain="custom.domain.com",
            bot_prefix="[Test] ",
            media_dir=str(tmp_path / "media"),
        )

        assert channel.enabled is True
        assert channel.app_id == "key_abc"
        assert channel.app_secret == "secret_xyz"
        assert channel.api_domain == "custom.domain.com"
        assert channel.bot_prefix == "[Test] "

    def test_init_creates_data_structures(self, yuanbao_channel):
        assert yuanbao_channel._ws is None
        assert yuanbao_channel._session is None
        assert yuanbao_channel._media_session is None
        assert yuanbao_channel._connected is False
        assert yuanbao_channel._reconnect_attempts == 0
        assert yuanbao_channel._bot_id == ""
        assert isinstance(yuanbao_channel._session_map, dict)
        assert yuanbao_channel._token_manager is None

    def test_init_media_dir_from_workspace(self, mock_process, tmp_path):
        from qwenpaw.app.channels.yuanbao.channel import YuanbaoChannel

        workspace = tmp_path / "workspace"
        channel = YuanbaoChannel(
            process=mock_process,
            enabled=True,
            app_id="k",
            app_secret="s",
            workspace_dir=workspace,
        )
        assert channel._media_dir == workspace / "media"

    def test_channel_name(self, yuanbao_channel):
        assert yuanbao_channel.channel == "yuanbao"


# =============================================================================
# P0: Factory Method Tests
# =============================================================================


class TestYuanbaoChannelFactory:
    """P0: Factory method tests."""

    def test_from_config_with_dict(self, mock_process):
        from qwenpaw.app.channels.yuanbao.channel import YuanbaoChannel

        config = {
            "enabled": True,
            "app_id": "dict_key",
            "app_secret": "dict_secret",
            "api_domain": "dict.domain.com",
            "bot_prefix": "[Dict] ",
        }
        channel = YuanbaoChannel.from_config(
            process=mock_process,
            config=config,
        )

        assert channel.enabled is True
        assert channel.app_id == "dict_key"
        assert channel.app_secret == "dict_secret"
        assert channel.api_domain == "dict.domain.com"

    def test_from_config_with_object(self, mock_process):
        from qwenpaw.app.channels.yuanbao.channel import YuanbaoChannel

        config = Mock()
        config.enabled = True
        config.app_id = "obj_key"
        config.app_secret = "obj_secret"
        config.api_domain = "obj.domain.com"
        config.bot_prefix = "[Obj] "
        config.media_dir = ""
        config.dm_policy = "open"
        config.group_policy = "open"
        config.allow_from = []
        config.deny_message = ""
        config.require_mention = True
        config.access_control_dm = False
        config.access_control_group = False

        channel = YuanbaoChannel.from_config(
            process=mock_process,
            config=config,
        )

        assert channel.app_id == "obj_key"
        assert channel.app_secret == "obj_secret"


# =============================================================================
# P0: Session Routing Tests
# =============================================================================


class TestSessionRouting:
    """P0: Session ID resolution and target routing."""

    def test_resolve_session_id_c2c(self, yuanbao_channel):
        result = yuanbao_channel.resolve_session_id("user123")
        assert "user123" in result

    def test_resolve_session_id_group(self, yuanbao_channel):
        result = yuanbao_channel.resolve_session_id(
            "user123",
            {"chat_type": "group", "group_code": "group456"},
        )
        assert "group456" in result

    def test_resolve_send_target_from_session_map(self, connected_channel):
        connected_channel._session_map["session_1"] = {
            "chat_type": "c2c",
            "sender_id": "user_abc",
        }
        target = connected_channel._resolve_send_target(
            "session_1",
            {"session_id": "session_1"},
        )
        assert target == {"chat_type": "c2c", "target_id": "user_abc"}

    def test_resolve_send_target_group(self, connected_channel):
        connected_channel._session_map["session_g"] = {
            "chat_type": "group",
            "group_code": "grp_xyz",
            "sender_id": "user_1",
        }
        target = connected_channel._resolve_send_target(
            "session_g",
            {"session_id": "session_g"},
        )
        assert target == {"chat_type": "group", "target_id": "grp_xyz"}

    def test_resolve_send_target_missing(self, connected_channel):
        target = connected_channel._resolve_send_target(
            "",
            {},
        )
        assert target is None


# =============================================================================
# P1: Media Module Tests
# =============================================================================


class TestMediaHelpers:
    """P1: media.py helper function tests."""

    def test_guess_mime_jpeg(self):
        from qwenpaw.app.channels.yuanbao.media import _guess_mime

        assert _guess_mime("photo.jpg") == "image/jpeg"
        assert _guess_mime("photo.jpeg") == "image/jpeg"

    def test_guess_mime_png(self):
        from qwenpaw.app.channels.yuanbao.media import _guess_mime

        assert _guess_mime("icon.png") == "image/png"

    def test_guess_mime_pdf(self):
        from qwenpaw.app.channels.yuanbao.media import _guess_mime

        assert _guess_mime("doc.pdf") == "application/pdf"

    def test_guess_mime_unknown(self):
        from qwenpaw.app.channels.yuanbao.media import _guess_mime

        assert _guess_mime("data.xyz") == "application/octet-stream"

    def test_parse_image_size_png(self):
        from qwenpaw.app.channels.yuanbao.media import _parse_image_size

        # Minimal PNG header: width=100, height=200
        header = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
        header += struct.pack(">II", 100, 200)
        width, height = _parse_image_size(header)
        assert width == 100
        assert height == 200

    def test_parse_image_size_unknown(self):
        from qwenpaw.app.channels.yuanbao.media import _parse_image_size

        width, height = _parse_image_size(b"not an image")
        assert width == 0
        assert height == 0

    def test_resolve_local_path_file_uri(self):
        from qwenpaw.app.channels.yuanbao.media import _resolve_local_path

        assert _resolve_local_path("file:///tmp/test.jpg") == "/tmp/test.jpg"

    def test_resolve_local_path_absolute(self):
        from qwenpaw.app.channels.yuanbao.media import _resolve_local_path

        assert _resolve_local_path("/tmp/test.jpg") == "/tmp/test.jpg"

    def test_resolve_local_path_url_returns_none(self):
        from qwenpaw.app.channels.yuanbao.media import _resolve_local_path

        assert _resolve_local_path("https://example.com/img.jpg") is None

    def test_resolve_local_path_empty(self):
        from qwenpaw.app.channels.yuanbao.media import _resolve_local_path

        assert _resolve_local_path("") is None


class TestMediaMsgBody:
    """P1: TIMImageElem / TIMFileElem message body building."""

    def test_build_image_msg_body(self, sample_upload_result):
        from qwenpaw.app.channels.yuanbao.media import build_image_msg_body

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

    def test_build_file_msg_body(self):
        from qwenpaw.app.channels.yuanbao.media import (
            UploadResult,
            build_file_msg_body,
        )

        result = UploadResult(
            url="https://cdn.example.com/doc.pdf",
            filename="report.pdf",
            size=99999,
            mime_type="application/pdf",
            uuid_hex="file_uuid_hex",
        )
        body = build_file_msg_body(result)

        assert len(body) == 1
        assert body[0]["msg_type"] == "TIMFileElem"
        content = body[0]["msg_content"]
        assert content["file_name"] == "report.pdf"
        assert content["file_size"] == 99999
        assert content["url"] == "https://cdn.example.com/doc.pdf"
        assert content["uuid"] == "file_uuid_hex"


class TestCosSignature:
    """P1: COS HMAC-SHA1 signature generation."""

    def test_sign_cos_request_format(self):
        from qwenpaw.app.channels.yuanbao.media import _sign_cos_request

        auth = _sign_cos_request(
            secret_id="AKIDxxx",
            secret_key="secretyyy",
            method="PUT",
            pathname="/upload/file.jpg",
            headers={"host": "bucket.cos.region.myqcloud.com"},
            start_time=1700000000,
            expired_time=1700003600,
        )

        assert "q-sign-algorithm=sha1" in auth
        assert "q-ak=AKIDxxx" in auth
        assert "q-sign-time=1700000000;1700003600" in auth
        assert "q-key-time=1700000000;1700003600" in auth
        assert "q-header-list=host" in auth
        assert "q-url-param-list=" in auth
        assert "q-signature=" in auth

    def test_sign_cos_request_deterministic(self):
        from qwenpaw.app.channels.yuanbao.media import _sign_cos_request

        args = {
            "secret_id": "id",
            "secret_key": "key",
            "method": "PUT",
            "pathname": "/path",
            "headers": {"host": "h"},
            "start_time": 100,
            "expired_time": 200,
        }
        assert _sign_cos_request(**args) == _sign_cos_request(**args)


# =============================================================================
# P1: Auth Tests
# =============================================================================


class TestAuthSignature:
    """P1: Auth signature computation."""

    def test_compute_signature(self):
        from qwenpaw.app.channels.yuanbao.auth import _compute_signature

        sig = _compute_signature(
            nonce="abc123",
            timestamp="2026-01-01 00:00:00",
            app_id="test_key",
            app_secret="test_secret",
        )
        assert isinstance(sig, str)
        assert len(sig) > 0

    def test_compute_signature_deterministic(self):
        from qwenpaw.app.channels.yuanbao.auth import _compute_signature

        args = ("nonce1", "2026-01-01 00:00:00", "key", "secret")
        assert _compute_signature(*args) == _compute_signature(*args)

    def test_compute_signature_changes_with_nonce(self):
        from qwenpaw.app.channels.yuanbao.auth import _compute_signature

        sig1 = _compute_signature("nonce1", "ts", "key", "secret")
        sig2 = _compute_signature("nonce2", "ts", "key", "secret")
        assert sig1 != sig2


@pytest.mark.asyncio
class TestTokenManager:
    """P1: TokenManager lifecycle tests."""

    async def test_token_manager_init(self):
        from qwenpaw.app.channels.yuanbao.auth import TokenManager

        manager = TokenManager(
            app_id="test_key",
            app_secret="test_secret",
            api_domain="yuanbao.tencent.com",
        )

        assert manager.app_id == "test_key"
        assert manager.app_secret == "test_secret"
        assert manager._cache is None

    async def test_get_auth_headers(self):
        from qwenpaw.app.channels.yuanbao.auth import (
            SignTokenResult,
            TokenCache,
            TokenManager,
        )
        import time

        manager = TokenManager("k", "s")
        manager._cache = TokenCache(
            data=SignTokenResult(
                bot_id="bot_123",
                token="tok_abc",
                source="bot",
                duration=3600,
            ),
            expires_at=time.time() + 3600,
        )

        headers = await manager.get_auth_headers()
        assert headers["X-ID"] == "bot_123"
        assert headers["X-Token"] == "tok_abc"
        assert headers["X-Source"] == "bot"

        await manager.close()


# =============================================================================
# P1: Send Tests
# =============================================================================


@pytest.mark.asyncio
class TestSendText:
    """P1: Text message sending."""

    async def test_send_not_connected(self, yuanbao_channel):
        """Send should silently return when not connected."""
        await yuanbao_channel.send("handle", "hello")
        # No error raised

    async def test_send_empty_text(self, connected_channel):
        """Send should skip empty text."""
        connected_channel._session_map["h"] = {
            "chat_type": "c2c",
            "sender_id": "u",
        }
        await connected_channel.send("h", "", {"session_id": "h"})
        connected_channel._ws.send_bytes.assert_not_called()

    async def test_send_text_calls_ws(self, connected_channel):
        """Send should encode and send via WebSocket."""
        connected_channel._session_map["sess"] = {
            "chat_type": "c2c",
            "sender_id": "user_1",
        }

        with patch(
            "qwenpaw.app.channels.yuanbao.channel.build_send_c2c_msg",
        ) as mock_build:
            mock_build.return_value = (b"\x00\x01\x02", "msg_id_1")
            await connected_channel.send(
                "sess",
                "hello world",
                {"session_id": "sess"},
            )

        connected_channel._ws.send_bytes.assert_called_once_with(
            b"\x00\x01\x02",
        )


# =============================================================================
# P1: Media Send Tests
# =============================================================================


@pytest.mark.asyncio
class TestSendMedia:
    """P1: Media upload and sending."""

    async def test_extract_media_url_image(self, connected_channel):
        from agentscope_runtime.engine.schemas.agent_schemas import ContentType

        part = MagicMock()
        part.type = ContentType.IMAGE
        part.image_url = "https://example.com/photo.jpg"

        url = connected_channel._extract_media_url(part)
        assert url == "https://example.com/photo.jpg"

    async def test_extract_media_url_file(self, connected_channel):
        from agentscope_runtime.engine.schemas.agent_schemas import ContentType

        part = MagicMock()
        part.type = ContentType.FILE
        part.file_url = "/tmp/report.pdf"
        part.file_id = ""

        url = connected_channel._extract_media_url(part)
        assert url == "/tmp/report.pdf"

    async def test_extract_media_url_empty(self, connected_channel):
        from agentscope_runtime.engine.schemas.agent_schemas import ContentType

        part = MagicMock()
        part.type = ContentType.TEXT
        url = connected_channel._extract_media_url(part)
        assert url == ""

    async def test_send_media_part_upload_success(self, connected_channel):
        """Media part should upload to COS and send via WebSocket."""
        from agentscope_runtime.engine.schemas.agent_schemas import ContentType
        from qwenpaw.app.channels.yuanbao.media import UploadResult

        part = MagicMock()
        part.type = ContentType.IMAGE
        part.image_url = "https://example.com/photo.jpg"

        mock_result = UploadResult(
            url="https://cdn.cos.com/uploaded.jpg",
            filename="photo.jpg",
            size=5000,
            mime_type="image/jpeg",
            uuid_hex="md5hex",
            width=640,
            height=480,
        )

        with patch(
            "qwenpaw.app.channels.yuanbao.channel.download_and_upload_media",
            new_callable=AsyncMock,
            return_value=mock_result,
        ), patch.object(
            connected_channel,
            "_send_raw_msg_body",
            new_callable=AsyncMock,
        ) as mock_send_raw, patch.object(
            connected_channel,
            "_get_or_create_http_session",
            new_callable=AsyncMock,
            return_value=MagicMock(),
        ):
            await connected_channel._send_media_part("c2c", "user1", part)

        mock_send_raw.assert_called_once()
        call_args = mock_send_raw.call_args
        assert call_args[0][0] == "c2c"
        assert call_args[0][1] == "user1"
        msg_body = call_args[0][2]
        assert msg_body[0]["msg_type"] == "TIMImageElem"

    async def test_send_media_part_upload_failure_fallback(
        self,
        connected_channel,
    ):
        """Failed upload should fall back to text link."""
        from agentscope_runtime.engine.schemas.agent_schemas import ContentType

        part = MagicMock()
        part.type = ContentType.IMAGE
        part.image_url = "https://example.com/photo.jpg"

        with patch(
            "qwenpaw.app.channels.yuanbao.channel.download_and_upload_media",
            new_callable=AsyncMock,
            side_effect=RuntimeError("COS upload failed"),
        ), patch.object(
            connected_channel,
            "_send_text_message",
            new_callable=AsyncMock,
        ) as mock_text, patch.object(
            connected_channel,
            "_get_or_create_http_session",
            new_callable=AsyncMock,
            return_value=MagicMock(),
        ):
            await connected_channel._send_media_part("c2c", "user1", part)

        mock_text.assert_called_once()
        fallback_text = mock_text.call_args[0][2]
        assert "图片" in fallback_text
        assert "https://example.com/photo.jpg" in fallback_text

    async def test_media_session_is_independent(self, connected_channel):
        """_media_session should be separate from _session."""
        connected_channel._media_session = None
        session = await connected_channel._get_or_create_http_session()
        assert connected_channel._media_session is session
        assert (
            connected_channel._media_session is not connected_channel._session
        )


# =============================================================================
# P1: Codec Tests
# =============================================================================


class TestCodecHelpers:
    """P1: Codec encode/decode helpers."""

    def test_to_proto_msg_body_text(self):
        from qwenpaw.app.channels.yuanbao.codec import _to_proto_msg_body

        elements = [
            {"msg_type": "TIMTextElem", "msg_content": {"text": "hello"}},
        ]
        result = _to_proto_msg_body(elements)
        assert len(result) == 1
        assert result[0]["msgType"] == "TIMTextElem"

    def test_to_proto_msg_body_image(self):
        from qwenpaw.app.channels.yuanbao.codec import _to_proto_msg_body

        elements = [
            {
                "msg_type": "TIMImageElem",
                "msg_content": {
                    "uuid": "img_uuid",
                    "image_format": 255,
                    "image_info_array": [
                        {
                            "type": 1,
                            "size": 1000,
                            "width": 100,
                            "height": 100,
                            "url": "https://cdn.example.com/img.jpg",
                        },
                    ],
                },
            },
        ]
        result = _to_proto_msg_body(elements)
        assert len(result) == 1
        assert result[0]["msgType"] == "TIMImageElem"
        # msgContent is a dict (not JSON string) in _to_proto_msg_body
        content = result[0]["msgContent"]
        assert content["uuid"] == "img_uuid"
        assert "imageInfoArray" in content

    def test_from_proto_msg_body(self):
        from qwenpaw.app.channels.yuanbao.codec import _from_proto_msg_body

        # _from_proto_msg_body expects msgContent as a dict, not JSON string
        elements = [
            {
                "msgType": "TIMTextElem",
                "msgContent": {"text": "world"},
            },
        ]
        result = _from_proto_msg_body(elements)
        assert len(result) == 1
        assert result[0]["msg_type"] == "TIMTextElem"
        assert result[0]["msg_content"]["text"] == "world"


# =============================================================================
# P1: Inbound Message Handling Tests
# =============================================================================


class TestHelperFunctions:
    """P1: Helper function tests (_short_id, _sender_display)."""

    def test_short_id_long_string(self):
        from qwenpaw.app.channels.yuanbao.channel import _short_id

        result = _short_id(
            "CK8kfT4SpnXTsZg7ovLVTzWJLv8EymvNXO1BhLuAgOYwVFC1HLHzx5qq7AG0zjPq",
        )
        assert result == "7AG0zjPq"
        assert len(result) == 8

    def test_short_id_short_string(self):
        from qwenpaw.app.channels.yuanbao.channel import _short_id

        result = _short_id("abc")
        assert result == "abc"

    def test_sender_display_normal(self):
        from qwenpaw.app.channels.yuanbao.channel import _sender_display

        result = _sender_display(
            "灰",
            "CK8kfT4SpnXTsZg7ovLVTzWJLv8EymvNXO1BhLuAgOYwVFC1HLHzx5qq7AG0zjPq",
        )
        assert result == "灰#zjPq"

    def test_sender_display_empty_nickname(self):
        from qwenpaw.app.channels.yuanbao.channel import _sender_display

        result = _sender_display("", "abcdefgh")
        assert result == "unknown#efgh"

    def test_sender_display_short_id(self):
        from qwenpaw.app.channels.yuanbao.channel import _sender_display

        result = _sender_display("Test", "ab")
        assert result == "Test#ab"


class TestNormalizeInbound:
    """P1: _normalize_inbound tests."""

    def test_normalize_text_message(self):
        from qwenpaw.app.channels.yuanbao.channel import YuanbaoChannel

        data = {
            "callback_command": "C2C.CallbackAfterSendMsg",
            "from_account": "sender123",
            "msg_body": [
                {"msg_type": "TIMTextElem", "msg_content": {"text": "你好"}},
            ],
        }
        result = YuanbaoChannel._normalize_inbound(data)
        assert result["msg_body"][0]["msg_content"]["text"] == "你好"

    def test_normalize_string_content(self):
        from qwenpaw.app.channels.yuanbao.channel import YuanbaoChannel

        data = {
            "msg_body": [
                {"msg_type": "TIMTextElem", "msg_content": '{"text": "hi"}'},
            ],
        }
        result = YuanbaoChannel._normalize_inbound(data)
        assert result["msg_body"][0]["msg_content"] == {"text": "hi"}

    def test_normalize_invalid_json_string_content(self):
        from qwenpaw.app.channels.yuanbao.channel import YuanbaoChannel

        data = {
            "msg_body": [
                {"msg_type": "TIMTextElem", "msg_content": "plain text"},
            ],
        }
        result = YuanbaoChannel._normalize_inbound(data)
        assert result["msg_body"][0]["msg_content"] == {"text": "plain text"}

    def test_parses_cloud_custom_data_quote(self):
        from qwenpaw.app.channels.yuanbao.channel import YuanbaoChannel

        raw = {
            "msg_body": [],
            "cloud_custom_data": (
                '{"quote":{"id":"abc","seq":1,"type":1,"desc":"hi"}}'
            ),
        }
        out = YuanbaoChannel._normalize_inbound(raw)
        ccd = out["cloud_custom_data"]
        assert isinstance(ccd, dict)
        quote = ccd.get("quote")
        assert isinstance(quote, dict)
        assert quote.get("desc") == "hi"

    def test_cloud_custom_data_empty_string_becomes_empty_dict(self):
        from qwenpaw.app.channels.yuanbao.channel import YuanbaoChannel

        out = YuanbaoChannel._normalize_inbound(
            {"msg_body": [], "cloud_custom_data": ""},
        )
        assert not out["cloud_custom_data"]

    def test_cloud_custom_data_invalid_json_becomes_empty_dict(self):
        from qwenpaw.app.channels.yuanbao.channel import YuanbaoChannel

        out = YuanbaoChannel._normalize_inbound(
            {"msg_body": [], "cloud_custom_data": "{not json"},
        )
        assert not out["cloud_custom_data"]

    def test_cloud_custom_data_missing_field_becomes_empty_dict(self):
        from qwenpaw.app.channels.yuanbao.channel import YuanbaoChannel

        out = YuanbaoChannel._normalize_inbound({"msg_body": []})
        assert out["cloud_custom_data"] == {}


@pytest.mark.asyncio
class TestParseMsgBody:
    """P1: _parse_msg_body tests."""

    async def test_parse_text_elem(self, connected_channel):
        msg_body = [
            {"msg_type": "TIMTextElem", "msg_content": {"text": "你好呀"}},
        ]
        parts, mentioned = await connected_channel._parse_msg_body(msg_body)
        assert len(parts) == 1
        assert parts[0].text == "你好呀"
        assert mentioned is False

    async def test_parse_custom_elem_at_mention(self, connected_channel):
        """TIMCustomElem with elem_type=1002 should set bot_mentioned."""
        import json

        connected_channel._bot_id = "test_bot_id"
        msg_body = [
            {
                "msg_type": "TIMCustomElem",
                "msg_content": {
                    "data": json.dumps(
                        {
                            "elem_type": 1002,
                            "user_id": "test_bot_id",
                            "text": "@Bot",
                        },
                    ),
                    "desc": "@Bot",
                },
            },
            {"msg_type": "TIMTextElem", "msg_content": {"text": "hello"}},
        ]
        parts, mentioned = await connected_channel._parse_msg_body(
            msg_body,
            is_group=True,
        )
        assert mentioned is True
        assert len(parts) == 1
        assert parts[0].text == "hello"

    async def test_parse_custom_elem_at_other(self, connected_channel):
        """TIMCustomElem mentioning another user should not set mentioned."""
        import json

        connected_channel._bot_id = "test_bot_id"
        msg_body = [
            {
                "msg_type": "TIMCustomElem",
                "msg_content": {
                    "data": json.dumps(
                        {
                            "elem_type": 1002,
                            "user_id": "other_user",
                        },
                    ),
                },
            },
            {"msg_type": "TIMTextElem", "msg_content": {"text": "hey"}},
        ]
        parts, mentioned = await connected_channel._parse_msg_body(
            msg_body,
            is_group=True,
        )
        assert mentioned is False
        assert len(parts) == 1

    async def test_parse_image_elem(self, connected_channel, tmp_path):
        """TIMImageElem should download and return ImageContent."""
        connected_channel._media_dir = tmp_path
        msg_body = [
            {
                "msg_type": "TIMImageElem",
                "msg_content": {
                    "uuid": "img.jpg",
                    "image_info_array": [
                        {"type": 1, "url": "https://example.com/img.jpg"},
                    ],
                },
            },
        ]

        async def fake_download(url, media_dir, filename=""):
            target = media_dir / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"\x00")
            return str(target)

        with patch(
            "qwenpaw.app.channels.yuanbao.channel.download_media",
            side_effect=fake_download,
        ), patch.object(
            connected_channel,
            "_resolve_media_url",
            new_callable=AsyncMock,
            return_value="https://example.com/img.jpg",
        ):
            parts, _ = await connected_channel._parse_msg_body(msg_body)

        assert len(parts) == 1
        assert parts[0].image_url.startswith("file://")
        assert parts[0].image_url.endswith("image.jpg")

    async def test_parse_empty_body(self, connected_channel):
        parts, mentioned = await connected_channel._parse_msg_body([])
        assert parts == []
        assert mentioned is False

    async def test_parse_file_elem_audio_routed_to_audio_content(
        self,
        connected_channel,
        tmp_path,
    ):
        """TIMFileElem with audio suffix should yield AudioContent."""
        from agentscope_runtime.engine.schemas.agent_schemas import (
            AudioContent,
        )

        connected_channel._media_dir = tmp_path

        async def fake_download(url, media_dir, filename=""):
            target = media_dir / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"\x00")
            return str(target)

        with patch(
            "qwenpaw.app.channels.yuanbao.channel.download_media",
            side_effect=fake_download,
        ):
            connected_channel._resolve_media_url = AsyncMock(
                side_effect=lambda u: u,
            )
            parts, _ = await connected_channel._parse_msg_body(
                [
                    {
                        "msg_type": "TIMFileElem",
                        "msg_content": {
                            "url": "https://cdn.example.com/x",
                            "file_name": "test_副本.mp3",
                        },
                    },
                ],
            )

        assert len(parts) == 1
        assert isinstance(parts[0], AudioContent)

    async def test_parse_file_elem_doc_routed_to_file_content(
        self,
        connected_channel,
        tmp_path,
    ):
        """TIMFileElem with non-audio suffix should yield FileContent."""
        from agentscope_runtime.engine.schemas.agent_schemas import (
            FileContent,
        )

        connected_channel._media_dir = tmp_path

        async def fake_download(url, media_dir, filename=""):
            target = media_dir / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"text")
            return str(target)

        with patch(
            "qwenpaw.app.channels.yuanbao.channel.download_media",
            side_effect=fake_download,
        ):
            connected_channel._resolve_media_url = AsyncMock(
                side_effect=lambda u: u,
            )
            parts, _ = await connected_channel._parse_msg_body(
                [
                    {
                        "msg_type": "TIMFileElem",
                        "msg_content": {
                            "url": "https://cdn.example.com/x",
                            "file_name": "陈灵威.txt",
                        },
                    },
                ],
            )

        assert len(parts) == 1
        assert isinstance(parts[0], FileContent)
        assert parts[0].filename == "陈灵威.txt"

    async def test_parse_file_elem_without_filename_uses_fallback(
        self,
        connected_channel,
        tmp_path,
    ):
        """Missing ``file_name`` should fall back to literal ``file``."""
        from agentscope_runtime.engine.schemas.agent_schemas import (
            FileContent,
        )

        connected_channel._media_dir = tmp_path

        async def fake_download(url, media_dir, filename=""):
            target = media_dir / (filename or "file")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"x")
            return str(target)

        with patch(
            "qwenpaw.app.channels.yuanbao.channel.download_media",
            side_effect=fake_download,
        ):
            connected_channel._resolve_media_url = AsyncMock(
                side_effect=lambda u: u,
            )
            parts, _ = await connected_channel._parse_msg_body(
                [
                    {
                        "msg_type": "TIMFileElem",
                        "msg_content": {
                            "url": "https://cdn.example.com/x",
                        },
                    },
                ],
            )

        assert len(parts) == 1
        assert isinstance(parts[0], FileContent)
        assert parts[0].filename == "file"

    async def test_parse_image_elem_download_failure_emits_placeholder(
        self,
        connected_channel,
        tmp_path,
    ):
        """Failed download should surface a TextContent placeholder."""
        from agentscope_runtime.engine.schemas.agent_schemas import (
            TextContent,
        )

        connected_channel._media_dir = tmp_path

        with patch(
            "qwenpaw.app.channels.yuanbao.channel.download_media",
            new=AsyncMock(return_value=None),
        ):
            connected_channel._resolve_media_url = AsyncMock(
                side_effect=lambda u: u,
            )
            parts, _ = await connected_channel._parse_msg_body(
                [
                    {
                        "msg_type": "TIMImageElem",
                        "msg_content": {
                            "image_info_array": [
                                {"url": "https://cdn/example.jpg"},
                            ],
                        },
                    },
                ],
            )

        assert len(parts) == 1
        assert isinstance(parts[0], TextContent)
        assert parts[0].text == "[image: download failed]"


@pytest.mark.asyncio
class TestHandleChatMessage:
    """P1: _handle_chat_message integration tests."""

    async def test_dedup_drops_duplicate(self, connected_channel):
        """Same msg_id should be dropped on second call."""
        connected_channel._enqueue = MagicMock()
        inbound = {
            "callback_command": "C2C.CallbackAfterSendMsg",
            "from_account": "sender_abc",
            "sender_nickname": "灰",
            "msg_id": "msg_123",
            "msg_body": [
                {"msg_type": "TIMTextElem", "msg_content": {"text": "hi"}},
            ],
        }
        await connected_channel._handle_chat_message(inbound)
        await connected_channel._handle_chat_message(inbound)
        assert connected_channel._enqueue.call_count == 1

    async def test_bot_account_filtered_by_default(self, connected_channel):
        """Bot accounts (bot_ prefix) should be ignored by default."""
        connected_channel._enqueue = MagicMock()
        connected_channel.accept_bot_messages = False
        inbound = {
            "callback_command": "C2C.CallbackAfterSendMsg",
            "from_account": "bot_test_bot_id",
            "sender_nickname": "Bot",
            "msg_id": "msg_self",
            "msg_body": [
                {"msg_type": "TIMTextElem", "msg_content": {"text": "echo"}},
            ],
        }
        await connected_channel._handle_chat_message(inbound)
        connected_channel._enqueue.assert_not_called()

    async def test_group_without_mention_filtered(self, connected_channel):
        """Group msg without @bot should be filtered when require_mention."""
        connected_channel._enqueue = MagicMock()
        connected_channel.require_mention = True
        inbound = {
            "callback_command": "Group.CallbackAfterSendMsg",
            "from_account": "sender_abc",
            "sender_nickname": "灰",
            "group_code": "293831858",
            "msg_id": "msg_grp_1",
            "msg_body": [
                {"msg_type": "TIMTextElem", "msg_content": {"text": "你是谁"}},
            ],
        }
        await connected_channel._handle_chat_message(inbound)
        connected_channel._enqueue.assert_not_called()

    async def test_group_with_mention_passes(self, connected_channel):
        """Group msg with @bot should pass through."""
        import json

        connected_channel._enqueue = MagicMock()
        connected_channel.require_mention = True
        connected_channel._bot_id = "test_bot_id"
        inbound = {
            "callback_command": "Group.CallbackAfterSendMsg",
            "from_account": "sender_abc",
            "sender_nickname": "灰",
            "group_code": "293831858",
            "msg_id": "msg_grp_2",
            "msg_body": [
                {
                    "msg_type": "TIMCustomElem",
                    "msg_content": {
                        "data": json.dumps(
                            {
                                "elem_type": 1002,
                                "user_id": "test_bot_id",
                            },
                        ),
                        "desc": "@Bot",
                    },
                },
                {"msg_type": "TIMTextElem", "msg_content": {"text": "1"}},
            ],
        }
        await connected_channel._handle_chat_message(inbound)
        connected_channel._enqueue.assert_called_once()

    async def test_c2c_message_enqueues_correct_payload(
        self,
        connected_channel,
    ):
        """C2C message should produce correct native payload."""
        connected_channel._enqueue = MagicMock()
        inbound = {
            "callback_command": "C2C.CallbackAfterSendMsg",
            "from_account": (
                "CK8kfT4SpnXTsZg7ovLVTzWJLv8Eymv"
                "NXO1BhLuAgOYwVFC1HLHzx5qq7AG0zjPq"
            ),
            "sender_nickname": "灰",
            "msg_id": "msg_c2c_1",
            "msg_body": [
                {"msg_type": "TIMTextElem", "msg_content": {"text": "你好呀"}},
            ],
        }
        await connected_channel._handle_chat_message(inbound)

        native = connected_channel._enqueue.call_args[0][0]
        assert native["channel_id"] == "yuanbao"
        assert native["sender_id"] == "灰#zjPq"
        expected_sender = (
            "CK8kfT4SpnXTsZg7ovLVTzWJLv8Eymv"
            "NXO1BhLuAgOYwVFC1HLHzx5qq7AG0zjPq"
        )
        assert native["acl_sender_id"] == expected_sender
        assert native["session_id"] == "7AG0zjPq"
        assert native["meta"]["chat_type"] == "c2c"
        assert native["meta"]["user_name"] == "灰"

    async def test_session_map_persisted(self, connected_channel, tmp_path):
        """Session map should be saved to disk after handling message."""
        connected_channel._enqueue = MagicMock()
        connected_channel._workspace_dir = tmp_path
        inbound = {
            "callback_command": "C2C.CallbackAfterSendMsg",
            "from_account": "sender12345678",
            "sender_nickname": "Test",
            "msg_id": "msg_persist",
            "msg_body": [
                {"msg_type": "TIMTextElem", "msg_content": {"text": "hi"}},
            ],
        }
        await connected_channel._handle_chat_message(inbound)

        session_file = tmp_path / "yuanbao_sessions.json"
        assert session_file.exists()

    async def test_bot_message_filtered_by_default(self, connected_channel):
        """Bot messages should be dropped when accept_bot_messages is False."""
        import json

        connected_channel._enqueue = MagicMock()
        connected_channel.accept_bot_messages = False
        inbound = {
            "callback_command": "Group.CallbackAfterSendMsg",
            "from_account": "szUvRH8s4ekettawNjDREmAG4W7h",
            "sender_nickname": "元宝",
            "group_code": "293831858",
            "msg_id": "msg_bot_1",
            "msg_body": [
                {
                    "msg_type": "TIMTextElem",
                    "msg_content": {
                        "text": "在呢～",
                        "data": json.dumps(
                            {
                                "elem_type": 1013,
                                "text": "在呢～",
                                "user_id": "",
                                "content": "",
                            },
                        ),
                    },
                },
            ],
        }
        await connected_channel._handle_chat_message(inbound)
        connected_channel._enqueue.assert_not_called()

    async def test_bot_message_accepted_when_enabled(self, connected_channel):
        """Bot messages pass through when accept_bot_messages is True."""
        import json

        connected_channel._enqueue = MagicMock()
        connected_channel.accept_bot_messages = True
        connected_channel.require_mention = False
        inbound = {
            "callback_command": "Group.CallbackAfterSendMsg",
            "from_account": "szUvRH8s4ekettawNjDREmAG4W7h",
            "sender_nickname": "元宝",
            "group_code": "293831858",
            "msg_id": "msg_bot_2",
            "msg_body": [
                {
                    "msg_type": "TIMTextElem",
                    "msg_content": {
                        "text": "在呢～",
                        "data": json.dumps(
                            {
                                "elem_type": 1013,
                                "text": "在呢～",
                                "user_id": "",
                                "content": "",
                            },
                        ),
                    },
                },
            ],
        }
        await connected_channel._handle_chat_message(inbound)
        connected_channel._enqueue.assert_called_once()

    async def test_custom_bot_filtered_by_from_account_prefix(
        self,
        connected_channel,
    ):
        """Custom bots with bot_ prefixed from_account should be filtered."""
        connected_channel._enqueue = MagicMock()
        connected_channel.accept_bot_messages = False
        inbound = {
            "callback_command": "Group.CallbackAfterSendMsg",
            "from_account": "bot_3c71636ecdf9455783ab22d3bfa21fd2",
            "sender_nickname": "灰的Bot3",
            "group_code": "293831858",
            "msg_id": "msg_custom_bot_1",
            "msg_body": [
                {
                    "msg_type": "TIMTextElem",
                    "msg_content": {"text": "收到！"},
                },
            ],
        }
        await connected_channel._handle_chat_message(inbound)
        connected_channel._enqueue.assert_not_called()


# =============================================================================
# P2: Cleanup Tests
# =============================================================================


@pytest.mark.asyncio
class TestCleanup:
    """P2: Resource cleanup tests."""

    async def test_cleanup_closes_media_session(self, connected_channel):
        mock_media_session = MagicMock()
        mock_media_session.close = AsyncMock()
        connected_channel._media_session = mock_media_session

        await connected_channel._cleanup_session()

        mock_media_session.close.assert_called_once()
        assert connected_channel._media_session is None

    async def test_cleanup_handles_no_media_session(self, connected_channel):
        connected_channel._media_session = None
        await connected_channel._cleanup_session()
        assert connected_channel._media_session is None


# =============================================================================
# P1: Filename / Extension Preservation (utils.py)
# =============================================================================


class TestResolveExtension:
    """``_resolve_extension`` should prefer the original filename suffix."""

    def test_filename_suffix_takes_priority_over_octet_stream(self):
        from qwenpaw.app.channels.yuanbao.utils import _resolve_extension

        # CDN often returns application/octet-stream; the real .txt must
        # not be silently rewritten to .bin.
        assert (
            _resolve_extension(
                "application/octet-stream",
                "陈灵威.txt",
            )
            == ".txt"
        )

    def test_filename_suffix_takes_priority_over_audio_mpeg(self):
        from qwenpaw.app.channels.yuanbao.utils import _resolve_extension

        # audio/mpeg may guess to .mpga depending on mime db; .mp3 must win.
        assert _resolve_extension("audio/mpeg", "test_副本.mp3") == ".mp3"

    def test_falls_back_to_content_type_when_no_filename_suffix(self):
        from qwenpaw.app.channels.yuanbao.utils import _resolve_extension

        ext = _resolve_extension("image/jpeg", "noext")
        assert ext in (".jpg", ".jpeg", ".jpe")

    def test_falls_back_to_bin_when_nothing_known(self):
        from qwenpaw.app.channels.yuanbao.utils import _resolve_extension

        assert _resolve_extension("", "") == ".bin"


class TestBuildSafeFilename:
    """``_build_safe_filename`` should preserve the original name."""

    def test_preserves_cjk_when_no_conflict(self, tmp_path):
        from qwenpaw.app.channels.yuanbao.utils import _build_safe_filename

        assert _build_safe_filename("陈灵威.txt", ".txt", tmp_path) == "陈灵威.txt"

    def test_strips_whitespace_keeps_parens(self, tmp_path):
        from qwenpaw.app.channels.yuanbao.utils import _build_safe_filename

        assert (
            _build_safe_filename("test 副本(1).mp3", ".mp3", tmp_path)
            == "test副本(1).mp3"
        )

    def test_appends_uid_only_on_conflict(self, tmp_path):
        from qwenpaw.app.channels.yuanbao.utils import _build_safe_filename

        existing = tmp_path / "陈灵威.txt"
        existing.write_text("seed")
        result = _build_safe_filename("陈灵威.txt", ".txt", tmp_path)
        assert result.startswith("陈灵威_")
        assert result.endswith(".txt")
        assert result != "陈灵威.txt"

    def test_blank_filename_uses_yuanbao_prefix(self, tmp_path):
        from qwenpaw.app.channels.yuanbao.utils import _build_safe_filename

        result = _build_safe_filename("", ".bin", tmp_path)
        assert result.startswith("yuanbao_")
        assert result.endswith(".bin")

    def test_all_whitespace_falls_back_to_file(self, tmp_path):
        from qwenpaw.app.channels.yuanbao.utils import _build_safe_filename

        # "  " (only whitespace) -> stripped to empty -> "file"
        assert _build_safe_filename("   .txt", ".txt", tmp_path) == "file.txt"


# =============================================================================
# P1: Quote Prefix Helpers (channel.py)
# =============================================================================


class TestClassifyFile:
    """``_classify_file`` routes audio extensions to AudioContent."""

    def test_audio_extensions(self):
        from qwenpaw.app.channels.yuanbao.channel import YuanbaoChannel

        for name in (
            "test_副本.mp3",
            "voice.WAV",
            "a.m4a",
            "x.opus",
            "y.silk",
        ):
            assert YuanbaoChannel._classify_file(name) == "audio"

    def test_non_audio_extensions(self):
        from qwenpaw.app.channels.yuanbao.channel import YuanbaoChannel

        for name in ("陈灵威.txt", "doc.pdf", "img.png", "noext"):
            assert YuanbaoChannel._classify_file(name) == "file"


class TestBuildQuotedPrefix:
    """``_build_quoted_prefix`` covers the 5 yuanbao quote scenarios."""

    def test_text_quote(self):
        from qwenpaw.app.channels.yuanbao.channel import YuanbaoChannel

        assert (
            YuanbaoChannel._build_quoted_prefix(
                {"type": 1, "desc": "你好呀"},
            )
            == "[quoted message: 你好呀]"
        )

    def test_image_quote_empty_desc(self):
        from qwenpaw.app.channels.yuanbao.channel import YuanbaoChannel

        assert (
            YuanbaoChannel._build_quoted_prefix({"type": 2, "desc": ""})
            == "[quoted image]"
        )

    def test_file_quote_with_filename(self):
        from qwenpaw.app.channels.yuanbao.channel import YuanbaoChannel

        assert (
            YuanbaoChannel._build_quoted_prefix(
                {"type": 3, "desc": "陈灵威.txt"},
            )
            == "[quoted file: 陈灵威.txt]"
        )

    def test_audio_quote_routed_by_suffix(self):
        from qwenpaw.app.channels.yuanbao.channel import YuanbaoChannel

        assert (
            YuanbaoChannel._build_quoted_prefix(
                {"type": 3, "desc": "test_副本.mp3"},
            )
            == "[quoted audio: test_副本.mp3]"
        )

    def test_file_type_with_empty_desc(self):
        from qwenpaw.app.channels.yuanbao.channel import YuanbaoChannel

        assert (
            YuanbaoChannel._build_quoted_prefix({"type": 3, "desc": ""})
            == "[quoted file]"
        )

    def test_unknown_type_falls_back_to_message(self):
        from qwenpaw.app.channels.yuanbao.channel import YuanbaoChannel

        assert (
            YuanbaoChannel._build_quoted_prefix({"type": 99, "desc": ""})
            == "[quoted message]"
        )

    def test_non_dict_returns_none(self):
        from qwenpaw.app.channels.yuanbao.channel import YuanbaoChannel

        assert YuanbaoChannel._build_quoted_prefix(None) is None
        assert YuanbaoChannel._build_quoted_prefix("oops") is None


@pytest.mark.asyncio
class TestHandleChatMessageQuoteInjection:
    """End-to-end check that quoted prefix lands at content_parts[0]."""

    async def test_quote_prefix_prepended_for_text_quote(
        self,
        connected_channel,
    ):
        captured: list = []
        connected_channel._enqueue = captured.append
        connected_channel._bot_id = "bot_xxx"

        inbound = {
            "callback_command": "C2C.CallbackAfterSendMsg",
            "msg_id": "msg_with_quote",
            "from_account": "user_account",
            "sender_nickname": "灰",
            "msg_body": [
                {
                    "msg_type": "TIMTextElem",
                    "msg_content": {"text": "11"},
                },
            ],
            "cloud_custom_data": {"quote": {"type": 1, "desc": "你好呀"}},
        }
        await connected_channel._handle_chat_message(inbound)

        assert len(captured) == 1
        parts = captured[0]["content_parts"]
        # quote prefix is merged into the same TextContent as user input,
        # mirroring wecom / dingtalk behavior.
        assert len(parts) == 1
        assert parts[0].text == "[quoted message: 你好呀]\n11"

    async def test_quote_prefix_prepended_for_audio_quote(
        self,
        connected_channel,
    ):
        captured: list = []
        connected_channel._enqueue = captured.append

        inbound = {
            "callback_command": "C2C.CallbackAfterSendMsg",
            "msg_id": "msg_audio_quote",
            "from_account": "user_account",
            "sender_nickname": "灰",
            "msg_body": [
                {
                    "msg_type": "TIMTextElem",
                    "msg_content": {"text": "11"},
                },
            ],
            "cloud_custom_data": {
                "quote": {"type": 3, "desc": "test_副本.mp3"},
            },
        }
        await connected_channel._handle_chat_message(inbound)

        parts = captured[0]["content_parts"]
        assert len(parts) == 1
        assert parts[0].text == "[quoted audio: test_副本.mp3]\n11"

    async def test_quote_prefix_falls_back_when_no_text_part(
        self,
        connected_channel,
        tmp_path,
    ):
        """Image-only msg + quote: prefix becomes standalone TextContent."""
        captured: list = []
        connected_channel._enqueue = captured.append
        connected_channel._media_dir = tmp_path

        async def fake_download(url, media_dir, filename=""):
            target = media_dir / (filename or "image.jpg")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"x")
            return str(target)

        with patch(
            "qwenpaw.app.channels.yuanbao.channel.download_media",
            side_effect=fake_download,
        ):
            inbound = {
                "callback_command": "C2C.CallbackAfterSendMsg",
                "msg_id": "msg_img_quote",
                "from_account": "user_account",
                "sender_nickname": "灰",
                "msg_body": [
                    {
                        "msg_type": "TIMImageElem",
                        "msg_content": {
                            "image_info_array": [
                                {"url": "https://cdn.example.com/x.jpg"},
                            ],
                        },
                    },
                ],
                "cloud_custom_data": {
                    "quote": {"type": 1, "desc": "hi"},
                },
            }
            await connected_channel._handle_chat_message(inbound)

        parts = captured[0]["content_parts"]
        # No TextContent in original parts -> prefix becomes standalone
        # at index 0; image part follows.
        assert len(parts) == 2
        assert parts[0].text == "[quoted message: hi]"
        assert parts[1].image_url.startswith("file://")

    async def test_no_quote_no_prefix(self, connected_channel):
        captured: list = []
        connected_channel._enqueue = captured.append

        inbound = {
            "callback_command": "C2C.CallbackAfterSendMsg",
            "msg_id": "msg_plain",
            "from_account": "user_account",
            "sender_nickname": "灰",
            "msg_body": [
                {
                    "msg_type": "TIMTextElem",
                    "msg_content": {"text": "hello"},
                },
            ],
            "cloud_custom_data": {},
        }
        await connected_channel._handle_chat_message(inbound)

        parts = captured[0]["content_parts"]
        assert len(parts) == 1
        assert parts[0].text == "hello"
