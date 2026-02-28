from __future__ import annotations

from typing import Any, AsyncIterator

from agentscope.message import Msg
from agentscope_runtime.engine.schemas.agent_schemas import (
    ContentType,
    ImageContent,
)

from copaw.app.channels.base import BaseChannel
from copaw.app.channels.qq.channel import QQChannel
from copaw.app.runner.utils import agentscope_msg_to_message


class _DummyChannel(BaseChannel):
    channel = "dummy"

    @classmethod
    def from_env(cls, process, on_reply_sent=None):  # type: ignore[override]
        return cls(process=process, on_reply_sent=on_reply_sent)

    @classmethod
    def from_config(
        cls,
        process,
        config,
        on_reply_sent=None,
        show_tool_details=True,
    ):  # type: ignore[override]
        del config
        del show_tool_details
        return cls(process=process, on_reply_sent=on_reply_sent)

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def send(self, to_handle: str, text: str, meta=None) -> None:
        del to_handle
        del text
        del meta
        return None


async def _dummy_process(_request: Any) -> AsyncIterator[Any]:
    if False:
        yield None


def test_base_channel_media_only_message_should_be_actionable() -> None:
    channel = _DummyChannel(process=_dummy_process)
    assert channel._content_has_text(  # pylint: disable=protected-access
        [
            ImageContent(
                type=ContentType.IMAGE,
                image_url="https://example.com/a.png",
            ),
        ],
    )


def test_agentscope_msg_to_message_supports_video_block() -> None:
    msg = Msg(
        name="user",
        role="user",
        content=[
            {
                "type": "video",
                "source": {"type": "url", "url": "https://example.com/a.mp4"},
            },
        ],
    )
    messages = agentscope_msg_to_message(msg)
    assert len(messages) == 1
    assert len(messages[0].content) == 1
    first = messages[0].content[0]
    assert getattr(first, "type", None) == ContentType.FILE
    assert getattr(first, "file_url", None) == "https://example.com/a.mp4"


def test_qq_attachment_is_mapped_to_audio_video() -> None:
    content_parts = QQChannel._build_content_parts(  # pylint: disable=protected-access
        "",
        [
            {
                "url": "https://example.com/sample.mp3",
                "filename": "sample.mp3",
                "content_type": "audio/mpeg",
            },
            {
                "url": "https://example.com/sample.mp4",
                "filename": "sample.mp4",
                "content_type": "video/mp4",
            },
        ],
    )
    types = [getattr(part, "type", None) for part in content_parts]
    assert ContentType.AUDIO in types
    assert ContentType.VIDEO in types

