# -*- coding: utf-8 -*-
"""Property-based integration tests for export-import \
round-trip and memory snapshot consistency.

Properties 1 and 14 from the design document.
"""
from __future__ import annotations

import json
import uuid
import zipfile
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings, HealthCheck, assume
from hypothesis import strategies as st

from qwenpaw.backup.exporter import AssetExporter
from qwenpaw.backup.importer import AssetImporter
from qwenpaw.backup.models import (
    AssetType,
    ConflictStrategy,
    ExportOptions,
    ExportResult,
)
from qwenpaw.backup.sanitizer import sanitize_preferences


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_safe_text = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=0,
    max_size=80,
)

_config_value = st.one_of(
    _safe_text,
    st.integers(min_value=-1000, max_value=1000),
    st.booleans(),
    st.none(),
)

_safe_key = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N")),
    min_size=1,
    max_size=12,
)


@st.composite
def _simple_config(draw: st.DrawFn) -> dict:
    """Generate a simple config dict (no sensitive fields)."""
    n = draw(st.integers(min_value=0, max_value=5))
    result: dict = {}
    for _ in range(n):
        key = draw(_safe_key)
        result[key] = draw(_config_value)
    return result


@st.composite
def _workspace_content(draw: st.DrawFn) -> dict[str, Any]:
    """Generate workspace file contents for round-trip testing.

    Returns a dict describing what files to create:
    - agent_json: dict for agent.json (may include tools)
    - config_json: dict for config.json
    - memory_files: list of (name, content_str) for memory entries
    - skill_files: list of (skill_name, filename, content_str)
    - include_preferences: bool
    - include_memories: bool
    - include_skills: bool
    - include_tools: bool
    """
    agent_id = draw(
        st.text(
            alphabet=st.characters(whitelist_categories=("L", "N")),
            min_size=1,
            max_size=8,
        ),
    )
    agent_json: dict[str, Any] = {"id": agent_id, "name": f"Agent {agent_id}"}

    # Optionally add tools config
    has_tools = draw(st.booleans())
    if has_tools:
        agent_json["tools"] = {"builtin_tools": draw(_simple_config())}

    config_json = draw(_simple_config())

    # Memory files
    n_memories = draw(st.integers(min_value=0, max_value=3))
    memory_files: list[tuple[str, str]] = []
    for i in range(n_memories):
        content = draw(_safe_text)
        memory_files.append(
            (f"{i:03d}.json", json.dumps({"content": content})),
        )

    # Skill files
    n_skills = draw(st.integers(min_value=0, max_value=2))
    skill_files: list[tuple[str, str, str]] = []
    for i in range(n_skills):
        skill_name = f"skill_{i}"
        content = draw(_safe_text)
        skill_files.append(
            (skill_name, "SKILL.md", f"# {skill_name}\n{content}"),
        )

    # Asset type flags
    include_preferences = draw(st.booleans())
    include_memories = draw(st.booleans())
    include_skills = draw(st.booleans())
    include_tools = draw(st.booleans())

    return {
        "agent_json": agent_json,
        "config_json": config_json,
        "memory_files": memory_files,
        "skill_files": skill_files,
        "include_preferences": include_preferences,
        "include_memories": include_memories,
        "include_skills": include_skills,
        "include_tools": include_tools,
    }


def _create_workspace(tmp_path: Path, content: dict) -> Path:
    """Create a workspace directory from generated content."""
    ws = tmp_path / "workspace"
    ws.mkdir(exist_ok=True)

    (ws / "agent.json").write_text(
        json.dumps(content["agent_json"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (ws / "config.json").write_text(
        json.dumps(content["config_json"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if content["memory_files"]:
        mem_dir = ws / "memory"
        mem_dir.mkdir(exist_ok=True)
        entries_dir = mem_dir / "entries"
        entries_dir.mkdir(exist_ok=True)
        index_entries: list[str] = []
        for fname, fcontent in content["memory_files"]:
            (entries_dir / fname).write_text(fcontent, encoding="utf-8")
            index_entries.append(fname)
        (mem_dir / "memory_index.json").write_text(
            json.dumps({"entries": index_entries}),
            encoding="utf-8",
        )

    if content["skill_files"]:
        skills_dir = ws / "skills"
        skills_dir.mkdir(exist_ok=True)
        for skill_name, filename, fcontent in content["skill_files"]:
            skill_sub = skills_dir / skill_name
            skill_sub.mkdir(exist_ok=True)
            (skill_sub / filename).write_text(fcontent, encoding="utf-8")

    return ws


# ---------------------------------------------------------------------------
# Property 1: Export-Import round-trip consistency
# (导出-导入往返一致性)
# ---------------------------------------------------------------------------


def _has_exportable_content(content: dict) -> bool:
    """Check if content dict has at least one selected type with data."""
    has_any = (
        content["include_preferences"]
        or content["include_memories"]
        or content["include_skills"]
        or content["include_tools"]
    )
    if not has_any:
        return False
    if content["include_preferences"]:
        return True
    if content["include_memories"] and content["memory_files"]:
        return True
    if content["include_skills"] and content["skill_files"]:
        return True
    if content["include_tools"] and content["agent_json"].get("tools"):
        return True
    return False


def _verify_zip_matches_imported(
    export_result: ExportResult,
    export_zip: Path,
    ws_target: Path,
) -> None:
    """Verify every exported file matches the imported copy."""
    with zipfile.ZipFile(export_zip, "r") as zf:
        for entry in export_result.manifest.assets:
            target_file = ws_target / entry.relative_path
            assert (
                target_file.exists()
            ), f"Imported file missing: {entry.relative_path}"
            assert target_file.read_bytes() == zf.read(
                entry.relative_path,
            ), f"Round-trip mismatch for {entry.relative_path}"


def _verify_preferences_sanitized(
    content: dict,
    ws_source: Path,
    ws_target: Path,
) -> None:
    """Verify sanitized preferences match imported versions."""
    if not content["include_preferences"]:
        return
    for pref_name in ["agent.json", "config.json"]:
        target_file = ws_target / f"preferences/{pref_name}"
        source_file = ws_source / pref_name
        if not target_file.exists() or not source_file.exists():
            continue
        original = json.loads(
            source_file.read_text(encoding="utf-8"),
        )
        sanitized = json.dumps(
            sanitize_preferences(original),
            ensure_ascii=False,
            indent=2,
        ).encode("utf-8")
        assert (
            target_file.read_bytes() == sanitized
        ), f"Sanitized round-trip mismatch for {pref_name}"


def _verify_asset_type_exists(
    export_result: ExportResult,
    ws_target: Path,
    asset_type: AssetType,
) -> None:
    """Verify all entries of a given type exist in target."""
    for entry in export_result.manifest.assets:
        if entry.asset_type == asset_type:
            assert (ws_target / entry.relative_path).exists()


@given(content=_workspace_content())
@settings(
    max_examples=50,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
@pytest.mark.asyncio
async def test_export_import_roundtrip_consistency(
    content: dict,
    tmp_path: Path,
) -> None:
    """Property 1: Export-import round-trip consistency.

    **Validates: Requirements 1.1, 1.2, 3.1, 3.2**
    """
    assume(_has_exportable_content(content))

    run_dir = tmp_path / uuid.uuid4().hex
    run_dir.mkdir()

    ws_source = _create_workspace(run_dir, content)
    export_zip = run_dir / "export.zip"

    exporter = AssetExporter()
    export_result = await exporter.export_assets(
        ExportOptions(
            workspace_dir=ws_source,
            output_path=export_zip,
            include_preferences=content["include_preferences"],
            include_memories=content["include_memories"],
            include_skills=content["include_skills"],
            include_tools=content["include_tools"],
        ),
    )
    assert export_zip.exists()
    assert export_result.asset_count > 0

    ws_target = run_dir / "workspace_target"
    ws_target.mkdir(exist_ok=True)

    importer = AssetImporter(workspace_dir=ws_target)
    import_result = await importer.import_assets(
        zip_path=export_zip,
        strategy=ConflictStrategy.OVERWRITE,
    )
    assert not import_result.errors, f"Import errors: {import_result.errors}"

    _verify_zip_matches_imported(export_result, export_zip, ws_target)
    _verify_preferences_sanitized(content, ws_source, ws_target)

    if content["include_memories"] and content["memory_files"]:
        _verify_asset_type_exists(
            export_result,
            ws_target,
            AssetType.MEMORIES,
        )
    if content["include_skills"] and content["skill_files"]:
        _verify_asset_type_exists(
            export_result,
            ws_target,
            AssetType.SKILLS,
        )
    if content["include_tools"] and content["agent_json"].get("tools"):
        _verify_asset_type_exists(
            export_result,
            ws_target,
            AssetType.TOOLS,
        )


# ---------------------------------------------------------------------------
# Mock MemoryManager for Property 14
# ---------------------------------------------------------------------------


class MockMemoryManager:
    """Mock MemoryManager that tracks lock acquire/release
    calls and verifies consistency during the locked region.
    """

    def __init__(self) -> None:
        self.lock_acquired = False
        self.lock_released = False
        self.acquire_count = 0
        self.release_count = 0

    async def acquire_read_lock(
        self,
        timeout: float = 30.0,  # pylint: disable=unused-argument
    ) -> str:
        self.lock_acquired = True
        self.acquire_count += 1
        return "mock-lock-token"

    async def release_read_lock(
        self,
        lock: Any,  # pylint: disable=unused-argument
    ) -> None:
        self.lock_released = True
        self.release_count += 1


# ---------------------------------------------------------------------------
# Strategies for Property 14
# ---------------------------------------------------------------------------


@st.composite
def _memory_workspace_content(draw: st.DrawFn) -> dict[str, Any]:
    """Generate workspace content with memory data for
    snapshot consistency testing.

    Ensures memory_index.json references match actual
    entry files.
    """
    agent_id = draw(
        st.text(
            alphabet=st.characters(whitelist_categories=("L", "N")),
            min_size=1,
            max_size=8,
        ),
    )

    n_entries = draw(st.integers(min_value=1, max_value=5))
    entry_names: list[str] = []
    entry_contents: dict[str, str] = {}
    for i in range(n_entries):
        name = f"{i:03d}.json"
        content_text = draw(_safe_text)
        entry_names.append(name)
        entry_contents[name] = json.dumps({"content": content_text, "id": i})

    return {
        "agent_id": agent_id,
        "entry_names": entry_names,
        "entry_contents": entry_contents,
    }


def _create_memory_workspace(tmp_path: Path, content: dict) -> Path:
    """Create a workspace with memory directory for snapshot testing."""
    ws = tmp_path / "mem_workspace"
    ws.mkdir(exist_ok=True)

    # Minimal agent.json
    (ws / "agent.json").write_text(
        json.dumps({"id": content["agent_id"]}),
        encoding="utf-8",
    )

    # Memory directory with index and entries
    mem_dir = ws / "memory"
    mem_dir.mkdir(exist_ok=True)
    entries_dir = mem_dir / "entries"
    entries_dir.mkdir(exist_ok=True)

    # Write index referencing all entries
    (mem_dir / "memory_index.json").write_text(
        json.dumps({"entries": content["entry_names"]}),
        encoding="utf-8",
    )

    # Write entry files
    for name, file_content in content["entry_contents"].items():
        (entries_dir / name).write_text(file_content, encoding="utf-8")

    return ws


# ---------------------------------------------------------------------------
# Property 14: Memory data snapshot consistency (记忆数据快照一致性)
# ---------------------------------------------------------------------------


@given(content=_memory_workspace_content())
@settings(
    max_examples=50,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
@pytest.mark.asyncio
async def test_memory_snapshot_consistency(
    content: dict,
    tmp_path: Path,
) -> None:
    """Property 14: For any export that includes memory data, between
    acquire_read_lock and release_read_lock, the memory index and memory
    entry files are consistent.

    - Memory index references should all have corresponding entry files
    - No orphan entries (entries not referenced by index)
    - Lock is properly acquired before and released after memory collection

    **Validates: Requirements 11.3, 11.4**
    """
    run_dir = tmp_path / uuid.uuid4().hex
    run_dir.mkdir()

    ws = _create_memory_workspace(run_dir, content)
    export_zip = run_dir / "memory_export.zip"

    # Create mock memory manager to verify lock behavior
    mock_mm = MockMemoryManager()
    exporter = AssetExporter(memory_manager=mock_mm)

    result = await exporter.export_assets(
        ExportOptions(
            workspace_dir=ws,
            output_path=export_zip,
            include_preferences=False,
            include_memories=True,
            include_skills=False,
            include_tools=False,
        ),
    )

    # Verify lock was acquired and released
    assert mock_mm.lock_acquired, "Memory read lock was not acquired"
    assert mock_mm.lock_released, "Memory read lock was not released"
    assert (
        mock_mm.acquire_count == 1
    ), f"Lock acquired {mock_mm.acquire_count} times, expected 1"
    assert (
        mock_mm.release_count == 1
    ), f"Lock released {mock_mm.release_count} times, expected 1"

    # Verify exported ZIP contains consistent memory data
    assert export_zip.exists()

    with zipfile.ZipFile(export_zip, "r") as zf:
        zip_names = zf.namelist()

        # Find memory index in ZIP
        index_path = None
        for name in zip_names:
            if name.endswith("memory_index.json"):
                index_path = name
                break

        assert index_path is not None, "memory_index.json not found in ZIP"

        # Parse the index
        index_data = json.loads(zf.read(index_path))
        referenced_entries = set(index_data.get("entries", []))

        # Find all entry files in ZIP
        entry_files_in_zip: set[str] = set()
        for name in zip_names:
            if (
                "entries/" in name
                and name != index_path
                and name != "manifest.json"
            ):
                # Extract just the filename from the path
                entry_filename = name.split("/")[-1]
                if entry_filename:  # skip directory entries
                    entry_files_in_zip.add(entry_filename)

        # Consistency check 1: Every index reference has
        # a corresponding entry file
        for ref in referenced_entries:
            assert ref in entry_files_in_zip, (
                f"Index references entry '{ref}' but it's not in the ZIP. "
                f"ZIP entries: {entry_files_in_zip}"
            )

        # Consistency check 2: No orphan entries (not referenced by index)
        for entry_file in entry_files_in_zip:
            assert entry_file in referenced_entries, (
                f"Orphan entry '{entry_file}' found in ZIP but not referenced "
                f"by index. Index references: {referenced_entries}"
            )

        # Consistency check 3: Entry count matches
        assert len(referenced_entries) == len(entry_files_in_zip), (
            f"Entry count mismatch: index references "
            f"{len(referenced_entries)}, "
            f"ZIP contains {len(entry_files_in_zip)} entry files"
        )

        # Consistency check 4: Each entry file content is valid and complete
        for entry in result.manifest.assets:
            if entry.relative_path in zip_names:
                file_data = zf.read(entry.relative_path)
                assert len(file_data) == entry.size_bytes, (
                    f"Size mismatch for {entry.relative_path}: "
                    f"manifest={entry.size_bytes}, actual={len(file_data)}"
                )
