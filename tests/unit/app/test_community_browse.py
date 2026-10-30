# -*- coding: utf-8 -*-
"""Platform filters, error isolation and publishing category contracts."""

import json
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


def test_draft_asl_renders_media_as_image_nodes():
    from qwenpaw.app.community_drafts import draft_asl

    content = (
        "![shot.jpg](https://oss.example.com/shot.jpg)\n\n"
        "![clip.mp4](https://oss.example.com/clip.mp4)"
    )
    asl = draft_asl(content)
    tree = json.loads(asl)
    images = [
        node
        for block in tree[1:]
        for node in block
        if isinstance(node, list) and node[0] == "img"
    ]
    # Both image and video become real img inline nodes; Platform turns
    # video URLs into players via useVideoImagePlayers.
    assert [img[1]["src"] for img in images] == [
        "https://oss.example.com/shot.jpg",
        "https://oss.example.com/clip.mp4",
    ]
    assert [img[1]["alt"] for img in images] == ["shot.jpg", "clip.mp4"]
    # Media is structured nodes, never raw Markdown source in a text leaf.
    assert "![" not in asl


def test_draft_asl_media_round_trips_to_markdown():
    from qwenpaw.app.community_drafts import (
        _rich_markdown,
        draft_asl,
        draft_content,
    )

    content = "intro ![pic](https://oss.example.com/p.png) outro"
    post = {"body_text": content, "body_asl": draft_asl(content)}
    assert draft_content(post) == (content, True)
    assert _rich_markdown(json.loads(draft_asl(content))) == content


@pytest.mark.parametrize(
    "href",
    [
        "https://example.com/a)b",  # unmatched ')' would close the link early
        "https://example.com/Foo_(bar)",  # balanced parens (Wikipedia-style)
        "https://example.com/a(b)c)",  # balanced pair plus a trailing ')'
    ],
)
def test_draft_asl_escapes_parens_in_link_destination(href):
    from markdown_it import MarkdownIt

    from qwenpaw.app.community_drafts import _rich_markdown, draft_asl

    # Parens in the destination must be escaped so the link is not truncated
    # when Platform re-parses it. Escaping only ')' would leave balanced URLs
    # like Foo_(bar) with an unmatched '(' that CommonMark rejects, so both
    # '(' and ')' are escaped.
    rendered = _rich_markdown(["root", ["p", ["a", {"href": href}, "link"]]])
    tokens = MarkdownIt("commonmark").parse(rendered, {})
    link_open = next(
        child
        for token in tokens
        if token.type == "inline"
        for child in token.children
        if child.type == "link_open"
    )
    assert link_open.attrGet("href") == href
    # Images use the same escaping and the ASL round trip stays lossless.
    img = _rich_markdown(
        ["root", ["p", ["img", {"src": href, "alt": "link"}]]]
    )
    assert img == "!" + rendered
    assert _rich_markdown(json.loads(draft_asl(rendered))) == rendered


def test_draft_content_recognizes_legacy_text_span_drafts():
    from qwenpaw.app.community_drafts import _legacy_tree, draft_content

    content = "![pic](https://oss.example.com/p.png)\nplain line"
    legacy = json.dumps(_legacy_tree(content))
    assert draft_content({"body_text": content, "body_asl": legacy}) == (
        content,
        True,
    )


def test_draft_asl_parses_rich_blocks():
    from qwenpaw.app.community_drafts import draft_asl

    tree = json.loads(
        draft_asl(
            "# Heading\n\n- item\n\n```python\nx = 1\n```\n\n"
            "use `code` and [link](https://example.com)",
        ),
    )
    assert [block[0] for block in tree[1:]] == ["h1", "ul", "code", "p"]
    code = tree[3]
    assert code[1]["code"] == "x = 1"
    assert code[1]["syntax"] == "python"
    inline_tags = [n[0] for n in tree[4][1:] if isinstance(n, list)]
    assert "inlineCode" in inline_tags
    assert "a" in inline_tags


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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "purpose,limit_attr",
    [("body", "_BODY_MEDIA_LIMIT"), ("comment", "_COMMENT_MEDIA_LIMIT")],
)
async def test_media_upload_rejects_oversize_before_forwarding(
    monkeypatch,
    purpose,
    limit_attr,
):
    # Shrink the limit so an oversized upload is exercised without buffering
    # hundreds of megabytes; the handler must 413 before forwarding upstream.
    monkeypatch.setattr(module, limit_attr, 8)
    service = SimpleNamespace(
        community_request=AsyncMock(return_value={"media_id": "m"}),
    )
    monkeypatch.setattr(module, "get_service", lambda _: service)
    app = FastAPI()
    app.include_router(module.router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://localhost",
    ) as client:
        response = await client.post(
            "/community/media",
            params={"purpose": purpose, "account_id": "alice"},
            files={"file": ("big.bin", b"x" * 64, "application/octet-stream")},
        )
    assert response.status_code == 413
    assert response.json() == {"detail": "media_too_large"}
    service.community_request.assert_not_awaited()


@pytest.mark.asyncio
async def test_media_upload_forwards_payload_within_limit(monkeypatch):
    monkeypatch.setattr(module, "_COMMENT_MEDIA_LIMIT", 1024)
    # Force several chunks so the reassembled payload is verified byte-exact.
    monkeypatch.setattr(module, "_MEDIA_CHUNK_SIZE", 4)
    service = SimpleNamespace(
        community_request=AsyncMock(return_value={"media_id": "m1"}),
    )
    monkeypatch.setattr(module, "get_service", lambda _: service)
    app = FastAPI()
    app.include_router(module.router)
    payload = b"image-bytes" * 4
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://localhost",
    ) as client:
        response = await client.post(
            "/community/media",
            params={"purpose": "comment", "account_id": "alice"},
            files={"file": ("pic.png", payload, "image/png")},
        )
    assert response.status_code == 200
    assert response.json() == {"media_id": "m1"}
    call = service.community_request.call_args
    assert call.args == ("POST", "/api/v1/community/media")
    assert call.kwargs["params"] == {"purpose": "comment"}
    assert call.kwargs["files"]["file"] == ("pic.png", payload, "image/png")
    assert call.kwargs["timeout"] == 60
