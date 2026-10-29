"""记忆检索行为。使用 FakeEmbedder，不访问网络。"""

from __future__ import annotations

import socket
import statistics

import pytest

from airport_sms.context.manual_index import DEFAULT_MANUALS_DIR, ManualIndex
from airport_sms.domain import CaseId, Role, new_draft
from airport_sms.memory.embedder import FakeEmbedder, Qwen3Embedder
from airport_sms.memory.retrieve import MemoryScope, Retriever
from airport_sms.memory.store import MemoryStore
from airport_sms.session.case_repo import CaseRepo
from airport_sms.session.principal import Principal
from airport_sms.session.store import open_db


def _store(embedder: FakeEmbedder | None = None) -> tuple[MemoryStore, FakeEmbedder]:
    """内存库加假嵌入器。"""
    fake = embedder or FakeEmbedder()
    return MemoryStore(open_db(), fake), fake


def _reporter() -> Principal:
    """默认报告人。"""
    return Principal("u1", "org-a", Role.REPORTER, "site-1")


def test_cite_writes_clause_ids_on_proposal() -> None:
    """引用片段把条款 id 写到提案，不改案件行。"""
    conn = open_db()
    fake = FakeEmbedder()
    store = MemoryStore(conn, fake)
    repo = CaseRepo(conn)
    principal = _reporter()
    case = repo.save_new(
        principal,
        new_draft(case_id=CaseId("C-1"), hazard="FOD", location="TWY A"),
    )
    store.index_manual("org-a", "SMS-1.1", "report hazard with location")
    retriever = Retriever(store)
    result = retriever.retrieve("org-a", "hazard location")
    proposal = retriever.cite(result.snippets)
    assert "SMS-1.1" in proposal.cited_source_ids
    loaded = repo.get(principal, case.id)
    assert loaded.version == case.version
    assert loaded.cited_clauses == ()


def test_index_sample_manual_count_nonzero() -> None:
    """示例手册入索引后条数非零。"""
    store, _embedder = _store()
    clauses = ManualIndex(DEFAULT_MANUALS_DIR).load_file("sample.md")
    assert store.index_manuals("org-a", clauses) > 0
    assert store.count("org-a") > 0


def test_query_known_hazard_phrase_hits_clause() -> None:
    """已知隐患短语应打中对应条款。"""
    store, _embedder = _store()
    store.index_manual("org-a", "SMS-1.1", "report hazard with location and evidence")
    store.index_manual("org-a", "SMS-2.3", "ALARP residual risk without new CAPA")
    store.index_manual("org-a", "SMS-4.1", "only safety office may close a case")
    result = Retriever(store).retrieve("org-a", "hazard location evidence", k=3)
    ids = [item.source_id for item in result.snippets]
    assert "SMS-1.1" in ids[:3]


def test_auto_retrieve_leaves_case_unchanged() -> None:
    """自动检索不改案件版本与引用。"""
    conn = open_db()
    store = MemoryStore(conn, FakeEmbedder())
    repo = CaseRepo(conn)
    principal = _reporter()
    case = repo.save_new(
        principal,
        new_draft(case_id=CaseId("C-1"), hazard="FOD", location="TWY A"),
    )
    store.index_manual("org-a", "SMS-1.1", "hazard reporting")
    Retriever(store).retrieve("org-a", "hazard")
    loaded = repo.get(principal, case.id)
    assert loaded.version == case.version
    assert loaded.cited_clauses == ()


def test_empty_corpus_returns_empty_list() -> None:
    """空语料返回空列表。"""
    store, _embedder = _store()
    result = Retriever(store).retrieve("org-a", "anything")
    assert result.snippets == ()
    assert result.scope is MemoryScope.LONG_TERM


def test_org_isolation_hides_other_org_docs() -> None:
    """其他组织文档不会出现。"""
    store, _embedder = _store()
    store.index_manual("org-a", "SMS-1.1", "org a secret clause")
    store.index_manual("org-b", "SMS-9.9", "org b other clause")
    result = Retriever(store).retrieve("org-a", "clause")
    ids = {item.source_id for item in result.snippets}
    assert "SMS-9.9" not in ids
    assert {item.org_id for item in result.snippets} <= {"org-a"}


def test_fake_embedder_used_without_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """测试路径只走 FakeEmbedder，不建套接字。"""
    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network")

    monkeypatch.setattr(socket, "socket", boom)
    embedder = FakeEmbedder()
    store = MemoryStore(open_db(), embedder)
    store.index_manual("org-a", "SMS-1.1", "hazard")
    Retriever(store).retrieve("org-a", "hazard")
    assert embedder.calls >= 2
    assert embedder.model_id == "fake"
    assert Qwen3Embedder.model_id == "qwen3-embed"


def test_retrieve_logs_latency() -> None:
    """检索结果带延迟字段。"""
    store, _embedder = _store()
    store.index_manual("org-a", "SMS-1.1", "hazard")
    result = Retriever(store).retrieve("org-a", "hazard")
    assert result.latency_ms >= 0
    assert result.snippets


def test_delete_document_removes_vectors() -> None:
    """删除后查询不再命中。"""
    store, _embedder = _store()
    doc = store.index_manual("org-a", "SMS-1.1", "unique fod taxiway phrase")
    store.delete("org-a", doc.doc_id)
    result = Retriever(store).retrieve("org-a", "unique fod taxiway phrase")
    assert result.snippets == ()
    assert store.count("org-a") == 0


def test_closed_case_memory_is_derived() -> None:
    """结案记忆标记为 derived，来源类型 closed_case。"""
    store, _embedder = _store()
    store.index_closed_case(
        "org-a",
        "C-closed",
        "closed FOD taxiway case with CAPA",
    )
    result = Retriever(store).retrieve("org-a", "FOD taxiway CAPA")
    assert result.snippets
    hit = result.snippets[0]
    assert hit.source_type.value == "closed_case"
    assert hit.derived is True
    assert hit.source_id == "C-closed"


def test_retrieve_p95_under_300ms() -> None:
    """50 次检索 p95 低于 300ms。"""
    store, _embedder = _store()
    clauses = ManualIndex(DEFAULT_MANUALS_DIR).load_file("sample.md")
    store.index_manuals("org-a", clauses)
    retriever = Retriever(store)
    samples: list[float] = []
    for _ in range(50):
        result = retriever.retrieve("org-a", "hazard reporting ALARP")
        assert result.snippets
        samples.append(result.latency_ms)
    p95 = statistics.quantiles(samples, n=20)[-1]
    assert p95 < 300, f"p95 {p95:.1f}ms"


def test_index_replace_keeps_single_row() -> None:
    """重复索引同一文档不复制行。"""
    store, _embedder = _store()
    store.index_manual("org-a", "SMS-1.1", "first")
    store.index_manual("org-a", "SMS-1.1", "second")
    assert store.count("org-a") == 1
    loaded = store.load("org-a")
    assert loaded[0][0].text == "second"
