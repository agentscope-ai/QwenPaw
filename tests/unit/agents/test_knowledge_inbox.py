# -*- coding: utf-8 -*-
"""Inbox metadata, auto-replay (scheme B), and human promote/merge/reject."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from qwenpaw.agents.knowledge.dream import (
    INBOX_MAX_RETRIES,
    InboxActionError,
    InboxMeta,
    KnowledgeUnit,
    MergeCandidate,
    _node_markdown,
    _parse_frontmatter,
    _slugify,
    get_inbox_item,
    integrate_units,
    list_inbox_items,
    merge_inbox_item,
    promote_inbox_item,
    reject_inbox_item,
    replay_retryable_inbox,
    run_knowledge_dream,
)
from qwenpaw.agents.knowledge.store import ensure_kb

_INTEGRITY_OK = '{"ok": true, "lost_claims": [], "injected_unrelated": []}'


def _patch_kb_roots(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.store.WORKING_DIR", tmp_path,
    )
    root = lambda kb_id: tmp_path / "knowledge_bases" / kb_id
    monkeypatch.setattr("qwenpaw.agents.knowledge.lock.kb_root", root)
    monkeypatch.setattr("qwenpaw.agents.knowledge.dream.kb_root", root)


def fname(name: str) -> str:
    return f"{_slugify(name)}.md"


def _seed_published(root: Path, bucket: str, name: str, body: str = "original body") -> Path:
    d = root / bucket
    d.mkdir(parents=True, exist_ok=True)
    p = d / fname(name)
    p.write_text(
        "\n".join([
            "---",
            f'name: "{name}"',
            f"bucket: {bucket}",
            'updated_at: "2026-08-01T00:00:00+00:00"',
            "---",
            "",
            f"# {name}",
            "",
            body,
            "",
        ]),
        encoding="utf-8",
    )
    return p


def _seed_inbox(
    root: Path,
    *,
    name: str,
    reason: str,
    intended: str = "business/wiki",
    target: str = "",
    retry: int = 0,
    summary: str = "7天无理由",
    action: str = "REFINE",
    merge_target: str = "",
) -> Path:
    unit = KnowledgeUnit(
        name=name,
        bucket=intended,
        summary=summary,
        action_hint=action,
        merge_target=merge_target,
        confidence=0.9,
    )
    d = root / "_inbox"
    d.mkdir(parents=True, exist_ok=True)
    dest = d / fname(name)
    dest.write_text(
        _node_markdown(
            unit,
            agent_id="ba-1",
            derived_from=["memory/2026-08-12.md"],
            status="inbox",
            bucket="_inbox",
            inbox_meta=InboxMeta(
                reason=reason,
                intended_bucket=intended,
                merge_target_path=target,
                retry_count=retry,
            ),
        ),
        encoding="utf-8",
    )
    return dest


def _biz_cand(name: str, path: str, *, is_clear: bool = True) -> MergeCandidate:
    return MergeCandidate(name=name, path=path, ratio=0.95, is_clear=is_clear)


# --- metadata on inbox write -----------------------------------------------


def test_inbox_write_records_reason_intended_bucket_and_retry(
    tmp_path, monkeypatch,
):
    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb_meta")
    root = tmp_path / "knowledge_bases" / "kb_meta"
    _seed_published(root, "business/wiki", "退款政策")
    unit = KnowledgeUnit(
        name="退款政策-补", bucket="business/wiki",
        summary="7天无理由", action_hint="REFINE",
    )
    written = integrate_units(
        kb_id="kb_meta", agent_id="ba-1", units=[unit],
        derived_from=["m/t.md"],
        merge_candidates={
            "退款政策-补": _biz_cand("退款政策", "business/wiki/退款政策.md"),
        },
        merge_enabled=True,
        merge_payloads={},
    )
    assert len(written) == 1
    text = written[0].read_text(encoding="utf-8")
    fm, _body = _parse_frontmatter(text)
    assert fm["status"] == "inbox"
    assert fm["bucket"] == "_inbox"
    assert fm["intended_bucket"] == "business/wiki"
    assert fm["inbox_reason"] == "missing_payload"
    assert fm["retry_count"] == "0"
    assert "business/wiki/退款政策.md" in fm.get("merge_target_path", "")


# --- scheme B: auto-replay -------------------------------------------------


def test_replay_missing_payload_merges_and_deletes_draft(tmp_path, monkeypatch):
    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb_replay")
    root = tmp_path / "knowledge_bases" / "kb_replay"
    target = _seed_published(root, "business/wiki", "退款政策")
    inbox = _seed_inbox(
        root,
        name="退款政策-补",
        reason="missing_payload",
        target="business/wiki/退款政策.md",
        merge_target="退款政策",
    )

    async def fake_llm(prompt: str) -> str:
        if "完整性审查" in prompt or "information loss" in prompt.lower():
            return _INTEGRITY_OK
        return "# 退款政策\n\n7天无理由退换\n"

    written = asyncio.run(
        replay_retryable_inbox(
            kb_id="kb_replay",
            agent_id="ba-1",
            language="zh",
            llm_call=fake_llm,
            merge_enabled=True,
        ),
    )
    assert written
    assert written[0] == target
    assert "7天无理由" in target.read_text(encoding="utf-8")
    assert not inbox.exists()
    assert list_inbox_items("kb_replay") == []


def test_replay_skips_ambiguous_human_reason(tmp_path, monkeypatch):
    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb_amb")
    root = tmp_path / "knowledge_bases" / "kb_amb"
    _seed_published(root, "business/wiki", "退款政策")
    inbox = _seed_inbox(
        root,
        name="退款政策-补",
        reason="ambiguous_candidate",
        target="business/wiki/退款政策.md",
    )

    async def fake_llm(_prompt: str) -> str:
        raise AssertionError("ambiguous drafts must not call the merge LLM")

    written = asyncio.run(
        replay_retryable_inbox(
            kb_id="kb_amb",
            agent_id="ba-1",
            language="zh",
            llm_call=fake_llm,
            merge_enabled=True,
        ),
    )
    assert written == []
    assert inbox.is_file()
    item = get_inbox_item("kb_amb", inbox.stem)
    assert item is not None
    assert item.retryable is False
    assert item.retry_count == 0


def test_replay_caps_retry_count(tmp_path, monkeypatch):
    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb_cap")
    root = tmp_path / "knowledge_bases" / "kb_cap"
    _seed_published(root, "business/wiki", "退款政策")
    inbox = _seed_inbox(
        root,
        name="退款政策-补",
        reason="missing_payload",
        target="business/wiki/退款政策.md",
        retry=INBOX_MAX_RETRIES,
    )

    async def fake_llm(_prompt: str) -> str:
        raise AssertionError("capped drafts must not be replayed")

    written = asyncio.run(
        replay_retryable_inbox(
            kb_id="kb_cap",
            agent_id="ba-1",
            language="zh",
            llm_call=fake_llm,
            merge_enabled=True,
        ),
    )
    assert written == []
    assert inbox.is_file()
    fm, _body = _parse_frontmatter(inbox.read_text(encoding="utf-8"))
    assert fm["retry_count"] == str(INBOX_MAX_RETRIES)


def test_replay_failed_attempt_overwrites_in_place_and_bumps_retry(
    tmp_path, monkeypatch,
):
    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb_bump")
    root = tmp_path / "knowledge_bases" / "kb_bump"
    _seed_published(root, "business/wiki", "退款政策")
    inbox = _seed_inbox(
        root,
        name="退款政策-补",
        reason="missing_payload",
        target="business/wiki/退款政策.md",
        retry=0,
    )

    async def fake_llm(_prompt: str) -> str:
        return ""  # empty merge body → missing_payload again

    written = asyncio.run(
        replay_retryable_inbox(
            kb_id="kb_bump",
            agent_id="ba-1",
            language="zh",
            llm_call=fake_llm,
            merge_enabled=True,
        ),
    )
    assert len(written) == 1
    assert written[0] == inbox
    fm, _body = _parse_frontmatter(inbox.read_text(encoding="utf-8"))
    assert fm["retry_count"] == "1"
    assert fm["inbox_reason"] == "missing_payload"
    items = list_inbox_items("kb_bump")
    assert len(items) == 1
    assert items[0].stem == inbox.stem


def test_run_knowledge_dream_replays_without_new_daily(tmp_path, monkeypatch):
    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb_dream_replay")
    root = tmp_path / "knowledge_bases" / "kb_dream_replay"
    target = _seed_published(root, "business/wiki", "退款政策")
    inbox = _seed_inbox(
        root,
        name="退款政策-补",
        reason="missing_payload",
        target="business/wiki/退款政策.md",
        merge_target="退款政策",
    )
    workspace = tmp_path / "ws"
    (workspace / "memory").mkdir(parents=True)

    async def fake_llm(prompt: str) -> str:
        if "完整性审查" in prompt or "information loss" in prompt.lower():
            return _INTEGRITY_OK
        return "# 退款政策\n\n7天无理由退换\n"

    result = asyncio.run(
        run_knowledge_dream(
            agent_id="ba-1",
            workspace_dir=workspace,
            kb_id="kb_dream_replay",
            daily_dir_name="memory",
            metadata_dir="mem_metadata",
            language="zh",
            domain="business",
            scan_days=2,
            max_units=8,
            write_mode="open",
            inbox_enabled=True,
            llm_call=fake_llm,
            merge_enabled=True,
        ),
    )
    assert result["skipped"] is False
    assert result["units"] == 0
    assert not inbox.exists()
    assert "7天无理由" in target.read_text(encoding="utf-8")


def test_run_knowledge_dream_does_not_replay_same_run_inbox(
    tmp_path, monkeypatch,
):
    """A missing_payload written by this dream waits for the next run."""
    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb_same_run")
    root = tmp_path / "knowledge_bases" / "kb_same_run"
    _seed_published(root, "business/wiki", "退款政策")
    workspace = tmp_path / "ws"
    daily = workspace / "memory"
    daily.mkdir(parents=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    (daily / f"{today}.md").write_text("退款政策补充\n", encoding="utf-8")

    async def fake_llm(prompt: str) -> str:
        if "合并助手" in prompt or "merge assistant" in prompt.lower():
            return ""
        return (
            '[{"name": "退款政策-补", "bucket": "business/wiki", '
            '"summary": "7天无理由", "confidence": 0.9, '
            '"action_hint": "REFINE", "merge_target": "退款政策"}]'
        )

    async def merge_search(name: str, summary: str):
        return MergeCandidate(
            name="退款政策",
            path="business/wiki/退款政策.md",
            ratio=0.95,
            is_clear=True,
        )

    result = asyncio.run(
        run_knowledge_dream(
            agent_id="ba-1",
            workspace_dir=workspace,
            kb_id="kb_same_run",
            daily_dir_name="memory",
            metadata_dir="mem_metadata",
            language="zh",
            domain="business",
            scan_days=2,
            max_units=8,
            write_mode="open",
            inbox_enabled=True,
            llm_call=fake_llm,
            merge_search=merge_search,
            merge_enabled=True,
        ),
    )
    assert result["skipped"] is False
    inbox_files = list((root / "_inbox").glob("*.md"))
    assert len(inbox_files) == 1
    fm, _body = _parse_frontmatter(inbox_files[0].read_text(encoding="utf-8"))
    assert fm["inbox_reason"] == "missing_payload"
    assert fm["retry_count"] == "0"


# --- scheme C: promote / merge / reject ------------------------------------


def test_promote_inbox_item_publishes_and_deletes_draft(tmp_path, monkeypatch):
    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb_prom")
    root = tmp_path / "knowledge_bases" / "kb_prom"
    inbox = _seed_inbox(
        root,
        name="全新口径",
        reason="low_confidence",
        intended="business/wiki",
        summary="GMV 不含退款",
        action="CREATE",
    )
    dest = promote_inbox_item("kb_prom", inbox.stem, agent_id="reviewer")
    assert dest.parent.name == "wiki"
    text = dest.read_text(encoding="utf-8")
    assert "status: published" in text
    assert "inbox_reason:" not in text
    assert "intended_bucket:" not in text
    assert "GMV 不含退款" in text
    assert not inbox.exists()
    assert list_inbox_items("kb_prom") == []


def test_promote_inbox_item_conflicts_when_title_exists(tmp_path, monkeypatch):
    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb_prom409")
    root = tmp_path / "knowledge_bases" / "kb_prom409"
    _seed_published(root, "business/wiki", "退款政策")
    inbox = _seed_inbox(
        root,
        name="退款政策",
        reason="create_conflict",
        intended="business/wiki",
    )
    with pytest.raises(InboxActionError) as exc:
        promote_inbox_item("kb_prom409", inbox.stem, agent_id="reviewer")
    assert exc.value.status_code == 409
    assert inbox.is_file()


def test_merge_inbox_item_weaves_body_and_deletes_draft(tmp_path, monkeypatch):
    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb_merge")
    root = tmp_path / "knowledge_bases" / "kb_merge"
    target = _seed_published(
        root, "business/wiki", "退款政策", body="原口径：3天退换",
    )
    inbox = _seed_inbox(
        root,
        name="退款政策-补",
        reason="semantic_dup",
        target="business/wiki/退款政策.md",
        summary="改为7天无理由",
        action="REFINE",
        merge_target="退款政策",
    )
    dest = merge_inbox_item(
        "kb_merge", inbox.stem, agent_id="reviewer",
    )
    assert dest == target
    text = target.read_text(encoding="utf-8")
    assert "改为7天无理由" in text
    assert not inbox.exists()


def test_merge_inbox_item_at_cap_keeps_draft(tmp_path, monkeypatch):
    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb_merge_cap")
    root = tmp_path / "knowledge_bases" / "kb_merge_cap"
    d = root / "business" / "wiki"
    d.mkdir(parents=True, exist_ok=True)
    target = d / fname("退款政策")
    target.write_text(
        "\n".join([
            "---",
            'name: "退款政策"',
            "bucket: business/wiki",
            "merge_count: 5",
            'updated_at: "2026-08-01T00:00:00+00:00"',
            "---",
            "",
            "# 退款政策",
            "",
            "original body",
            "",
        ]),
        encoding="utf-8",
    )
    inbox = _seed_inbox(
        root,
        name="退款政策-补",
        reason="at_cap",
        target="business/wiki/退款政策.md",
        summary="新边界",
    )
    with pytest.raises(InboxActionError) as exc:
        merge_inbox_item(
            "kb_merge_cap", inbox.stem, agent_id="reviewer",
            merge_max_updates=5,
        )
    assert exc.value.status_code == 409
    assert inbox.is_file()


def test_reject_inbox_item_moves_to_rejected(tmp_path, monkeypatch):
    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb_rej")
    root = tmp_path / "knowledge_bases" / "kb_rej"
    inbox = _seed_inbox(
        root,
        name="噪声草稿",
        reason="low_confidence",
        summary="闲聊",
    )
    dest = reject_inbox_item("kb_rej", inbox.stem)
    assert dest.parent.name == "_rejected"
    assert dest.is_file()
    assert not inbox.exists()
    assert list_inbox_items("kb_rej") == []
    assert get_inbox_item("kb_rej", inbox.stem) is None


def test_resolve_inbox_rejects_path_traversal(tmp_path, monkeypatch):
    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb_trav")
    root = tmp_path / "knowledge_bases" / "kb_trav"
    _seed_published(root, "business/wiki", "退款政策")
    assert get_inbox_item("kb_trav", "../business/wiki/退款政策") is None
    assert get_inbox_item("kb_trav", "_rejected/foo") is None


# --- REST API --------------------------------------------------------------


@pytest.fixture
def kb_client() -> TestClient:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from qwenpaw.app.routers.knowledge_bases import router as kb_router

    application = FastAPI()
    application.include_router(kb_router, prefix="/api")
    return TestClient(application)


def test_inbox_api_list_get_promote(kb_client, tmp_path, monkeypatch):
    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb_api_inbox")
    root = tmp_path / "knowledge_bases" / "kb_api_inbox"
    inbox = _seed_inbox(
        root,
        name="全新口径",
        reason="low_confidence",
        summary="GMV 不含退款",
        action="CREATE",
    )
    listed = kb_client.get("/api/knowledge-bases/kb_api_inbox/inbox")
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert len(items) == 1
    assert items[0]["inbox_reason"] == "low_confidence"
    assert items[0]["retryable"] is False

    detail = kb_client.get(
        f"/api/knowledge-bases/kb_api_inbox/inbox/{inbox.stem}",
    )
    assert detail.status_code == 200
    assert "GMV 不含退款" in detail.json()["body"]

    promoted = kb_client.post(
        f"/api/knowledge-bases/kb_api_inbox/inbox/{inbox.stem}/promote",
    )
    assert promoted.status_code == 200
    assert not inbox.exists()
    empty = kb_client.get("/api/knowledge-bases/kb_api_inbox/inbox")
    assert empty.json()["items"] == []


def test_inbox_api_merge_and_reject(kb_client, tmp_path, monkeypatch):
    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb_api_mr")
    root = tmp_path / "knowledge_bases" / "kb_api_mr"
    _seed_published(root, "business/wiki", "退款政策", body="原口径")
    merge_draft = _seed_inbox(
        root,
        name="退款政策-补",
        reason="semantic_dup",
        target="business/wiki/退款政策.md",
        summary="改为7天",
        merge_target="退款政策",
    )
    merged = kb_client.post(
        f"/api/knowledge-bases/kb_api_mr/inbox/{merge_draft.stem}/merge",
        json={"mode": "REFINE"},
    )
    assert merged.status_code == 200
    assert not merge_draft.exists()

    noise = _seed_inbox(
        root, name="噪声草稿", reason="low_confidence", summary="闲聊",
    )
    rejected = kb_client.post(
        f"/api/knowledge-bases/kb_api_mr/inbox/{noise.stem}/reject",
    )
    assert rejected.status_code == 200
    assert "_rejected" in rejected.json()["path"].replace("\\", "/")
    missing = kb_client.get(
        f"/api/knowledge-bases/kb_api_mr/inbox/{noise.stem}",
    )
    assert missing.status_code == 404


def test_inbox_api_promote_conflict_is_409(kb_client, tmp_path, monkeypatch):
    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb_api_409")
    root = tmp_path / "knowledge_bases" / "kb_api_409"
    _seed_published(root, "business/wiki", "退款政策")
    inbox = _seed_inbox(
        root, name="退款政策", reason="create_conflict",
    )
    response = kb_client.post(
        f"/api/knowledge-bases/kb_api_409/inbox/{inbox.stem}/promote",
    )
    assert response.status_code == 409
    assert inbox.is_file()
