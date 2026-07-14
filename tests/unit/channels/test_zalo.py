# -*- coding: utf-8 -*-
"""
Zalo Channel Unit Tests

Covers:
- Channel initialization and factory methods
- Session routing (group vs private, share_session_in_group)
- Smart outbound routing (markdown, bare URL, magic tokens)
- Thinking / null-token stripping
- File dispatch
- build_agent_request_from_native (group prefix injection)
- _handle_update (long-poll dispatch)

Run:
    pytest tests/unit/channels/test_zalo.py -v
"""
# pylint: disable=redefined-outer-name,protected-access,unused-argument
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from qwenpaw.app.channels.zalo.channel import (
    ZaloChannel,
    ZALO_DEFAULT_API_BASE,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def process() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def channel(process: AsyncMock) -> ZaloChannel:
    """Default ZaloChannel instance for most tests."""
    return ZaloChannel(
        process=process,
        enabled=True,
        bot_token="test_token_123",
        api_base_url=ZALO_DEFAULT_API_BASE,
        secret_token="",
        show_typing=True,
        poll_interval=30.0,
        max_retries=3,
        max_message_len=2000,
        share_session_in_group=True,
        show_tool_details=False,
        filter_tool_messages=True,
    )


# =============================================================================
# 1. Channel init + factory methods
# =============================================================================


class TestZaloChannelInit:
    """Channel construction and factory methods."""

    def test_default_attributes(self, channel: ZaloChannel) -> None:
        assert channel.channel == "zalo"
        assert channel.enabled is True
        assert channel.bot_token == "test_token_123"
        assert channel.api_base_url == ZALO_DEFAULT_API_BASE
        assert channel.share_session_in_group is True
        assert channel.poll_interval == 30.0
        assert channel.max_retries == 3
        assert channel.max_message_len == 2000

    def test_disabled_channel(self, process: AsyncMock) -> None:
        ch = ZaloChannel(process=process, enabled=False, bot_token="")
        assert ch.enabled is False
        assert ch.bot_token == ""

    def test_from_config(self, process: AsyncMock) -> None:
        cfg = {
            "enabled": True,
            "bot_token": "cfg_token",
            "api_base_url": "https://custom.api",
            "show_typing": False,
            "poll_interval": 15.0,
            "max_retries": 5,
            "max_message_len": 1000,
            "share_session_in_group": False,
        }
        ch = ZaloChannel.from_config(cfg, process=process)
        assert ch.bot_token == "cfg_token"
        assert ch.api_base_url == "https://custom.api"
        assert ch.show_typing is False
        assert ch.poll_interval == 15.0
        assert ch.max_retries == 5
        assert ch.max_message_len == 1000
        assert ch.share_session_in_group is False

    def test_from_config_empty(self, process: AsyncMock) -> None:
        ch = ZaloChannel.from_config({}, process=process)
        assert ch.bot_token == ""
        assert ch.enabled is True  # default

    def test_from_env(self, process: AsyncMock) -> None:
        class FakeEnv:
            process = process
            zalo_bot_token = "env_token"
            zalo_show_typing = False

        ch = ZaloChannel.from_env(FakeEnv())
        assert ch.bot_token == "env_token"
        assert ch.show_typing is False

    @pytest.mark.asyncio
    async def test_health_check_disabled(self, process: AsyncMock) -> None:
        ch = ZaloChannel(process=process, enabled=False, bot_token="")
        hc = await ch.health_check()
        assert hc["ok"] is False
        assert hc["enabled"] is False

    @pytest.mark.asyncio
    async def test_health_check_no_http(self, channel: ZaloChannel) -> None:
        hc = await channel.health_check()
        assert hc["ok"] is False  # http not started yet
        assert hc["bot_token_set"] is True


# =============================================================================
# 2. Session routing
# =============================================================================


class TestZaloSessionRouting:
    """Session id resolution for private vs group chats."""

    def test_private_chat(self, channel: ZaloChannel) -> None:
        sid = channel.resolve_session_id("user_42")
        assert sid == "zalo:user_42"

    def test_private_chat_with_meta(self, channel: ZaloChannel) -> None:
        sid = channel.resolve_session_id(
            "user_42",
            channel_meta={"chat_id": "123", "chat_type": "private"},
        )
        assert sid == "zalo:user_42"

    def test_group_chat_shared(self, channel: ZaloChannel) -> None:
        sid = channel.resolve_session_id(
            "user_42",
            channel_meta={"chat_id": "group_99", "chat_type": "group"},
        )
        assert sid == "zalo:group:group_99"

    def test_group_chat_not_shared(self, process: AsyncMock) -> None:
        ch = ZaloChannel(
            process=process,
            enabled=True,
            bot_token="t",
            share_session_in_group=False,
        )
        sid = ch.resolve_session_id(
            "user_42",
            channel_meta={"chat_id": "group_99", "chat_type": "group"},
        )
        assert sid == "zalo:user_42:group_99"

    def test_supergroup(self, channel: ZaloChannel) -> None:
        sid = channel.resolve_session_id(
            "u1",
            channel_meta={"chat_id": "sg_1", "chat_type": "supergroup"},
        )
        assert sid == "zalo:group:sg_1"

    def test_channel_type(self, channel: ZaloChannel) -> None:
        sid = channel.resolve_session_id(
            "u1",
            channel_meta={"chat_id": "ch_1", "chat_type": "channel"},
        )
        assert sid == "zalo:group:ch_1"

    def test_to_handle_from_target_private(self, channel: ZaloChannel) -> None:
        h = channel.to_handle_from_target(user_id="u42", session_id="zalo:u42")
        assert h == "zalo:u42"

    def test_to_handle_from_target_group(self, channel: ZaloChannel) -> None:
        h = channel.to_handle_from_target(
            user_id="",
            session_id="zalo:group:g99",
        )
        assert h == "zalo:group:g99"

    def test_get_to_handle_from_request_private(
        self,
        channel: ZaloChannel,
    ) -> None:
        req = MagicMock()
        req.meta = {"sender_id": "u42", "is_group": False}
        req.session_id = "zalo:u42"
        h = channel.get_to_handle_from_request(req)
        assert h == "zalo:u42"

    def test_get_to_handle_from_request_group(
        self,
        channel: ZaloChannel,
    ) -> None:
        req = MagicMock()
        req.meta = {"chat_id": "g99", "is_group": True}
        req.session_id = "zalo:group:g99"
        h = channel.get_to_handle_from_request(req)
        assert h == "zalo:group:g99"


# =============================================================================
# 3. Smart outbound routing (_extract_actions)
# =============================================================================


class TestZaloExtractActions:
    """Extraction of photo/sticker/voice/file actions from LLM text."""

    def test_plain_text(self, channel: ZaloChannel) -> None:
        actions, leftover = channel._extract_actions("Hello, how are you?")
        assert actions == []
        assert leftover == "Hello, how are you?"

    def test_markdown_image(self, channel: ZaloChannel) -> None:
        actions, leftover = channel._extract_actions(
            "Nhìn nè ![alt](https://x.com/pic.png)",
        )
        assert len(actions) == 1
        assert actions[0].kind == "photo"
        assert actions[0].payload == "https://x.com/pic.png"
        assert leftover == "Nhìn nè"

    def test_bare_image_url(self, channel: ZaloChannel) -> None:
        actions, leftover = channel._extract_actions(
            "xem https://x.com/pic.jpg, nó đẹp",
        )
        assert len(actions) == 1
        assert actions[0].kind == "photo"
        assert actions[0].payload == "https://x.com/pic.jpg"
        assert "nó đẹp" in leftover

    def test_magic_image(self, channel: ZaloChannel) -> None:
        actions, leftover = channel._extract_actions(
            "Đây [IMAGE: https://x.com/y.png] nhé",
        )
        assert len(actions) == 1
        assert actions[0].kind == "photo"
        assert actions[0].payload == "https://x.com/y.png"
        assert leftover == "Đây nhé"

    def test_magic_sticker(self, channel: ZaloChannel) -> None:
        actions, leftover = channel._extract_actions("haha [STICKER: 12345]")
        assert len(actions) == 1
        assert actions[0].kind == "sticker"
        assert actions[0].payload == "12345"
        assert leftover == "haha"

    def test_magic_voice(self, channel: ZaloChannel) -> None:
        actions, leftover = channel._extract_actions(
            "nghe [VOICE: https://x.com/a.mp3] đi",
        )
        assert len(actions) == 1
        assert actions[0].kind == "voice"
        assert actions[0].payload == "https://x.com/a.mp3"
        assert leftover == "nghe đi"

    def test_magic_file(self, channel: ZaloChannel) -> None:
        actions, leftover = channel._extract_actions(
            "file [FILE: /tmp/foo.txt] đây",
        )
        assert len(actions) == 1
        assert actions[0].kind == "local_file"
        assert actions[0].payload == "/tmp/foo.txt"
        assert leftover == "file đây"

    def test_mixed_order(self, channel: ZaloChannel) -> None:
        actions, _ = channel._extract_actions(
            "Reply nè ![caption](https://i.io/a.png) và "
            "https://i.io/b.jpg, kèm [STICKER: 999]",
        )
        kinds = [a.kind for a in actions]
        assert kinds == ["sticker", "photo", "photo"]

    def test_empty_input(self, channel: ZaloChannel) -> None:
        actions, leftover = channel._extract_actions("")
        assert actions == []
        assert leftover == ""

    def test_non_image_url(self, channel: ZaloChannel) -> None:
        actions, leftover = channel._extract_actions(
            "trang https://example.com chính hãng",
        )
        assert actions == []
        assert "https://example.com" in leftover

    def test_png_with_query_string(self, channel: ZaloChannel) -> None:
        actions, _ = channel._extract_actions(
            "see https://x.com/p.png?token=abc",
        )
        assert len(actions) == 1
        assert actions[0].payload == "https://x.com/p.png?token=abc"


# =============================================================================
# 4. Thinking / null-token stripping
# =============================================================================


class TestZaloThinkingStrip:
    """_strip_thinking and _strip_null_tokens."""

    def test_no_think_block(self, channel: ZaloChannel) -> None:
        s = channel._strip_thinking("hello world")
        assert s == "hello world"

    def test_thinking_label_removed(self, channel: ZaloChannel) -> None:
        s = channel._strip_thinking("real\nThinking:\nmore real")
        assert s == "real\nmore real"

    def test_reasoning_label_removed(self, channel: ZaloChannel) -> None:
        s = channel._strip_thinking("x\nReasoning:\ny")
        assert s == "x\ny"

    def test_null_token_line(self, channel: ZaloChannel) -> None:
        s = channel._strip_null_tokens("hello\nnull\nworld")
        assert s == "hello\nworld"

    def test_leading_null_leak(self, channel: ZaloChannel) -> None:
        s = channel._strip_null_tokens("null\n\nactual reply")
        assert s == "actual reply"

    def test_multiple_null_tokens(self, channel: ZaloChannel) -> None:
        s = channel._strip_null_tokens(
            "a\nNone\nb\nundefined\nc\nnil\nd",
        )
        assert s == "a\nb\nc\nd"


# =============================================================================
# 5. File dispatch
# =============================================================================


class TestZaloFileDispatch:
    """_dispatch_local_file behavior."""

    @pytest.mark.asyncio
    async def test_file_exists(self, channel: ZaloChannel) -> None:
        with tempfile.NamedTemporaryFile(
            suffix=".bin",
            delete=False,
        ) as f:
            f.write(b"x" * 2048)
            tmppath = f.name
        try:
            channel._http = AsyncMock()
            channel._http.post = AsyncMock(
                return_value=AsyncMock(
                    status_code=200,
                    json=lambda: {"ok": True},
                ),
            )
            await channel._dispatch_local_file("u1", tmppath)
            assert channel._http.post.called
            call_text = channel._http.post.call_args[1]["json"]["text"]
            assert "File:" in call_text
            assert Path(tmppath).name in call_text
        finally:
            os.unlink(tmppath)

    @pytest.mark.asyncio
    async def test_file_not_found(self, channel: ZaloChannel) -> None:
        channel._http = AsyncMock()
        channel._http.post = AsyncMock(
            return_value=AsyncMock(
                status_code=200,
                json=lambda: {"ok": True},
            ),
        )
        await channel._dispatch_local_file("u1", "/nonexistent/foo.txt")
        call_text = channel._http.post.call_args[1]["json"]["text"]
        assert "File not found" in call_text


# =============================================================================
# 6. build_agent_request_from_native (group prefix injection)
# =============================================================================


class TestZaloBuildAgentRequest:
    """build_agent_request_from_native — group prefix injection."""

    def test_private_chat(self, channel: ZaloChannel) -> None:
        req = channel.build_agent_request_from_native(
            {
                "sender_id": "u42",
                "from_name": "Alice",
                "chat_id": "123",
                "chat_type": "private",
                "is_group": False,
                "text": "Hello bot!",
                "session_id": "zalo:u42",
                "update_id": 100,
            },
        )
        assert req is not None
        assert req.session_id == "zalo:u42"
        assert len(req.content_parts) == 1
        assert req.content_parts[0].text == "Hello bot!"

    def test_group_chat(self, channel: ZaloChannel) -> None:
        req = channel.build_agent_request_from_native(
            {
                "sender_id": "u42",
                "from_name": "Alice",
                "chat_id": "g99",
                "chat_type": "group",
                "is_group": True,
                "text": "Xin chào",
                "session_id": "zalo:group:g99",
                "update_id": 101,
            },
        )
        assert req is not None
        assert req.session_id == "zalo:group:g99"
        assert "[Alice trong nhóm g99]:" in req.content_parts[0].text

    def test_empty_text(self, channel: ZaloChannel) -> None:
        req = channel.build_agent_request_from_native(
            {
                "sender_id": "u42",
                "text": "",
                "session_id": "zalo:u42",
            },
        )
        assert req is None

    def test_meta_preserved(self, channel: ZaloChannel) -> None:
        req = channel.build_agent_request_from_native(
            {
                "sender_id": "u42",
                "from_name": "Bob",
                "chat_id": "g99",
                "chat_type": "group",
                "is_group": True,
                "text": "Hi",
                "session_id": "zalo:group:g99",
                "update_id": 102,
            },
        )
        assert req.meta["channel"] == "zalo"
        assert req.meta["sender_id"] == "u42"
        assert req.meta["from_name"] == "Bob"
        assert req.meta["is_group"] is True
        assert req.meta["update_id"] == 102


# =============================================================================
# 7. _handle_update (long-poll dispatch)
# =============================================================================


class TestZaloHandleUpdate:
    """_handle_update — incoming message dispatch."""

    @pytest.mark.asyncio
    async def test_private_message(self, channel: ZaloChannel) -> None:
        channel._enqueue = AsyncMock()
        update = {
            "update_id": 1,
            "message": {
                "message_id": 10,
                "from": {"id": 42, "first_name": "Alice"},
                "chat": {"id": 123, "type": "private"},
                "text": "Hello bot!",
            },
        }
        await channel._handle_update(update)
        assert channel._enqueue.called
        args = channel._enqueue.call_args[0]
        assert args[0].session_id == "zalo:42"
        assert args[0].content_parts[0].text == "Hello bot!"

    @pytest.mark.asyncio
    async def test_group_message(self, channel: ZaloChannel) -> None:
        channel._enqueue = AsyncMock()
        update = {
            "update_id": 2,
            "message": {
                "message_id": 11,
                "from": {"id": 42, "first_name": "Alice"},
                "chat": {"id": -10099, "type": "group"},
                "text": "Xin chào",
            },
        }
        await channel._handle_update(update)
        assert channel._enqueue.called
        args = channel._enqueue.call_args[0]
        assert args[0].session_id == "zalo:group:-10099"
        assert "[Alice trong nhóm -10099]:" in args[0].content_parts[0].text

    @pytest.mark.asyncio
    async def test_empty_text_skipped(self, channel: ZaloChannel) -> None:
        channel._enqueue = AsyncMock()
        update = {
            "update_id": 3,
            "message": {
                "message_id": 12,
                "from": {"id": 42},
                "chat": {"id": 123, "type": "private"},
                "text": "",
            },
        }
        await channel._handle_update(update)
        assert not channel._enqueue.called

    @pytest.mark.asyncio
    async def test_offset_updated(self, channel: ZaloChannel) -> None:
        channel._enqueue = AsyncMock()
        update = {
            "update_id": 5,
            "message": {
                "message_id": 13,
                "from": {"id": 1},
                "chat": {"id": 1, "type": "private"},
                "text": "hi",
            },
        }
        await channel._handle_update(update)
        assert channel._offset == 6  # update_id + 1

    @pytest.mark.asyncio
    async def test_mention_stripped_in_group(
        self,
        channel: ZaloChannel,
    ) -> None:
        channel._enqueue = AsyncMock()
        update = {
            "update_id": 6,
            "message": {
                "message_id": 14,
                "from": {"id": 42, "first_name": "Alice"},
                "chat": {"id": -100, "type": "group"},
                "text": "@botname hello",
                "entities": [
                    {"type": "mention", "offset": 0, "length": 8},
                ],
            },
        }
        await channel._handle_update(update)
        assert channel._enqueue.called
        text = channel._enqueue.call_args[0][0].content_parts[0].text
        assert "hello" in text
        assert "@botname" not in text


# =============================================================================
# 8. Send path
# =============================================================================


class TestZaloSend:
    """send() — outbound dispatch."""

    @pytest.mark.asyncio
    async def test_send_text_only(self, channel: ZaloChannel) -> None:
        channel._http = AsyncMock()
        channel._http.post = AsyncMock(
            return_value=AsyncMock(
                status_code=200,
                json=lambda: {"ok": True},
            ),
        )
        from qwenpaw.schemas import TextContent

        await channel.send(
            "zalo:u42",
            [TextContent(text="Hello back!")],
        )
        assert channel._http.post.called
        call_kwargs = channel._http.post.call_args[1]
        assert "sendMessage" in channel._http.post.call_args[0][0]
        assert call_kwargs["json"]["text"] == "Hello back!"

    @pytest.mark.asyncio
    async def test_send_to_group(self, channel: ZaloChannel) -> None:
        channel._http = AsyncMock()
        channel._http.post = AsyncMock(
            return_value=AsyncMock(
                status_code=200,
                json=lambda: {"ok": True},
            ),
        )
        from qwenpaw.schemas import TextContent

        await channel.send(
            "zalo:group:g99",
            [TextContent(text="Group reply")],
        )
        call_kwargs = channel._http.post.call_args[1]
        assert call_kwargs["json"]["chat_id"] == "g99"

    @pytest.mark.asyncio
    async def test_send_no_http(self, channel: ZaloChannel) -> None:
        from qwenpaw.schemas import TextContent

        # _http is None — should not crash
        await channel.send(
            "zalo:u42",
            [TextContent(text="test")],
        )

    @pytest.mark.asyncio
    async def test_send_empty_parts(self, channel: ZaloChannel) -> None:
        await channel.send("zalo:u42", [])
        # no crash


# =============================================================================
# 9. Lifecycle
# =============================================================================


class TestZaloLifecycle:
    """start / stop / health_check."""

    @pytest.mark.asyncio
    async def test_start_disabled(self, process: AsyncMock) -> None:
        ch = ZaloChannel(process=process, enabled=False, bot_token="")
        await ch.start()
        assert ch._task is None

    @pytest.mark.asyncio
    async def test_start_no_token(self, process: AsyncMock) -> None:
        ch = ZaloChannel(process=process, enabled=True, bot_token="")
        await ch.start()
        assert ch._task is None

    @pytest.mark.asyncio
    async def test_start_stop(self, channel: ZaloChannel) -> None:
        await channel.start()
        assert channel._task is not None
        assert not channel._task.done()
        await channel.stop()
        assert channel._task is None
        assert channel._http is None

    @pytest.mark.asyncio
    async def test_double_start(self, channel: ZaloChannel) -> None:
        await channel.start()
        task = channel._task
        await channel.start()  # second start should be no-op
        assert channel._task is task

    @pytest.mark.asyncio
    async def test_stop_idle(self, channel: ZaloChannel) -> None:
        # stop without start — should not crash
        await channel.stop()


# =============================================================================
# 10. Helpers
# =============================================================================


class TestZaloHelpers:
    """_handle_to_chat_id, _split_text."""

    def test_handle_to_chat_id_private(self) -> None:
        assert ZaloChannel._handle_to_chat_id("zalo:u42") == "u42"

    def test_handle_to_chat_id_group(self) -> None:
        assert ZaloChannel._handle_to_chat_id("zalo:group:g99") == "g99"

    def test_handle_to_chat_id_raw(self) -> None:
        assert ZaloChannel._handle_to_chat_id("raw_id") == "raw_id"

    def test_split_text_short(self) -> None:
        chunks = ZaloChannel._split_text("hello", 2000)
        assert chunks == ["hello"]

    def test_split_text_long(self) -> None:
        text = "a " * 500
        chunks = ZaloChannel._split_text(text, 100)
        assert len(chunks) > 1
        assert all(len(c) <= 100 for c in chunks)
