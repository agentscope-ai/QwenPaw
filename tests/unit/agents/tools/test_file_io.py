# -*- coding: utf-8 -*-
"""Tests for file I/O tools."""

import pytest

from qwenpaw.agents.tools import file_io
from qwenpaw.config.context import set_current_recent_max_bytes
from qwenpaw.constant import TRUNCATION_NOTICE_MARKER


@pytest.fixture(autouse=True)
def reset_recent_max_bytes():
    set_current_recent_max_bytes(None)
    yield
    set_current_recent_max_bytes(None)


def _response_text(response):
    return response.content[0].get("text", "")


@pytest.mark.asyncio
async def test_read_file_streams_oversized_single_line(monkeypatch, tmp_path):
    monkeypatch.setattr(file_io, "STREAMING_READ_MIN_BYTES", 32)
    set_current_recent_max_bytes(64)

    path = tmp_path / "session.json"
    path.write_text("x" * 512, encoding="utf-8")

    response = await file_io.read_file(str(path))
    text = _response_text(response)
    excerpt = text.split(TRUNCATION_NOTICE_MARKER, 1)[0]

    assert excerpt.count("x") == 64
    assert TRUNCATION_NOTICE_MARKER in text
    assert "total line count was not scanned" in text
    assert f"file_path={path}" in text
    assert "start_line=2" in text


@pytest.mark.asyncio
async def test_read_file_streams_range_from_oversized_file(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(file_io, "STREAMING_READ_MIN_BYTES", 32)
    set_current_recent_max_bytes(128)

    path = tmp_path / "large.log"
    path.write_text(
        "\n".join(f"line {index}" for index in range(1, 101)),
        encoding="utf-8",
    )

    response = await file_io.read_file(
        str(path),
        start_line=10,
        end_line=12,
    )
    text = _response_text(response)

    assert "line 10" in text
    assert "line 12" in text
    assert "line 9" not in text
    assert "line 13" not in text
    assert TRUNCATION_NOTICE_MARKER in text
    assert "start_line=13" in text
