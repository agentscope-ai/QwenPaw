# -*- coding: utf-8 -*-
"""Verify exact resource identity, platform type mapping and safe links."""
import httpx
import pytest

from qwenpaw.app.community_feedback import (
    FeedbackLinkError,
    resolve_feedback_link,
)
from qwenpaw.installation_origin import origin_from_platform_url

pytestmark = [pytest.mark.unit, pytest.mark.p0]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["app", "plugin", "skill"])
async def test_feedback_resolves_full_identity_not_display_name(kind):
    collection = "skills" if kind == "skill" else "plugins"
    target = (
        "01a0156d-88e5-7571-bae4-4c34b45edd6a" if kind == "skill" else "demo"
    )
    origin = origin_from_platform_url(
        f"https://platform.agentscope.io/{collection}/@alice/demo",
        kind,
        "1.2.3",
    )

    def handle(request):
        if "/openapi/" in request.url.path:
            assert request.url.params["search"] == "demo"
            return httpx.Response(
                200,
                json={
                    "data": {
                        "total": 2,
                        collection: [
                            {
                                "id": "@bob/demo",
                                "details_url": (
                                    "https://platform.agentscope.io/"
                                    f"{collection}/wrong"
                                ),
                            },
                            {
                                "id": "@alice/demo",
                                "details_url": (
                                    "https://platform.agentscope.io/"
                                    f"{collection}/{target}"
                                ),
                            },
                        ],
                    },
                },
            )
        return httpx.Response(
            200,
            json={
                "data": {
                    "id": target,
                    "plugin_id": target,
                    "tech_type": {
                        "code": "app" if kind == "app" else "backend",
                    },
                },
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle),
    ) as client:
        url = await resolve_feedback_link(origin, client)
    key = "relatedSkillId" if kind == "skill" else "relatedPluginId"
    assert (
        url == f"https://platform.agentscope.io/community/ask?{key}={target}"
    )
    assert "version" not in url


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "details",
    [
        "https://evil.example/plugins/demo",
        "https://platform.agentscope.io/plugins/demo?redirect=evil",
        "https://platform.agentscope.io/plugins/%2e%2e",
    ],
)
async def test_feedback_rejects_untrusted_detail_url(details):
    origin = origin_from_platform_url(
        "https://platform.agentscope.io/plugins/@alice/demo",
        "plugin",
    )

    def handle(_request):
        return httpx.Response(
            200,
            json={
                "data": {
                    "total": 1,
                    "plugins": [{"id": "@alice/demo", "details_url": details}],
                },
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle),
    ) as client:
        with pytest.raises(FeedbackLinkError):
            await resolve_feedback_link(origin, client)


@pytest.mark.asyncio
async def test_feedback_does_not_fall_back_to_same_name():
    origin = origin_from_platform_url(
        "https://platform.agentscope.io/plugins/@alice/demo",
        "plugin",
    )

    def handle(_request):
        return httpx.Response(
            200,
            json={
                "data": {
                    "total": 1,
                    "plugins": [
                        {
                            "id": "@bob/demo",
                            "details_url": (
                                "https://platform.agentscope.io/plugins/demo"
                            ),
                        },
                    ],
                },
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle),
    ) as client:
        with pytest.raises(FeedbackLinkError, match="no longer available"):
            await resolve_feedback_link(origin, client)


@pytest.mark.asyncio
async def test_feedback_rejects_changed_resource_type():
    origin = origin_from_platform_url(
        "https://platform.agentscope.io/plugins/@alice/demo",
        "app",
    )

    def handle(request):
        if "/openapi/" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "total": 1,
                        "plugins": [
                            {
                                "id": "@alice/demo",
                                "details_url": (
                                    "https://platform.agentscope.io/"
                                    "plugins/demo"
                                ),
                            },
                        ],
                    },
                },
            )
        return httpx.Response(
            200,
            json={
                "data": {
                    "plugin_id": "demo",
                    "tech_type": {"code": "backend"},
                },
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle),
    ) as client:
        with pytest.raises(FeedbackLinkError, match="type does not match"):
            await resolve_feedback_link(origin, client)


@pytest.mark.asyncio
async def test_post_resources_resolve_all_unique_skills_and_plugins(
    monkeypatch,
):
    from importlib import import_module

    router = import_module("qwenpaw.app.routers.community")

    class Service:
        async def community_request(self, method, path):
            assert method == "GET"
            if path.endswith("/articles/post"):
                return {
                    "title": "Not a resource",
                    "related_skill_ids": ["s1", "s2", "s1"],
                    "related_plugin_ids": ["p1", "p2"],
                }
            if path.endswith("/plugins/p2"):
                raise router.CommunityConnectionError("unavailable", 502)
            return {"name": "Plugin", "skill_code": "Skill"}

    monkeypatch.setattr(router, "get_service", lambda _: Service())
    result = await router.community_post_resources(None, "post")
    assert [item["id"] for item in result["resources"]] == [
        "s1",
        "s2",
        "p1",
        "p2",
    ]
    assert result["resources"][1]["url"] == (
        "https://platform.agentscope.io/skills/s2"
    )
    assert result["resources"][-1]["name"] == "p2"
    assert all(
        item["name"] != "Not a resource" for item in result["resources"]
    )


@pytest.mark.asyncio
async def test_publish_requires_account_and_maps_resource(monkeypatch):
    from importlib import import_module
    from fastapi import HTTPException

    router = import_module("qwenpaw.app.routers.community")
    calls = []

    class Service:
        async def status(self, **_kwargs):
            return {"account": {"id": "alice"}}

        async def community_request(self, method, path, **kwargs):
            calls.append((method, path, kwargs))
            return {"id": "post"}

    async def resolve(_):
        return {
            "url": (
                "https://platform.agentscope.io/community/ask"
                "?relatedPluginId=demo"
            ),
        }

    monkeypatch.setattr(router, "get_service", lambda _: Service())
    monkeypatch.setattr(router, "feedback_link", resolve)
    body = router.CommunityPostRequest(
        title="Title",
        content="<script>x</script>",
        account_id="other",
    )
    with pytest.raises(HTTPException):
        await router.publish_community_post(body, None)
    assert not calls
    body.account_id = "alice"
    body.origin = origin_from_platform_url(
        "https://platform.agentscope.io/plugins/@alice/demo",
        "plugin",
        "1.0",
    )
    body.origin = router.InstallationOrigin.model_validate(body.origin)
    await router.publish_community_post(body, None)
    payload = calls[0][2]["json"]
    assert payload["related_plugin_ids"] == ["demo"]
    assert "<script>" not in payload["body_html"]
    assert calls[0][2]["account_id"] == "alice"
