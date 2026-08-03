# -*- coding: utf-8 -*-
"""Tests for /files router file/folder management endpoints."""
# pylint: disable=redefined-outer-name,protected-access
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import qwenpaw.app.routers.files as files_module
from qwenpaw.app.routers.files import router, _check_path


@pytest.fixture
def fs_root(tmp_path: Path) -> Path:
    """Isolated WORKING_DIR for each test."""
    return tmp_path / "root"


@pytest.fixture
def client(fs_root: Path, monkeypatch: pytest.MonkeyPatch):
    """TestClient with _ALLOWED_ROOT pointed at an isolated tmp dir."""
    monkeypatch.setattr(files_module, "_ALLOWED_ROOT", fs_root)
    app = FastAPI()
    app.include_router(router, prefix="/api")
    with patch.object(
        files_module._file_guardian, "_is_sensitive", return_value=False
    ):
        yield TestClient(app), fs_root


def test_check_path_write_blocks_outside_workspace(
    fs_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """for_write=True must reject paths outside WORKING_DIR."""
    monkeypatch.setattr(files_module, "_ALLOWED_ROOT", fs_root)
    outside = fs_root.parent / "evil" / "file.txt"
    outside.mkdir(parents=True)
    assert _check_path(outside, for_write=True) == "OUTSIDE_WORKSPACE"


def test_check_path_read_skips_when_allowed(
    fs_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """for_write=False with allow_preview_outside_workspace=True allows outside."""
    monkeypatch.setattr(files_module, "_ALLOWED_ROOT", fs_root)
    monkeypatch.setattr(
        files_module,
        "_is_preview_outside_workspace_allowed",
        lambda: True,
    )
    outside = fs_root.parent / "evil" / "file.txt"
    outside.mkdir(parents=True)
    assert _check_path(outside, for_write=False) is None
