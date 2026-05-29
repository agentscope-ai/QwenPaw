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
        app_key="test_app_key_123",
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
            app_key="key_abc",
            app_secret="secret_xyz",
            api_domain="custom.domain.com",
            bot_prefix="[Test] ",
            media_dir=str(tmp_path / "media"),
        )

        assert channel.enabled is True
        assert channel.app_key == "key_abc"
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
            app_key="k",
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
            "app_key": "dict_key",
            "app_secret": "dict_secret",
            "api_domain": "dict.domain.com",
            "bot_prefix": "[Dict] ",
        }
        channel = YuanbaoChannel.from_config(
            process=mock_process,
            config=config,
        )

        assert channel.enabled is True
        assert channel.app_key == "dict_key"
        assert channel.app_secret == "dict_secret"
        assert channel.api_domain == "dict.domain.com"

    def test_from_config_with_object(self, mock_process):
        from qwenpaw.app.channels.yuanbao.channel import YuanbaoChannel

        config = Mock()
        config.enabled = True
        config.app_key = "obj_key"
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

        assert channel.app_key == "obj_key"
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
            app_key="test_key",
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
            app_key="test_key",
            app_secret="test_secret",
            api_domain="yuanbao.tencent.com",
        )

        assert manager.app_key == "test_key"
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
