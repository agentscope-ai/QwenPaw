"""Actual nio sync/parser/download inbound paths; host acceptance is explicit."""
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest
from matrix_native_support import BOT, ROOM, hs, platform_factory, sync_payload, text_event, until


async def ready(server, platform):
    server.sync.put_nowait((sync_payload("catchup"), 200))
    await platform.start()
    await until(lambda: len(server.calls("/sync")) == 2)


@pytest.mark.asyncio
@pytest.mark.parametrize(("kind", "filename"), [("image", "image.png"), ("video", "video.mp4"), ("audio", "audio.mp3"), ("file", "document.pdf")])
async def test_native_media_event_is_downloaded_and_admitted_once(hs, platform_factory, kind, filename):
    platform = platform_factory(vision_enabled=True)
    await ready(hs, platform)
    event = text_event(filename, "$abc123")
    event["content"] = {"msgtype": "m." + kind, "body": filename, "url": "mxc://example.org/media", "info": {"mimetype": "application/octet-stream", "size": len(hs.download)}}
    hs.sync.put_nowait((sync_payload("media", [event]), 200))
    await until(lambda: len(platform.observed_events) == 1)
    payload = platform.observed_events[0]
    parts = payload["content_parts"]
    assert any(getattr(p, "type", None) == kind for p in parts)
    assert len(parts) == 1 and payload["sender_id"] == "@user:example.com"
    part = parts[0]
    uri = getattr(part, "data" if kind == "audio" else kind + "_url")
    path = Path(unquote(urlparse(uri).path))
    assert uri.startswith("file://") and path.is_relative_to(Path(platform.config["workspace_dir"]))
    assert path.read_bytes() == hs.download
    assert len([r for r in hs.requests if "/download/" in r["path"]]) == 1
    assert hs.calls("/read_markers")[0]["body"] == {"m.fully_read": "$abc123", "m.read": "$abc123"}


@pytest.mark.asyncio
async def test_native_vision_disabled_preserves_text_fallback(hs, platform_factory):
    platform = platform_factory(vision_enabled=False)
    await ready(hs, platform)
    event = text_event("image.png", "$img")
    event["content"].update(msgtype="m.image", url="mxc://example.org/image")
    hs.sync.put_nowait((sync_payload("image", [event]), 200))
    await until(lambda: len(platform.observed_events) == 1)
    assert [p.type for p in platform.observed_events[0]["content_parts"]] == ["text"]
    assert platform.observed_events[0]["content_parts"][0].text == "[User sent an image (current model does not support image input): image.png]"


@pytest.mark.asyncio
async def test_native_self_no_reply_and_dm_mute_never_admit(hs, platform_factory):
    platform = platform_factory()
    await ready(hs, platform)
    hs.sync.put_nowait((sync_payload("ignored", [text_event("own", "$own", BOT), text_event("NO_REPLY", "$no")]), 200))
    await until(lambda: len(hs.calls("/sync")) == 3)
    assert platform.observed_events == []
    assert [r["body"]["m.read"] for r in hs.calls("/read_markers")] == ["$no"]
    platform.dm_disabled = True
    hs.sync.put_nowait((sync_payload("muted", [text_event("Hello", "$muted")]), 200))
    await until(lambda: len(hs.calls("/sync")) == 4)
    assert platform.observed_events == []
    assert len(hs.calls("/read_markers")) == 1


@pytest.mark.asyncio
async def test_group_history_retained_until_accepted_and_slash_alias_is_exact(hs, platform_factory):
    hs.group = True
    platform = platform_factory()
    await ready(hs, platform)
    hs.sync.put_nowait((sync_payload("history", [text_event("earlier", "$earlier")]), 200))
    await until(lambda: len(hs.calls("/sync")) == 3)
    assert platform.observed_events == [] and len(platform._room_histories[ROOM]) == 1
    original = platform.on_event
    async def rejected(payload):
        await original(payload)
        return False
    platform.on_event = rejected
    hs.sync.put_nowait((sync_payload("reject", [text_event("@bot:example.com help", "$reject")]), 200))
    await until(lambda: len(hs.calls("/sync")) == 4)
    assert len(platform.observed_events) == 1 and len(platform._room_histories[ROOM]) == 1
    text = platform.observed_events[0]["content_parts"][0].text
    assert "earlier" in text and "[Chat messages since your last reply - for context]" in text
    platform.on_event = original
    hs.sync.put_nowait((sync_payload("accept", [text_event("@bot:example.com /reset", "$reset")]), 200))
    await until(lambda: len(platform.observed_events) == 2)
    assert platform.observed_events[1]["content_parts"][0].text == "/clear"
    assert not platform._room_histories.get(ROOM)
