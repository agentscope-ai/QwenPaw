# -*- coding: utf-8 -*-
"""个人资料库的轻量本地检索索引。"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass


INDEX_VERSION = 1
MAX_INDEXED_CHARACTERS = 2_000_000
MAX_KEYWORDS = 512


@dataclass(frozen=True, slots=True)
class PersonalLibrarySearchIndex:
    version: int
    document_id: str
    sha256: str
    content: str
    keywords: tuple[str, ...]

    def to_json_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["keywords"] = list(self.keywords)
        return payload

    @classmethod
    def from_json_dict(cls, payload: dict[str, object]) -> "PersonalLibrarySearchIndex":
        return cls(
            version=int(payload["version"]),
            document_id=str(payload["document_id"]),
            sha256=str(payload["sha256"]),
            content=str(payload.get("content", "")),
            keywords=tuple(str(item) for item in payload.get("keywords", [])),
        )


def build_search_index(
    *,
    document_id: str,
    sha256: str,
    filename: str,
    content: str,
) -> PersonalLibrarySearchIndex:
    """构建无需外部服务、可按资料文件独立更新的关键词索引。"""
    indexed_content = content[:MAX_INDEXED_CHARACTERS]
    searchable = unicodedata.normalize(
        "NFKC", f"{filename}\n{indexed_content}"
    ).casefold()
    weights: Counter[str] = Counter()
    weights.update(re.findall(r"[a-z0-9][a-z0-9_-]{1,63}", searchable))
    for run in re.findall(r"[\u4e00-\u9fff]{2,}", searchable):
        # 中文没有稳定的空格边界，以 2~4 字片段形成可模糊召回的本地倒排词。
        for width in (2, 3, 4):
            weights.update(
                run[index : index + width]
                for index in range(max(0, len(run) - width + 1))
            )
    keywords = tuple(
        token
        for token, _ in sorted(
            weights.items(),
            key=lambda item: (-item[1], -len(item[0]), item[0]),
        )[:MAX_KEYWORDS]
    )
    return PersonalLibrarySearchIndex(
        version=INDEX_VERSION,
        document_id=document_id,
        sha256=sha256,
        content=indexed_content,
        keywords=keywords,
    )
