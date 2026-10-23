"""Retained upload/event metadata oracles at the real nio HTTP boundary."""
import base64
from pathlib import Path

import pytest
from matrix_native_support import ROOM, hs, platform_factory
from qwenpaw_channel_matrix.errors import MatrixDeliveryError


@pytest.mark.asyncio
@pytest.mark.parametrize(("byte_count", "filename"), [(8, "report.pdf"), (64 * 1024, None)])
async def test_data_url_event_reuses_upload_metadata(hs, platform_factory, byte_count, filename):
    # Exact original sizes/names/body oracle, observed on wire instead of an SDK mock.
    platform = platform_factory()
    await platform.start()
    data = b"a" * byte_count
    encoded = base64.b64encode(data).decode("ascii")
    part = {"type": "file", "file_url": f"data:application/pdf;base64,{encoded}", "filename": filename}
    await platform.send_parts({"room_id": ROOM}, [part], "media", "upload-1")
    assert len(hs.uploads) == 1 and len(hs.sent) == 1
    upload = hs.uploads[0]
    expected_name = filename or "file.pdf"
    assert upload["body"] == data
    assert upload["headers"]["Content-Type"] == "application/pdf"
    assert upload["query"]["filename"] == expected_name
    assert int(upload["headers"]["Content-Length"]) == byte_count
    assert hs.sent[0]["body"] == {"msgtype": "m.file", "body": expected_name,
                                  "url": "mxc://example.org/media",
                                  "info": {"mimetype": "application/pdf", "size": byte_count}}


@pytest.mark.asyncio
@pytest.mark.parametrize(("kind", "name", "mime", "data"), [
    ("image", "test_image.png", "image/png", b"fake image data"),
    ("video", "test_video.mp4", "video/mp4", b"fake video data"),
    ("audio", "test_audio.mp3", "audio/mpeg", b"fake audio data"),
    ("file", "test_document.pdf", "application/pdf", b"fake pdf data"),
])
async def test_local_media_types_and_original_bytes(hs, platform_factory, kind, name, mime, data):
    platform = platform_factory()
    await platform.start()
    path = Path(platform.config["workspace_dir"]) / name
    path.write_bytes(data)
    key = "data" if kind == "audio" else kind + "_url"
    await platform.send_parts({"room_id": ROOM}, [{"type": kind, key: path.as_uri()}], "media", "file-1")
    assert len(hs.uploads) == len(hs.sent) == 1
    assert hs.uploads[0]["body"] == data
    assert hs.sent[0]["body"] == {"msgtype": "m." + kind, "body": name,
                                  "url": "mxc://example.org/media",
                                  "info": {"mimetype": mime, "size": len(data)}}
    assert path.read_bytes() == data


@pytest.mark.asyncio
@pytest.mark.parametrize("file_ref", [
    r"C:\Users\alice\workspace\photo.png",
    "C:/Users/alice/workspace/photo.png",
])
async def test_windows_drive_path_upload(hs, platform_factory, monkeypatch, file_ref):
    platform = platform_factory()
    await platform.start()
    path = Path(platform.config["workspace_dir"]) / "photo.png"
    path.write_bytes(b"windows attachment")
    # Emulate only filesystem resolution; retain real locator classification/upload.
    monkeypatch.setattr(
        "qwenpaw_channel_matrix.platform.Path",
        lambda value: path if str(value) == file_ref else Path(value),
    )
    uploaded = await platform._upload_file(file_ref)
    assert uploaded is not None and uploaded.filename == "photo.png"
    assert len(hs.uploads) == 1
    assert hs.uploads[0]["body"] == b"windows attachment"
    assert hs.uploads[0]["headers"]["Content-Type"] == "image/png"


@pytest.mark.asyncio
@pytest.mark.parametrize("url", ["https://example.com/img.png", "ftp://example.com/img.png", "file:///not/owned/no.png"])
async def test_unsupported_media_never_uploads_or_sends(hs, platform_factory, url):
    platform = platform_factory()
    await platform.start()
    with pytest.raises(MatrixDeliveryError) as error:
        await platform.send_parts({"room_id": ROOM}, [{"type": "image", "image_url": url}], "media", "unsupported")
    assert error.value.side_effect_possible is False
    assert not hs.uploads and not hs.sent


@pytest.mark.asyncio
async def test_native_stream_edit_unknown_keeps_target_and_never_falls_back(hs, platform_factory):
    platform = platform_factory()
    await platform.start()
    resource = await platform.start_stream({"room_id": ROOM}, "answer", "stream-1")
    assert hs.sent[0]["body"]["body"] == "..."
    hs.send.append(({"errcode": "M_UNKNOWN", "error": "upstream write outcome unknown"}, 503))
    with pytest.raises(MatrixDeliveryError) as error:
        await platform.update_stream(resource, "answer", "edit-1", final=True)
    assert error.value.side_effect_possible is True
    assert len(hs.sent) == 2
    assert hs.sent[1]["body"]["m.relates_to"] == {"rel_type": "m.replace", "event_id": resource["event_id"]}
    assert hs.sent[1]["body"]["m.new_content"]["body"] == "answer"
