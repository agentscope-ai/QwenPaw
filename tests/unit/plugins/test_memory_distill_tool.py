# -*- coding: utf-8 -*-
import importlib.util
from pathlib import Path

import pytest


MODULE_PATH = (
    Path(__file__).resolve().parents[3]
    / "plugins"
    / "tool"
    / "memory-distill"
    / "memory_distill_tool.py"
)
SPEC = importlib.util.spec_from_file_location(
    "memory_distill_tool",
    MODULE_PATH,
)
assert SPEC is not None and SPEC.loader is not None
memory_distill_tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(memory_distill_tool)


@pytest.mark.asyncio
async def test_distill_memory_rejects_non_workspace_dir(tmp_path):
    result = await memory_distill_tool.distill_memory(
        working_dir=str(tmp_path),
        days=7,
        dry_run=True,
    )
    block = result.content[0]
    text = block["text"] if isinstance(block, dict) else block.text
    assert "agent workspace" in text


@pytest.mark.asyncio
async def test_distill_memory_detects_new_titles_when_known_topics_exist(
    tmp_path,
):
    (tmp_path / "memory").mkdir()
    (tmp_path / "MEMORY.md").write_text(
        "# MEMORY\n\n- **Known Topic**: existing note\n",
        encoding="utf-8",
    )
    (tmp_path / "memory" / "2026-06-03.md").write_text(
        "# Daily\n\n## New Discovery\nFresh content here.\n\n"
        "## Known Topic\nShould be skipped.\n",
        encoding="utf-8",
    )

    result = await memory_distill_tool.distill_memory(
        working_dir=str(tmp_path),
        days=30,
        dry_run=True,
    )
    block = result.content[0]
    text = block["text"] if isinstance(block, dict) else block.text
    assert "New Discovery" in text
    assert "Known Topic" not in text


@pytest.mark.asyncio
async def test_consolidate_memory_does_not_delete_workspace_png(tmp_path):
    (tmp_path / "memory").mkdir()
    (tmp_path / "MEMORY.md").write_text("# MEMORY\n", encoding="utf-8")
    (tmp_path / "tool_results").mkdir()
    png = tmp_path / "keep.png"
    png.write_bytes(b"png")

    await memory_distill_tool.consolidate_memory(
        working_dir=str(tmp_path),
        days=30,
        dry_run=False,
    )

    assert png.exists()
