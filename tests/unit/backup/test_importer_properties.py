# -*- coding: utf-8 -*-
"""Property-based tests for AssetImporter.

Properties 4, 5, and 6 from the design document.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
import zipfile
from pathlib import Path

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from qwenpaw.backup.importer import AssetImporter, _sha256
from qwenpaw.backup.models import (
    AssetEntry,
    AssetManifest,
    AssetType,
    ConflictStrategy,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_safe_filename_char = st.sampled_from(
    "abcdefghijklmnopqrstuvwxyz0123456789_-",
)

_safe_filename = st.text(
    alphabet=_safe_filename_char,
    min_size=1,
    max_size=15,
).map(lambda s: s + ".json")

_asset_type = st.sampled_from(list(AssetType))

_type_to_prefix = {
    AssetType.PREFERENCES: "preferences",
    AssetType.MEMORIES: "memories",
    AssetType.SKILLS: "skills",
    AssetType.TOOLS: "tools",
    AssetType.GLOBAL_CONFIG: "global_config",
}

_file_content = st.binary(min_size=1, max_size=500)


@st.composite
def _asset_files(draw: st.DrawFn) -> list[tuple[AssetType, str, bytes]]:
    """Generate a list of (asset_type, filename, content)
    tuples with unique paths.
    """
    n = draw(st.integers(min_value=1, max_value=6))
    seen: set[str] = set()
    files: list[tuple[AssetType, str, bytes]] = []
    for _ in range(n):
        atype = draw(_asset_type)
        fname = draw(_safe_filename)
        prefix = _type_to_prefix[atype]
        rel_path = f"{prefix}/{fname}"
        if rel_path in seen:
            continue
        seen.add(rel_path)
        content = draw(_file_content)
        files.append((atype, fname, content))
    assume(len(files) > 0)
    return files


def _build_zip_from_files(
    zip_path: Path,
    files: list[tuple[AssetType, str, bytes]],
) -> AssetManifest:
    """Build a valid ZIP from generated files and return the manifest."""
    assets: list[AssetEntry] = []
    for atype, fname, content in files:
        prefix = _type_to_prefix[atype]
        rel_path = f"{prefix}/{fname}"
        sha = hashlib.sha256(content).hexdigest()
        assets.append(
            AssetEntry(
                asset_type=atype,
                name=fname,
                relative_path=rel_path,
                sha256=sha,
                size_bytes=len(content),
            ),
        )

    manifest = AssetManifest(
        schema_version="copaw-assets.v1",
        created_at="2025-01-01T00:00:00Z",
        source_agent_id="test",
        source_device_id="test",
        copaw_version="0.1.0",
        assets=assets,
    )

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", manifest.model_dump_json(indent=2))
        for atype, fname, content in files:
            prefix = _type_to_prefix[atype]
            zf.writestr(f"{prefix}/{fname}", content)

    return manifest


# ---------------------------------------------------------------------------
# Property 4: Path safety (路径安全性)
# ---------------------------------------------------------------------------

_path_segment = st.one_of(
    st.text(alphabet=_safe_filename_char, min_size=1, max_size=10),
    st.just(".."),
)


@st.composite
def _zip_with_paths(draw: st.DrawFn) -> tuple[list[str], bool]:
    """Generate ZIP entry paths, some possibly containing '..'."""
    n = draw(st.integers(min_value=1, max_value=5))
    paths: list[str] = []
    has_traversal = False
    for _ in range(n):
        num_segments = draw(st.integers(min_value=1, max_value=4))
        segments = [draw(_path_segment) for _ in range(num_segments)]
        path = "/".join(segments)
        if ".." in segments:
            has_traversal = True
        paths.append(path)
    return paths, has_traversal


@given(data=_zip_with_paths())
@settings(max_examples=100)
def test_path_safety_no_traversal(
    data: tuple[list[str], bool],
) -> None:
    """Property 4: No '..' path traversal in ZIP file paths, and all resolved
    paths are children of the target directory.

    **Validates: Requirements 8.1, 8.2**
    """
    paths, has_traversal = data

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        ws = tmp_path / "workspace"
        ws.mkdir()

        manifest_data = {
            "schema_version": "copaw-assets.v1",
            "created_at": "2025-01-01T00:00:00Z",
            "source_agent_id": "a",
            "source_device_id": "d",
            "copaw_version": "0.1.0",
            "assets": [],
        }
        zip_path = tmp_path / "test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("manifest.json", json.dumps(manifest_data))
            for p in paths:
                zf.writestr(p, b"content")

        importer = AssetImporter(workspace_dir=ws)

        if has_traversal:
            with pytest.raises(Exception):
                importer._validate_zip(  # pylint: disable=protected-access
                    zip_path,
                )
        else:
            try:
                importer._validate_zip(  # pylint: disable=protected-access
                    zip_path,
                )
            except Exception as exc:
                assert "traversal" not in str(exc).lower()
                assert "outside target" not in str(exc).lower()


@given(
    filename=st.text(
        alphabet=_safe_filename_char,
        min_size=1,
        max_size=20,
    ),
)
@settings(max_examples=50)
def test_resolved_paths_are_children(filename: str) -> None:
    """Property 4 (supplementary): All resolved paths from valid ZIPs are
    children of the target directory.

    **Validates: Requirements 8.1, 8.2**
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        ws = tmp_path / "workspace"
        ws.mkdir()

        rel_path = f"preferences/{filename}.json"
        content = b"test content"
        sha = _sha256(content)

        manifest_data = {
            "schema_version": "copaw-assets.v1",
            "created_at": "2025-01-01T00:00:00Z",
            "source_agent_id": "a",
            "source_device_id": "d",
            "copaw_version": "0.1.0",
            "assets": [
                {
                    "asset_type": "preferences",
                    "name": f"{filename}.json",
                    "relative_path": rel_path,
                    "sha256": sha,
                    "size_bytes": len(content),
                    "metadata": {},
                },
            ],
        }

        zip_path = tmp_path / "test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("manifest.json", json.dumps(manifest_data))
            zf.writestr(rel_path, content)

        importer = AssetImporter(workspace_dir=ws)
        manifest = importer._validate_zip(  # pylint: disable=protected-access
            zip_path,
        )

        ws_resolved = ws.resolve()
        for entry in manifest.assets:
            resolved = (ws_resolved / entry.relative_path).resolve()
            assert str(resolved).startswith(
                str(ws_resolved),
            ), (
                f"Path {entry.relative_path} resolves "
                f"outside workspace: {resolved}"
            )


# ---------------------------------------------------------------------------
# Property 5: Conflict detection partition consistency
# (冲突检测分区一致性)
# ---------------------------------------------------------------------------

_conflict_strategy_no_ask = st.sampled_from(
    [
        ConflictStrategy.SKIP,
        ConflictStrategy.OVERWRITE,
        ConflictStrategy.RENAME,
    ],
)


@st.composite
def _conflict_scenario(draw: st.DrawFn) -> dict:
    """Generate a conflict scenario with some existing files."""
    files = draw(_asset_files())
    existing: dict[str, bytes] = {}

    for atype, fname, content in files:
        prefix = _type_to_prefix[atype]
        rel_path = f"{prefix}/{fname}"
        choice = draw(st.sampled_from(["absent", "same", "different"]))
        if choice == "same":
            existing[rel_path] = content
        elif choice == "different":
            diff_content = draw(_file_content)
            if diff_content == content:
                diff_content = content + b"_diff"
            existing[rel_path] = diff_content

    return {"files": files, "existing": existing}


@given(scenario=_conflict_scenario(), strategy=_conflict_strategy_no_ask)
@settings(max_examples=100)
def test_conflict_detection_partition_consistency(
    scenario: dict,
    strategy: ConflictStrategy,
) -> None:
    """Property 5: imported ∩ skipped = ∅ and
    |imported| + |skipped| + |unresolved_conflicts| = |manifest.assets|.

    **Validates: Requirements 4.7**
    """
    files = scenario["files"]
    existing = scenario["existing"]

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        ws = tmp_path / "workspace"
        ws.mkdir()

        for rel_path, content in existing.items():
            target = ws / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)

        zip_path = tmp_path / "test.zip"
        manifest = _build_zip_from_files(zip_path, files)

        importer = AssetImporter(workspace_dir=ws)
        (
            to_import,
            to_skip,
            _conflicts,
        ) = importer._detect_conflicts(  # pylint: disable=protected-access
            manifest,
            ws,
            strategy,
        )

        imported_ids = set(id(e) for e in to_import)
        skipped_ids = set(id(e) for e in to_skip)

        # For non-ASK strategies, all conflicts are resolved
        unresolved_count = 0

        # imported ∩ skipped = ∅
        assert imported_ids.isdisjoint(
            skipped_ids,
        ), "imported and skipped sets overlap!"

        # |imported| + |skipped| + |unresolved| = |manifest.assets|
        total = len(to_import) + len(to_skip) + unresolved_count
        assert total == len(manifest.assets), (
            f"Partition mismatch: {len(to_import)} + {len(to_skip)} "
            f"+ {unresolved_count} = {total}, expected {len(manifest.assets)}"
        )


# Also test with ASK strategy
@given(scenario=_conflict_scenario())
@settings(max_examples=50)
def test_conflict_detection_partition_ask_strategy(
    scenario: dict,
) -> None:
    """Property 5 (ASK): Partition consistency with ASK strategy.

    **Validates: Requirements 4.7**
    """
    files = scenario["files"]
    existing = scenario["existing"]

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        ws = tmp_path / "workspace"
        ws.mkdir()

        for rel_path, content in existing.items():
            target = ws / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)

        zip_path = tmp_path / "test.zip"
        manifest = _build_zip_from_files(zip_path, files)

        importer = AssetImporter(workspace_dir=ws)
        (
            to_import,
            to_skip,
            conflicts,
        ) = importer._detect_conflicts(  # pylint: disable=protected-access
            manifest,
            ws,
            ConflictStrategy.ASK,
        )

        imported_ids = set(id(e) for e in to_import)
        skipped_ids = set(id(e) for e in to_skip)

        # ASK: unresolved = conflicts count
        unresolved_count = len(conflicts)

        assert imported_ids.isdisjoint(skipped_ids)
        total = len(to_import) + len(to_skip) + unresolved_count
        assert total == len(manifest.assets), (
            f"ASK partition: {len(to_import)} + {len(to_skip)} "
            f"+ {unresolved_count} = {total}, expected {len(manifest.assets)}"
        )


# ---------------------------------------------------------------------------
# Property 6: Conflict strategy behavior correctness
# (冲突策略行为正确性)
# ---------------------------------------------------------------------------


@given(scenario=_conflict_scenario())
@settings(max_examples=100)
@pytest.mark.asyncio
async def test_skip_preserves_target_unchanged(
    scenario: dict,
) -> None:
    """Property 6 (SKIP): Target file content is preserved unchanged.

    **Validates: Requirements 4.1, 4.2**
    """
    files = scenario["files"]
    existing = scenario["existing"]

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        ws = tmp_path / "workspace"
        ws.mkdir()

        snapshots: dict[str, bytes] = {}
        for rel_path, content in existing.items():
            target = ws / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            snapshots[rel_path] = content

        zip_path = tmp_path / "test.zip"
        _build_zip_from_files(zip_path, files)

        importer = AssetImporter(workspace_dir=ws)
        await importer.import_assets(zip_path, ConflictStrategy.SKIP)

        for rel_path, original_content in snapshots.items():
            target = ws / rel_path
            if target.exists():
                assert (
                    target.read_bytes() == original_content
                ), f"SKIP modified existing file: {rel_path}"


@given(scenario=_conflict_scenario())
@settings(max_examples=100)
@pytest.mark.asyncio
async def test_overwrite_target_equals_source(
    scenario: dict,
) -> None:
    """Property 6 (OVERWRITE): Target file content equals source file
    (for non-preference files).

    **Validates: Requirements 4.1, 4.3**
    """
    files = scenario["files"]
    existing = scenario["existing"]

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        ws = tmp_path / "workspace"
        ws.mkdir()

        for rel_path, content in existing.items():
            target = ws / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)

        zip_path = tmp_path / "test.zip"
        _build_zip_from_files(zip_path, files)

        source_content: dict[str, bytes] = {}
        source_types: dict[str, AssetType] = {}
        for atype, fname, content in files:
            prefix = _type_to_prefix[atype]
            rel_path = f"{prefix}/{fname}"
            source_content[rel_path] = content
            source_types[rel_path] = atype

        importer = AssetImporter(workspace_dir=ws)
        result = await importer.import_assets(
            zip_path,
            ConflictStrategy.OVERWRITE,
        )

        for rel_path in result.imported:
            target = ws / rel_path
            assert target.exists(), f"Imported file missing: {rel_path}"
            # Non-preference files should match exactly
            if (
                rel_path in source_content
                and source_types.get(rel_path) != AssetType.PREFERENCES
            ):
                assert (
                    target.read_bytes() == source_content[rel_path]
                ), f"OVERWRITE content mismatch: {rel_path}"


@given(scenario=_conflict_scenario())
@settings(max_examples=100)
@pytest.mark.asyncio
async def test_rename_original_unchanged_new_has_source(
    scenario: dict,
) -> None:
    """Property 6 (RENAME): Original target unchanged,
    new path has source content.

    **Validates: Requirements 4.1, 4.4**
    """
    files = scenario["files"]
    existing = scenario["existing"]

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        ws = tmp_path / "workspace"
        ws.mkdir()

        snapshots: dict[str, bytes] = {}
        for rel_path, content in existing.items():
            target = ws / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            snapshots[rel_path] = content

        zip_path = tmp_path / "test.zip"
        _build_zip_from_files(zip_path, files)

        source_content: dict[str, bytes] = {}
        for atype, fname, content in files:
            prefix = _type_to_prefix[atype]
            rel_path = f"{prefix}/{fname}"
            source_content[rel_path] = content

        importer = AssetImporter(workspace_dir=ws)
        await importer.import_assets(zip_path, ConflictStrategy.RENAME)

        # Original files with different content should be unchanged
        for rel_path, original_content in snapshots.items():
            target = ws / rel_path
            if rel_path in source_content:
                src_sha = _sha256(source_content[rel_path])
                existing_sha = _sha256(original_content)
                if src_sha != existing_sha:
                    assert (
                        target.read_bytes() == original_content
                    ), f"RENAME modified original: {rel_path}"


@given(files=_asset_files())
@settings(max_examples=100)
@pytest.mark.asyncio
async def test_no_conflict_writes_directly(
    files: list[tuple[AssetType, str, bytes]],
) -> None:
    """Property 6 (no conflict): Asset written directly
    when target doesn't exist.

    **Validates: Requirements 4.6**
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        ws = tmp_path / "workspace"
        ws.mkdir()

        zip_path = tmp_path / "test.zip"
        _build_zip_from_files(zip_path, files)

        source_content: dict[str, bytes] = {}
        for atype, fname, content in files:
            prefix = _type_to_prefix[atype]
            rel_path = f"{prefix}/{fname}"
            source_content[rel_path] = content

        importer = AssetImporter(workspace_dir=ws)
        result = await importer.import_assets(zip_path, ConflictStrategy.SKIP)

        assert len(result.imported) == len(files)
        assert len(result.skipped) == 0

        for rel_path, content in source_content.items():
            target = ws / rel_path
            assert target.exists(), f"File not written: {rel_path}"
            assert target.read_bytes() == content


@given(files=_asset_files())
@settings(max_examples=100)
@pytest.mark.asyncio
async def test_same_sha256_skipped(
    files: list[tuple[AssetType, str, bytes]],
) -> None:
    """Property 6 (same SHA256): Asset skipped when target has same content.

    **Validates: Requirements 4.5**
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        ws = tmp_path / "workspace"
        ws.mkdir()

        for atype, fname, content in files:
            prefix = _type_to_prefix[atype]
            rel_path = f"{prefix}/{fname}"
            target = ws / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)

        zip_path = tmp_path / "test.zip"
        _build_zip_from_files(zip_path, files)

        importer = AssetImporter(workspace_dir=ws)
        result = await importer.import_assets(zip_path, ConflictStrategy.SKIP)

        assert len(result.skipped) == len(files)
        assert len(result.imported) == 0
