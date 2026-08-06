# -*- coding: utf-8 -*-
"""Tests for non-blocking send-file inspection."""

# pylint: disable=protected-access

import importlib
from pathlib import Path

import pytest

send_file_module = importlib.import_module(
    "qwenpaw.agents.tools.send_file",
)


def test_inspect_file_distinguishes_regular_files(
    tmp_path: Path,
) -> None:
    """Return stable statuses from one synchronous stat operation."""
    file_path = tmp_path / "report.txt"
    file_path.write_text("report", encoding="utf-8")
    directory = tmp_path / "folder"
    directory.mkdir()

    assert send_file_module._inspect_file(str(file_path)) == "file"
    assert send_file_module._inspect_file(str(directory)) == "not_file"
    assert send_file_module._inspect_file(str(tmp_path / "missing")) == (
        "missing"
    )


@pytest.mark.asyncio
async def test_send_file_inspection_uses_sync_io(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Run file metadata inspection through the shared I/O executor."""
    file_path = tmp_path / "report.txt"
    file_path.write_text("report", encoding="utf-8")
    calls: list[object] = []

    async def fake_run_sync_io(function, *args):
        calls.append(function)
        return function(*args)

    monkeypatch.setattr(send_file_module, "run_sync_io", fake_run_sync_io)
    monkeypatch.setattr(
        send_file_module,
        "register_current_artifact",
        lambda _path: True,
    )

    await send_file_module.send_file_to_user(str(file_path))

    assert calls[0] is send_file_module._inspect_file
    assert calls[1] is send_file_module.register_current_artifact
