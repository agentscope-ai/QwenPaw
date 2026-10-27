# -*- coding: utf-8 -*-
"""Extended tests for DingTalk send_content_parts delivery branches.

Covers the delivery paths that the existing send-content tests do not
exercise: the AI-card (cron/proactive) path with Open API media
follow-up, the AI-card failure fallback, webhook media failure falling
back to Open API, the no-webhook Open API text+media path, the
no-webhook/no-conversation skip, the plain-text fallback, and refusal
content handling.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

from pathlib import Path
from typing import Generator
from unittest.mock import AsyncMock, patch

import pytest

from qwenpaw.app.channels.base import (
    FileContent,
    TextContent,
)
from qwenpaw.app.channels.renderer import ChannelDisplayConfig
from qwenpaw.exceptions import ChannelError
from qwenpaw.schemas import ContentType


@pytest.fixture
def mock_process_handler() -> AsyncMock:
    async def mock_process(*_args, **_kwargs):
        from unittest.mock import MagicMock

        mock_event = MagicMock()
        mock_event.object = "message"
        mock_event.status = "completed"
        mock_event.type = "text"
        yield mock_event

    return AsyncMock(side_effect=mock_process)


@pytest.fixture
def temp_media_dir(tmp_path) -> Path:
    media_dir = tmp_path / ".copaw" / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    return media_dir


@pytest.fixture
def channel(mock_process_handler, temp_media_dir) -> Generator:
    from qwenpaw.app.channels.dingtalk.channel import DingTalkChannel

    channel = DingTalkChannel(
        process=mock_process_handler,
        enabled=True,
        client_id="test_client_id",
        client_secret="test_client_secret",
        bot_prefix="[TestBot] ",
        media_dir=str(temp_media_dir),
        display_config=ChannelDisplayConfig(
            show_tool_calls=False,
            show_tool_results=False,
        ),
    )
    yield channel


def _open_api_params(conversation_id: str = "conv-1") -> dict:
    return {
        "conversation_id": conversation_id,
        "conversation_type": "group",
        "sender_staff_id": "staff-1",
    }


# ---------------------------------------------------------------------------
# AI card path (cron / proactive sends)
# ---------------------------------------------------------------------------


class TestSendContentPartsAiCardPath:
    async def test_ai_card_sends_and_returns_early(self, channel):
        """When the cron AI card is enabled and resolves, media parts go
        out via Open API and the webhook path is skipped entirely."""
        channel.cron_message_type = "card"
        channel.card_template_id = "tpl-1"
        channel.robot_code = "robot-1"
        card = object()
        media_part = FileContent(
            type=ContentType.FILE,
            file_url="/tmp/report.pdf",
        )
        parts = [
            TextContent(type=ContentType.TEXT, text="summary body"),
            media_part,
        ]
        with (
            patch.object(
                channel,
                "_get_session_webhook_for_send",
                new=AsyncMock(return_value="http://webhook"),
            ),
            patch.object(
                channel,
                "_resolve_open_api_params_from_handle",
                new=AsyncMock(return_value=_open_api_params()),
            ),
            patch.object(
                channel,
                "_create_ai_card",
                new=AsyncMock(return_value=card),
            ) as create_card,
            patch.object(
                channel,
                "_stream_ai_card",
                new=AsyncMock(return_value=None),
            ) as stream_card,
            patch.object(
                channel,
                "_send_media_part_via_open_api",
                new=AsyncMock(return_value=True),
            ) as send_media,
            patch.object(
                channel,
                "_send_via_session_webhook",
                new=AsyncMock(return_value=True),
            ) as send_webhook,
        ):
            await channel.send_content_parts(
                to_handle="dingtalk:sw:test",
                parts=parts,
                meta={},
            )
        create_card.assert_awaited_once()
        stream_card.assert_awaited_once()
        send_media.assert_awaited_once()
        send_webhook.assert_not_awaited()

    async def test_ai_card_failure_falls_back_to_webhook(self, channel):
        """When the AI card raises, the webhook path still delivers."""
        channel.cron_message_type = "card"
        channel.card_template_id = "tpl-1"
        channel.robot_code = "robot-1"
        parts = [TextContent(type=ContentType.TEXT, text="body")]
        with (
            patch.object(
                channel,
                "_get_session_webhook_for_send",
                new=AsyncMock(return_value="http://webhook"),
            ),
            patch.object(
                channel,
                "_resolve_open_api_params_from_handle",
                new=AsyncMock(return_value=_open_api_params()),
            ),
            patch.object(
                channel,
                "_create_ai_card",
                new=AsyncMock(side_effect=RuntimeError("card boom")),
            ),
            patch.object(
                channel,
                "_send_via_session_webhook",
                new=AsyncMock(return_value=True),
            ) as send_webhook,
        ):
            await channel.send_content_parts(
                to_handle="dingtalk:sw:test",
                parts=parts,
                meta={},
            )
        send_webhook.assert_awaited_once()

    async def test_ai_card_without_conversation_skips_card(
        self,
        channel,
    ):
        """No conversation id means the card cannot target anyone."""
        channel.cron_message_type = "card"
        channel.card_template_id = "tpl-1"
        channel.robot_code = "robot-1"
        parts = [TextContent(type=ContentType.TEXT, text="body")]
        with (
            patch.object(
                channel,
                "_get_session_webhook_for_send",
                new=AsyncMock(return_value="http://webhook"),
            ),
            patch.object(
                channel,
                "_resolve_open_api_params_from_handle",
                new=AsyncMock(return_value=_open_api_params("")),
            ),
            patch.object(
                channel,
                "_create_ai_card",
                new=AsyncMock(return_value=object()),
            ) as create_card,
            patch.object(
                channel,
                "_send_via_session_webhook",
                new=AsyncMock(return_value=True),
            ) as send_webhook,
        ):
            await channel.send_content_parts(
                to_handle="dingtalk:sw:test",
                parts=parts,
                meta={},
            )
        create_card.assert_not_awaited()
        send_webhook.assert_awaited_once()


# ---------------------------------------------------------------------------
# webhook media failure -> Open API fallback
# ---------------------------------------------------------------------------


class TestSendContentPartsMediaFallback:
    async def test_webhook_media_failure_falls_back_to_open_api(
        self,
        channel,
    ):
        media_part = FileContent(
            type=ContentType.FILE,
            file_url="/tmp/report.pdf",
        )
        parts = [TextContent(type=ContentType.TEXT, text="body"), media_part]
        with (
            patch.object(
                channel,
                "_get_session_webhook_for_send",
                new=AsyncMock(return_value="http://webhook"),
            ),
            patch.object(
                channel,
                "_send_via_session_webhook",
                new=AsyncMock(return_value=True),
            ),
            patch.object(
                channel,
                "_send_media_part_via_webhook",
                new=AsyncMock(return_value=False),
            ),
            patch.object(
                channel,
                "_resolve_open_api_params_from_handle",
                new=AsyncMock(return_value=_open_api_params()),
            ),
            patch.object(
                channel,
                "_send_media_part_via_open_api",
                new=AsyncMock(return_value=True),
            ) as open_api_media,
        ):
            await channel.send_content_parts(
                to_handle="dingtalk:sw:test",
                parts=parts,
                meta={},
            )
        open_api_media.assert_awaited_once()
        call_kwargs = open_api_media.await_args.kwargs
        assert call_kwargs["conversation_id"] == "conv-1"
        assert call_kwargs["conversation_type"] == "group"
        assert call_kwargs["sender_staff_id"] == "staff-1"

    async def test_text_failure_invalidates_webhook_before_fallback(
        self,
        channel,
    ):
        parts = [TextContent(type=ContentType.TEXT, text="body")]
        with (
            patch.object(
                channel,
                "_get_session_webhook_for_send",
                new=AsyncMock(return_value="http://webhook"),
            ),
            patch.object(
                channel,
                "_send_via_session_webhook",
                new=AsyncMock(return_value=False),
            ),
            patch.object(
                channel,
                "_invalidate_session_webhook",
                new=AsyncMock(return_value=None),
            ) as invalidate,
            patch.object(
                channel,
                "_try_open_api_fallback",
                new=AsyncMock(return_value=True),
            ) as fallback,
        ):
            await channel.send_content_parts(
                to_handle="dingtalk:sw:test",
                parts=parts,
                meta={},
            )
        invalidate.assert_awaited_once_with("dingtalk:sw:test")
        fallback.assert_awaited_once()


# ---------------------------------------------------------------------------
# no webhook -> Open API path
# ---------------------------------------------------------------------------


class TestSendContentPartsWithoutWebhook:
    async def test_media_sent_via_open_api_with_text_first(
        self,
        channel,
    ):
        media_part = FileContent(
            type=ContentType.FILE,
            file_url="/tmp/report.pdf",
        )
        parts = [TextContent(type=ContentType.TEXT, text="body"), media_part]
        with (
            patch.object(
                channel,
                "_get_session_webhook_for_send",
                new=AsyncMock(return_value=None),
            ),
            patch.object(
                channel,
                "_resolve_open_api_params_from_handle",
                new=AsyncMock(return_value=_open_api_params()),
            ),
            patch.object(
                channel,
                "_send_via_open_api",
                new=AsyncMock(return_value=True),
            ) as open_api_text,
            patch.object(
                channel,
                "_send_media_part_via_open_api",
                new=AsyncMock(return_value=True),
            ) as open_api_media,
            patch.object(
                channel,
                "send",
                new=AsyncMock(return_value=None),
            ) as plain_send,
        ):
            await channel.send_content_parts(
                to_handle="dingtalk:user-1",
                parts=parts,
                meta={},
            )
        open_api_text.assert_awaited_once()
        open_api_media.assert_awaited_once()
        plain_send.assert_not_awaited()

    async def test_open_api_text_failure_raises_for_api_send(
        self,
        channel,
    ):
        media_part = FileContent(
            type=ContentType.FILE,
            file_url="/tmp/report.pdf",
        )
        parts = [TextContent(type=ContentType.TEXT, text="body"), media_part]
        with (
            patch.object(
                channel,
                "_get_session_webhook_for_send",
                new=AsyncMock(return_value=None),
            ),
            patch.object(
                channel,
                "_resolve_open_api_params_from_handle",
                new=AsyncMock(return_value=_open_api_params()),
            ),
            patch.object(
                channel,
                "_send_via_open_api",
                new=AsyncMock(return_value=False),
            ),
        ):
            with pytest.raises(ChannelError, match="Open API text"):
                await channel.send_content_parts(
                    to_handle="dingtalk:user-1",
                    parts=parts,
                    meta={"_api_send": True},
                )

    async def test_no_webhook_no_conversation_skips_media(
        self,
        channel,
    ):
        """Without webhook or conversation id the media parts are skipped."""
        media_part = FileContent(
            type=ContentType.FILE,
            file_url="/tmp/report.pdf",
        )
        parts = [media_part]
        with (
            patch.object(
                channel,
                "_get_session_webhook_for_send",
                new=AsyncMock(return_value=None),
            ),
            patch.object(
                channel,
                "_resolve_open_api_params_from_handle",
                new=AsyncMock(return_value=_open_api_params("")),
            ),
            patch.object(
                channel,
                "_send_media_part_via_open_api",
                new=AsyncMock(return_value=True),
            ) as open_api_media,
        ):
            await channel.send_content_parts(
                to_handle="dingtalk:user-1",
                parts=parts,
                meta={},
            )
        open_api_media.assert_not_awaited()

    async def test_text_only_without_webhook_uses_plain_send(
        self,
        channel,
    ):
        parts = [TextContent(type=ContentType.TEXT, text="plain body")]
        with (
            patch.object(
                channel,
                "_get_session_webhook_for_send",
                new=AsyncMock(return_value=None),
            ),
            patch.object(
                channel,
                "send",
                new=AsyncMock(return_value=None),
            ) as plain_send,
        ):
            await channel.send_content_parts(
                to_handle="dingtalk:user-1",
                parts=parts,
                meta={},
            )
        plain_send.assert_awaited_once()
        args = plain_send.await_args.args
        assert args[0] == "dingtalk:user-1"
        assert args[1] == "plain body"

    async def test_bot_prefix_in_meta_prepended_to_body(self, channel):
        """The bot_prefix carried in meta is joined to the text body."""
        parts = [TextContent(type=ContentType.TEXT, text="hello")]
        with (
            patch.object(
                channel,
                "_get_session_webhook_for_send",
                new=AsyncMock(return_value=None),
            ),
            patch.object(
                channel,
                "send",
                new=AsyncMock(return_value=None),
            ) as plain_send,
        ):
            await channel.send_content_parts(
                to_handle="dingtalk:user-1",
                parts=parts,
                meta={"bot_prefix": "[Bot]"},
            )
        plain_send.assert_awaited_once()
        assert plain_send.await_args.args[1] == "[Bot]  hello"


# ---------------------------------------------------------------------------
# content type handling
# ---------------------------------------------------------------------------


class TestSendContentPartsContentTypes:
    async def test_refusal_content_delivered_as_text(self, channel):
        from qwenpaw.app.channels.base import ContentType as CT

        refusal_part = TextContent(
            type=CT.REFUSAL,
            refusal="I cannot do that",
        )
        with (
            patch.object(
                channel,
                "_get_session_webhook_for_send",
                new=AsyncMock(return_value="http://webhook"),
            ),
            patch.object(
                channel,
                "_send_via_session_webhook",
                new=AsyncMock(return_value=True),
            ) as send_webhook,
        ):
            await channel.send_content_parts(
                to_handle="dingtalk:sw:test",
                parts=[refusal_part],
                meta={},
            )
        send_webhook.assert_awaited_once()
        sent_body = send_webhook.await_args.args[1]
        assert "I cannot do that" in sent_body

    async def test_dict_parts_are_accepted(self, channel):
        """Legacy dict-shaped parts still route by their 'type' key."""
        dict_part = {
            "type": ContentType.TEXT,
            "text": "dict body",
        }
        with (
            patch.object(
                channel,
                "_get_session_webhook_for_send",
                new=AsyncMock(return_value="http://webhook"),
            ),
            patch.object(
                channel,
                "_send_via_session_webhook",
                new=AsyncMock(return_value=True),
            ) as send_webhook,
        ):
            await channel.send_content_parts(
                to_handle="dingtalk:sw:test",
                parts=[dict_part],
                meta={},
            )
        send_webhook.assert_awaited_once()
        sent_body = send_webhook.await_args.args[1]
        assert "dict body" in sent_body

    async def test_whitespace_refusal_is_dropped(self, channel):
        from qwenpaw.app.channels.base import ContentType as CT

        refusal_part = TextContent(
            type=CT.REFUSAL,
            refusal="   ",
        )
        with (
            patch.object(
                channel,
                "send",
                new=AsyncMock(return_value=None),
            ) as plain_send,
            patch.object(
                channel,
                "_send_via_session_webhook",
                new=AsyncMock(return_value=True),
            ) as send_webhook,
        ):
            await channel.send_content_parts(
                to_handle="dingtalk:user-1",
                parts=[refusal_part],
                meta={},
            )
        send_webhook.assert_not_awaited()
        plain_send.assert_not_awaited()


# ---------------------------------------------------------------------------
# _api_send_delivery_errors helper
# ---------------------------------------------------------------------------


class TestApiSendDeliveryErrors:
    def test_none_meta_returns_false(self, channel):
        assert channel._api_send_delivery_errors(None) is False

    def test_empty_meta_returns_false(self, channel):
        assert channel._api_send_delivery_errors({}) is False

    def test_api_send_flag_returns_true(self, channel):
        assert channel._api_send_delivery_errors({"_api_send": True}) is True

    def test_raise_helper_raises_only_for_api_send(self, channel):
        with pytest.raises(ChannelError, match="boom"):
            channel._raise_delivery_error_if_api_send(True, "boom")
        # No raise when flag is False:
        channel._raise_delivery_error_if_api_send(False, "no raise")
