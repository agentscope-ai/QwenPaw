# -*- coding: utf-8 -*-
"""公共与私有 ReMe 搜索结果的安全合并。"""

import pytest

from qwenpaw.memory_scope.models import MemoryScope
from qwenpaw.agents.memory.scoped_memory_pool import merge_memory_search_results


@pytest.mark.asyncio
async def test_merge_labels_scope_and_deduplicates_same_source_location() -> None:
    async def public_search(query, limit):
        assert query == "project"
        assert limit == 5
        return [
            {"path": "daily/public.md", "line": 3, "text": "shared", "score": 0.8},
            {"path": "daily/public.md", "line": 3, "text": "shared", "score": 0.7},
        ]

    async def private_search(query, limit):
        return [{"path": "daily/private.md", "line": 4, "text": "secret", "score": 0.9}]

    result = await merge_memory_search_results(
        public_search=public_search,
        private_search=private_search,
        query="project",
        max_results=5,
    )

    assert [item.scope for item in result] == [
        MemoryScope.PRIVATE,
        MemoryScope.PUBLIC,
    ]
    assert [item.text for item in result] == ["secret", "shared"]
    assert result[0].scope_label == "my_memory"
    assert result[1].scope_label == "public_memory"


@pytest.mark.asyncio
async def test_one_scope_failure_does_not_hide_other_scope() -> None:
    async def public_search(query, limit):
        raise RuntimeError("public index unavailable")

    async def private_search(query, limit):
        return [{"path": "private.md", "line": 1, "text": "only me", "score": 1.0}]

    result = await merge_memory_search_results(
        public_search=public_search,
        private_search=private_search,
        query="only",
        max_results=3,
    )

    assert len(result) == 1
    assert result[0].scope is MemoryScope.PRIVATE
    assert result.public_error == "public index unavailable"


@pytest.mark.asyncio
async def test_same_root_location_is_preserved_once_per_scope() -> None:
    """两个独立 workspace 中同名 MEMORY.md 不能被跨作用域去重。"""

    async def public_search(query, limit):
        return [
            {"path": "MEMORY.md", "line": 1, "text": "same", "score": 0.8},
        ]

    async def private_search(query, limit):
        return [
            {"path": "MEMORY.md", "line": 1, "text": "same", "score": 0.9},
        ]

    result = await merge_memory_search_results(
        public_search=public_search,
        private_search=private_search,
        query="same",
        max_results=5,
    )

    assert [item.scope for item in result] == [
        MemoryScope.PRIVATE,
        MemoryScope.PUBLIC,
    ]
