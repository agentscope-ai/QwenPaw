# -*- coding: utf-8 -*-

import io
import json
from pathlib import Path
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from copaw.app.routers import knowledge as knowledge_router_module
from copaw.config.config import Config
from copaw.knowledge import GraphOpsManager, KnowledgeManager


@pytest.fixture
def knowledge_api_client(tmp_path: Path, monkeypatch) -> TestClient:
    config = Config()
    state = {"config": config}

    def fake_load_config():
        return state["config"]

    def fake_save_config(new_config):
        state["config"] = new_config

    monkeypatch.setattr(knowledge_router_module, "load_config", fake_load_config)
    monkeypatch.setattr(knowledge_router_module, "save_config", fake_save_config)
    monkeypatch.setattr(knowledge_router_module, "WORKING_DIR", tmp_path)

    app = FastAPI()
    app.include_router(knowledge_router_module.router)
    return TestClient(app)


def test_upsert_source_auto_generates_summary_when_empty(
    knowledge_api_client: TestClient,
):
    response = knowledge_api_client.put(
        "/knowledge/sources",
        json={
            "id": "text-auto-summary",
            "name": "Manual Name",
            "type": "text",
            "content": "Quarterly planning checklist and milestone review for the release train.",
            "enabled": True,
            "recursive": False,
            "tags": [],
            "summary": "",
        },
    )

    assert response.status_code == 200
    generated = response.json()["summary"]
    assert generated


def test_upsert_source_auto_summary_includes_keywords(
    knowledge_api_client: TestClient,
):
    response = knowledge_api_client.put(
        "/knowledge/sources",
        json={
            "id": "text-auto-keywords",
            "name": "Manual Name",
            "type": "text",
            "content": (
                "支付系统 风控规则 更新。"
                "支付系统 对账流程 优化。"
                "支付系统 异常告警 升级。"
                "风控规则 每日巡检。"
            ),
            "enabled": True,
            "recursive": False,
            "tags": [],
            "summary": "",
        },
    )

    assert response.status_code == 200
    generated = response.json()["summary"]
    assert "关键词:" in generated


def test_upsert_source_subject_prefers_summary_over_content(
    knowledge_api_client: TestClient,
):
    response = knowledge_api_client.put(
        "/knowledge/sources",
        json={
            "id": "text-subject-from-summary",
            "name": "Manual Name",
            "type": "text",
            "content": "Very long internal content that should not be the direct subject source.",
            "enabled": True,
            "recursive": False,
            "tags": [],
            "summary": "Release checklist summary for sprint handoff",
        },
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Release checklist summary for sprint handoff"


def test_list_sources_uses_auto_generated_subjects_for_existing_config(
    knowledge_api_client: TestClient,
):
    put_response = knowledge_api_client.put(
        "/knowledge/sources",
        json={
            "id": "url-auto-subject",
            "name": "Old URL Name",
            "type": "url",
            "location": "https://example.com/path/to/guide.html",
            "enabled": True,
            "recursive": False,
            "tags": ["remote"],
            "summary": "",
        },
    )
    assert put_response.status_code == 200

    listing = knowledge_api_client.get("/knowledge/sources")
    assert listing.status_code == 200
    source = listing.json()["sources"][0]
    assert source["name"] == "example.com/guide.html"


def test_list_sources_returns_structured_summary_keywords(
    knowledge_api_client: TestClient,
):
    put_response = knowledge_api_client.put(
        "/knowledge/sources",
        json={
            "id": "text-structured-fields",
            "name": "Manual Name",
            "type": "text",
            "content": (
                "支付系统 风控规则 更新。"
                "支付系统 对账流程 优化。"
                "支付系统 异常告警 升级。"
            ),
            "enabled": True,
            "recursive": False,
            "tags": [],
            "summary": "",
        },
    )
    assert put_response.status_code == 200

    listing = knowledge_api_client.get("/knowledge/sources")
    assert listing.status_code == 200
    source = listing.json()["sources"][0]
    assert isinstance(source.get("subject"), str)
    assert isinstance(source.get("summary"), str)
    assert isinstance(source.get("keywords"), list)


def test_history_backfill_status_includes_progress(
    knowledge_api_client: TestClient,
):
    response = knowledge_api_client.get("/knowledge/history-backfill/status")
    assert response.status_code == 200
    payload = response.json()
    assert "progress" in payload
    assert isinstance(payload["progress"], dict)
    assert "running" in payload["progress"]


def test_history_backfill_progress_ws_snapshot(
    knowledge_api_client: TestClient,
):
    with knowledge_api_client.websocket_connect(
        "/knowledge/history-backfill/progress/ws?interval_ms=300",
    ) as ws:
        payload = ws.receive_json()

    assert payload["type"] == "snapshot"
    assert isinstance(payload["progress"], dict)
    assert "running" in payload["progress"]


def test_clear_knowledge_requires_confirmation(knowledge_api_client: TestClient):
    response = knowledge_api_client.delete("/knowledge/clear")
    assert response.status_code == 400
    assert response.json()["detail"] == "KNOWLEDGE_CLEAR_CONFIRM_REQUIRED"


def test_clear_knowledge_removes_sources_and_indexes(
    knowledge_api_client: TestClient,
    tmp_path: Path,
):
    config_payload = Config().knowledge.model_dump(mode="json")
    config_payload["enabled"] = True
    config_payload["sources"] = [
        {
            "id": "clear-1",
            "name": "to-clear",
            "type": "text",
            "location": "",
            "content": "clear me",
            "enabled": True,
            "recursive": False,
            "tags": [],
            "summary": "",
        }
    ]
    saved = knowledge_api_client.put("/knowledge/config", json=config_payload)
    assert saved.status_code == 200

    source_root = tmp_path / "knowledge" / "sources" / "clear-1"
    source_root.mkdir(parents=True, exist_ok=True)
    (source_root / "index.json").write_text("{}", encoding="utf-8")

    response = knowledge_api_client.delete(
        "/knowledge/clear?confirm=true&remove_sources=true"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["cleared"] is True
    assert payload["removed_source_configs"] is True
    assert payload["cleared_sources"] == 1
    assert payload["cleared_indexes"] >= 1


def test_read_url_document_skips_binary_content(monkeypatch):
    class _Resp:
        headers = {"content-type": "image/png"}
        text = "binary"

        @staticmethod
        def raise_for_status():
            return None

    monkeypatch.setattr("copaw.knowledge.manager.httpx.get", lambda *args, **kwargs: _Resp())

    doc = KnowledgeManager._read_url_document("https://example.com/a.png")

    assert doc["path"] == "https://example.com/a.png"
    assert doc["text"] == ""


def test_get_memify_job_status_requires_memify_enabled(
    knowledge_api_client: TestClient,
):
    config_payload = Config().knowledge.model_dump(mode="json")
    config_payload["enabled"] = True
    config_payload["memify_enabled"] = False
    saved = knowledge_api_client.put("/knowledge/config", json=config_payload)
    assert saved.status_code == 200

    response = knowledge_api_client.get("/knowledge/memify/jobs/job-1")
    assert response.status_code == 400
    assert response.json()["detail"] == "MEMIFY_DISABLED"


def test_get_memify_job_status_success(
    knowledge_api_client: TestClient,
    tmp_path: Path,
):
    knowledge_config = Config().knowledge
    config_payload = knowledge_config.model_dump(mode="json")
    config_payload["enabled"] = True
    config_payload["memify_enabled"] = True
    saved = knowledge_api_client.put("/knowledge/config", json=config_payload)
    assert saved.status_code == 200

    knowledge_config.enabled = True
    knowledge_config.memify_enabled = True

    graph_ops = GraphOpsManager(tmp_path)
    job = graph_ops.run_memify(
        config=knowledge_config,
        pipeline_type="default",
        dataset_scope=[],
        idempotency_key="route-status-job",
        dry_run=False,
    )
    job_id = job["job_id"]

    response = knowledge_api_client.get(f"/knowledge/memify/jobs/{job_id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["job_id"] == job_id
    assert payload["status"] in {"succeeded", "failed"}


def test_put_knowledge_config_syncs_running_toggle_and_module_skill(
    knowledge_api_client: TestClient,
    monkeypatch,
):
    sync_calls: list[bool] = []
    monkeypatch.setattr(
        knowledge_router_module,
        "sync_knowledge_module_skills",
        lambda enabled: sync_calls.append(enabled),
    )

    config_payload = Config().knowledge.model_dump(mode="json")
    config_payload["enabled"] = False

    response = knowledge_api_client.put("/knowledge/config", json=config_payload)

    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert sync_calls == [False]


def test_put_knowledge_config_does_not_resync_module_skill_when_toggle_unchanged(
    knowledge_api_client: TestClient,
    monkeypatch,
):
    sync_calls: list[bool] = []
    monkeypatch.setattr(
        knowledge_router_module,
        "sync_knowledge_module_skills",
        lambda enabled: sync_calls.append(enabled),
    )

    config_payload = Config().knowledge.model_dump(mode="json")
    config_payload["enabled"] = True

    response = knowledge_api_client.put("/knowledge/config", json=config_payload)

    assert response.status_code == 200
    assert response.json()["enabled"] is True
    assert sync_calls == []


def _build_knowledge_zip(entries: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path, content in entries.items():
            zf.writestr(path, content)
    return buf.getvalue()


def _source_index_payload(source_id: str, content: str = "knowledge text") -> str:
    payload = {
        "source": {
            "id": source_id,
            "name": source_id,
            "type": "text",
            "location": "",
            "content": content,
            "enabled": True,
            "recursive": False,
            "tags": [],
            "summary": "",
        },
        "documents": [
            {
                "path": f"{source_id}.md",
                "title": source_id,
                "text": content,
            }
        ],
        "chunks": [],
    }
    return json.dumps(payload, ensure_ascii=False)


def test_restore_knowledge_backup_replace_existing(
    knowledge_api_client: TestClient,
    tmp_path: Path,
):
    old_source_dir = tmp_path / "knowledge" / "sources" / "old-source"
    old_source_dir.mkdir(parents=True, exist_ok=True)
    (old_source_dir / "index.json").write_text(
        _source_index_payload("old-source", "old content"),
        encoding="utf-8",
    )

    zip_data = _build_knowledge_zip(
        {
            "sources/new-source/index.json": _source_index_payload(
                "new-source",
                "new content",
            ),
            "sources/new-source/content.md": "# new-source\n\nnew content\n",
            "catalog.json": json.dumps({"version": 2}),
        }
    )

    response = knowledge_api_client.post(
        "/knowledge/restore",
        files={"file": ("knowledge.zip", zip_data, "application/zip")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["replace_existing"] is True
    assert payload["restored_sources"] == 1
    assert not old_source_dir.exists()
    assert (tmp_path / "knowledge" / "sources" / "new-source" / "index.json").exists()

    listing = knowledge_api_client.get("/knowledge/sources")
    assert listing.status_code == 200
    ids = {item["id"] for item in listing.json()["sources"]}
    assert ids == {"new-source"}


def test_restore_knowledge_backup_merge_existing(
    knowledge_api_client: TestClient,
    tmp_path: Path,
):
    existing_source_dir = tmp_path / "knowledge" / "sources" / "local-source"
    existing_source_dir.mkdir(parents=True, exist_ok=True)
    (existing_source_dir / "index.json").write_text(
        _source_index_payload("local-source", "local content"),
        encoding="utf-8",
    )

    zip_data = _build_knowledge_zip(
        {
            "sources/imported-source/index.json": _source_index_payload(
                "imported-source",
                "imported content",
            ),
            "sources/imported-source/content.md": "# imported-source\n\nimported content\n",
        }
    )

    response = knowledge_api_client.post(
        "/knowledge/restore?replace_existing=false",
        files={"file": ("knowledge.zip", zip_data, "application/zip")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["replace_existing"] is False
    assert payload["restored_sources"] == 2
    assert (tmp_path / "knowledge" / "sources" / "local-source" / "index.json").exists()
    assert (
        tmp_path / "knowledge" / "sources" / "imported-source" / "index.json"
    ).exists()

    listing = knowledge_api_client.get("/knowledge/sources")
    assert listing.status_code == 200
    ids = {item["id"] for item in listing.json()["sources"]}
    assert ids == {"local-source", "imported-source"}


def test_restore_knowledge_backup_rejects_unsafe_zip_path(
    knowledge_api_client: TestClient,
):
    zip_data = _build_knowledge_zip(
        {
            "../escape/index.json": _source_index_payload("escape"),
        }
    )

    response = knowledge_api_client.post(
        "/knowledge/restore",
        files={"file": ("knowledge.zip", zip_data, "application/zip")},
    )

    assert response.status_code == 400
    assert "unsafe path" in response.json()["detail"]
