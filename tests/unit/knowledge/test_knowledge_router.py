# -*- coding: utf-8 -*-
"""Unit tests for knowledge router search endpoint."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from copaw.app.routers import knowledge as knowledge_router


class _FakeWorkspace:
    def __init__(
        self,
        workspace_dir: Path,
        *,
        channel_manager=None,
    ):
        self.workspace_dir = workspace_dir
        self.channel_manager = channel_manager


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _seed_workspace(workspace_dir: Path) -> None:
    _write_json(
        workspace_dir / "knowledge/state/index.json",
        {
            "version": 1,
            "updated_at": "2026-03-28T00:00:00Z",
            "documents": {
                "einstein-doc": {
                    "doc_id": "einstein-doc",
                    "title": "Einstein Facts",
                    "source_file": "einstein.md",
                    "source_type": "md",
                    "imported_at": "2026-03-28T10:00:00Z",
                    "paths": {
                        "chunks": "knowledge/chunks/einstein-doc.json",
                    },
                },
            },
            "source_hash_to_doc_id": {},
            "content_hash_to_doc_id": {},
        },
    )
    _write_json(
        workspace_dir / "knowledge/chunks/einstein-doc.json",
        {
            "doc_id": "einstein-doc",
            "chunk_count": 1,
            "chunks": [
                {
                    "chunk_id": "chunk-0000",
                    "index": 0,
                    "text": "Albert Einstein was born in 1879 in Ulm.",
                    "char_count": 41,
                },
            ],
        },
    )


def test_search_endpoint_returns_hits(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _seed_workspace(tmp_path)

    async def _fake_get_agent_for_request(_request):
        return _FakeWorkspace(tmp_path)

    monkeypatch.setattr(
        knowledge_router,
        "get_agent_for_request",
        _fake_get_agent_for_request,
    )

    app = FastAPI()
    app.include_router(knowledge_router.router)
    client = TestClient(app)

    response = client.post(
        "/knowledge/search",
        json={
            "query": "Einstein 1879",
            "max_results": 5,
            "min_score": 0.1,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == "Einstein 1879"
    assert payload["total"] >= 1
    first = payload["hits"][0]
    assert first["doc_id"] == "einstein-doc"
    assert "einstein" in first["chunk_text"].lower()


def test_search_endpoint_validates_query(
    tmp_path: Path,
    monkeypatch,
) -> None:
    async def _fake_get_agent_for_request(_request):
        return _FakeWorkspace(tmp_path)

    monkeypatch.setattr(
        knowledge_router,
        "get_agent_for_request",
        _fake_get_agent_for_request,
    )

    app = FastAPI()
    app.include_router(knowledge_router.router)
    client = TestClient(app)

    response = client.post(
        "/knowledge/search",
        json={
            "query": "",
            "max_results": 5,
            "min_score": 0.1,
        },
    )

    assert response.status_code == 422


def test_import_endpoint_returns_503_when_console_channel_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    async def _fake_get_agent_for_request(_request):
        return _FakeWorkspace(tmp_path, channel_manager=None)

    monkeypatch.setattr(
        knowledge_router,
        "get_agent_for_request",
        _fake_get_agent_for_request,
    )

    app = FastAPI()
    app.include_router(knowledge_router.router)
    client = TestClient(app)

    response = client.post(
        "/knowledge/import",
        json={
            "uploads": [],
            "mode": "current_message",
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Channel Console not found"
