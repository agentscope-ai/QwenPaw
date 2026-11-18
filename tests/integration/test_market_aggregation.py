# -*- coding: utf-8 -*-
"""Real market routes and providers with controlled upstream HTTP responses."""

import httpx
import pytest
from fastapi import FastAPI

from qwenpaw.agents.skill_system import hub
from qwenpaw.app.routers import market
from qwenpaw.market import service
from qwenpaw.market.builtin import BuiltinMarketProvider
from qwenpaw.market.providers.clawhub import ClawHubProvider
from qwenpaw.market.providers.modelscope import ModelScopeProvider
from qwenpaw.market.providers.qwenpaw import QwenPawProvider
from qwenpaw.market.registry import MarketRegistry


@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.parametrize("clawhub_status", [200, 503])
async def test_market_search_multiple_providers_aggregates(
    monkeypatch,
    clawhub_status,
):
    registry = MarketRegistry()
    for provider in (
        QwenPawProvider(),
        ClawHubProvider(),
        ModelScopeProvider(),
    ):
        registry.register(provider.key, BuiltinMarketProvider(provider))
    monkeypatch.setattr(market, "market_registry", registry)
    monkeypatch.setattr(service, "market_registry", registry)
    calls = []

    def upstream(request):
        calls.append(request.url.host)
        if request.url.host == "clawhub.ai":
            assert request.url.path == "/api/v1/trending"
            assert request.url.params["kind"] == "skills"
            return httpx.Response(
                clawhub_status,
                json={
                    "items": [
                        {
                            "source": "clawhub",
                            "canonicalUrl": "/tester/skill",
                            "displayName": "Claw skill",
                        },
                    ],
                },
            )
        assert request.url.host in {
            "platform.agentscope.io",
            "www.modelscope.cn",
        }
        assert request.url.path == "/openapi/v1/skills"
        assert request.url.params["page_size"] == "5"
        assert request.url.params["page_number"] == "2"
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "skills": [
                        {"id": "@tester/skill", "display_name": "Skill"},
                    ],
                    "total": 11,
                },
            },
        )

    app = FastAPI()
    app.include_router(market.router, prefix="/api")
    async with (
        httpx.AsyncClient(
            transport=httpx.MockTransport(upstream),
        ) as external,
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client,
    ):
        monkeypatch.setattr(hub, "_async_client", external)
        response = await client.post(
            "/api/market/search",
            json={
                "provider_pages": {
                    "qwenpaw": 2,
                    "clawhub": 1,
                    "modelscope": 2,
                },
                "limit": 5,
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    expected = {("qwenpaw", "@tester/skill"), ("modelscope", "@tester/skill")}
    if clawhub_status == 200:
        expected.add(("clawhub", "tester/skill"))
        assert payload["errors"] == []
    else:
        assert len(payload["errors"]) == 1
        assert payload["errors"][0]["provider"] == "clawhub"
        assert "503" in payload["errors"][0]["message"]
    assert len(payload["results"]) == len(expected)
    assert {(r["source"], r["slug"]) for r in payload["results"]} == expected
    pages = {
        key: {"has_more": True, "total": 11}
        for key in ("qwenpaw", "modelscope")
    }
    if clawhub_status == 200:
        pages["clawhub"] = {"has_more": False, "total": 0}
    assert payload["by_provider"] == pages
    assert set(calls) == {
        "platform.agentscope.io",
        "clawhub.ai",
        "www.modelscope.cn",
    }
