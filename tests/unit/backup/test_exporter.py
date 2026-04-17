# -*- coding: utf-8 -*-
"""Unit tests for AssetExporter."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

import pytest

from qwenpaw.backup.exporter import AssetExporter
from qwenpaw.backup.models import AssetType, ExportOptions


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_workspace(tmp_path: Path) -> Path:
    """Create a minimal CoPaw workspace for testing."""
    ws = tmp_path / "workspace"
    ws.mkdir()

    # agent.json
    (ws / "agent.json").write_text(
        json.dumps(
            {
                "id": "test-agent",
                "name": "Test Agent",
                "tools": {
                    "builtin_tools": {
                        "read_file": {"name": "read_file", "enabled": True},
                    },
                },
            },
        ),
        encoding="utf-8",
    )

    # config.json with sensitive fields
    (ws / "config.json").write_text(
        json.dumps(
            {
                "channels": {
                    "discord": {
                        "bot_token": "secret-token-123",
                        "enabled": True,
                    },
                },
            },
        ),
        encoding="utf-8",
    )

    # memory directory
    mem_dir = ws / "memory"
    mem_dir.mkdir()
    (mem_dir / "memory_index.json").write_text(
        json.dumps({"entries": ["001"]}),
        encoding="utf-8",
    )
    entries_dir = mem_dir / "entries"
    entries_dir.mkdir()
    (entries_dir / "001.json").write_text(
        json.dumps({"content": "test memory"}),
        encoding="utf-8",
    )

    # skills directory
    skills_dir = ws / "skills"
    skills_dir.mkdir()
    skill_sub = skills_dir / "my_skill"
    skill_sub.mkdir()
    (skill_sub / "SKILL.md").write_text(
        "# My Skill\nA test skill.",
        encoding="utf-8",
    )

    return ws


class FakeMemoryManager:
    """Fake memory manager for testing."""

    def __init__(self) -> None:
        self.lock_acquired = False
        self.lock_released = False

    async def acquire_read_lock(
        self,
        timeout: float = 30.0,  # pylint: disable=unused-argument
    ) -> str:
        self.lock_acquired = True
        return "fake-lock"

    async def release_read_lock(
        self,
        lock: Any,  # pylint: disable=unused-argument
    ) -> None:
        self.lock_released = True


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_all_assets(tmp_path: Path) -> None:
    """Export all asset types and verify ZIP structure."""
    ws = _create_workspace(tmp_path)
    output = tmp_path / "export.zip"

    mm = FakeMemoryManager()
    exporter = AssetExporter(memory_manager=mm)
    result = await exporter.export_assets(
        ExportOptions(
            workspace_dir=ws,
            output_path=output,
        ),
    )

    assert result.zip_path == output
    assert result.zip_path.exists()
    assert result.asset_count > 0
    assert result.total_size_bytes > 0

    # Verify ZIP contents
    with zipfile.ZipFile(output) as zf:
        names = zf.namelist()
        assert "manifest.json" in names
        # Check directory structure
        assert any(n.startswith("preferences/") for n in names)
        assert any(n.startswith("memories/") for n in names)
        assert any(n.startswith("skills/") for n in names)
        assert any(n.startswith("tools/") for n in names)

    # Memory manager should have been used
    assert mm.lock_acquired
    assert mm.lock_released


@pytest.mark.asyncio
async def test_export_selective_types(tmp_path: Path) -> None:
    """Export only selected asset types."""
    ws = _create_workspace(tmp_path)
    output = tmp_path / "export.zip"

    exporter = AssetExporter()
    await exporter.export_assets(
        ExportOptions(
            workspace_dir=ws,
            include_preferences=False,
            include_memories=False,
            include_tools=False,
            include_skills=True,
            output_path=output,
        ),
    )

    with zipfile.ZipFile(output) as zf:
        names = zf.namelist()
        assert any(n.startswith("skills/") for n in names)
        assert not any(n.startswith("preferences/") for n in names)
        assert not any(n.startswith("memories/") for n in names)
        assert not any(n.startswith("tools/") for n in names)


@pytest.mark.asyncio
async def test_export_sanitizes_preferences(tmp_path: Path) -> None:
    """Verify sensitive fields are redacted in exported preferences."""
    ws = _create_workspace(tmp_path)
    output = tmp_path / "export.zip"

    exporter = AssetExporter()
    await exporter.export_assets(
        ExportOptions(
            workspace_dir=ws,
            include_memories=False,
            include_skills=False,
            include_tools=False,
            output_path=output,
        ),
    )

    with zipfile.ZipFile(output) as zf:
        config_data = json.loads(zf.read("preferences/config.json"))
        assert (
            config_data["channels"]["discord"]["bot_token"] == "***REDACTED***"
        )


@pytest.mark.asyncio
async def test_export_excludes_env_files(tmp_path: Path) -> None:
    """Verify .env files are excluded from export."""
    ws = _create_workspace(tmp_path)
    (ws / ".env").write_text("SECRET=value", encoding="utf-8")
    (ws / "memory" / ".env.local").write_text("X=1", encoding="utf-8")
    output = tmp_path / "export.zip"

    exporter = AssetExporter()
    await exporter.export_assets(
        ExportOptions(
            workspace_dir=ws,
            output_path=output,
        ),
    )

    with zipfile.ZipFile(output) as zf:
        names = zf.namelist()
        assert not any(".env" in n for n in names)


@pytest.mark.asyncio
async def test_export_nonexistent_workspace(tmp_path: Path) -> None:
    """Raise FileNotFoundError for missing workspace."""
    exporter = AssetExporter()
    with pytest.raises(FileNotFoundError):
        await exporter.export_assets(
            ExportOptions(
                workspace_dir=tmp_path / "nonexistent",
                output_path=tmp_path / "out.zip",
            ),
        )


@pytest.mark.asyncio
async def test_export_manifest_checksums(tmp_path: Path) -> None:
    """Verify SHA256 checksums in manifest match actual file contents."""
    ws = _create_workspace(tmp_path)
    output = tmp_path / "export.zip"

    exporter = AssetExporter()
    result = await exporter.export_assets(
        ExportOptions(
            workspace_dir=ws,
            output_path=output,
        ),
    )

    import hashlib

    with zipfile.ZipFile(output) as zf:
        for entry in result.manifest.assets:
            file_data = zf.read(entry.relative_path)
            actual_sha = hashlib.sha256(file_data).hexdigest()
            assert (
                actual_sha == entry.sha256
            ), f"Checksum mismatch for {entry.relative_path}"


@pytest.mark.asyncio
async def test_memory_lock_timeout(tmp_path: Path) -> None:
    """Memory lock timeout marks memories as partial."""
    ws = _create_workspace(tmp_path)
    output = tmp_path / "export.zip"

    class TimeoutMemoryManager:
        async def acquire_read_lock(self, timeout: float = 30.0) -> str:
            raise TimeoutError("Lock timeout")

        async def release_read_lock(self, lock: Any) -> None:
            pass

    exporter = AssetExporter(memory_manager=TimeoutMemoryManager())
    result = await exporter.export_assets(
        ExportOptions(
            workspace_dir=ws,
            output_path=output,
        ),
    )

    # Memory entries should be marked as partial
    memory_entries = [
        e for e in result.manifest.assets if e.asset_type == AssetType.MEMORIES
    ]
    for entry in memory_entries:
        assert entry.metadata.get("partial") is True


@pytest.mark.asyncio
async def test_export_global_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Global config is collected, sanitized, and placed
    under global_config/.
    """
    ws = _create_workspace(tmp_path)
    output = tmp_path / "export.zip"

    # Create a fake global config.json
    global_dir = tmp_path / "copaw_home"
    global_dir.mkdir()
    (global_dir / "config.json").write_text(
        json.dumps(
            {
                "providers": {
                    "openai": {"api_key": "sk-secret", "model": "gpt-4"},
                },
            },
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("qwenpaw.backup.exporter.WORKING_DIR", global_dir)

    exporter = AssetExporter()
    result = await exporter.export_assets(
        ExportOptions(
            workspace_dir=ws,
            include_preferences=False,
            include_memories=False,
            include_skills=False,
            include_tools=False,
            include_global_config=True,
            output_path=output,
        ),
    )

    assert result.asset_count == 1
    gc_entries = [
        e
        for e in result.manifest.assets
        if e.asset_type == AssetType.GLOBAL_CONFIG
    ]
    assert len(gc_entries) == 1
    assert gc_entries[0].relative_path == "global_config/config.json"

    with zipfile.ZipFile(output) as zf:
        data = json.loads(zf.read("global_config/config.json"))
        assert data["providers"]["openai"]["api_key"] == "***REDACTED***"
        assert data["providers"]["openai"]["model"] == "gpt-4"


@pytest.mark.asyncio
async def test_export_global_config_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No error when global config.json doesn't exist."""
    ws = _create_workspace(tmp_path)
    output = tmp_path / "export.zip"

    empty_dir = tmp_path / "empty_home"
    empty_dir.mkdir()
    monkeypatch.setattr("qwenpaw.backup.exporter.WORKING_DIR", empty_dir)

    exporter = AssetExporter()
    result = await exporter.export_assets(
        ExportOptions(
            workspace_dir=ws,
            include_preferences=False,
            include_memories=False,
            include_skills=False,
            include_tools=False,
            include_global_config=True,
            output_path=output,
        ),
    )

    gc_entries = [
        e
        for e in result.manifest.assets
        if e.asset_type == AssetType.GLOBAL_CONFIG
    ]
    assert len(gc_entries) == 0


@pytest.mark.asyncio
async def test_export_excludes_global_config_when_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Global config excluded when include_global_config=False."""
    ws = _create_workspace(tmp_path)
    output = tmp_path / "export.zip"

    global_dir = tmp_path / "copaw_home2"
    global_dir.mkdir()
    (global_dir / "config.json").write_text(
        json.dumps({"x": 1}),
        encoding="utf-8",
    )
    monkeypatch.setattr("qwenpaw.backup.exporter.WORKING_DIR", global_dir)

    exporter = AssetExporter()
    result = await exporter.export_assets(
        ExportOptions(
            workspace_dir=ws,
            include_global_config=False,
            output_path=output,
        ),
    )

    gc_entries = [
        e
        for e in result.manifest.assets
        if e.asset_type == AssetType.GLOBAL_CONFIG
    ]
    assert len(gc_entries) == 0
