# -*- coding: utf-8 -*-
"""资料索引必须可重建、可观察，并继续遵守用户和智能体边界。"""

from uuid import uuid4

import pytest

from qwenpaw.personal_library.service import PersonalLibraryService
from tests.unit.personal_library.test_service import InMemoryRepository


@pytest.mark.asyncio
async def test_index_reuse_update_delete_and_scope(tmp_path, monkeypatch):
    owner, stranger = uuid4(), uuid4()
    service = PersonalLibraryService(
        repository=InMemoryRepository(), working_dir=tmp_path
    )
    doc = await service.create_text(
        owner_user_id=owner, relative_path="旅行.md", content="北海道冬季滑雪"
    )
    status = await service.index_status(owner_user_id=owner, agent_key="default")
    assert status[0]["status"] == "ready"
    assert status[0]["document_id"] == str(doc.id)
    assert await service.index_status(owner_user_id=stranger, agent_key="default") == []
    assert await service.index_status(owner_user_id=owner, agent_key="other") == []

    def no_parse(_path):
        raise AssertionError("未变更文件不能重复解析")

    with monkeypatch.context() as patch:
        patch.setattr(
            "qwenpaw.personal_library.service.extract_searchable_text", no_parse
        )
        hits = await service.search_text(
            owner_user_id=owner, agent_key="default", query="滑雪"
        )
        assert [hit.document.id for hit in hits] == [doc.id]
    await service.create_text(
        owner_user_id=owner,
        relative_path="旅行.md",
        content="云南雨林徒步",
        overwrite=True,
    )
    assert not await service.search_text(
        owner_user_id=owner, agent_key="default", query="滑雪"
    )
    assert await service.search_text(
        owner_user_id=owner, agent_key="default", query="雨林"
    )
    await service.delete(owner_user_id=owner, document_id=doc.id)
    assert not await service.index_status(owner_user_id=owner, agent_key="default")


@pytest.mark.asyncio
async def test_failed_extraction_is_visible_and_not_retried_until_rebuild(
    tmp_path, monkeypatch
):
    owner = uuid4()
    calls = []

    def parser(path):
        calls.append(path)
        raise ValueError("private server path must not appear in status")

    monkeypatch.setattr(
        "qwenpaw.personal_library.service.extract_searchable_text", parser
    )
    service = PersonalLibraryService(
        repository=InMemoryRepository(), working_dir=tmp_path
    )
    await service.save_upload(
        owner_user_id=owner,
        filename="broken.pdf",
        content=b"broken",
        media_type="application/pdf",
    )
    for _ in range(2):
        assert not await service.search_text(
            owner_user_id=owner, agent_key="default", query="unrelated"
        )
    assert len(calls) == 1
    status = await service.index_status(owner_user_id=owner, agent_key="default")
    assert status[0]["status"] == "failed"
    assert "private server" not in str(status)
    monkeypatch.setattr(
        "qwenpaw.personal_library.service.extract_searchable_text",
        lambda _: "repair keyword",
    )
    status = await service.rebuild_index(owner_user_id=owner, agent_key="default")
    assert status[0]["status"] == "ready"
    assert await service.search_text(
        owner_user_id=owner, agent_key="default", query="keyword"
    )


@pytest.mark.asyncio
async def test_missing_file_not_returned_by_filename_and_status_is_visible(tmp_path):
    owner = uuid4()
    service = PersonalLibraryService(
        repository=InMemoryRepository(), working_dir=tmp_path
    )
    doc = await service.create_text(
        owner_user_id=owner, relative_path="missing.md", content="example"
    )
    _, path, _ = await service.resolve_download(owner_user_id=owner, document_id=doc.id)
    path.unlink()
    assert not await service.search_text(
        owner_user_id=owner, agent_key="default", query="missing"
    )
    assert (await service.index_status(owner_user_id=owner, agent_key="default"))[0][
        "status"
    ] == "missing"


@pytest.mark.asyncio
async def test_empty_unsupported_and_oversized_files_remain_available(
    tmp_path, monkeypatch
):
    owner = uuid4()
    service = PersonalLibraryService(
        repository=InMemoryRepository(), working_dir=tmp_path
    )
    await service.create_text(
        owner_user_id=owner, relative_path="empty.md", content=" "
    )
    await service.save_upload(
        owner_user_id=owner,
        filename="image.png",
        content=b"png",
        media_type="image/png",
    )
    monkeypatch.setattr("qwenpaw.personal_library.service.MAX_INDEX_FILE_BYTES", 4)
    await service.create_text(
        owner_user_id=owner, relative_path="large.txt", content="too large"
    )
    statuses = {
        item["status"]
        for item in await service.index_status(owner_user_id=owner, agent_key="default")
    }
    assert statuses == {"empty", "unsupported", "too_large"}


@pytest.mark.asyncio
async def test_only_candidates_load_cached_body(tmp_path, monkeypatch):
    from qwenpaw.personal_library.derived_index import LibraryIndexStore

    owner = uuid4()
    service = PersonalLibraryService(
        repository=InMemoryRepository(), working_dir=tmp_path
    )
    expected = await service.create_text(
        owner_user_id=owner, relative_path="notes.md", content="北海道旅行"
    )
    await service.create_text(
        owner_user_id=owner, relative_path="other.md", content="量子计算学习"
    )
    original = LibraryIndexStore.load
    loaded = []

    def counted(self, document_id):
        loaded.append(document_id)
        return original(self, document_id)

    monkeypatch.setattr(LibraryIndexStore, "load", counted)
    hits = await service.search_text(
        owner_user_id=owner, agent_key="default", query="北海道"
    )
    assert [hit.document.id for hit in hits] == [expected.id]
    assert loaded == [str(expected.id)]


@pytest.mark.asyncio
async def test_corrupt_derived_database_can_be_rebuilt_without_touching_original(
    tmp_path,
):
    from qwenpaw.access.agent_repository import agent_database_id
    from qwenpaw.personal_library.derived_index import LibraryIndexStore

    owner = uuid4()
    service = PersonalLibraryService(
        repository=InMemoryRepository(), working_dir=tmp_path
    )
    doc = await service.create_text(
        owner_user_id=owner, relative_path="notes.md", content="故障恢复资料"
    )
    store = LibraryIndexStore(tmp_path, owner, agent_database_id("default"))
    store.path.write_bytes(b"broken sqlite")
    assert (await service.index_status(owner_user_id=owner, agent_key="default"))[0][
        "status"
    ] == "unavailable"
    with pytest.raises(ValueError, match="索引暂不可用"):
        await service.search_text(
            owner_user_id=owner, agent_key="default", query="故障恢复"
        )
    assert (
        await service.match_prompt_documents(
            owner_user_id=owner, agent_key="default", text="介绍故障恢复资料"
        )
        == []
    )
    result = await service.rebuild_index(owner_user_id=owner, agent_key="default")
    assert result[0]["status"] == "ready"
    assert (
        await service.read_text(owner_user_id=owner, document_id=doc.id)
    ).content == "故障恢复资料"
    assert len(list(store.path.parent.glob("search.broken-*.sqlite3"))) == 1


@pytest.mark.asyncio
async def test_old_documents_build_once_and_external_file_change_invalidates(
    tmp_path, monkeypatch
):
    from qwenpaw.access.agent_repository import agent_database_id
    from qwenpaw.personal_library.derived_index import LibraryIndexStore

    owner = uuid4()
    service = PersonalLibraryService(
        repository=InMemoryRepository(), working_dir=tmp_path
    )
    doc = await service.create_text(
        owner_user_id=owner, relative_path="notes.md", content="老版本文档"
    )
    store = LibraryIndexStore(tmp_path, owner, agent_database_id("default"))
    store.delete(str(doc.id))
    assert (await service.index_status(owner_user_id=owner, agent_key="default"))[0][
        "status"
    ] == "pending"
    assert await service.search_text(
        owner_user_id=owner, agent_key="default", query="老版本"
    )
    _, path, _ = await service.resolve_download(owner_user_id=owner, document_id=doc.id)
    path.write_text("外部工具更新后的北海道旅行计划", encoding="utf-8")
    assert (await service.index_status(owner_user_id=owner, agent_key="default"))[0][
        "status"
    ] == "pending"
    assert not await service.search_text(
        owner_user_id=owner, agent_key="default", query="老版本"
    )
    assert await service.search_text(
        owner_user_id=owner, agent_key="default", query="北海道"
    )


@pytest.mark.asyncio
async def test_fullwidth_tokens_and_fuzzy_chinese_candidates(tmp_path):
    owner = uuid4()
    service = PersonalLibraryService(
        repository=InMemoryRepository(), working_dir=tmp_path
    )
    doc = await service.create_text(
        owner_user_id=owner,
        relative_path="guide.md",
        content="Ｗ８外墙防水装饰一体化系统",
    )
    hits = await service.search_text(
        owner_user_id=owner, agent_key="default", query="w8外墙装饰一体化系统"
    )
    assert [hit.document.id for hit in hits] == [doc.id]


@pytest.mark.asyncio
async def test_partial_index_and_user_filename_cannot_overwrite_index(
    tmp_path, monkeypatch
):
    from qwenpaw.access.agent_repository import agent_database_id
    from qwenpaw.personal_library.derived_index import LibraryIndexStore
    from qwenpaw.personal_library.paths import PersonalLibraryPathDenied

    owner = uuid4()
    service = PersonalLibraryService(
        repository=InMemoryRepository(), working_dir=tmp_path
    )
    monkeypatch.setattr("qwenpaw.personal_library.service.MAX_INDEXED_CHARACTERS", 5)
    monkeypatch.setattr(
        "qwenpaw.personal_library.search_index.MAX_INDEXED_CHARACTERS", 5
    )
    with pytest.raises(PersonalLibraryPathDenied, match="invalid_library_path"):
        await service.create_text(
            owner_user_id=owner,
            relative_path=".qwenpaw-index/search.sqlite3",
            content="must not enter reserved directory",
        )
    doc = await service.create_text(
        owner_user_id=owner,
        relative_path="search.sqlite3",
        content="keep original document",
    )
    await service.create_text(
        owner_user_id=owner, relative_path="long.md", content="before after"
    )
    states = await service.index_status(owner_user_id=owner, agent_key="default")
    partial = next(row for row in states if row["status"] == "partial")
    assert partial["indexed_characters"] == 5
    assert not await service.search_text(
        owner_user_id=owner, agent_key="default", query="after"
    )
    store = LibraryIndexStore(tmp_path, owner, agent_database_id("default"))
    assert str(doc.id) in store.metadata()
    assert (await service.resolve_download(owner_user_id=owner, document_id=doc.id))[
        1
    ] != store.path
