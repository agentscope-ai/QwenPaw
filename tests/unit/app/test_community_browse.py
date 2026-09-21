# -*- coding: utf-8 -*-
"""Platform filters, error isolation and publishing category contracts."""

from importlib import import_module
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from qwenpaw.app.community_connection import CommunityConnectionError

module = import_module("qwenpaw.app.routers.community")


@pytest.mark.asyncio
@pytest.mark.parametrize("sort", ["latest", "recommended"])
@pytest.mark.parametrize(
    "kind",
    [
        "all",
        "question",
        "work_share",
        "app_case",
        "beginner_tutorial",
        "discussion",
        "official_announcement",
    ],
)
async def test_platform_browse_filters(monkeypatch, sort, kind):
    service = SimpleNamespace(
        community_request=AsyncMock(return_value={"items": [], "total": 0}),
    )
    monkeypatch.setattr(module, "get_service", lambda _: service)
    app = FastAPI()
    app.include_router(module.router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://localhost",
    ) as client:
        response = await client.get(
            "/community/posts",
            params={
                "sort": sort,
                "post_type": kind,
                "page": 2,
                "keyword": "demo",
            },
        )
    assert response.status_code == 200
    assert service.community_request.call_args.kwargs["params"] == {
        "sort": sort,
        "type": kind,
        "page": 2,
        "page_size": 20,
        "keyword": "demo",
    }


@pytest.mark.asyncio
async def test_platform_unauthorized_does_not_log_out_local_console(
    monkeypatch,
):
    service = SimpleNamespace(
        community_request=AsyncMock(
            side_effect=CommunityConnectionError("authorization_expired", 401),
        ),
    )
    monkeypatch.setattr(module, "get_service", lambda _: service)
    app = FastAPI()
    app.include_router(module.router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://localhost",
    ) as client:
        response = await client.post(
            "/community/posts/post/comments",
            json={"content": "Draft", "account_id": "alice"},
        )
    assert response.status_code == 409
    assert response.json() == {"detail": "authorization_expired"}


@pytest.mark.parametrize(
    "kind",
    ["question", "work_share", "app_case", "beginner_tutorial", "discussion"],
)
def test_editor_accepts_platform_post_categories(kind):
    assert (
        module.CommunityPostRequest(
            title="Title",
            content="Body",
            account_id="alice",
            article_type=kind,
        ).article_type
        == kind
    )
