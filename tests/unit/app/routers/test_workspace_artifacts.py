# -*- coding: utf-8 -*-
from pathlib import Path

import pytest
from fastapi import HTTPException

from qwenpaw.app.routers.workspace import (
    _ARTIFACT_BINARY_PREVIEW_MAX_BYTES,
    _ARTIFACT_TEXT_PREVIEW_MAX_BYTES,
    _resolve_artifact_file,
    _resolve_artifact_preview_file,
)


def test_resolve_artifact_file_accepts_regular_file(tmp_path: Path) -> None:
    artifact = tmp_path / "reports" / "summary.md"
    artifact.parent.mkdir()
    artifact.write_text("ready", encoding="utf-8")

    assert (
        _resolve_artifact_file(
            tmp_path,
            "reports/summary.md",
        )
        == artifact.resolve()
    )


def test_resolve_artifact_file_rejects_traversal(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")

    with pytest.raises(HTTPException) as exc_info:
        _resolve_artifact_file(workspace, "../outside.txt")

    assert exc_info.value.status_code == 400


def test_resolve_artifact_file_rejects_directory(tmp_path: Path) -> None:
    directory = tmp_path / "folder"
    directory.mkdir()

    with pytest.raises(HTTPException) as exc_info:
        _resolve_artifact_file(tmp_path, "folder")

    assert exc_info.value.status_code == 404


def test_resolve_artifact_file_rejects_symlink_escape(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    link = workspace / "link.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        return

    with pytest.raises(HTTPException) as exc_info:
        _resolve_artifact_file(workspace, "link.txt")

    assert exc_info.value.status_code == 400


@pytest.mark.parametrize(
    "filename,limit,media_type",
    [
        (
            "report.txt",
            _ARTIFACT_TEXT_PREVIEW_MAX_BYTES,
            "text/plain",
        ),
        (
            "image.png",
            _ARTIFACT_BINARY_PREVIEW_MAX_BYTES,
            "image/png",
        ),
    ],
)
def test_artifact_preview_accepts_exact_size_limit(
    tmp_path: Path,
    filename: str,
    limit: int,
    media_type: str,
) -> None:
    artifact = tmp_path / filename
    with artifact.open("wb") as file:
        file.truncate(limit)

    assert _resolve_artifact_preview_file(
        tmp_path,
        filename,
    ) == (artifact.resolve(), media_type)


@pytest.mark.parametrize(
    "filename,limit",
    [
        ("report.txt", _ARTIFACT_TEXT_PREVIEW_MAX_BYTES),
        ("image.png", _ARTIFACT_BINARY_PREVIEW_MAX_BYTES),
    ],
)
def test_artifact_preview_rejects_file_over_limit(
    tmp_path: Path,
    filename: str,
    limit: int,
) -> None:
    artifact = tmp_path / filename
    with artifact.open("wb") as file:
        file.truncate(limit + 1)

    with pytest.raises(HTTPException) as exc_info:
        _resolve_artifact_preview_file(tmp_path, filename)

    assert exc_info.value.status_code == 413
    assert _resolve_artifact_file(tmp_path, filename) == artifact.resolve()
