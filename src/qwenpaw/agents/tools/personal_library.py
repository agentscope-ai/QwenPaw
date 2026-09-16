# -*- coding: utf-8 -*-
"""只读个人资料库工具；身份和 Agent 均由运行时闭包固定。"""

from __future__ import annotations

from uuid import UUID

from ...personal_library.service import PersonalLibraryService


def build_personal_library_tools(*, service: PersonalLibraryService, owner_user_id: UUID, agent_key: str):
    """创建仅搜索、读取的工具，绝不向模型暴露用户或 Agent 参数。"""

    async def personal_library_search(query: str, max_results: int = 5) -> list[dict[str, object]]:
        """只读搜索已授权的个人资料库，正文和文件名均可匹配；先搜索再按 ID 分页读取，不能修改资料。"""
        hits = await service.search_text(owner_user_id=owner_user_id, agent_key=agent_key, query=query, max_results=max_results)
        return [{"document_id": str(hit.document.id), "relative_path": hit.document.relative_path, "excerpt": hit.excerpt, "score": hit.score} for hit in hits]

    async def personal_library_read(document_id: str, offset: int = 0, limit: int = 65_536) -> dict[str, object]:
        """只读分页读取个人资料库文本；授权会在每一次调用时重新检查。"""
        content = await service.read_text_for_agent(owner_user_id=owner_user_id, agent_key=agent_key, document_id=UUID(document_id), offset=offset, limit=limit)
        return {"document_id": str(content.document.id), "relative_path": content.document.relative_path, "content": content.content, "offset": content.offset, "next_offset": content.next_offset, "truncated": content.truncated}

    return [personal_library_search, personal_library_read]
