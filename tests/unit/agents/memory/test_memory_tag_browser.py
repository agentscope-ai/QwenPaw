# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access
"""Tag browsing enumerates complete files through the existing ReMe index."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from reme.components.tag_index import LocalTagIndex
from reme.components.file_chunker.markdown_file_chunker import (
    MarkdownFileChunker,
)
from reme.schema import FileFrontMatter, FileNode

from qwenpaw.agents.memory.reme_tags import list_tag_files


@pytest.mark.parametrize(
    "case",
    json.loads(
        (
            Path(__file__).parents[3] / "fixtures/memory_tags_contract.json"
        ).read_text(encoding="utf-8"),
    ),
    ids=lambda case: case["name"],
)
def test_preview_tags_match_reme_frontmatter_contract(case):
    """The Console and real ReMe consume the same cross-language fixtures."""
    frontmatter, _, _ = MarkdownFileChunker._parse_front_matter(
        f"---\n{case['frontmatter']}\n---\nBody",
    )
    index = LocalTagIndex()
    assert (
        index.normalize_tags(
            (frontmatter.model_extra or {}).get("memory_tags"),
        )
        == case["canonical"]
    )
    assert index.normalize_query_tags(case["display"]) == case["canonical"]


@pytest.fixture
async def indexed_runtime():
    """Include an unlinked daily file and a file outside the digest graph."""
    nodes = [
        FileNode(
            path=path,
            st_mtime=mtime,
            front_matter=FileFrontMatter(
                name=path,
                description="Indexed description",
                memory_tags=tags,
            ),
        )
        for path, mtime, tags in [
            ("memory/unlinked.md", 10, ["赵六", "Orion"]),
            ("resources/orion.md", 30, ["赵六", "Orion"]),
            ("digest/wiki/a.md", 20, ["赵六"]),
            ("digest/wiki/other.md", 40, ["Other"]),
        ]
    ]
    index = LocalTagIndex()
    await index.rebuild(nodes)
    store = SimpleNamespace(
        require_tag_index=lambda: index,
        get_nodes=AsyncMock(
            side_effect=lambda paths=None: [
                node for node in nodes if paths is None or node.path in paths
            ],
        ),
    )
    return (
        SimpleNamespace(
            context=SimpleNamespace(
                components={"file_store": {"default": store}},
            ),
            config=SimpleNamespace(daily_dir="memory", digest_dir="digest"),
        ),
        index,
        store,
    )


@pytest.mark.asyncio
async def test_browser_enumerates_all_tagged_files_before_paginating(
    indexed_runtime,
):
    runtime, _, store = indexed_runtime
    first = await list_tag_files(runtime, tag="赵六", page_size=2)
    second = await list_tag_files(runtime, tag="赵六", page=2, page_size=2)

    assert first["total_files"] == second["total_files"] == 3
    assert [item["path"] for item in first["items"]] == [
        "resources/orion.md",
        "digest/wiki/a.md",
    ]
    assert second["items"][0]["path"] == "memory/unlinked.md"
    assert second["items"][0]["source"] == "daily"
    assert second["items"][0]["relative_path"] == "unlinked.md"
    assert first["items"][0]["source"] == "workspace"
    assert first["items"][0]["memory_tags"] == ["赵六", "orion"]
    assert first["items"][0]["description"] == "Indexed description"
    assert set(store.get_nodes.await_args.args[0]) == {
        "memory/unlinked.md",
        "resources/orion.md",
        "digest/wiki/a.md",
    }


@pytest.mark.asyncio
async def test_browser_normalizes_lookup_and_does_not_read_all_files_on_miss(
    indexed_runtime,
):
    runtime, _, store = indexed_runtime
    found = await list_tag_files(runtime, tag=" ORION ")
    assert found["tag"] == "orion"
    assert found["total_files"] == 2

    store.get_nodes.reset_mock()
    missing = await list_tag_files(runtime, tag="missing")
    assert missing["total_files"] == 0
    assert missing["items"] == []
    store.get_nodes.assert_not_awaited()


@pytest.mark.asyncio
async def test_browser_reports_unavailable_index_instead_of_an_empty_result(
    indexed_runtime,
):
    runtime, index, store = indexed_runtime
    index.set_healthy(False)
    with pytest.raises(RuntimeError, match="unavailable"):
        await list_tag_files(runtime, tag="赵六")
    store.get_nodes.assert_not_awaited()


@pytest.mark.asyncio
async def test_browser_rejects_invalid_tag(indexed_runtime):
    runtime, _, _ = indexed_runtime
    with pytest.raises(ValueError, match="valid memory tag"):
        await list_tag_files(runtime, tag="  !!!  ")


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["ß" * 33, "ﬃ" * 64])
async def test_browser_accepts_source_and_expanded_canonical_tags(
    indexed_runtime,
    source,
):
    runtime, index, store = indexed_runtime
    node = FileNode(
        path="memory/unicode.md",
        st_mtime=1,
        front_matter=FileFrontMatter(memory_tags=[source]),
    )
    await index.rebuild([node])
    store.get_nodes.side_effect = lambda paths=None: (
        [node] if paths is None or node.path in paths else []
    )
    listed = await index.list_tags()
    canonical = listed["items"][0][0]
    assert len(canonical) > index.max_tag_length
    for tag in [source, canonical]:
        result = await list_tag_files(runtime, tag=tag)
        assert result["tag"] == canonical
        assert result["total_files"] == 1
        assert result["items"][0]["path"] == node.path

    missing = await list_tag_files(runtime, tag="x" * 65)
    assert missing["items"] == []
    with pytest.raises(ValueError, match="valid memory tag"):
        await list_tag_files(runtime, tag="x" * 193)
