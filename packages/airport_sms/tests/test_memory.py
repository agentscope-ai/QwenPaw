"""记忆检索行为。使用 FakeEmbedder，不访问网络。"""

from __future__ import annotations

import statistics
import time

from airport_sms.context.manual_index import DEFAULT_MANUALS_DIR, ManualIndex
from airport_sms.domain import CaseId, new_draft
from airport_sms.memory.embedder import FakeEmbedder
from airport_sms.memory.retrieve import Retriever
from airport_sms.memory.store import MemoryDoc, MemoryStore, SourceType
from airport_sms.session.store import open_db


def _store(embedder: FakeEmbedder | None = None) -> tuple[MemoryStore, FakeEmbedder]:
    """内存库加假嵌入器。"""
    fake = embedder or FakeEmbedder()
    return MemoryStore(open_db(), fake), fake


def _manual(org: str, clause_id: str, text: str) -> MemoryDoc:
    """手册文档。"""
    return MemoryDoc(
        doc_id=f"{org}:{clause_id}",
        org_id=org,
        source_type=SourceType.MANUAL,
        source_id=clause_id,
        text=text,
    )


def test_cite_writes_clause_ids_on_case() -> None:
    """引用片段会把条款 id 写到案件副本。"""
    store, embedder = _store()
    store.index(_manual("org-a", "SMS-1.1", "report hazard with location"))
    retriever = Retriever(store, embedder)
    case = new_draft(case_id=CaseId("C-1"), hazard="FOD", location="TWY A")
    result = retriever.retrieve("org-a", "hazard location")
    cited = retriever.cite(case, result.snippets)
    assert "SMS-1.1" in cited.cited_clauses
    assert cited.version == case.version + 1


def test_index_sample_manual_count_nonzero() -> None:
    """示例手册入索引后条数非零。"""
    store, _embedder = _store()
    index = ManualIndex(DEFAULT_MANUALS_DIR)
    clauses = index.load_file("sample.md")
    for cid, text in clauses.items():
        store.index(_manual("org-a", cid, text))
    assert store.count("org-a") > 0


def test_query_known_hazard_phrase_hits_clause() -> None:
    """已知隐患短语应打中对应条款。"""
    store, embedder = _store()
    store.index(_manual("org-a", "SMS-1.1", "report hazard with location and evidence"))
    store.index(_manual("org-a", "SMS-2.3", "ALARP residual risk without new CAPA"))
    store.index(_manual("org-a", "SMS-4.1", "only safety office may close a case"))
    retriever = Retriever(store, embedder)
    result = retriever.retrieve("org-a", "hazard location evidence", k=3)
    ids = [item.source_id for item in result.snippets]
    assert "SMS-1.1" in ids[:3]


def test_auto_retrieve_leaves_case_unchanged() -> None:
    """自动检索不改案件版本。"""
    store, embedder = _store()
    store.index(_manual("org-a", "SMS-1.1", "hazard reporting"))
    case = new_draft(case_id=CaseId("C-1"), hazard="FOD", location="TWY A")
    before = case.version
    Retriever(store, embedder).retrieve("org-a", "hazard")
    assert case.version == before
    assert case.cited_clauses == ()


def test_empty_corpus_returns_empty_list() -> None:
    """空语料返回空列表。"""
    store, embedder = _store()
    result = Retriever(store, embedder).retrieve("org-a", "anything")
    assert result.snippets == ()


def test_org_isolation_hides_other_org_docs() -> None:
    """其他组织文档不会出现。"""
    store, embedder = _store()
    store.index(_manual("org-a", "SMS-1.1", "org a secret clause"))
    store.index(_manual("org-b", "SMS-9.9", "org b other clause"))
    result = Retriever(store, embedder).retrieve("org-a", "clause")
    ids = {item.source_id for item in result.snippets}
    assert "SMS-9.9" not in ids
    assert all(item.doc_id.startswith("org-a:") for item in result.snippets)


def test_fake_embedder_used_without_network() -> None:
    """测试路径只走 FakeEmbedder。"""
    embedder = FakeEmbedder()
    store = MemoryStore(open_db(), embedder)
    store.index(_manual("org-a", "SMS-1.1", "hazard"))
    Retriever(store, embedder).retrieve("org-a", "hazard")
    assert embedder.calls >= 2
    assert not hasattr(embedder, "base_url")


def test_retrieve_logs_latency() -> None:
    """检索结果带延迟字段。"""
    store, embedder = _store()
    store.index(_manual("org-a", "SMS-1.1", "hazard"))
    result = Retriever(store, embedder).retrieve("org-a", "hazard")
    assert result.latency_ms >= 0
    assert result.snippets


def test_delete_document_removes_vectors() -> None:
    """删除后查询不再命中。"""
    store, embedder = _store()
    store.index(_manual("org-a", "SMS-1.1", "unique fod taxiway phrase"))
    store.delete("org-a", "org-a:SMS-1.1")
    result = Retriever(store, embedder).retrieve("org-a", "unique fod taxiway phrase")
    assert result.snippets == ()
    assert store.count("org-a") == 0


def test_closed_case_memory_is_derived() -> None:
    """结案记忆标记为 derived，来源类型 closed_case。"""
    store, embedder = _store()
    store.index(
        MemoryDoc(
            doc_id="org-a:closed-1",
            org_id="org-a",
            source_type=SourceType.CLOSED_CASE,
            source_id="C-closed",
            text="closed FOD taxiway case with CAPA",
        )
    )
    result = Retriever(store, embedder).retrieve("org-a", "FOD taxiway CAPA")
    assert result.snippets
    hit = result.snippets[0]
    assert hit.source_type is SourceType.CLOSED_CASE
    assert hit.derived is True


def test_retrieve_p95_under_300ms() -> None:
    """50 次检索 p95 低于 300ms。"""
    store, embedder = _store()
    index = ManualIndex(DEFAULT_MANUALS_DIR)
    for cid, text in index.load_file("sample.md").items():
        store.index(_manual("org-a", cid, text))
    retriever = Retriever(store, embedder)
    samples: list[float] = []
    for _ in range(50):
        start = time.perf_counter()
        retriever.retrieve("org-a", "hazard reporting ALARP")
        samples.append((time.perf_counter() - start) * 1000)
    p95 = statistics.quantiles(samples, n=20)[-1]
    assert p95 < 300, f"p95 {p95:.1f}ms"
