# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from qwenpaw.utils.http import (
    is_loopback_host,
    is_loopback_url,
    trust_env_for_url,
)


@pytest.mark.parametrize(
    "host",
    [
        "localhost",
        "localhost.",
        "127.0.0.1",
        "127.1.2.3",
        "::1",
        "[::1]",
    ],
)
def test_is_loopback_host_recognizes_loopback_targets(host: str) -> None:
    assert is_loopback_host(host) is True


@pytest.mark.parametrize(
    "host",
    [
        "",
        "0.0.0.0",
        "::",
        "192.168.1.10",
        "10.0.0.1",
        "example.com",
    ],
)
def test_is_loopback_host_keeps_non_loopback_targets(host: str) -> None:
    assert is_loopback_host(host) is False


# Local API calls should bypass env proxies for localhost/loopback targets.
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


# Non-loopback URLs keep httpx's normal env proxy behavior.
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
