# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from copaw.agents.tools.send_file import send_file_to_user


def _write_file(path: Path, content: bytes = b"data") -> str:
    path.write_bytes(content)
    return str(path)


def test_send_file_to_user_returns_image_block(tmp_path: Path) -> None:
    file_path = _write_file(tmp_path / "image.png")

    response = asyncio.run(send_file_to_user(file_path))

    assert response.content[0]["type"] == "image"
    assert response.content[0]["source"]["type"] == "url"
    assert response.content[0]["source"]["url"].startswith("file://")
    assert response.content[1]["type"] == "text"


def test_send_file_to_user_returns_audio_block(tmp_path: Path) -> None:
    file_path = _write_file(tmp_path / "audio.mp3")

    response = asyncio.run(send_file_to_user(file_path))

    assert response.content[0]["type"] == "audio"
    assert response.content[0]["source"]["type"] == "url"
    assert response.content[0]["source"]["url"].startswith("file://")
    assert response.content[1]["type"] == "text"


def test_send_file_to_user_returns_video_block(tmp_path: Path) -> None:
    file_path = _write_file(tmp_path / "video.mp4")

    response = asyncio.run(send_file_to_user(file_path))

    assert response.content[0]["type"] == "video"
    assert response.content[0]["source"]["type"] == "url"
    assert response.content[0]["source"]["url"].startswith("file://")
    assert response.content[1]["type"] == "text"


def test_send_file_to_user_returns_file_block_for_text_plain(
    tmp_path: Path,
) -> None:
    file_path = _write_file(tmp_path / "notes.txt", b"hello world")

    response = asyncio.run(send_file_to_user(file_path))

    assert response.content[0]["type"] == "file"
    assert response.content[0]["filename"] == "notes.txt"
    assert response.content[0]["source"]["type"] == "url"
    assert response.content[0]["source"]["url"].startswith("file://")
    assert response.content[1]["type"] == "text"


def test_send_file_to_user_returns_file_block_for_json(
    tmp_path: Path,
) -> None:
    file_path = _write_file(tmp_path / "payload.json", b'{"ok": true}')

    response = asyncio.run(send_file_to_user(file_path))

    assert response.content[0]["type"] == "file"
    assert response.content[0]["filename"] == "payload.json"
    assert response.content[0]["source"]["type"] == "url"
    assert response.content[0]["source"]["url"].startswith("file://")
    assert response.content[1]["type"] == "text"


def test_send_file_to_user_returns_error_for_missing_file() -> None:
    response = asyncio.run(send_file_to_user("missing-file.txt"))

    assert response.content[0]["type"] == "text"
    assert "does not exist" in response.content[0]["text"]


def test_send_file_to_user_returns_error_for_directory(tmp_path: Path) -> None:
    response = asyncio.run(send_file_to_user(str(tmp_path)))

    assert response.content[0]["type"] == "text"
    assert "is not a file" in response.content[0]["text"]
