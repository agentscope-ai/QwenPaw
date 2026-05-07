# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from qwenpaw.utils.http import is_loopback_url, trust_env_for_url


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8088/api",
        "http://localhost.:8088/api",
        "http://127.0.0.1:8088/api",
        "http://127.1.2.3:8088/api",
        "http://[::1]:8088/api",
    ],
)
def test_is_loopback_url_recognizes_loopback_targets(url: str) -> None:
    assert is_loopback_url(url) is True
    assert trust_env_for_url(url) is False


@pytest.mark.parametrize(
    "url",
    [
        "http://192.168.1.10:8088/api",
        "https://example.com/api",
        "http://10.0.0.1:8088/api",
    ],
)
def test_is_loopback_url_keeps_non_loopback_targets(url: str) -> None:
    assert is_loopback_url(url) is False
    assert trust_env_for_url(url) is True
