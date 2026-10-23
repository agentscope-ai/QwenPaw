# -*- coding: utf-8 -*-
"""Preserved CH-0-007 actual SDK/platform cases after host driver retirement.

Generic runner ownership/checkpoint cases migrated to B147/C2/C3 and protocol
lifecycle suites.
"""
# pylint: disable=protected-access,redefined-outer-name,wrong-import-position
from __future__ import annotations
from collections.abc import Mapping
import threading
import asyncio
import io
import json
import logging
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import AsyncMock, patch
import pytest

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[2] / "channel_plugins"),
)
from c6_artifacts import artifact_module  # noqa: E402

platform_module = artifact_module("feishu", "platform")
LarkOapiPlatform = platform_module.LarkOapiPlatform
FeishuDeliveryError = platform_module.FeishuDeliveryError


class _Builder:
    """Minimal fluent SDK request builder used at the production seam."""

    def __init__(self, value: dict[str, Any] | None = None) -> None:
        self.value = value or {}

    @classmethod
    def builder(cls) -> "_Builder":
        return cls()

    def __getattr__(self, name: str) -> Callable[[Any], "_Builder"]:
        def setter(value: Any) -> "_Builder":
            self.value[name] = value
            return self

        return setter

    def build(self) -> dict[str, Any]:
        return dict(self.value)


class _SdkResponse:
    """Configurable lark-oapi response object."""

    def __init__(
        self,
        *,
        success: bool = True,
        data: Any = None,
        file_data: bytes | None = None,
    ) -> None:
        self._success = success
        self.data = data
        self.file = io.BytesIO(file_data) if file_data is not None else None
        self.code = 0 if success else 1
        self.msg = "ok" if success else "failed"

    def success(self) -> bool:
        return self._success


def _sdk_message(
    event_id: str,
    message_id: str,
    content: str,
    *,
    message_type: str = "text",
    app_id: str = "app-sdk",
) -> Any:
    message = SimpleNamespace(
        message_id=message_id,
        chat_id="oc-sdk",
        chat_type="group",
        message_type=message_type,
        content=content,
        mentions=[],
        thread_id="",
        parent_id="",
    )
    sender = SimpleNamespace(
        sender_id=SimpleNamespace(open_id="ou-sdk"),
        name="SDK User",
        nickname="",
    )
    return SimpleNamespace(
        header=SimpleNamespace(
            event_id=event_id,
            app_id=app_id,
            create_time=str(int(time.time() * 1000)),
        ),
        event=SimpleNamespace(message=message, sender=sender),
    )


@pytest.mark.asyncio
async def test_production_sdk_callback_is_fast_and_observes_failure() -> None:
    """The sync SDK callback returns promptly and observes Future errors."""
    platform = LarkOapiPlatform()
    platform._config = {"app_id": "app-sdk"}
    platform._runner_loop = asyncio.get_running_loop()
    errors: list[str] = []

    async def failing(_value: object) -> None:
        await asyncio.sleep(0.05)
        errors.append("failed")
        raise RuntimeError("fixture failure")

    value = _sdk_message("evt-fast", "msg-fast", '{"text":"hello"}')
    started = time.monotonic()
    platform._on_message_sync(value, failing)
    assert time.monotonic() - started < 0.02
    await asyncio.sleep(0.08)
    assert errors == ["failed"]


@pytest.mark.asyncio
async def test_production_sdk_callback_failure_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A scheduled SDK callback failure is consumed and diagnosed."""
    platform = LarkOapiPlatform()
    platform._config = {"app_id": "app-sdk"}
    platform._runner_loop = asyncio.get_running_loop()

    async def failing(_value: object) -> None:
        raise RuntimeError("fixture callback failure")

    caplog.set_level(logging.ERROR)
    with caplog.at_level(
        logging.ERROR,
        logger="c6_artifact_feishu.platform",
    ):
        platform._on_message_sync(
            _sdk_message("evt-log", "msg-log", '{"text":"hello"}'),
            failing,
        )
        for _ in range(20):
            if caplog.records:
                break
            await asyncio.sleep(0.001)
        assert any(
            record.getMessage() == "Feishu message callback failed"
            for record in caplog.records
        )


@pytest.mark.asyncio
async def test_production_sdk_media_download_keeps_legacy_paths(
    tmp_path: Path,
) -> None:
    """The production adapter preserves legacy image and file naming."""
    platform = LarkOapiPlatform()
    platform._client = SimpleNamespace(
        im=SimpleNamespace(
            v1=SimpleNamespace(
                message_resource=SimpleNamespace(
                    aget=lambda request: asyncio.sleep(
                        0,
                        result=_SdkResponse(
                            file_data={
                                "image-a": b"\x89PNG\r\n\x1a\nA",
                                "image-b": b"\x89PNG\r\n\x1a\nB",
                                "file-a": b"file-A",
                                "file-b": b"file-B",
                            }[request["file_key"]],
                        ),
                    ),
                ),
            ),
        ),
    )
    platform._media_work_dir = tmp_path
    post = json.dumps(
        {
            "content": [
                [
                    {"tag": "img", "image_key": "image-a"},
                    {"tag": "img", "image_key": "image-b"},
                    {"tag": "media", "file_key": "file-a"},
                    {"tag": "media", "file_key": "file-b"},
                ],
            ],
        },
    )
    with patch(
        "c6_artifact_feishu.platform.GetMessageResourceRequest",
        _Builder,
    ):
        _, _, parts = await platform._parse_message_content(
            "post",
            post,
            "msg-post",
        )
    paths = [
        Path(part.get("image_url") or part.get("file_url")) for part in parts
    ]
    assert paths[0].name == "msg-post_image-a.png"
    assert paths[1].name == "msg-post_image-b.png"
    assert paths[2].name == "msg-post_file.bin"
    assert paths[3].name == "msg-post_file.bin"
    assert paths[0].read_bytes().endswith(b"A")
    assert paths[1].read_bytes().endswith(b"B")
    assert paths[2] == paths[3]
    assert paths[3].read_bytes() == b"file-B"


@pytest.mark.asyncio
async def test_production_sdk_media_failure_preserves_inbound_event(
    tmp_path: Path,
) -> None:
    """A media download failure emits the legacy diagnostic text."""
    platform = LarkOapiPlatform()
    platform._media_work_dir = tmp_path
    platform._client = SimpleNamespace(
        im=SimpleNamespace(
            v1=SimpleNamespace(
                message_resource=SimpleNamespace(
                    aget=lambda _request: asyncio.sleep(
                        0,
                        result=_SdkResponse(success=False),
                    ),
                ),
            ),
        ),
    )
    with patch(
        "c6_artifact_feishu.platform.GetMessageResourceRequest",
        _Builder,
    ):
        text, hints, parts = await platform._parse_message_content(
            "image",
            '{"image_key":"missing"}',
            "msg-missing",
        )
    assert text is None
    assert hints == ["[image: download failed]"]
    assert parts == []


@pytest.mark.asyncio
async def test_production_sdk_file_uri_vectors(tmp_path: Path) -> None:
    """The production adapter reuses the shared cross-platform URI parser."""
    path = tmp_path / "空 格.txt"
    path.write_bytes(b"payload")
    platform = LarkOapiPlatform()
    assert await platform._read_locator(path.as_uri()) == b"payload"
    assert await platform._read_locator(str(path)) == b"payload"
    with patch(
        "c6_artifact_feishu.platform.file_url_to_local_path",
        return_value=str(path),
    ) as parser:
        assert await platform._read_locator("file:///C:/Temp/test.txt") == (
            b"payload"
        )
    parser.assert_called_once_with("file:///C:/Temp/test.txt")


@pytest.mark.asyncio
async def test_production_sdk_partial_success_becomes_unknown(
    tmp_path: Path,
) -> None:
    """A later media failure after text send reports an uncertain result."""
    platform = LarkOapiPlatform()
    platform._config = {"bot_prefix": ""}

    async def sent_text(
        _receive_type: str,
        _receive_id: str,
        _body: str,
        *,
        reply_message_id: str = "",
    ) -> list[str]:
        _ = reply_message_id
        return ["msg-text"]

    async def failed_file(
        _receive_type: str,
        _receive_id: str,
        _part: Mapping[str, Any],
        *,
        reply_message_id: str = "",
    ) -> str:
        _ = reply_message_id
        raise FeishuDeliveryError(
            "LOCAL_FILE_UNAVAILABLE",
            side_effect_possible=False,
        )

    platform._send_text = sent_text
    platform._send_file_part = failed_file
    with pytest.raises(FeishuDeliveryError) as captured:
        await platform.send_message(
            "chat_id",
            "oc-partial",
            (
                {"type": "text", "text": "already sent"},
                {"type": "file", "file_url": str(tmp_path / "missing")},
            ),
        )
    assert captured.value.side_effect_possible is True
    assert captured.value.retryable is False


@pytest.mark.asyncio
async def test_production_sdk_send_card_stream_and_reaction_boundaries(
    tmp_path: Path,
) -> None:
    """The production adapter invokes each existing lark-oapi API family."""
    calls: list[str] = []
    message_counter = 0

    async def create_message(_request: object) -> _SdkResponse:
        nonlocal message_counter
        message_counter += 1
        calls.append("message.create")
        return _SdkResponse(
            data=SimpleNamespace(message_id=f"message-{message_counter}"),
        )

    async def reply_message(request: object) -> _SdkResponse:
        nonlocal message_counter
        message_counter += 1
        calls.append("message.reply")
        assert isinstance(request, Mapping)
        assert request["message_id"] == "msg-thread-source"
        body = request["request_body"]
        assert isinstance(body, Mapping)
        assert body["reply_in_thread"] is True
        return _SdkResponse(
            data=SimpleNamespace(message_id=f"reply-{message_counter}"),
        )

    async def create_image(_request: object) -> _SdkResponse:
        calls.append("image.create")
        return _SdkResponse(data=SimpleNamespace(image_key="image-key"))

    async def create_file(_request: object) -> _SdkResponse:
        calls.append("file.create")
        return _SdkResponse(data=SimpleNamespace(file_key="file-key"))

    async def create_card(_request: object) -> _SdkResponse:
        calls.append("card.create")
        return _SdkResponse(data=SimpleNamespace(card_id="card-id"))

    async def update_card(_request: object) -> _SdkResponse:
        calls.append("card.update")
        return _SdkResponse()

    async def finalize_card(_request: object) -> _SdkResponse:
        calls.append("card.finalize")
        return _SdkResponse()

    async def create_reaction(_request: object) -> _SdkResponse:
        calls.append("reaction.create")
        return _SdkResponse()

    platform = LarkOapiPlatform()
    platform._config = {"bot_prefix": "[Bot]"}
    platform._client = SimpleNamespace(
        im=SimpleNamespace(
            v1=SimpleNamespace(
                message=SimpleNamespace(
                    acreate=create_message,
                    areply=reply_message,
                ),
                image=SimpleNamespace(acreate=create_image),
                file=SimpleNamespace(acreate=create_file),
                message_reaction=SimpleNamespace(acreate=create_reaction),
            ),
        ),
        cardkit=SimpleNamespace(
            v1=SimpleNamespace(
                card=SimpleNamespace(
                    acreate=create_card,
                    asettings=finalize_card,
                ),
                card_element=SimpleNamespace(acontent=update_card),
            ),
        ),
    )
    image_path = tmp_path / "image.png"
    file_path = tmp_path / "file.txt"
    image_path.write_bytes(b"image")
    file_path.write_bytes(b"file")
    builder_names = (
        "CreateMessageRequest",
        "CreateMessageRequestBody",
        "ReplyMessageRequest",
        "ReplyMessageRequestBody",
        "CreateImageRequest",
        "CreateImageRequestBody",
        "CreateFileRequest",
        "CreateFileRequestBody",
        "CreateMessageReactionRequest",
        "CreateMessageReactionRequestBody",
        "Emoji",
        "CreateCardRequest",
        "CreateCardRequestBody",
        "ContentCardElementRequest",
        "ContentCardElementRequestBody",
        "SettingsCardRequest",
        "SettingsCardRequestBody",
    )
    patches = [
        patch.object(platform_module, name, _Builder) for name in builder_names
    ]
    for item in patches:
        item.start()
    try:
        message_id = await platform.send_message(
            "chat_id",
            "oc-sdk",
            (
                {"type": "text", "text": "hello"},
                {"type": "image", "image_url": image_path.as_uri()},
                {
                    "type": "file",
                    "file_url": file_path.as_uri(),
                    "filename": "file.txt",
                },
            ),
        )
        approval_id = await platform.send_approval(
            "chat_id",
            "oc-sdk",
            {
                "request_id": "approval-sdk",
                "tool_name": "shell",
                "severity": "high",
            },
            "Approve?",
        )
        stream = await platform.start_stream("chat_id", "oc-sdk", "...")
        assert await platform.update_stream(
            stream,
            "partial",
            1,
            final=False,
        )
        assert await platform.update_stream(
            stream,
            "complete",
            2,
            final=True,
        )
        assert await platform.add_reaction(message_id, "DONE")
        thread_id = await platform.send_message(
            "chat_id",
            "oc-sdk",
            (
                {"type": "text", "text": "| A | B |"},
                {"type": "image", "image_url": image_path.as_uri()},
                {
                    "type": "file",
                    "file_url": file_path.as_uri(),
                    "filename": "file.txt",
                },
            ),
            reply_message_id="msg-thread-source",
        )
    finally:
        for item in reversed(patches):
            item.stop()
    assert message_id == "message-3"
    assert approval_id == "message-4"
    assert thread_id == "reply-8"
    assert calls == [
        "message.create",
        "image.create",
        "message.create",
        "file.create",
        "message.create",
        "message.create",
        "card.create",
        "message.create",
        "card.update",
        "card.update",
        "card.finalize",
        "reaction.create",
        "message.reply",
        "image.create",
        "message.reply",
        "file.create",
        "message.reply",
    ]


@pytest.mark.asyncio
async def test_production_sdk_half_open_connection_wakes_disconnect() -> None:
    """A silent SDK-shaped connection is closed by the health monitor."""

    class HalfOpenConnection:
        async def recv(self) -> bytes:
            await asyncio.Event().wait()
            return b""

        async def close(self) -> None:
            return None

    class HalfOpenClient:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            self._conn: HalfOpenConnection | None = None

        async def _connect(self) -> None:
            self._conn = HalfOpenConnection()
            asyncio.get_running_loop().create_task(
                self._receive_message_loop(),
            )

        async def _disconnect(self) -> None:
            connection = self._conn
            self._conn = None
            if connection is not None:
                await connection.close()

        async def _ping_loop(self) -> None:
            while True:
                await asyncio.sleep(3600)

        async def _handle_message(self, _message: bytes) -> None:
            return None

    fake_sdk = SimpleNamespace(
        LogLevel=SimpleNamespace(INFO="info"),
        FEISHU_DOMAIN="https://open.feishu.cn",
        LARK_DOMAIN="https://open.larksuite.com",
        ws=SimpleNamespace(Client=HalfOpenClient),
    )
    platform = LarkOapiPlatform()
    platform._config = {"app_id": "app-sdk", "domain": "feishu"}
    platform._secret = {"app_secret": "secret"}
    platform._runner_loop = asyncio.get_running_loop()
    platform._closed = False
    platform._disconnected = asyncio.Event()
    platform._ws_started.clear()
    with (
        patch.object(platform_module, "lark", fake_sdk),
        patch.object(platform_module.lark_ws, "Client", HalfOpenClient),
        patch.object(platform_module, "_WS_HEALTH_CHECK_INTERVAL", 0.01),
        patch.object(platform_module, "FEISHU_WS_RECV_TIMEOUT", 0.01),
    ):
        platform._ws_thread = threading.Thread(
            target=platform._run_ws,
            args=(SimpleNamespace(),),
            daemon=True,
        )
        platform._ws_thread.start()
        assert await asyncio.to_thread(platform._ws_started.wait, 1.0)
        await asyncio.wait_for(platform.wait_disconnected(), timeout=0.3)
        thread = platform._ws_thread
        if thread is not None:
            await asyncio.to_thread(thread.join, 0.3)
            assert not thread.is_alive()
    await platform.disconnect()


@pytest.mark.asyncio
async def test_production_sdk_disconnect_timeout_is_retryable() -> None:
    """A blocked SDK disconnect cannot hold platform shutdown forever."""
    platform = LarkOapiPlatform()
    loop = asyncio.new_event_loop()
    started = threading.Event()

    def run_loop() -> None:
        asyncio.set_event_loop(loop)
        started.set()
        loop.run_forever()
        loop.close()

    thread = threading.Thread(target=run_loop, daemon=True)
    thread.start()
    assert started.wait(1.0)

    class BlockingClient:
        _conn = object()
        gate = None
        released = False

        async def _disconnect(self) -> None:
            self.gate = asyncio.Event()
            if not self.released:
                await self.gate.wait()
            self._conn = None

    platform._closed = False
    platform._ws_loop = loop
    platform._ws_client = BlockingClient()
    platform._ws_thread = thread
    client = platform._ws_client
    with (
        patch.object(platform_module, "_WS_DISCONNECT_TIMEOUT", 0.01),
        patch.object(platform_module, "_WS_THREAD_JOIN_TIMEOUT", 0.1),
    ):
        started_at = time.monotonic()
        try:
            with pytest.raises(
                RuntimeError,
                match="disconnect did not finish",
            ):
                await platform.disconnect()
            assert time.monotonic() - started_at < 0.2
            assert platform._ws_thread is thread and thread.is_alive()
            assert platform._ws_client is client and client._conn is not None
        finally:
            client.released = True
            await platform.disconnect()
    assert not thread.is_alive()
    assert platform._disconnected.is_set()


@pytest.mark.asyncio
async def test_production_sdk_active_connection_auth_failure(
    tmp_path: Path,
) -> None:
    """A controlled SDK WebSocket authentication failure aborts connect."""

    class AuthFailureClient:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            self._conn = None

        async def _connect(self) -> None:
            raise RuntimeError("invalid credentials")

        async def _disconnect(self) -> None:
            return None

        async def _ping_loop(self) -> None:
            return None

    class ClientBuilder(_Builder):
        def build(self) -> Any:
            return SimpleNamespace(_config=object())

    class DispatcherBuilder(_Builder):
        @classmethod
        def builder(cls, *_args: object) -> "DispatcherBuilder":
            return cls()

        def build(self) -> Any:
            return SimpleNamespace()

    fake_sdk = SimpleNamespace(
        Client=ClientBuilder,
        EventDispatcherHandler=DispatcherBuilder,
        LogLevel=SimpleNamespace(INFO="info"),
        FEISHU_DOMAIN="https://open.feishu.cn",
        LARK_DOMAIN="https://open.larksuite.com",
        ws=SimpleNamespace(Client=AuthFailureClient),
    )
    platform = LarkOapiPlatform()
    token_manager = SimpleNamespace(
        get_self_tenant_token=lambda _config: "fixture-token",
    )
    with (
        patch.object(platform_module, "lark", fake_sdk),
        patch.object(platform_module.lark_ws, "Client", AuthFailureClient),
        patch.object(platform_module, "TokenManager", token_manager),
    ):
        await platform.prepare(
            {"app_id": "app-sdk", "domain": "feishu"},
            {
                "app_secret": "sdk-secret",
                "encrypt_key": "sdk-encrypt",
                "verification_token": "sdk-token",
            },
            tmp_path,
        )

        async def noop(_value: object) -> None:
            return None

        try:
            with pytest.raises(
                RuntimeError, match="connection failed"
            ) as caught:
                await platform.connect(noop, noop)
            assert str(caught.value.__cause__) == "invalid credentials"
        finally:
            await platform.close()
        assert platform._ws_thread is None


@pytest.mark.asyncio
async def test_production_sdk_prepare_rejects_invalid_credentials(
    tmp_path: Path,
) -> None:
    """Prepare performs the required read-only platform auth probe."""

    class ClientBuilder(_Builder):
        def build(self) -> Any:
            return SimpleNamespace(_config=object())

    fake_sdk = SimpleNamespace(
        Client=ClientBuilder,
        LogLevel=SimpleNamespace(INFO="info"),
        FEISHU_DOMAIN="https://open.feishu.cn",
        LARK_DOMAIN="https://open.larksuite.com",
    )
    platform = LarkOapiPlatform()

    def reject_credentials(_config: object) -> str:
        raise RuntimeError("invalid credentials")

    token_manager = SimpleNamespace(
        get_self_tenant_token=reject_credentials,
    )
    with (
        patch.object(platform_module, "lark", fake_sdk),
        patch.object(platform_module, "TokenManager", token_manager),
    ):
        with pytest.raises(RuntimeError, match="invalid credentials"):
            await platform.prepare(
                {"app_id": "app-invalid", "domain": "feishu"},
                {
                    "app_secret": "invalid-secret",
                    "encrypt_key": "",
                    "verification_token": "",
                },
                tmp_path,
            )
    assert platform._client is None
    assert platform._http_client is None
    assert not platform._secret


@pytest.fixture
def feishu_channel(tmp_path):
    platform = artifact_module("feishu", "platform").LarkOapiPlatform()
    platform._media_work_dir = tmp_path
    return platform


class TestParseMessageContent:
    """Tests for the shared _parse_message_content engine.

    Returns (main_text, error_hints, content_parts).
    """

    @pytest.mark.asyncio
    async def test_text_basic(self, feishu_channel):
        (
            main_text,
            error_hints,
            content_parts,
        ) = await feishu_channel._parse_message_content(
            "text",
            '{"text": "Hello world"}',
            "msg_001",
        )
        assert main_text == "Hello world"
        assert error_hints == []
        assert content_parts == []

    @pytest.mark.asyncio
    async def test_text_empty(self, feishu_channel):
        (
            main_text,
            error_hints,
            _,
        ) = await feishu_channel._parse_message_content(
            "text",
            '{"text": ""}',
            "msg_002",
        )
        assert main_text is None
        assert error_hints == []

    @pytest.mark.asyncio
    async def test_text_whitespace_only(self, feishu_channel):
        main_text, _, _ = await feishu_channel._parse_message_content(
            "text",
            '{"text": "   "}',
            "msg_003",
        )
        assert main_text is None

    @pytest.mark.asyncio
    async def test_post_basic(self, feishu_channel):
        content = json.dumps(
            {
                "content": [[{"tag": "text", "text": "Post body"}]],
            },
        )
        (
            main_text,
            error_hints,
            _,
        ) = await feishu_channel._parse_message_content(
            "post",
            content,
            "msg_010",
        )
        assert main_text is not None
        assert "Post body" in main_text
        assert error_hints == []

    @pytest.mark.asyncio
    async def test_image_missing_key(self, feishu_channel):
        (
            main_text,
            error_hints,
            content_parts,
        ) = await feishu_channel._parse_message_content(
            "image",
            '{"other": "val"}',
            "msg_020",
        )
        assert main_text is None
        assert "[image: missing key]" in error_hints
        assert content_parts == []

    @pytest.mark.asyncio
    async def test_image_download_success(self, feishu_channel):
        feishu_channel._download_resource = AsyncMock(
            return_value="/tmp/img.jpg",
        )
        (
            main_text,
            error_hints,
            content_parts,
        ) = await feishu_channel._parse_message_content(
            "image",
            '{"image_key": "img_abc"}',
            "msg_021",
        )
        assert main_text is None
        assert error_hints == []
        assert len(content_parts) == 1
        assert content_parts[0]["image_url"] == "/tmp/img.jpg"

    @pytest.mark.asyncio
    async def test_file_missing_key(self, feishu_channel):
        _, error_hints, _ = await feishu_channel._parse_message_content(
            "file",
            '{"other": "val"}',
            "msg_030",
        )
        assert "[file: missing key]" in error_hints

    @pytest.mark.asyncio
    async def test_audio_download_success(self, feishu_channel):
        feishu_channel._download_resource = AsyncMock(
            return_value="/tmp/audio.opus",
        )
        (
            main_text,
            error_hints,
            content_parts,
        ) = await feishu_channel._parse_message_content(
            "audio",
            '{"file_key": "file_abc"}',
            "msg_031",
        )
        assert main_text is None
        assert error_hints == []
        assert len(content_parts) == 1
        assert content_parts[0]["type"] == "audio"

    @pytest.mark.asyncio
    async def test_interactive_basic(self, feishu_channel):
        content = json.dumps(
            {
                "header": {"title": {"content": "Card Title"}},
                "body": {"elements": [{"tag": "text", "text": "Card body"}]},
            },
        )
        (
            main_text,
            error_hints,
            _,
        ) = await feishu_channel._parse_message_content(
            "interactive",
            content,
            "msg_040",
        )
        assert main_text is not None
        assert "Card Title" in main_text
        assert "Card body" in main_text
        assert error_hints == []

    @pytest.mark.asyncio
    async def test_interactive_empty_returns_none(self, feishu_channel):
        content = json.dumps({"other": "data"})
        main_text, _, _ = await feishu_channel._parse_message_content(
            "interactive",
            content,
            "msg_041",
        )
        assert main_text is None

    @pytest.mark.asyncio
    async def test_unknown_type_returns_empty(self, feishu_channel):
        (
            main_text,
            error_hints,
            content_parts,
        ) = await feishu_channel._parse_message_content(
            "sticker",
            "{}",
            "msg_099",
        )
        assert main_text is None
        assert error_hints == []
        assert content_parts == []


class TestProcessQuotedMessage:
    """Tests for _append_quoted_message."""

    @pytest.mark.asyncio
    async def test_quoted_text_message(self, feishu_channel):
        feishu_channel._fetch_quoted_message = AsyncMock(
            return_value=("text", '{"text": "Original message"}'),
        )
        text_parts = ["My reply"]
        content_parts = []
        await feishu_channel._append_quoted_message(
            "parent_123",
            text_parts,
            content_parts,
        )
        assert text_parts[0] == "[quoted message: Original message]"
        assert text_parts[1] == "My reply"

    @pytest.mark.asyncio
    async def test_quoted_image_with_label(self, feishu_channel):
        feishu_channel._fetch_quoted_message = AsyncMock(
            return_value=("image", '{"image_key": "img_abc"}'),
        )
        feishu_channel._download_resource = AsyncMock(
            return_value="/tmp/img.jpg",
        )
        text_parts = ["Reply text"]
        content_parts = []
        await feishu_channel._append_quoted_message(
            "parent_456",
            text_parts,
            content_parts,
        )
        # Pure image — should still add a label
        assert text_parts[0] == "[quoted image]"
        assert text_parts[1] == "Reply text"
        assert len(content_parts) == 1

    @pytest.mark.asyncio
    async def test_quoted_interactive_card(self, feishu_channel):
        card_content = json.dumps(
            {
                "header": {"title": {"content": "Card Title"}},
                "body": {"elements": [{"tag": "text", "text": "Card body"}]},
            },
        )
        feishu_channel._fetch_quoted_message = AsyncMock(
            return_value=("interactive", card_content),
        )
        text_parts = ["My reply"]
        content_parts = []
        await feishu_channel._append_quoted_message(
            "parent_789",
            text_parts,
            content_parts,
        )
        assert "quoted interactive card:" in text_parts[0]
        assert "Card Title" in text_parts[0]

    @pytest.mark.asyncio
    async def test_quoted_fetch_failure_no_change(self, feishu_channel):
        feishu_channel._fetch_quoted_message = AsyncMock(
            return_value=None,
        )
        text_parts = ["My reply"]
        content_parts = []
        await feishu_channel._append_quoted_message(
            "parent_000",
            text_parts,
            content_parts,
        )
        assert text_parts == ["My reply"]
        assert not content_parts

    @pytest.mark.asyncio
    async def test_quoted_error_hints_preserved(self, feishu_channel):
        feishu_channel._fetch_quoted_message = AsyncMock(
            return_value=("image", '{"other": "no key"}'),
        )
        text_parts = ["Reply"]
        content_parts = []
        await feishu_channel._append_quoted_message(
            "parent_err",
            text_parts,
            content_parts,
        )
        assert text_parts[0] == "[quoted image]"
        assert any("missing key" in t for t in text_parts)

    @pytest.mark.asyncio
    async def test_quoted_lines_order_preserved(self, feishu_channel):
        """Error hints after post with failed downloads stay ordered."""
        content = json.dumps(
            {
                "content": [[{"tag": "text", "text": "Post text"}]],
            },
        )
        feishu_channel._fetch_quoted_message = AsyncMock(
            return_value=("post", content),
        )
        text_parts = ["Reply"]
        content_parts = []
        await feishu_channel._append_quoted_message(
            "parent_order",
            text_parts,
            content_parts,
        )
        # quoted label should be first, reply should be last
        assert text_parts[0].startswith("[quoted message:")
        assert text_parts[-1] == "Reply"
