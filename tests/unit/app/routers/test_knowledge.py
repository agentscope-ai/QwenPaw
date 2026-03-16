# -*- coding: utf-8 -*-

from pathlib import Path

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


def test_upsert_source_auto_generates_description_when_empty(
    knowledge_api_client: TestClient,
):
    response = knowledge_api_client.put(
        "/knowledge/sources",
        json={
            "id": "text-auto-description",
            "name": "Manual Name",
            "type": "text",
            "content": "Quarterly planning checklist and milestone review for the release train.",
            "enabled": True,
            "recursive": False,
            "tags": [],
            "description": "",
        },
    )

    assert response.status_code == 200
    generated = response.json()["description"]
    assert generated


def test_upsert_source_title_prefers_description_over_content(
    knowledge_api_client: TestClient,
):
    response = knowledge_api_client.put(
        "/knowledge/sources",
        json={
            "id": "text-title-from-description",
            "name": "Manual Name",
            "type": "text",
            "content": "Very long internal content that should not be the direct title source.",
            "enabled": True,
            "recursive": False,
            "tags": [],
            "description": "Release checklist summary for sprint handoff",
        },
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Release checklist summary for sprint handoff"


def test_list_sources_uses_auto_generated_titles_for_existing_config(
    knowledge_api_client: TestClient,
):
    put_response = knowledge_api_client.put(
        "/knowledge/sources",
        json={
            "id": "url-auto-title",
            "name": "Old URL Name",
            "type": "url",
            "location": "https://example.com/path/to/guide.html",
            "enabled": True,
            "recursive": False,
            "tags": ["remote"],
            "description": "",
        },
    )
    assert put_response.status_code == 200

    listing = knowledge_api_client.get("/knowledge/sources")
    assert listing.status_code == 200
    source = listing.json()["sources"][0]
    assert source["name"] == "example.com/guide.html"


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
            "description": "",
        }
    ]
    saved = knowledge_api_client.put("/knowledge/config", json=config_payload)
    assert saved.status_code == 200

    index_root = tmp_path / "knowledge" / "indexes"
    index_root.mkdir(parents=True, exist_ok=True)
    (index_root / "clear-1.json").write_text("{}", encoding="utf-8")

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
