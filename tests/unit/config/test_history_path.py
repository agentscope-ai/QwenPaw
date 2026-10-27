# -*- coding: utf-8 -*-
"""Local path handling for the durable history database."""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from qwenpaw.config.config import ScrollContextConfig
from qwenpaw.config.history_path import (
    normalize_history_db_filename,
    resolve_history_db_path,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("history.db", "history.db"),
        (" state/events.db ", "state/events.db"),
        (r"state\events.db", "state/events.db"),
        ("./history.db", "history.db"),
        (f"../history.db", f"../history.db"),
        (f"/tmp/history.db", f"/tmp/history.db"),
        (f"C:/tmp/history.db", f"C:/tmp/history.db"),
        (f"//server/share/history.db", f"//server/share/history.db"),
        (f"~/history.db", f"~/history.db"),
    ],
)
def test_normalize_history_db_filename(
    value: str,
    expected: str,
) -> None:
    assert normalize_history_db_filename(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        ".",
        "..",
        f"invalid\0.db",
    ],
)
def test_normalize_history_db_filename_rejects_invalid_paths(
    value: str,
) -> None:
    with pytest.raises(ValueError):
        normalize_history_db_filename(value)


def test_scroll_config_normalizes_and_validates_history_path() -> None:
    config = ScrollContextConfig(db_filename=r"state\events.db")
    assert config.db_filename == "state/events.db"

    with pytest.raises(ValidationError):
        ScrollContextConfig(db_filename=f" ")


def test_resolve_history_db_path_stays_in_workspace(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    assert (
        resolve_history_db_path(
            workspace,
            "state/events.db",
        )
        == workspace / "state" / "events.db"
    )


def test_resolve_history_db_path_follows_external_symlink(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    link = workspace / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable")

    assert (
        resolve_history_db_path(workspace, f"linked/history.db")
        == (outside / f"history.db").resolve()
    )
