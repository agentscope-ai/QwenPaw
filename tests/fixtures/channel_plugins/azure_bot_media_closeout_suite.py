"""Uncovered original Azure URL/data and explicit parts packing responsibilities."""
import pytest

from azure_bot_native_support import (
    azure,
    connector,
    rsa_material,
    post,
    activity,
)
from azure_bot_native_suite import send_params

__all__ = ["azure", "connector", "rsa_material"]


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["content_parts", "media"])
async def test_native_url_data_media_keep_legacy_parts_presentation(
    azure,
    connector,
    source,
):
    image_url = "https://media.test/image.png"
    file_url = "data:application/pdf;base64,cGRm"
    audio_url = "data:audio/mpeg;base64,YXVkaW8="
    media = [
        {"type": "image", "image_url": image_url},
        {"type": "file", "file_url": file_url, "filename": "report.pdf"},
        {"type": "audio", "data": audio_url},
    ]
    parts = (
        [
            media[0],
            {"type": "text", "text": "alpha"},
            media[1],
            {"type": "text", "text": "omega"},
            media[2],
        ]
        if source == "content_parts"
        else media
    )
    async with azure() as (driver, peer):
        assert (await post(driver, connector, activity()))[0] == 200
        batches = (
            [parts]
            if source == "content_parts"
            else [[part] for part in parts]
        )
        for number, batch in enumerate(batches):
            result = await driver._send(
                send_params(
                    driver,
                    peer.events[0],
                    delivery=f"media-{number}",
                    parts=batch,
                    source=source,
                ),
                None,
            )
            assert result["state"] == "acknowledged"
        bodies = [row[1] for row in connector.requests]
        if source == "content_parts":
            assert bodies.pop(0) == {
                "type": "message",
                "from": {"id": "native-bot"},
                "text": f"alpha\nomega\n[Image: {image_url}]\n[File: {file_url}]\n[Audio]",
            }
        assert bodies == [
            {
                "type": "message",
                "from": {"id": "native-bot"},
                "attachments": [attachment],
            }
            for attachment in [
                {
                    "contentType": "image/png",
                    "contentUrl": image_url,
                    "name": "image.png",
                },
                {
                    "contentType": "application/octet-stream",
                    "contentUrl": file_url,
                    "name": "report.pdf",
                },
                {
                    "contentType": "audio/mpeg",
                    "contentUrl": audio_url,
                    "name": "audio.mp3",
                },
            ]
        ]
        assert all(
            row[0] == "/v3/conversations/conversation-ABCDEFGHIJ/activities"
            for row in connector.requests
        )
        assert all(row[2] == "Bearer access-1" for row in connector.requests)
        # Native remote/data attachments are referenced, never downloaded/uploaded.
        assert len(connector.requests) == (
            4 if source == "content_parts" else 3
        )
        assert connector.token_calls == 1
