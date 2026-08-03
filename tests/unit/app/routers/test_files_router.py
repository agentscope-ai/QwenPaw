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
    root = tmp_path / "root"
    root.mkdir(parents=True, exist_ok=True)
    return root


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


def test_list_directory(client) -> None:
    test_client, fs_root = client
    (fs_root / "sub").mkdir()
    (fs_root / "sub" / "a.txt").write_text("hello", encoding="utf-8")
    (fs_root / "b.txt").write_text("world", encoding="utf-8")

    resp = test_client.get("/api/files/list")
    assert resp.status_code == 200
    entries = {e["name"]: e for e in resp.json()}
    assert "sub" in entries and entries["sub"]["is_dir"] is True
    assert "b.txt" in entries and entries["b.txt"]["is_dir"] is False


def test_list_directory_nested(client) -> None:
    test_client, fs_root = client
    (fs_root / "sub" / "deep").mkdir(parents=True)
    (fs_root / "sub" / "deep" / "f.txt").write_text("x", encoding="utf-8")

    resp = test_client.get("/api/files/list", params={"path": "sub"})
    assert resp.status_code == 200
    names = [e["name"] for e in resp.json()]
    assert "deep" in names


def test_list_missing_dir_404(client) -> None:
    test_client, _ = client
    resp = test_client.get("/api/files/list", params={"path": "nope"})
    assert resp.status_code == 404


def test_list_directory_filters_sensitive(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sensitive files inside WORKING_DIR must not appear in the listing."""
    test_client, fs_root = client
    (fs_root / "ok.txt").write_text("hello", encoding="utf-8")
    sensitive = fs_root / "secret.txt"
    sensitive.write_text("secret", encoding="utf-8")

    def fake_is_sensitive(normalized: str) -> bool:
        return normalized == str(sensitive.resolve())

    monkeypatch.setattr(
        files_module._file_guardian, "_is_sensitive", fake_is_sensitive
    )

    resp = test_client.get("/api/files/list")
    assert resp.status_code == 200
    names = [e["name"] for e in resp.json()]
    assert "ok.txt" in names
    assert "secret.txt" not in names


def test_mkdir_creates_dir(client) -> None:
    test_client, fs_root = client
    resp = test_client.post(
        "/api/files/mkdir", json={"path": "newdir"}
    )
    assert resp.status_code == 200
    assert (fs_root / "newdir").is_dir()


def test_mkdir_existing_409(client) -> None:
    test_client, fs_root = client
    (fs_root / "exists").mkdir()
    resp = test_client.post(
        "/api/files/mkdir", json={"path": "exists"}
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Target exists"


def test_mkdir_nested_creates_parents(client) -> None:
    test_client, fs_root = client
    resp = test_client.post(
        "/api/files/mkdir", json={"path": "a/b/c"}
    )
    assert resp.status_code == 200
    assert (fs_root / "a" / "b" / "c").is_dir()
