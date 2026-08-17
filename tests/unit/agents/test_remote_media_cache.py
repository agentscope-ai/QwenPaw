# -*- coding: utf-8 -*-
"""Tests for client-side localization of remote media URLs."""

# pylint: disable=protected-access,redefined-outer-name
import os

import pytest
from agentscope.message import DataBlock, URLSource

from qwenpaw.agents import model_factory, remote_media_cache
from qwenpaw.agents.remote_media_cache import MediaFetchError

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
REMOTE_URL = "https://i.pximg.net/img-original/a.png"


@pytest.fixture(autouse=True)
def _cache_dir(tmp_path, monkeypatch):
    """Isolate the on-disk cache and clear the kill switch."""
    cache_dir = str(tmp_path / "media_cache")
    monkeypatch.setenv(remote_media_cache.CACHE_DIR_ENV, cache_dir)
    monkeypatch.delenv(remote_media_cache.KILL_SWITCH_ENV, raising=False)
    return cache_dir


def _remote_dict_block() -> dict:
    return {
        "type": "image",
        "source": {"type": "url", "url": REMOTE_URL},
    }


def _remote_data_block() -> DataBlock:
    return DataBlock(
        source=URLSource(url=REMOTE_URL, media_type="image/png"),
    )


def test_localize_success_caches_on_disk(monkeypatch):
    calls = []

    def fake_download(url):
        calls.append(url)
        return PNG_BYTES, "image/png"

    monkeypatch.setattr(remote_media_cache, "_download", fake_download)

    path1, err1 = remote_media_cache.localize_remote_url(REMOTE_URL)
    path2, err2 = remote_media_cache.localize_remote_url(REMOTE_URL)

    assert err1 is None and err2 is None
    assert path1 == path2
    assert os.path.isfile(path1)
    assert len(calls) == 1  # second call served from disk cache


def test_localize_failure_negative_cached(monkeypatch):
    calls = []

    def fake_download(url):
        calls.append(url)
        raise MediaFetchError("HTTP 403")

    monkeypatch.setattr(remote_media_cache, "_download", fake_download)

    path1, reason1 = remote_media_cache.localize_remote_url(REMOTE_URL)
    path2, reason2 = remote_media_cache.localize_remote_url(REMOTE_URL)

    assert path1 is None and path2 is None
    assert reason1 == "HTTP 403" and reason2 == "HTTP 403"
    assert len(calls) == 1  # second call served from negative cache


def test_non_media_content_type_rejected(monkeypatch):
    monkeypatch.setattr(
        remote_media_cache,
        "_download",
        lambda url: (b"<html>404</html>", "text/html"),
    )

    path, reason = remote_media_cache.localize_remote_url(REMOTE_URL)

    assert path is None
    assert "non-media" in reason


def test_fixup_dict_block_localizes_remote_url(monkeypatch):
    monkeypatch.setattr(
        remote_media_cache,
        "_download",
        lambda url: (PNG_BYTES, "image/png"),
    )
    items = [_remote_dict_block()]

    model_factory._fixup_media_list(items)

    url = items[0]["source"]["url"]
    assert url != REMOTE_URL
    assert os.path.isfile(url)


def test_fixup_dict_block_degrades_on_failure(monkeypatch):
    def fake_download(url):
        raise MediaFetchError("HTTP 403")

    monkeypatch.setattr(remote_media_cache, "_download", fake_download)
    items = [_remote_dict_block()]

    model_factory._fixup_media_list(items)

    # Degraded dict blocks are replaced by TextBlock objects.
    assert items[0].type == "text"
    assert "remote fetch failed: HTTP 403" in items[0].text


def test_fixup_data_block_localizes_remote_url(monkeypatch):
    monkeypatch.setattr(
        remote_media_cache,
        "_download",
        lambda url: (PNG_BYTES, "image/png"),
    )
    items = [_remote_data_block()]

    model_factory._fixup_media_list(items)

    url = str(items[0].source.url)
    assert url != REMOTE_URL
    assert os.path.isfile(url)


def test_fixup_data_block_degrades_on_failure(monkeypatch):
    def fake_download(url):
        raise MediaFetchError("HTTP 422")

    monkeypatch.setattr(remote_media_cache, "_download", fake_download)
    items = [_remote_data_block()]

    model_factory._fixup_media_list(items)

    assert items[0].type == "text"
    assert "remote fetch failed: HTTP 422" in items[0].text


def test_kill_switch_passes_remote_urls_through(
    monkeypatch,
    _cache_dir,
):
    monkeypatch.setenv(remote_media_cache.KILL_SWITCH_ENV, "1")
    monkeypatch.setattr(
        remote_media_cache,
        "_download",
        lambda url: pytest.fail("download must not run when disabled"),
    )
    dict_items = [_remote_dict_block()]
    data_items = [_remote_data_block()]

    model_factory._fixup_media_list(dict_items)
    model_factory._fixup_media_list(data_items)

    assert dict_items[0]["source"]["url"] == REMOTE_URL
    assert str(data_items[0].source.url) == REMOTE_URL
