# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from pathlib import Path

import pytest

from qwenpaw.portability import planner
from qwenpaw.portability.models import (
    ProviderInventory,
    SourceMemoryFile,
    SourceMemoryProject,
    SourceSkill,
)
from qwenpaw.portability.planner import inventory_fingerprint


def _skill_inventory(root: Path) -> ProviderInventory:
    return ProviderInventory(
        provider_id="codex",
        provider_name="Codex",
        detected=True,
        skills=[
            SourceSkill(
                source_id="skill-1",
                name="test-skill",
                directory=root,
            ),
        ],
    )


def test_tree_fingerprint_is_stable_and_detects_source_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "skill"
    nested = root / "scripts"
    nested.mkdir(parents=True)
    skill_file = root / "SKILL.md"
    skill_file.write_text("original instructions", encoding="utf-8")
    (nested / "run.sh").write_text("echo safe", encoding="utf-8")
    inventory = _skill_inventory(root)

    def fail_rglob(_self, _pattern):
        raise AssertionError("inventory_fingerprint must not use Path.rglob")

    monkeypatch.setattr(Path, "rglob", fail_rglob)
    first = inventory_fingerprint(inventory)

    assert inventory_fingerprint(inventory) == first
    skill_file.write_text("changed instructions", encoding="utf-8")
    assert inventory_fingerprint(inventory) != first


def test_tree_entry_limit_stops_wide_directory_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "skill"
    root.mkdir()
    for index in range(3):
        (root / f"file-{index}.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(planner, "_MAX_FINGERPRINT_ENTRIES", 3)

    with pytest.raises(ValueError, match="fingerprint entry limit"):
        inventory_fingerprint(_skill_inventory(root))


def test_tree_byte_limit_is_checked_before_large_file_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "skill"
    root.mkdir()
    (root / "large.bin").write_bytes(b"12345")
    monkeypatch.setattr(planner, "_MAX_FINGERPRINT_BYTES", 4)

    with pytest.raises(ValueError, match="fingerprint byte limit"):
        inventory_fingerprint(_skill_inventory(root))


def test_tree_rejects_symbolic_link_escape(tmp_path: Path) -> None:
    root = tmp_path / "skill"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("do not read", encoding="utf-8")
    (root / "escape.txt").symlink_to(outside)
    inventory = _skill_inventory(root)

    fingerprint = inventory_fingerprint(inventory)
    outside.write_text("changed outside content", encoding="utf-8")

    # The link is represented only as a rejected marker; its target is never
    # read into the fingerprint.
    assert inventory_fingerprint(inventory) == fingerprint


def test_tree_rejects_non_regular_entry(tmp_path: Path) -> None:
    root = tmp_path / "skill"
    root.mkdir()
    os.mkfifo(root / "named-pipe")

    # In particular, fingerprinting must not open the FIFO and block.
    assert inventory_fingerprint(_skill_inventory(root))


def test_memory_relative_path_must_stay_in_declared_scope(
    tmp_path: Path,
) -> None:
    source = tmp_path / "memory.md"
    source.write_text("memory", encoding="utf-8")
    inventory = ProviderInventory(
        provider_id="codex",
        provider_name="Codex",
        detected=True,
        memory_projects=[
            SourceMemoryProject(
                source_id="memory-1",
                project_key="project",
                files=[
                    SourceMemoryFile(
                        source_path=source,
                        relative_path=Path("../escape.md"),
                    ),
                ],
            ),
        ],
    )

    with pytest.raises(ValueError, match="relative path escapes"):
        inventory_fingerprint(inventory)
