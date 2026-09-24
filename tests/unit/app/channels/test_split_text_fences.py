# -*- coding: utf-8 -*-
"""Unit tests for code-fence handling in ``split_text``.

A chunk that ends inside an open fence must be closed with the marker that
opened it: a ``~~~`` fence cannot be closed by three backticks, and a shorter
fence inside an open fence stays content. Otherwise WeChat/WeCom/Yuanbao
receive chunks whose fence never closes and render the rest of the message as
code.
"""
from __future__ import annotations

from qwenpaw.app.channels.utils import split_text

TILDE_TEXT = (
    "~~~python\n"
    "def a(): return 1\ndef b(): return 2\ndef c(): return 3\n"
    "~~~"
)

NESTED_TEXT = (
    "````markdown\n"
    "Example:\n"
    "```python\nprint(1)\n```\n"
    "Done here now\n"
    "````"
)


def test_tilde_fence_is_closed_with_tildes():
    chunks = split_text(TILDE_TEXT, max_len=40)
    assert len(chunks) > 1
    for chunk in chunks[:-1]:
        assert chunk.startswith("~~~python\n")
        assert chunk.endswith("\n~~~")
        assert "```" not in chunk


def test_shorter_fence_inside_a_longer_fence_stays_content():
    chunks = split_text(NESTED_TEXT, max_len=40)
    opener = "````markdown\n"
    assert chunks[0].startswith(opener)
    # The inner three-backtick line is content, so the chunk that carries it
    # must still be closed with the four-backtick marker it opened with.
    assert chunks[0].endswith("\n````")
    assert any("```python" in chunk for chunk in chunks)


def test_plain_backtick_chunking_is_unchanged():
    body = "\n".join(f"body line {i} with some text" for i in range(3))
    chunks = split_text(f"```python\n{body}\n```", max_len=40)
    assert chunks[:2] == [
        "```python\nbody line 0 with some text\n```",
        "```python\nbody line 1 with some text\n```",
    ]
