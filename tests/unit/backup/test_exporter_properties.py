# -*- coding: utf-8 -*-
"""Property-based tests for AssetExporter.

Properties 11, 12, 13, and 2 from the design document.
"""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from qwenpaw.backup.exporter import AssetExporter
from qwenpaw.backup.models import AssetType, ExportOptions


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_safe_text = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=0,
    max_size=100,
)

_config_value = st.one_of(
    _safe_text,
    st.integers(min_value=-1000, max_value=1000),
    st.booleans(),
    st.none(),
)


@st.composite
def _simple_config(draw: st.DrawFn) -> dict:
    """Generate a simple config dict."""
    n = draw(st.integers(min_value=0, max_value=5))
    result: dict = {}
    for _ in range(n):
        key = draw(
            st.text(
                alphabet=st.characters(whitelist_categories=("L", "N")),
                min_size=1,
                max_size=15,
            ),
        )
        result[key] = draw(_config_value)
    return result


@st.composite
def _workspace_content(draw: st.DrawFn) -> dict[str, Any]:
    """Generate workspace file contents.

    Returns a dict describing what files to create:
    - agent_json: dict for agent.json
    - config_json: dict for config.json
    - memory_files: list of (name, content) for memory entries
    - skill_files: list of (skill_name, filename, content)
    """
    agent_id = draw(
        st.text(
            alphabet=st.characters(whitelist_categories=("L", "N")),
            min_size=1,
            max_size=10,
        ),
    )
    agent_json = {"id": agent_id, "name": f"Agent {agent_id}"}

    # Optionally add tools config
    if draw(st.booleans()):
        agent_json["tools"] = {"builtin_tools": draw(_simple_config())}

    config_json = draw(_simple_config())

    # Memory files
    n_memories = draw(st.integers(min_value=0, max_value=3))
    memory_files = []
    for i in range(n_memories):
        content = draw(_safe_text)
        memory_files.append(
            (f"{i:03d}.json", json.dumps({"content": content})),
        )

    # Skill files
    n_skills = draw(st.integers(min_value=0, max_value=2))
    skill_files = []
    for i in range(n_skills):
        skill_name = f"skill_{i}"
        content = draw(_safe_text)
        skill_files.append(
            (skill_name, "SKILL.md", f"# {skill_name}\n{content}"),
        )

    return {
        "agent_json": agent_json,
        "config_json": config_json,
        "memory_files": memory_files,
        "skill_files": skill_files,
    }


def _create_workspace_from_content(tmp_path: Path, content: dict) -> Path:
    """Create a workspace directory from generated content."""
    ws = tmp_path / "workspace"
    ws.mkdir(exist_ok=True)

    (ws / "agent.json").write_text(
        json.dumps(content["agent_json"], ensure_ascii=False),
        encoding="utf-8",
    )
    (ws / "config.json").write_text(
        json.dumps(content["config_json"], ensure_ascii=False),
        encoding="utf-8",
    )

    if content["memory_files"]:
        mem_dir = ws / "memory"
        mem_dir.mkdir(exist_ok=True)
        entries_dir = mem_dir / "entries"
        entries_dir.mkdir(exist_ok=True)
        index_entries = []
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


def _snapshot_directory(directory: Path) -> dict[str, bytes]:
    """Take a snapshot of all files in a directory (path -> content bytes)."""
    snapshot: dict[str, bytes] = {}
    if not directory.exists():
        return snapshot
    for fpath in sorted(directory.rglob("*")):
        if fpath.is_file():
            rel = str(fpath.relative_to(directory))
            snapshot[rel] = fpath.read_bytes()
    return snapshot


# Asset type subsets strategy
_asset_type_flags = st.fixed_dictionaries(
    {
        "include_preferences": st.booleans(),
        "include_memories": st.booleans(),
        "include_skills": st.booleans(),
        "include_tools": st.booleans(),
    },
)


# ---------------------------------------------------------------------------
# Property 12: Export doesn't modify source workspace
# ---------------------------------------------------------------------------


@given(content=_workspace_content())
@settings(
    max_examples=50,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@pytest.mark.asyncio
async def test_export_does_not_modify_source_workspace(
    content: dict,
    tmp_path: Path,
) -> None:
    """Property 12: export_assets doesn't modify source workspace files.

    **Validates: Requirements 1.4**
    """
    ws = _create_workspace_from_content(tmp_path, content)
    output = tmp_path / "export.zip"

    # Snapshot before export
    before = _snapshot_directory(ws)

    exporter = AssetExporter()
    await exporter.export_assets(
        ExportOptions(
            workspace_dir=ws,
            output_path=output,
        ),
    )

    # Snapshot after export
    after = _snapshot_directory(ws)

    assert before == after, "Export modified source workspace files!"


# ---------------------------------------------------------------------------
# Property 13: Selective export filtering
# ---------------------------------------------------------------------------


@given(content=_workspace_content(), flags=_asset_type_flags)
@settings(
    max_examples=50,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@pytest.mark.asyncio
async def test_selective_export_filtering(
    content: dict,
    flags: dict,
    tmp_path: Path,
) -> None:
    """Property 13: Only selected asset types are included in export.

    **Validates: Requirements 1.2**
    """
    ws = _create_workspace_from_content(tmp_path, content)
    output = tmp_path / "export.zip"

    exporter = AssetExporter()
    result = await exporter.export_assets(
        ExportOptions(
            workspace_dir=ws,
            output_path=output,
            **flags,
        ),
    )

    type_to_prefix = {
        AssetType.PREFERENCES: "preferences/",
        AssetType.MEMORIES: "memories/",
        AssetType.SKILLS: "skills/",
        AssetType.TOOLS: "tools/",
        AssetType.GLOBAL_CONFIG: "global_config/",
    }

    flag_to_type = {
        "include_preferences": AssetType.PREFERENCES,
        "include_memories": AssetType.MEMORIES,
        "include_skills": AssetType.SKILLS,
        "include_tools": AssetType.TOOLS,
    }

    # Check manifest entries
    for flag_name, asset_type in flag_to_type.items():
        entries_of_type = [
            e for e in result.manifest.assets if e.asset_type == asset_type
        ]
        if not flags[flag_name]:
            assert (
                len(entries_of_type) == 0
            ), f"Found {asset_type.value} entries when {flag_name}=False"

    # Check ZIP contents (excluding manifest.json)
    if output.exists():
        with zipfile.ZipFile(output) as zf:
            names = [n for n in zf.namelist() if n != "manifest.json"]
            for flag_name, asset_type in flag_to_type.items():
                prefix = type_to_prefix[asset_type]
                matching = [n for n in names if n.startswith(prefix)]
                if not flags[flag_name]:
                    assert (
                        len(matching) == 0
                    ), f"ZIP contains {prefix} files when {flag_name}=False"


# ---------------------------------------------------------------------------
# Property 11: Asset package directory structure
# ---------------------------------------------------------------------------


@given(content=_workspace_content())
@settings(
    max_examples=50,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@pytest.mark.asyncio
async def test_asset_package_directory_structure(
    content: dict,
    tmp_path: Path,
) -> None:
    """Property 11: ZIP contains manifest.json at root
    and proper directory structure.

    **Validates: Requirements 13.1, 13.2, 13.3, 13.4, 13.5**
    """
    ws = _create_workspace_from_content(tmp_path, content)
    output = tmp_path / "export.zip"

    exporter = AssetExporter()
    result = await exporter.export_assets(
        ExportOptions(
            workspace_dir=ws,
            output_path=output,
        ),
    )

    with zipfile.ZipFile(output) as zf:
        names = zf.namelist()

        # 13.1: manifest.json at root
        assert "manifest.json" in names

        # Verify manifest is valid JSON
        manifest_data = json.loads(zf.read("manifest.json"))
        assert "schema_version" in manifest_data
        assert "assets" in manifest_data

        # All non-manifest files must be under the correct directories
        valid_prefixes = (
            "preferences/",
            "memories/",
            "skills/",
            "tools/",
            "global_config/",
        )
        for name in names:
            if name == "manifest.json":
                continue
            assert any(
                name.startswith(p) for p in valid_prefixes
            ), f"File {name!r} is not under a valid directory"

        # 13.2: preferences files under preferences/
        pref_entries = [
            e
            for e in result.manifest.assets
            if e.asset_type == AssetType.PREFERENCES
        ]
        for e in pref_entries:
            assert e.relative_path.startswith("preferences/")

        # 13.3: memory files under memories/
        mem_entries = [
            e
            for e in result.manifest.assets
            if e.asset_type == AssetType.MEMORIES
        ]
        for e in mem_entries:
            assert e.relative_path.startswith("memories/")

        # 13.4: skill files under skills/
        skill_entries = [
            e
            for e in result.manifest.assets
            if e.asset_type == AssetType.SKILLS
        ]
        for e in skill_entries:
            assert e.relative_path.startswith("skills/")

        # 13.5: tool files under tools/
        tool_entries = [
            e
            for e in result.manifest.assets
            if e.asset_type == AssetType.TOOLS
        ]
        for e in tool_entries:
            assert e.relative_path.startswith("tools/")


# ---------------------------------------------------------------------------
# Property 2: Manifest integrity (SHA256 checksums)
# ---------------------------------------------------------------------------


@given(content=_workspace_content())
@settings(
    max_examples=50,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@pytest.mark.asyncio
async def test_manifest_sha256_integrity(
    content: dict,
    tmp_path: Path,
) -> None:
    """Property 2: SHA256 checksums in manifest match
    actual file contents in ZIP.

    **Validates: Requirements 2.2, 2.3**
    """
    ws = _create_workspace_from_content(tmp_path, content)
    output = tmp_path / "export.zip"

    exporter = AssetExporter()
    result = await exporter.export_assets(
        ExportOptions(
            workspace_dir=ws,
            output_path=output,
        ),
    )

    with zipfile.ZipFile(output) as zf:
        for entry in result.manifest.assets:
            # File must exist in ZIP
            assert (
                entry.relative_path in zf.namelist()
            ), f"Manifest entry {entry.relative_path!r} not found in ZIP"

            # SHA256 must match
            file_data = zf.read(entry.relative_path)
            actual_sha = hashlib.sha256(file_data).hexdigest()
            assert actual_sha == entry.sha256, (
                f"SHA256 mismatch for {entry.relative_path}: "
                f"manifest={entry.sha256}, actual={actual_sha}"
            )

            # Size must match
            assert len(file_data) == entry.size_bytes, (
                f"Size mismatch for {entry.relative_path}: "
                f"manifest={entry.size_bytes}, actual={len(file_data)}"
            )
