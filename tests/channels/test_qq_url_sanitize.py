# -*- coding: utf-8 -*-

from copaw.app.channels.qq.channel import _sanitize_qq_text


def test_sanitize_qq_text_replaces_http_and_https_urls() -> None:
    text = "请看 https://example.com 和 http://a.b/c?q=1"
    sanitized, had_url = _sanitize_qq_text(text)

    assert had_url is True
    assert "http://" not in sanitized
    assert "https://" not in sanitized
    assert sanitized.count("[链接已省略]") == 2


def test_sanitize_qq_text_keeps_plain_text_unchanged() -> None:
    text = "这是普通消息，没有链接"
    sanitized, had_url = _sanitize_qq_text(text)

    assert had_url is False
    assert sanitized == text
