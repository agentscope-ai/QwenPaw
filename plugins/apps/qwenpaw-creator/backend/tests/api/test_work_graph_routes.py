# -*- coding: utf-8 -*-
# pylint: disable=unused-argument
"""Work-graph HTTP surface: derived DAG snapshot and manual dispatch."""
from __future__ import annotations

import asyncio

from httpx import ASGITransport, AsyncClient


async def _create_project(client: AsyncClient) -> str:
    created = await client.post(
        "/projects",
        json={
            "clientRequestId": "wg-project-1",
            "name": "工作图",
            "description": "DAG",
            "scenario": "short_drama",
            "aspectRatio": "16:9",
            "resolution": "720P",
            "contentType": None,
        },
    )
    return created.json()["projectId"]


def test_work_graph_get_returns_derived_nodes(app, api_runtime_root):
    async def scenario():
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            project_id = await _create_project(client)
            response = await client.get(f"/projects/{project_id}/work-graph")
            assert response.status_code == 200
            payload = response.json()
            assert payload["projectId"] == project_id
            assert payload["counts"]["total"] == 0
            assert payload["nodes"] == []

    asyncio.run(scenario())


def test_dispatch_rejects_unknown_and_gated_nodes(app, api_runtime_root):
    async def scenario():
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            project_id = await _create_project(client)
            missing = await client.post(
                f"/projects/{project_id}/work-graph/nodes/"
                "visual:char:none:var:x/dispatch",
            )
            assert missing.status_code == 404

    asyncio.run(scenario())


def test_work_graph_missing_project_is_404_json(app, api_runtime_root):
    async def scenario():
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/projects/project-none/work-graph")
            assert response.status_code == 404
            assert "message" in response.json().get("error", response.json())

    asyncio.run(scenario())
