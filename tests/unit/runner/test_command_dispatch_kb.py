# -*- coding: utf-8 -*-
"""Unit tests for /kb command handling in command_dispatch."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from copaw.app.runner.command_dispatch import _is_command, run_command_path


def _make_request(
    *,
    text: str,
    file_paths: list[Path] | None = None,
):
    file_paths = file_paths or []
    content = [SimpleNamespace(type="text", text=text)]
    content.extend(
        SimpleNamespace(
            type="file",
            file_url=str(path),
            filename=path.name,
        )
        for path in file_paths
    )
    message = SimpleNamespace(content=content)
    return SimpleNamespace(
        session_id="test-session",
        user_id="test-user",
        channel="console",
        input=[message],
    )


def _make_msgs(text: str):
    return [{"content": [{"type": "text", "text": text}]}]


async def _collect(stream):
    return [item async for item in stream]


async def test_kb_command_imports_files(tmp_path: Path) -> None:
    source = tmp_path / "media" / "kb-note.txt"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("KB command import content.", encoding="utf-8")

    request = _make_request(text="/kb", file_paths=[source])
    runner = SimpleNamespace(workspace_dir=tmp_path)
    result = await _collect(
        run_command_path(request, _make_msgs("/kb"), runner),
    )

    assert len(result) == 1
    msg, is_last = result[0]
    assert is_last is True
    text = msg.get_text_content() or ""
    assert "Knowledge Import Complete" in text
    assert "- Imported: 1" in text


async def test_kb_import_alias_imports_files(tmp_path: Path) -> None:
    source = tmp_path / "media" / "kb-note-alias.txt"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("KB alias import content.", encoding="utf-8")

    request = _make_request(text="/kb import", file_paths=[source])
    runner = SimpleNamespace(workspace_dir=tmp_path)
    result = await _collect(
        run_command_path(request, _make_msgs("/kb import"), runner),
    )

    assert len(result) == 1
    msg, is_last = result[0]
    assert is_last is True
    text = msg.get_text_content() or ""
    assert "Knowledge Import Complete" in text
    assert "- Imported: 1" in text


async def test_kb_command_without_attachments(tmp_path: Path) -> None:
    request = _make_request(text="/kb", file_paths=[])
    runner = SimpleNamespace(workspace_dir=tmp_path)
    result = await _collect(
        run_command_path(request, _make_msgs("/kb"), runner),
    )

    assert len(result) == 1
    msg, is_last = result[0]
    assert is_last is True
    text = msg.get_text_content() or ""
    assert "No importable file attachments found" in text


async def test_kb_command_rejects_attachments_outside_media_dir(
    tmp_path: Path,
) -> None:
    source = tmp_path / "incoming" / "outside.txt"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("outside media dir", encoding="utf-8")

    request = _make_request(text="/kb", file_paths=[source])
    runner = SimpleNamespace(workspace_dir=tmp_path)
    result = await _collect(
        run_command_path(request, _make_msgs("/kb"), runner),
    )

    assert len(result) == 1
    msg, is_last = result[0]
    assert is_last is True
    text = msg.get_text_content() or ""
    assert "No importable file attachments found" in text


async def test_kb_command_invalid_subcommand(tmp_path: Path) -> None:
    request = _make_request(text="/kb list", file_paths=[])
    runner = SimpleNamespace(workspace_dir=tmp_path)
    result = await _collect(
        run_command_path(request, _make_msgs("/kb list"), runner),
    )

    assert len(result) == 1
    msg, is_last = result[0]
    assert is_last is True
    text = msg.get_text_content() or ""
    assert "Usage" in text
    assert "/kb import" in text


def test_is_command_includes_kb_namespace() -> None:
    assert _is_command("/kb") is True
    assert _is_command("/kb import") is True
    assert _is_command("/kb list") is True
