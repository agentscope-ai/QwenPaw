# -*- coding: utf-8 -*-
"""Tests for stateful terminal byte-to-text formatting."""

from __future__ import annotations

import pytest

from qwenpaw.terminal.text_stream import TerminalTextStream


@pytest.mark.parametrize("chunk_size", [1, 2, 3, 5])
def test_text_stream_preserves_boundaries_and_strips_ansi(chunk_size):
    source = "\x1b[31m输入🙂\x1b[0m\r\n".encode("utf-8")
    stream = TerminalTextStream()
    output = []

    for start in range(0, len(source), chunk_size):
        end = min(len(source), start + chunk_size)
        output.append(stream.feed(source[start:end], final=end == len(source)))

    assert "".join(output) == "输入🙂\r\n"


def test_text_stream_preserves_incomplete_escape_at_end():
    stream = TerminalTextStream()

    assert stream.feed(b"before\x1b[", final=False) == "before"
    assert stream.feed(b"", final=True) == "\x1b["
