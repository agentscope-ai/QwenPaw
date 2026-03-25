# -*- coding: utf-8 -*-

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from copaw.app.routers import agents_pipeline as pipeline_router_module
from copaw.app.routers.agents_pipeline_core import _pipeline_md_path


class _FakeAgentWorkspace:
    def __init__(self, workspace_dir: str):
        self.workspace_dir = workspace_dir


class _FakeManager:
    def __init__(self, workspace_dir: str):
        self._workspace = _FakeAgentWorkspace(workspace_dir)

    async def get_agent(self, _agent_id: str):
        return self._workspace


@pytest.fixture
def pipeline_router_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    manager = _FakeManager(str(tmp_path))
    monkeypatch.setattr(
        pipeline_router_module.agents_router_impl,
        "_get_multi_agent_manager",
        lambda _request: manager,
    )

    app = FastAPI()
    app.include_router(pipeline_router_module.router)
    return TestClient(app)


def _sample_payload(template_id: str = "router-pipeline") -> dict:
    return {
        "id": template_id,
        "name": "Router Pipeline",
        "version": "0.1.0",
        "description": "router-level test",
        "steps": [
            {
                "id": "step-1",
                "name": "Collect",
                "kind": "ingest",
                "description": "collect",
            }
        ],
    }


def test_put_pipeline_template_returns_conflict_on_expected_revision_mismatch(
    pipeline_router_client: TestClient,
):
    payload = _sample_payload()
    first = pipeline_router_client.put(
        "/agents/default/pipelines/templates/router-pipeline",
        json=payload,
    )
    assert first.status_code == 200

    conflict = pipeline_router_client.put(
        "/agents/default/pipelines/templates/router-pipeline?expectedRevision=999",
        json=payload,
    )
    assert conflict.status_code == 409
    detail = conflict.json().get("detail", {})
    assert detail.get("code") == "pipeline_revision_conflict"


def test_stream_save_pipeline_emits_validation_failed_event(
    pipeline_router_client: TestClient,
    tmp_path: Path,
):
    payload = _sample_payload("stream-pipeline")
    created = pipeline_router_client.put(
        "/agents/default/pipelines/templates/stream-pipeline",
        json=payload,
    )
    assert created.status_code == 200

    md_path = _pipeline_md_path(tmp_path, "stream-pipeline")
    md_path.write_text(
        "---\n"
        "pipeline_id: stream-pipeline\n"
        "name: Broken\n"
        "version: 0.1.0\n"
        "---\n\n"
        "# Broken\n\n"
        "No valid step headings.\n",
        encoding="utf-8",
    )

    stream_resp = pipeline_router_client.post(
        "/agents/default/pipelines/templates/stream-pipeline/save/stream?expectedRevision=1",
        json=payload,
    )
    assert stream_resp.status_code == 200
    assert "text/event-stream" in stream_resp.headers.get("content-type", "")
    body = stream_resp.text
    assert "validation_failed" in body
    assert "pipeline_md_validation_failed" in body