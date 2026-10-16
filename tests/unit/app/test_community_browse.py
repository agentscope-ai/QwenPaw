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


@pytest.mark.asyncio
async def test_answers_and_interactions_forward_platform_contract(monkeypatch):
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
            "/community/posts/post/comments?kind=answer&page=2",
        )
        assert response.status_code == 200
        assert service.community_request.call_args.kwargs == {
            "params": {"page": 2, "page_size": 20, "kind": "answer"},
            "personalized": True,
        }
        response = await client.post(
            "/community/posts/post/comments",
            json={"content": "Solution", "kind": "answer", "account_id": "a"},
        )
        assert response.status_code == 200
        assert service.community_request.call_args.kwargs["json"] == {
            "content": "Solution",
            "kind": "answer",
            "parent_id": None,
        }
        for action in ("like", "favorite"):
            response = await client.post(
                f"/community/posts/post/interactions/{action}",
                json={"account_id": "a"},
            )
            assert response.status_code == 200
            service.community_request.assert_awaited_with(
                "POST",
                f"/api/v1/community/articles/post/{action}",
                account_id="a",
            )
        response = await client.post(
            "/community/comments/comment/like",
            json={"account_id": "a"},
        )
        assert response.status_code == 200
        service.community_request.assert_awaited_with(
            "POST",
            "/api/v1/community/comments/comment/like",
            account_id="a",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["discussion", "question"])
async def test_draft_save_and_publish_reuse_native_identity(monkeypatch, kind):
    post = {
        "id": "draft-1",
        "author_user_id": "alice",
        "status": "draft",
        "article_type": kind,
        "body_text": "Original",
        "tags": ["qwenpaw"],
        "media_ids": ["existing-image"],
    }
    service = SimpleNamespace(
        status=AsyncMock(return_value={"account": {"id": "alice"}}),
        community_request=AsyncMock(side_effect=[post, {"id": "draft-1"}]),
    )
    monkeypatch.setattr(module, "get_service", lambda _: service)
    body = {
        "account_id": "alice",
        "draft_id": "draft-1",
        "title": "Title",
        "content": "Revised",
        "article_type": kind,
    }
    app = FastAPI()
    app.include_router(module.router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://localhost",
    ) as client:
        response = await client.put("/community/drafts", json=body)
        assert response.status_code == 200
        collection = "questions" if kind == "question" else "articles"
        call = service.community_request.call_args
        assert call.args == (
            "PUT",
            f"/api/v1/community/{collection}/drafts/draft-1",
        )
        assert call.kwargs["json"]["media_ids"] == ["existing-image"]
        assert call.kwargs["json"]["tags"] == ["qwenpaw"]
        service.community_request.side_effect = [post, {"id": "draft-1"}]
        response = await client.post("/community/posts", json=body)
        assert response.status_code == 200
        assert service.community_request.call_args.args == (
            "POST",
            f"/api/v1/community/{collection}/drafts/draft-1/publish",
        )


def test_draft_asl_round_trip_and_unsupported_embeds():
    from qwenpaw.app.community_drafts import draft_asl, draft_content

    content = "# Title\n\n**Bold** and ![image](https://example.com/image.png)"
    assert draft_content(
        {"body_text": content, "body_asl": draft_asl(content)},
    ) == (content, True)
    assert draft_content(
        {"body_text": "Embed", "body_asl": '["root",["custom-embed",{}]]'},
    ) == ("Embed", False)


@pytest.mark.asyncio
async def test_draft_write_cannot_modify_a_published_post(monkeypatch):
    service = SimpleNamespace(
        community_request=AsyncMock(
            return_value={
                "id": "post",
                "author_user_id": "alice",
                "status": "published",
            },
        ),
    )
    monkeypatch.setattr(module, "get_service", lambda _: service)
    with pytest.raises(module.HTTPException) as error:
        await module.delete_community_draft(
            module.CommunityInteractionRequest(account_id="alice"),
            None,
            "post",
        )
    assert error.value.detail == "not_a_draft"
    assert service.community_request.await_count == 1
