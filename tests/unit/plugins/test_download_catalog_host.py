# -*- coding: utf-8 -*-
"""Which host the plugin catalog is read from.

The official plugin list is served from whatever this resolves to, so a build
that publishes plugins to its own bucket has to read that bucket's index --
otherwise its plugin page shows someone else's catalog. It also makes the
catalog reachable from a test at all: before this the host was fixed, and the
endpoint's own integration test is still marked expected-to-fail because its
result depended on whether the machine running it could reach the internet.
"""

from __future__ import annotations

import http.client
import json
import ssl
import urllib.error
from typing import Any

import pytest

from qwenpaw.plugins import download_catalog
from qwenpaw.plugins.download_catalog import (
    DEFAULT_PLUGIN_DOWNLOAD_CDN,
    PLUGIN_DOWNLOAD_CDN_ENV,
    build_plugin_catalog,
    plugin_download_cdn,
)


def test_the_default_host_is_used_when_nothing_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(PLUGIN_DOWNLOAD_CDN_ENV, raising=False)
    assert plugin_download_cdn() == DEFAULT_PLUGIN_DOWNLOAD_CDN


def test_a_configured_host_replaces_the_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(PLUGIN_DOWNLOAD_CDN_ENV, "https://example.invalid/cdn")
    assert plugin_download_cdn() == "https://example.invalid/cdn"


def test_a_blank_host_falls_back_rather_than_building_bad_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty variable is a mistake, not an instruction.

    Taking it literally would build requests against ``/metadata/index.json``
    with no host at all, which fails in a way that says nothing useful.
    """
    monkeypatch.setenv(PLUGIN_DOWNLOAD_CDN_ENV, "   ")
    assert plugin_download_cdn() == DEFAULT_PLUGIN_DOWNLOAD_CDN


def test_the_catalog_is_fetched_from_the_configured_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole point: the index actually requested is the one configured."""
    monkeypatch.setenv(PLUGIN_DOWNLOAD_CDN_ENV, "https://fork.invalid")
    requested: list[str] = []

    def _fetch(url: str) -> Any:
        requested.append(url)
        if url.endswith("/metadata/index.json"):
            return {
                "products": {
                    "plugins": {"index_url": "/metadata/plugins/index.json"},
                },
            }
        return {
            "updated_at": "2026-01-01T00:00:00Z",
            "files": {
                "computer-use-tool-2.0.0": {
                    "id": "computer-use-tool-2.0.0",
                    "plugin_id": "computer-use-tool",
                    "name": {"en-US": "Computer Use"},
                    "description": {
                        "zh-CN": "\u4e2d\u6587\u8bf4\u660e",
                        "en-US": "English description",
                    },
                    "version": "2.0.0",
                    "author": "QwenPaw Team",
                    "platform": "tool",
                    "size": "1.2 MB",
                    "sha256": "0" * 64,
                    "url": "/files/plugins/tool/computer-use-tool/x.zip",
                },
            },
        }

    monkeypatch.setattr(download_catalog, "_fetch_json", _fetch)
    monkeypatch.setattr(download_catalog, "_installed_plugin_ids", dict)

    catalog = build_plugin_catalog()

    assert requested == [
        "https://fork.invalid/metadata/index.json",
        "https://fork.invalid/metadata/plugins/index.json",
    ]
    assert catalog["error"] is None
    entry = catalog["plugins"][0]
    # The install URL has to point at the same host, or the page would offer a
    # plugin it cannot download.
    assert entry["install_url"].startswith("https://fork.invalid/")
    assert entry["description_i18n"]["zh-CN"] == "\u4e2d\u6587\u8bf4\u660e"


def test_an_unreachable_host_degrades_instead_of_failing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The console has to keep working when the catalog cannot be reached.

    This is the behaviour the endpoint's integration test documents but could
    not exercise, since it had no way to point the fetch at a host that fails.
    """
    monkeypatch.setenv(PLUGIN_DOWNLOAD_CDN_ENV, "https://unreachable.invalid")

    def _fetch(_url: str) -> Any:
        raise urllib.error.URLError("no route to host")

    monkeypatch.setattr(download_catalog, "_fetch_json", _fetch)

    catalog = build_plugin_catalog()

    assert not catalog["plugins"]
    assert catalog["error"]
    # Serialisable, because the router returns it as the response body.
    json.dumps(catalog)


@pytest.mark.parametrize(
    "failure",
    [
        pytest.param(urllib.error.URLError("no route"), id="url-error"),
        pytest.param(ConnectionResetError("reset"), id="connection-reset"),
        pytest.param(ssl.SSLError("handshake"), id="tls-error"),
        pytest.param(
            http.client.IncompleteRead(b"half"),
            id="truncated-response",
        ),
        pytest.param(TimeoutError("too slow"), id="timeout"),
        pytest.param(
            json.JSONDecodeError("bad", "doc", 0),
            id="body-is-not-json",
        ),
    ],
)
def test_every_way_a_fetch_fails_still_answers(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
) -> None:
    """None of these may escape and become a 500 from the endpoint.

    Only three were handled, and the ones that were not are the ones a flaky
    network actually produces -- a reset connection and a TLS error are not
    URLErrors, and a truncated read is not an OSError at all. The console's
    plugin page turned an unreachable catalog into a server error.
    """
    monkeypatch.setenv(PLUGIN_DOWNLOAD_CDN_ENV, "https://unreachable.invalid")

    def _fetch(_url: str) -> Any:
        raise failure

    monkeypatch.setattr(download_catalog, "_fetch_json", _fetch)

    catalog = build_plugin_catalog()

    assert not catalog["plugins"]
    assert catalog["error"]
    json.dumps(catalog)


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(["not", "an", "object"], id="array"),
        pytest.param("a string", id="string"),
        pytest.param(None, id="null"),
        pytest.param(7, id="number"),
    ],
)
def test_a_body_that_is_not_an_object_still_answers(
    monkeypatch: pytest.MonkeyPatch,
    body: Any,
) -> None:
    """Valid JSON that is not a mapping used to raise on the first lookup.

    An error page served as JSON is the usual way this arrives.
    """
    monkeypatch.setenv(PLUGIN_DOWNLOAD_CDN_ENV, "https://odd.invalid")
    monkeypatch.setattr(download_catalog, "_fetch_json", lambda _url: body)

    catalog = build_plugin_catalog()

    assert not catalog["plugins"]
    json.dumps(catalog)


def test_a_plugins_index_that_is_not_an_object_still_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The second fetch needs the same guard as the first."""
    monkeypatch.setenv(PLUGIN_DOWNLOAD_CDN_ENV, "https://odd.invalid")

    def _fetch(url: str) -> Any:
        if url.endswith("/metadata/index.json"):
            return {
                "products": {
                    "plugins": {"index_url": "/metadata/plugins/index.json"},
                },
            }
        return ["not", "an", "object"]

    monkeypatch.setattr(download_catalog, "_fetch_json", _fetch)

    catalog = build_plugin_catalog()

    assert not catalog["plugins"]
    assert catalog["error"]
    json.dumps(catalog)
