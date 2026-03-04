# -*- coding: utf-8 -*-
# pylint: disable=protected-access
import asyncio
from pathlib import Path

from copaw.agents.utils import message_processing


def test_update_image_block_uses_local_absolute_path(tmp_path):
    image_path = tmp_path / "sample.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake_png_content")

    block = {"type": "image", "source": {"type": "url", "url": "mock://old"}}
    updated = message_processing._update_block_with_local_path(
        block,
        "image",
        str(image_path),
    )

    source = updated["source"]
    assert source["type"] == "url"
    assert source["url"] == str(image_path.resolve())
    assert not source["url"].startswith("file://")


def test_update_audio_block_keeps_file_url_source(tmp_path):
    audio_path = tmp_path / "sample.wav"
    audio_path.write_bytes(b"RIFFxxxxWAVE")

    block = {"type": "audio", "source": {"type": "url", "url": "mock://old"}}
    updated = message_processing._update_block_with_local_path(
        block,
        "audio",
        str(audio_path),
    )

    source = updated["source"]
    assert source["type"] == "url"
    assert source["url"].startswith("file://")
    assert source["media_type"] == "audio/wav"


def test_process_single_file_block_rejects_plain_local_path_outside_media_root(
    tmp_path,
    monkeypatch,
):
    media_root = tmp_path / "media"
    media_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(message_processing, "_ALLOWED_MEDIA_ROOT", media_root)

    outside_path = tmp_path / "outside.png"
    outside_path.write_bytes(b"fake")

    result = asyncio.run(
        message_processing._process_single_file_block(
            source={"type": "url", "url": str(outside_path)},
            filename=None,
        ),
    )

    assert result is None


def test_process_single_file_block_accepts_plain_local_path_inside_media_root(
    tmp_path,
    monkeypatch,
):
    media_root = tmp_path / "media"
    media_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(message_processing, "_ALLOWED_MEDIA_ROOT", media_root)

    inside_file = media_root / "telegram" / "ok.png"
    inside_file.parent.mkdir(parents=True, exist_ok=True)
    inside_file.write_bytes(b"ok")

    result = asyncio.run(
        message_processing._process_single_file_block(
            source={"type": "url", "url": str(inside_file)},
            filename=None,
        ),
    )

    assert result == str(inside_file.resolve())


def test_is_allowed_media_path_rejects_same_prefix_not_child(
    tmp_path,
    monkeypatch,
):
    media_root = tmp_path / "media"
    media_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(message_processing, "_ALLOWED_MEDIA_ROOT", media_root)

    evil_file = tmp_path / "media_evil" / "bad.png"
    evil_file.parent.mkdir(parents=True, exist_ok=True)
    evil_file.write_bytes(b"bad")

    assert message_processing._is_allowed_media_path(str(evil_file)) is False


def test_extract_local_path_from_file_url(tmp_path):
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"img")

    result = message_processing._extract_local_path_from_url(
        Path(image_path).as_uri(),
    )

    assert result == str(image_path)
