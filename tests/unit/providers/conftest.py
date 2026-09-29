# -*- coding: utf-8 -*-
"""Keep provider tests independent from public catalogs and user caches."""

import pytest

from qwenpaw.providers import model_catalog, model_cooldown
from qwenpaw.providers.model_cooldown import reset_model_cooldowns


class _Clock:
    """Controllable monotonic clock."""

    def __init__(self) -> None:
        self.value = 1000.0

    def __call__(self) -> float:
        return self.value


@pytest.fixture(autouse=True)
def isolate_model_cooldowns():
    """The cooldown registry is process-wide, so tests must not share it."""
    reset_model_cooldowns()
    yield
    reset_model_cooldowns()


@pytest.fixture(autouse=True)
def cooldown_clock(monkeypatch):
    """Freeze the cooldown registry's clock so deadlines are exact.

    Autouse because most tests only need the frozen clock as a
    precondition; a test that advances time takes the fixture and mutates
    ``value``.
    """
    control = _Clock()
    monkeypatch.setattr(model_cooldown, f"_now", control)
    return control


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
