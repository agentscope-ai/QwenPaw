# -*- coding: utf-8 -*-
"""Keep provider tests independent from public catalogs and user caches."""

import pytest

from qwenpaw.providers import model_catalog


@pytest.fixture(autouse=True)
def isolate_remote_catalogs(monkeypatch, tmp_path):
    """Network behavior is exercised with explicit fixture payloads."""
    monkeypatch.setattr(
        model_catalog,
        f"METADATA_CACHE_PATH",
        tmp_path / f"metadata.json",
    )
    monkeypatch.setattr(
        model_catalog,
        f"OTA_CATALOG_PATH",
        tmp_path / f"ota.json",
    )
    monkeypatch.setattr(
        model_catalog,
        f"LOCAL_CATALOG_PATH",
        tmp_path / f"local.json",
    )

    def offline_download(url, timeout):
        raise OSError(f"Unmocked catalog download: {url}")

    monkeypatch.setattr(model_catalog, f"_download_bytes", offline_download)
