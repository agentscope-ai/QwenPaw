# -*- coding: utf-8 -*-
"""Unit tests for src/qwenpaw/plugins/download_catalog.py."""

from __future__ import annotations

import http.client
import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from qwenpaw.plugins.download_catalog import (
    _build_remote_plugin_catalog as build_plugin_catalog,
    _is_entry_compatible,
)


@pytest.mark.parametrize(
    "failure",
    [
        ConnectionResetError("connection reset"),
        http.client.IncompleteRead(b"partial", 10),
    ],
)
def test_main_catalog_transport_failure_returns_fallback(
    failure: Exception,
) -> None:
    with patch(
        "qwenpaw.plugins.download_catalog._fetch_json",
        side_effect=failure,
    ):
        result = build_plugin_catalog()

    assert not result["plugins"]
    assert result["error"] == "Failed to fetch plugin catalog index"


@pytest.mark.parametrize(
    "failure",
    [
        ConnectionResetError("connection reset"),
        http.client.IncompleteRead(b"partial", 10),
    ],
)
def test_plugins_catalog_transport_failure_returns_fallback(
    failure: Exception,
) -> None:
    main_index = {"products": {"plugins": {"index_url": "/plugins.json"}}}
    with patch(
        "qwenpaw.plugins.download_catalog._fetch_json",
        side_effect=[main_index, failure],
    ):
        result = build_plugin_catalog()

    assert not result["plugins"]
    assert result["error"] == "Failed to fetch plugins metadata"


def test_build_plugin_catalog_returns_normalized_plugins() -> None:
    main_index = {"products": {"plugins": {"index_url": "/plugins.json"}}}
    plugins_index = {
        "updated_at": "2026-09-14T00:00:00Z",
        "files": {
            "demo-1.0.0": {
                "id": "demo-1.0.0",
                "plugin_id": "demo",
                "name": {"en-US": "Demo"},
                "description": {"en-US": "A demo plugin"},
                "version": "1.0.0",
                "platform": "python",
                "url": "/plugins/demo-1.0.0.zip",
            },
        },
    }
    with (
        patch(
            "qwenpaw.plugins.download_catalog._fetch_json",
            side_effect=[main_index, plugins_index],
        ),
        patch(
            "qwenpaw.plugins.download_catalog._installed_plugin_ids",
            return_value={},
        ),
    ):
        result = build_plugin_catalog()

    assert result["error"] is None
    assert result["updated_at"] == "2026-09-14T00:00:00Z"
    assert result["plugins"] == [
        {
            "id": "demo-1.0.0",
            "plugin_id": "demo",
            "name": "Demo",
            "description": "A demo plugin",
            "description_i18n": {"en-US": "A demo plugin"},
            "version": "1.0.0",
            "author": "",
            "kind": "python",
            "size": "",
            "sha256": "",
            "install_url": (
                "https://download.qwenpaw.agentscope.io"
                "/plugins/demo-1.0.0.zip"
            ),
            "installed": False,
            "installed_version": None,
            "upgrade_available": False,
        },
    ]


def test_bundled_hubs_remain_installable_when_cdn_is_unavailable() -> None:
    from qwenpaw.plugins.download_catalog import (
        build_plugin_catalog as catalog,
    )

    with (
        patch(
            "qwenpaw.plugins.download_catalog._fetch_json",
            side_effect=ConnectionResetError("offline"),
        ),
        patch(
            "qwenpaw.plugins.download_catalog._installed_plugin_ids",
            return_value={"qwenpaw-hub": "0.9.0"},
        ),
    ):
        result = catalog()

    hubs = {entry["plugin_id"]: entry for entry in result["plugins"]}
    assert set(hubs) == {
        "qwenpaw-hub",
        "clawhub-hub",
        "modelscope-hub",
        "aliyun-hub",
    }
    assert result["error"] == "Failed to fetch plugin catalog index"
    assert hubs["qwenpaw-hub"]["installed_version"] == "0.9.0"
    assert hubs["qwenpaw-hub"]["upgrade_available"] is True
    assert hubs["clawhub-hub"]["installed"] is False
    for entry in hubs.values():
        assert entry["kind"] == "hub"
        assert (Path(entry["install_url"]) / "plugin.json").is_file()


def test_bundled_hubs_replace_same_cdn_version_and_keep_remote_updates(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.market.builtin import get_builtin_hub_plugins_dir
    from qwenpaw.plugins.download_catalog import (
        build_plugin_catalog as catalog,
    )

    bundled = tmp_path / "bundled"
    shutil.copytree(get_builtin_hub_plugins_dir(), bundled / "hub")
    tool = bundled / "tool" / "bundled-tool"
    tool.mkdir(parents=True)
    (tool / "plugin.json").write_text(
        json.dumps({"id": "bundled-tool", "version": "1.0.0", "type": "tool"}),
    )
    monkeypatch.setattr(
        "qwenpaw.plugins.download_catalog.__file__",
        str(tmp_path / "download_catalog.py"),
    )
    versions = ("1.0.0", "1.1.0")
    files = {
        version: {
            "id": f"qwenpaw-hub-{version}",
            "plugin_id": "qwenpaw-hub",
            "version": version,
            "name": "QwenPaw Hub",
            "platform": "hub",
            "url": f"/plugins/qwenpaw-hub-{version}.zip",
        }
        for version in versions
    }
    with (
        patch(
            "qwenpaw.plugins.download_catalog._fetch_json",
            side_effect=[
                {"products": {"plugins": {"index_url": "/plugins.json"}}},
                {"files": files},
            ],
        ),
        patch(
            "qwenpaw.plugins.download_catalog._installed_plugin_ids",
            return_value={"qwenpaw-hub": "1.0.0"},
        ),
    ):
        result = catalog()

    qwenpaw = {
        entry["version"]: entry
        for entry in result["plugins"]
        if entry["plugin_id"] == "qwenpaw-hub"
    }
    assert set(qwenpaw) == set(versions)
    assert (Path(qwenpaw["1.0.0"]["install_url"]) / "plugin.json").is_file()
    assert qwenpaw["1.1.0"]["install_url"].endswith(
        "/plugins/qwenpaw-hub-1.1.0.zip",
    )
    assert qwenpaw["1.1.0"]["upgrade_available"] is True
    tool_entry = next(
        entry
        for entry in result["plugins"]
        if entry["plugin_id"] == "bundled-tool"
    )
    assert tool_entry["kind"] == "tool"
    assert Path(tool_entry["install_url"]) == tool


def test_entry_with_qwenpaw_version_compatible() -> None:
    entry = {
        "id": "demo",
        "version": "1.0.0",
        # Exclusive upper bound: current 2.1.0b1 is treated as 2.1.0.
        "qwenpaw_version": {"min": "1.1.6", "max": "2.2.0"},
    }
    assert _is_entry_compatible(entry) is True


def test_entry_with_qwenpaw_version_max_ignored() -> None:
    """Declared max must not exclude a newer running QwenPaw."""
    entry = {
        "id": "demo",
        "version": "1.0.0",
        "qwenpaw_version": {"min": "0.1.0", "max": "1.1.0"},
    }
    assert _is_entry_compatible(entry) is True


def test_entry_with_only_min_compatible() -> None:
    entry = {
        "id": "demo",
        "version": "1.0.0",
        # Derived exclusive max is 2.2.0 for min 2.1.0.
        "qwenpaw_version": {"min": "2.1.0"},
    }
    assert _is_entry_compatible(entry) is True


def test_entry_with_only_min_incompatible() -> None:
    entry = {
        "id": "demo",
        "version": "1.0.0",
        "qwenpaw_version": {"min": "3.0.0"},
    }
    assert _is_entry_compatible(entry) is False


def test_entry_without_version_constraints_is_compatible() -> None:
    entry = {
        "id": "demo",
        "version": "1.0.0",
    }
    assert _is_entry_compatible(entry) is True


def test_entry_with_malformed_qwenpaw_version_falls_to_legacy() -> None:
    """Non-dict qwenpaw_version falls back to min_version/max_version."""
    entry = {
        "id": "demo",
        "version": "1.0.0",
        "qwenpaw_version": "not-a-dict",
        "min_version": "1.0.0",
        "max_version": "2.2.0",
    }
    assert _is_entry_compatible(entry) is True


def test_entry_with_malformed_qwenpaw_version_no_legacy() -> None:
    """Non-dict qwenpaw_version with no legacy fields is compatible."""
    entry = {
        "id": "demo",
        "version": "1.0.0",
        "qwenpaw_version": "not-a-dict",
    }
    assert _is_entry_compatible(entry) is True


def test_legacy_min_version_compatible() -> None:
    """Legacy min_version within range is compatible."""
    entry = {
        "id": "demo",
        "version": "1.0.0",
        "min_version": "2.1.0",
    }
    assert _is_entry_compatible(entry) is True


def test_legacy_min_version_incompatible() -> None:
    """Legacy min_version above current QwenPaw is incompatible."""
    entry = {
        "id": "demo",
        "version": "1.0.0",
        "min_version": "3.0.0",
    }
    assert _is_entry_compatible(entry) is False


def test_legacy_min_max_version_compatible() -> None:
    """Legacy min+max still loads when min is satisfied (max ignored)."""
    entry = {
        "id": "demo",
        "version": "1.0.0",
        "min_version": "1.0.0",
        "max_version": "2.2.0",
    }
    assert _is_entry_compatible(entry) is True


def test_legacy_max_version_ignored() -> None:
    """Legacy max_version alone must not make an entry incompatible."""
    entry = {
        "id": "demo",
        "version": "1.0.0",
        "min_version": "0.1.0",
        "max_version": "1.0.0",
    }
    assert _is_entry_compatible(entry) is True


def test_entry_with_empty_dict_qwenpaw_version() -> None:
    """Empty dict qwenpaw_version triggers compat check with defaults."""
    entry = {
        "id": "demo",
        "version": "1.0.0",
        "qwenpaw_version": {},
    }
    # Empty dict is isinstance(dict) but has no min/max, should
    # still pass through PluginManifest validation or fallback gracefully
    result = _is_entry_compatible(entry)
    assert isinstance(result, bool)
