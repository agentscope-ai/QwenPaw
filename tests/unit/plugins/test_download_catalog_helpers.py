# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
"""Unit tests for the plugin-catalog fetch/normalisation helpers.

``download_catalog`` is the module behind the console App Center: it
downloads the CDN index and turns it into the rows the UI renders.  The
existing ``test_download_catalog.py`` covers ``build_plugin_catalog``'s
transport-failure fallbacks and ``_is_entry_compatible``; this file covers
the remaining helpers that decide *which* rows appear and whether an
upgrade is offered:

* ``_fetch_json`` — gzip sniffing (the CDN serves gzipped JSON, so a
  wrong guess surfaces as mojibake in the console),
* ``_plugin_id_from_file_entry`` — legacy ``{id}-{version}`` and
  ``{id}-{version}-{sha8}`` index ids,
* ``_is_upgrade_available`` — PEP 440 comparison with a non-PEP-440
  fallback,
* ``_pick_en`` — locale fallback chain,
* ``_installed_plugin_ids`` — manifest scan of the plugins dir,
* ``build_plugin_catalog`` — index shapes that must be dropped.
"""

from __future__ import annotations

import gzip
import http.client
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from qwenpaw.plugins.download_catalog import (
    PLUGIN_DOWNLOAD_CDN,
    _fetch_json,
    _installed_plugin_ids,
    _is_upgrade_available,
    _normalize_ver,
    _pick_en,
    _plugin_id_from_file_entry,
    build_plugin_catalog,
    fetch_plugin_catalog_async,
)


class _FakeResponse:
    """Stand-in for ``urllib.request.urlopen``'s HTTP response."""

    def __init__(self, payload: bytes, headers: dict[str, str] | None = None):
        self._payload = payload
        self.headers = _FakeHeaders(headers or {})
        self.read_calls = 0

    def read(self) -> bytes:
        self.read_calls += 1
        return self._payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None


class _FakeHeaders:
    """Minimal ``email.message.Message`` look-alike."""

    def __init__(self, values: dict[str, str]):
        self._values = values

    def get(self, key: str) -> str | None:
        return self._values.get(key)


# ---------------------------------------------------------------------
# _fetch_json
# ---------------------------------------------------------------------


def test_fetch_json_declares_json_accept_and_gzip_encoding() -> None:
    """The request must advertise gzip, else the CDN may send a huge body."""
    seen: dict[str, Any] = {}

    def fake_urlopen(req: Any, timeout: Any = None) -> _FakeResponse:
        seen["url"] = req.full_url
        seen["accept"] = req.get_header("Accept")
        # urllib capitalises only the first letter of a header name.
        seen["encoding"] = req.get_header("Accept-encoding")
        seen["timeout"] = timeout
        return _FakeResponse(json.dumps({"ok": True}).encode("utf-8"))

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = _fetch_json("https://cdn.example/metadata/index.json")

    assert result == {"ok": True}
    assert seen["url"] == "https://cdn.example/metadata/index.json"
    assert seen["accept"] == "application/json"
    assert seen["encoding"] == "gzip"
    assert seen["timeout"] == 30


def test_fetch_json_decodes_gzip_from_content_encoding_header() -> None:
    body = gzip.compress(json.dumps({"gzip": "header"}).encode("utf-8"))
    resp = _FakeResponse(body, {"Content-Encoding": "gzip"})
    with patch("urllib.request.urlopen", return_value=resp):
        assert _fetch_json("https://cdn.example/x.json") == {
            "gzip": "header",
        }


def test_fetch_json_sniffs_gzip_magic_when_header_absent() -> None:
    """A CDN that omits Content-Encoding must still be decoded."""
    body = gzip.compress(json.dumps({"sniffed": 1}).encode("utf-8"))
    resp = _FakeResponse(body, {})
    with patch("urllib.request.urlopen", return_value=resp):
        assert _fetch_json("https://cdn.example/x.json") == {"sniffed": 1}


def test_fetch_json_passes_plain_json_through_untouched() -> None:
    body = json.dumps({"plain": True}).encode("utf-8")
    resp = _FakeResponse(body, {})
    with patch("urllib.request.urlopen", return_value=resp):
        assert _fetch_json("https://cdn.example/x.json") == {"plain": True}


def test_fetch_json_propagates_read_failure() -> None:
    """#7763: a truncated body must surface, not become an empty catalog."""

    def exploding_urlopen(*_args: Any, **_kwargs: Any) -> Any:
        raise http.client.IncompleteRead(b"partial", 10)

    with patch("urllib.request.urlopen", side_effect=exploding_urlopen):
        with pytest.raises(http.client.IncompleteRead):
            _fetch_json("https://cdn.example/x.json")


def test_fetch_json_propagates_malformed_payload() -> None:
    resp = _FakeResponse(b"{not json", {})
    with patch("urllib.request.urlopen", return_value=resp):
        with pytest.raises(json.JSONDecodeError):
            _fetch_json("https://cdn.example/x.json")


# ---------------------------------------------------------------------
# _plugin_id_from_file_entry
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "entry,expected",
    [
        # explicit plugin_id always wins
        ({"plugin_id": "demo", "id": "other-1.0.0"}, "demo"),
        ({"plugin_id": 42}, "42"),
        # no version at all -> raw file id
        ({"id": "demo"}, "demo"),
        ({"id": ""}, ""),
        ({}, ""),
        # legacy ``{plugin_id}-{version}``
        ({"id": "demo-1.0.0", "version": "1.0.0"}, "demo"),
        # plugin id that itself contains a dash
        (
            {"id": "my-cool-plugin-2.1.0", "version": "2.1.0"},
            "my-cool-plugin",
        ),
        # legacy ``{plugin_id}-{version}-{sha8}``
        ({"id": "demo-1.0.0-deadbeef", "version": "1.0.0"}, "demo"),
        ({"id": "a-b-1.0.0-0abc1234", "version": "1.0.0"}, "a-b"),
        # 8 chars but not hex -> not a content hash -> raw file id kept
        (
            {"id": "demo-1.0.0-zzzzzzzz", "version": "1.0.0"},
            "demo-1.0.0-zzzzzzzz",
        ),
        # 7 chars -> not a content hash -> raw file id kept
        (
            {"id": "demo-1.0.0-deadbee", "version": "1.0.0"},
            "demo-1.0.0-deadbee",
        ),
        # version suffix does not match the id -> unchanged
        ({"id": "demo-9.9.9", "version": "1.0.0"}, "demo-9.9.9"),
        # marker at index 0 must not yield an empty plugin id
        ({"id": "-1.0.0-abcd1234", "version": "1.0.0"}, "-1.0.0-abcd1234"),
        # non-string values are coerced
        ({"id": 7, "version": 1.5}, "7"),
    ],
)
def test_plugin_id_from_file_entry(
    entry: dict[str, Any],
    expected: str,
) -> None:
    assert _plugin_id_from_file_entry(entry) == expected


def test_plugin_id_prefers_exact_version_suffix_over_hash_suffix() -> None:
    """``demo-1.0.0-1.0.0`` ends with ``-1.0.0`` -> strip that, not a hash."""
    entry = {"id": "demo-1.0.0-1.0.0", "version": "1.0.0"}
    assert _plugin_id_from_file_entry(entry) == "demo-1.0.0"


# ---------------------------------------------------------------------
# _is_upgrade_available
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "installed,catalog,expected",
    [
        ("1.0.0", "1.0.1", True),
        ("1.0.0", "1.1.0", True),
        ("1.0.0", "2.0.0", True),
        ("1.0.0", "1.0.0", False),
        ("1.0.1", "1.0.0", False),
        ("2.0.0", "1.9.9", False),
        # missing either side -> never advertise an upgrade
        ("", "1.0.0", False),
        ("1.0.0", "", False),
        ("", "", False),
        # non-PEP-440 versions fall back to string inequality
        ("abc", "abd", True),
        ("abc", "abc", False),
        ("1.0.0", "not-a-version", True),
        # pre-release ordering
        ("1.0.0a1", "1.0.0", True),
        ("1.0.0", "1.0.0a1", False),
    ],
)
def test_is_upgrade_available(
    installed: str,
    catalog: str,
    expected: bool,
) -> None:
    assert _is_upgrade_available(installed, catalog) is expected


# ---------------------------------------------------------------------
# _pick_en
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ({"en-US": "Hello"}, "Hello"),
        # en-US wins over the others
        ({"en-US": "US", "en": "EN", "zh-CN": "ZH"}, "US"),
        ({"en": "EN", "zh-CN": "ZH"}, "EN"),
        ({"zh-CN": "ZH", "zh": "Z"}, "ZH"),
        ({"zh": "Z"}, "Z"),
        ({"fr": "Bonjour"}, ""),
        ({}, ""),
        # falsy entries are skipped, not returned as ""
        ({"en-US": "", "en": "fallback"}, "fallback"),
        ({"en-US": None, "zh-CN": "ZH"}, "ZH"),
        # scalars
        ("plain", "plain"),
        (None, ""),
        (7, "7"),
    ],
)
def test_pick_en(value: Any, expected: str) -> None:
    assert _pick_en(value) == expected


# ---------------------------------------------------------------------
# _normalize_ver
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1.2.3", "1.2.3"),
        ("v1.2.3", "1.2.3"),
        ("V1.2.3", "1.2.3"),
        ("  v1.2.3  ", "1.2.3"),
        ("", ""),
        ("   ", ""),
        ("v", ""),
        # only a single leading v is stripped
        ("vv1.0", "v1.0"),
    ],
)
def test_normalize_ver(raw: str, expected: str) -> None:
    assert _normalize_ver(raw) == expected


# ---------------------------------------------------------------------
# _installed_plugin_ids
# ---------------------------------------------------------------------


@pytest.fixture(name="plugins_dir")
def fixture_plugins_dir(tmp_path: Path, monkeypatch: Any) -> Path:
    """Point ``get_plugins_dir`` at an isolated tmp dir."""
    target = tmp_path / "plugins"
    target.mkdir()
    monkeypatch.setattr(
        "qwenpaw.config.utils.get_plugins_dir",
        lambda: target,
    )
    return target


def _write_manifest(root: Path, name: str, manifest: Any) -> Path:
    item = root / name
    item.mkdir()
    (item / "plugin.json").write_text(
        json.dumps(manifest) if not isinstance(manifest, str) else manifest,
        encoding="utf-8",
    )
    return item


def test_installed_plugin_ids_missing_dir_returns_empty(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        "qwenpaw.config.utils.get_plugins_dir",
        lambda: tmp_path / "nope",
    )
    assert _installed_plugin_ids() == {}


def test_installed_plugin_ids_reads_manifests(plugins_dir: Path) -> None:
    _write_manifest(plugins_dir, "demo", {"id": "demo", "version": "1.2.3"})
    # missing version -> 0.0.0 placeholder
    _write_manifest(plugins_dir, "nover", {"id": "nover"})
    # missing id -> directory name is the plugin id
    _write_manifest(plugins_dir, "fromdir", {"version": "0.5.0"})

    assert _installed_plugin_ids() == {
        "demo": "1.2.3",
        "nover": "0.0.0",
        "fromdir": "0.5.0",
    }


def test_installed_plugin_ids_skips_noise(plugins_dir: Path) -> None:
    _write_manifest(plugins_dir, "good", {"id": "good", "version": "1.0.0"})
    # a stray file, not a directory
    (plugins_dir / "README.md").write_text("hi", encoding="utf-8")
    # a directory without a manifest
    (plugins_dir / "empty").mkdir()
    # malformed JSON must be skipped, not raise
    _write_manifest(plugins_dir, "broken", "{not json")

    assert _installed_plugin_ids() == {"good": "1.0.0"}


# ---------------------------------------------------------------------
# build_plugin_catalog — index shapes that must be dropped
# ---------------------------------------------------------------------


_MAIN_INDEX = {"products": {"plugins": {"index_url": "/plugins.json"}}}


def test_catalog_without_plugins_product_is_empty() -> None:
    with patch(
        "qwenpaw.plugins.download_catalog._fetch_json",
        return_value={"products": {}},
    ):
        result = build_plugin_catalog()

    assert result == {"updated_at": None, "plugins": [], "error": None}


def test_catalog_without_products_key_is_empty() -> None:
    with patch(
        "qwenpaw.plugins.download_catalog._fetch_json",
        return_value={},
    ):
        result = build_plugin_catalog()

    assert result["plugins"] == []
    assert result["error"] is None


def test_catalog_with_empty_plugins_product_is_empty() -> None:
    """A falsy ``plugins`` product is 'no catalog', not a malformed one."""
    with patch(
        "qwenpaw.plugins.download_catalog._fetch_json",
        return_value={"products": {"plugins": {}}},
    ):
        result = build_plugin_catalog()

    assert result == {"updated_at": None, "plugins": [], "error": None}


@pytest.mark.parametrize(
    "plugins_product",
    [
        {"index_url": ""},
        {"index_url": "plugins.json"},
        {"index_url": "https://evil.example/plugins.json"},
        {"index_url": None},
    ],
)
def test_catalog_rejects_non_root_relative_index_url(
    plugins_product: dict[str, Any],
) -> None:
    """An absolute or foreign index_url must not be fetched."""
    main_index = {"products": {"plugins": plugins_product}}
    with patch(
        "qwenpaw.plugins.download_catalog._fetch_json",
        return_value=main_index,
    ) as fetch:
        result = build_plugin_catalog()

    assert result["plugins"] == []
    assert result["error"] == "Invalid plugins index_url in main metadata"
    assert fetch.call_count == 1


def test_catalog_drops_malformed_and_foreign_entries() -> None:
    plugins_index = {
        "updated_at": "2026-09-16T00:00:00Z",
        "files": {
            # not a dict -> dropped
            "junk": "not-a-dict",
            # relative url missing -> dropped
            "no-url": {"id": "no-url", "version": "1.0.0", "url": ""},
            # absolute url -> dropped (only CDN-relative paths are served)
            "abs": {
                "id": "abs",
                "version": "1.0.0",
                "url": "https://evil.example/p.zip",
            },
            # incompatible with the running QwenPaw -> dropped
            "future": {
                "id": "future",
                "version": "1.0.0",
                "url": "/plugins/future.zip",
                "qwenpaw_version": {"min": "99.0.0"},
            },
            # kept
            "ok": {
                "id": "ok",
                "plugin_id": "ok",
                "version": "1.0.0",
                "url": "/plugins/ok.zip",
                "name": {"en-US": "OK"},
                "description": "plain text description",
                "platform": "python",
            },
        },
    }
    with (
        patch(
            "qwenpaw.plugins.download_catalog._fetch_json",
            side_effect=[_MAIN_INDEX, plugins_index],
        ),
        patch(
            "qwenpaw.plugins.download_catalog._installed_plugin_ids",
            return_value={},
        ),
    ):
        result = build_plugin_catalog()

    assert result["updated_at"] == "2026-09-16T00:00:00Z"
    assert [p["plugin_id"] for p in result["plugins"]] == ["ok"]
    kept = result["plugins"][0]
    # scalar description -> empty i18n map, description passed through
    assert kept["description"] == "plain text description"
    assert kept["description_i18n"] == {}
    assert kept["install_url"] == f"{PLUGIN_DOWNLOAD_CDN}/plugins/ok.zip"


def test_catalog_marks_installed_and_upgrade_available() -> None:
    plugins_index = {
        "updated_at": None,
        "files": {
            "stale-1.0.0": {
                "id": "stale-1.0.0",
                "plugin_id": "stale",
                "version": "1.1.0",
                "url": "/plugins/stale.zip",
                "platform": "zzz",
                "name": "Stale",
            },
            "fresh-2.0.0": {
                "id": "fresh-2.0.0",
                "plugin_id": "fresh",
                "version": "2.0.0",
                "url": "/plugins/fresh.zip",
                "platform": "aaa",
                "name": "Fresh",
            },
        },
    }
    with (
        patch(
            "qwenpaw.plugins.download_catalog._fetch_json",
            side_effect=[_MAIN_INDEX, plugins_index],
        ),
        patch(
            "qwenpaw.plugins.download_catalog._installed_plugin_ids",
            return_value={"stale": "1.0.0", "fresh": "2.0.0"},
        ),
    ):
        result = build_plugin_catalog()

    by_id = {p["plugin_id"]: p for p in result["plugins"]}
    assert by_id["stale"]["installed"] is True
    assert by_id["stale"]["installed_version"] == "1.0.0"
    assert by_id["stale"]["upgrade_available"] is True
    assert by_id["fresh"]["upgrade_available"] is False
    # sorted by (kind, name)
    assert [p["plugin_id"] for p in result["plugins"]] == ["fresh", "stale"]


def test_catalog_missing_files_key_is_empty() -> None:
    with (
        patch(
            "qwenpaw.plugins.download_catalog._fetch_json",
            side_effect=[_MAIN_INDEX, {"updated_at": "ts"}],
        ),
        patch(
            "qwenpaw.plugins.download_catalog._installed_plugin_ids",
            return_value={},
        ),
    ):
        result = build_plugin_catalog()

    assert result["plugins"] == []
    assert result["updated_at"] == "ts"


# ---------------------------------------------------------------------
# async wrapper
# ---------------------------------------------------------------------


async def test_fetch_plugin_catalog_async_delegates_to_sync() -> None:
    sentinel = {"updated_at": None, "plugins": [], "error": None}
    with patch(
        "qwenpaw.plugins.download_catalog.build_plugin_catalog",
        return_value=sentinel,
    ) as build:
        result = await fetch_plugin_catalog_async()

    assert result is sentinel
    assert build.call_count == 1
