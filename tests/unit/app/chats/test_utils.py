# -*- coding: utf-8 -*-
from __future__ import annotations

from qwenpaw.app.chats.utils import (
    _abspath_from_url,
    _is_local_file_url,
    _resolve_content_url,
    strip_injected_skill_block,
)
from qwenpaw.app.chats.title_generator import _clean_title


# ---------------------------------------------------------------------------
# _is_local_file_url
# ---------------------------------------------------------------------------


def test_is_local_file_url_file_scheme():
    assert _is_local_file_url("file:///tmp/x.txt") is True


def test_is_local_file_url_unix_path():
    assert _is_local_file_url("/home/user/doc.pdf") is True


def test_is_local_file_url_windows_path():
    assert _is_local_file_url("C:\\Users\\doc.pdf") is True


def test_is_local_file_url_rejects_http():
    assert _is_local_file_url("https://example.com/f") is False


def test_is_local_file_url_rejects_data_uri():
    assert _is_local_file_url("data:image/png;base64,abc") is False


def test_is_local_file_url_rejects_empty():
    assert _is_local_file_url("") is False


# ---------------------------------------------------------------------------
# _abspath_from_url
# ---------------------------------------------------------------------------


def test_abspath_from_file_url():
    assert _abspath_from_url("file:///tmp/x.txt") == "/tmp/x.txt"


def test_abspath_from_bare_path():
    assert _abspath_from_url("/tmp/x.txt") == "/tmp/x.txt"


def test_abspath_decodes_percent():
    assert (
        _abspath_from_url("file:///path/my%20file.txt") == "/path/my file.txt"
    )


# ---------------------------------------------------------------------------
# _resolve_content_url
# ---------------------------------------------------------------------------


def test_resolve_local_returns_abspath():
    assert _resolve_content_url("file:///tmp/x.txt") == "/tmp/x.txt"


def test_resolve_remote_passthrough():
    assert (
        _resolve_content_url("https://example.com/f")
        == "https://example.com/f"
    )


# ---------------------------------------------------------------------------
# strip_injected_skill_block
# ---------------------------------------------------------------------------


def test_strip_skill_block_removes_user_skill():
    text = "/hello<skill name='greeter'>expanded content</skill>"
    result = strip_injected_skill_block(text, "user")
    assert "<skill" not in result
    assert "/hello" in result


def test_strip_skill_block_skips_non_user_role():
    text = "some text<skill name='x'>content</skill>"
    assert strip_injected_skill_block(text, "assistant") == text


def test_strip_skill_block_skips_when_no_skill_tag():
    assert strip_injected_skill_block("plain text", "user") == "plain text"


# ---------------------------------------------------------------------------
# _clean_title
# ---------------------------------------------------------------------------


def test_clean_title_strips_quotes_and_punctuation():
    assert _clean_title('"Hello World,"') == "Hello World"


def test_clean_title_takes_first_line():
    assert _clean_title("Line one\nLine two") == "Line one"


def test_clean_title_empty_returns_empty():
    assert _clean_title("") == ""
    assert _clean_title("   ") == ""


def test_clean_title_truncates_long_title():
    long_title = "x" * 200
    result = _clean_title(long_title)
    assert len(result) <= 80
