# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from qwenpaw.access.agent_repository import agent_database_id
from qwenpaw.personal_library.service import PersonalLibraryService
from tests.unit.personal_library.test_service import InMemoryRepository


def _docx_bytes(*paragraphs: str) -> bytes:
    """构造只包含正文段落的最小 DOCX，避免测试依赖 Office 软件。"""
    body = "".join(
        "<w:p><w:r><w:t>" + paragraph + "</w:t></w:r></w:p>"
        for paragraph in paragraphs
    )
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", document_xml)
    return buffer.getvalue()


class GrantRepository(InMemoryRepository):
    def __init__(self) -> None:
        super().__init__()
        self.grants = {}

    async def list_grants(self, *, owner_user_id):
        return [grant for (owner, _), grant in self.grants.items() if owner == owner_user_id]

    async def set_grant(self, *, owner_user_id, agent_id, enabled):
        previous = self.grants.get((owner_user_id, agent_id))
        if not enabled and previous is None:
            return None
        now = datetime.now(UTC)
        grant = SimpleNamespace(owner_user_id=owner_user_id, agent_id=agent_id, status="active" if enabled else "revoked", created_at=previous.created_at if previous else now, updated_at=now, revoked_at=None if enabled else now)
        self.grants[(owner_user_id, agent_id)] = grant
        return grant

    async def has_active_grant(self, *, owner_user_id, agent_id):
        grant = self.grants.get((owner_user_id, agent_id))
        return grant is not None and grant.status == "active"


@pytest.mark.asyncio
async def test_search_and_read_use_current_agent_library_without_grant(tmp_path: Path) -> None:
    owner_id = uuid4()
    repository = GrantRepository()
    service = PersonalLibraryService(repository=repository, working_dir=tmp_path)
    document = await service.create_text(owner_user_id=owner_id, relative_path="notes/key.md", content="unique keyword")
    hits = await service.search_text(owner_user_id=owner_id, agent_key="default", query="keyword")
    assert [hit.document.id for hit in hits] == [document.id]
    loaded = await service.read_text_for_agent(owner_user_id=owner_id, agent_key="default", document_id=document.id)
    assert loaded.content == "unique keyword"


@pytest.mark.asyncio
async def test_search_matches_filename_and_never_returns_another_users_document(
    tmp_path: Path,
) -> None:
    """同一 Agent 的资料检索仍必须以实际对话用户隔离。"""
    owner_id, other_id = uuid4(), uuid4()
    repository = GrantRepository()
    service = PersonalLibraryService(repository=repository, working_dir=tmp_path)
    owner_document = await service.create_text(
        owner_user_id=owner_id,
        relative_path="AI写作需求文档.md",
        content="正文不包含文件名。",
    )
    await service.create_text(
        owner_user_id=other_id,
        relative_path="AI写作需求文档.md",
        content="另一个用户的私有正文。",
    )
    agent_id = agent_database_id("default")
    await repository.set_grant(owner_user_id=owner_id, agent_id=agent_id, enabled=True)
    await repository.set_grant(owner_user_id=other_id, agent_id=agent_id, enabled=True)

    owner_hits = await service.search_text(
        owner_user_id=owner_id,
        agent_key="default",
        query="ai写作需求文档",
    )
    other_hits = await service.search_text(
        owner_user_id=other_id,
        agent_key="default",
        query="ai写作需求文档",
    )

    assert [hit.document.id for hit in owner_hits] == [owner_document.id]
    assert owner_hits[0].excerpt == "[按文件名匹配]"
    assert owner_document.id not in [hit.document.id for hit in other_hits]


@pytest.mark.asyncio
async def test_search_matches_multiple_terms_across_filename_and_content(
    tmp_path: Path,
) -> None:
    owner_id = uuid4()
    repository = GrantRepository()
    service = PersonalLibraryService(repository=repository, working_dir=tmp_path)
    document = await service.create_text(
        owner_user_id=owner_id,
        relative_path="AI写作需求文档.md",
        content="教学闭环：启发灵感、构思提纲、写作与分析批改。",
    )
    await repository.set_grant(
        owner_user_id=owner_id,
        agent_id=agent_database_id("default"),
        enabled=True,
    )

    hits = await service.search_text(
        owner_user_id=owner_id,
        agent_key="default",
        query="AI写作需求文档 教学闭环",
    )

    assert [hit.document.id for hit in hits] == [document.id]
    assert "教学闭环" in hits[0].excerpt


@pytest.mark.asyncio
async def test_search_and_read_docx_in_current_agent_library(tmp_path: Path) -> None:
    owner_id = uuid4()
    repository = GrantRepository()
    service = PersonalLibraryService(repository=repository, working_dir=tmp_path)
    document = await service.save_upload(
        owner_user_id=owner_id,
        agent_key="qa-agent",
        filename="威盾防水-W8硅橡胶外墙防水装饰一体化系统说明文档.docx",
        content=_docx_bytes(
            "W8硅橡胶外墙防水装饰一体化系统",
            "采用硅橡胶技术，兼具防水、装饰和防护功能。",
        ),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    hits = await service.search_text(
        owner_user_id=owner_id,
        agent_key="qa-agent",
        query="威盾防水 W8 外墙装饰一体化系统",
    )
    loaded = await service.read_text_for_agent(
        owner_user_id=owner_id,
        agent_key="qa-agent",
        document_id=document.id,
    )

    assert [hit.document.id for hit in hits] == [document.id]
    assert hits[0].excerpt == "[按文件名匹配]"
    assert "W8硅橡胶外墙防水装饰一体化系统" in loaded.content
    assert "防水、装饰和防护" in loaded.content
