# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from qwenpaw.app.routers import config as config_router
from qwenpaw.config import config as config_module
from qwenpaw.config.config import AgentsLLMRoutingConfig, ModelSlotConfig
from qwenpaw import providers as providers_module


class DummyProvider:
    def __init__(
        self,
        *,
        is_local: bool,
        base_url: str,
        models: set[str],
    ) -> None:
        self.is_local = is_local
        self.base_url = base_url
        self._models = models

    def has_model(self, model_id: str) -> bool:
        return model_id in self._models


class DummyProviderManager:
    def __init__(self) -> None:
        self.providers = {
            "local-provider": DummyProvider(
                is_local=True,
                base_url="http://127.0.0.1:1234/v1",
                models={"local-model", "other-local-model"},
            ),
            "cloud-provider": DummyProvider(
                is_local=False,
                base_url="https://api.example.com/v1",
                models={"cloud-model"},
            ),
        }

    def get_provider(self, provider_id: str):
        return self.providers.get(provider_id)


def _dummy_provider_manager():
    return DummyProviderManager()


def test_validate_routing_config_allows_disabled_stale_slots(monkeypatch):
    monkeypatch.setattr(
        providers_module.ProviderManager,
        "get_instance",
        staticmethod(_dummy_provider_manager),
    )

    config_router._validate_routing_config(
        AgentsLLMRoutingConfig(
            enabled=False,
            mode="local_first",
            local=ModelSlotConfig(
                provider_id="missing-provider",
                model="missing-model",
            ),
            cloud=ModelSlotConfig(
                provider_id="local-provider",
                model="local-model",
            ),
        ),
    )


def test_validate_routing_config_skips_inactive_slot(monkeypatch):
    monkeypatch.setattr(
        providers_module.ProviderManager,
        "get_instance",
        staticmethod(_dummy_provider_manager),
    )

    config_router._validate_routing_config(
        AgentsLLMRoutingConfig(
            enabled=True,
            mode="local_first",
            local=ModelSlotConfig(
                provider_id="local-provider",
                model="local-model",
            ),
            cloud=ModelSlotConfig(
                provider_id="missing-provider",
                model="missing-model",
            ),
        ),
    )


@pytest.mark.asyncio
async def test_hides_inherited_global_routing_when_agent_model_exists(
    monkeypatch,
):
    monkeypatch.setattr(
        config_router,
        "load_config",
        lambda: SimpleNamespace(
            agents=SimpleNamespace(
                llm_routing=AgentsLLMRoutingConfig(
                    enabled=True,
                    mode="local_first",
                    local=ModelSlotConfig(
                        provider_id="local-provider",
                        model="local-model",
                    ),
                ),
            ),
        ),
    )
    monkeypatch.setattr(
        config_module,
        "load_agent_config",
        lambda _agent_id: SimpleNamespace(
            active_model=ModelSlotConfig(
                provider_id="cloud-provider",
                model="cloud-model",
            ),
            llm_routing=AgentsLLMRoutingConfig(),
        ),
    )

    routing = await config_router.get_agents_llm_routing(agent_id="agent-1")

    assert routing.enabled is False
    assert routing.local.provider_id == ""
    assert routing.cloud is None


@pytest.mark.asyncio
async def test_put_agent_llm_routing_rejects_unknown_provider(monkeypatch):
    monkeypatch.setattr(
        providers_module.ProviderManager,
        "get_instance",
        staticmethod(_dummy_provider_manager),
    )

    with pytest.raises(HTTPException) as exc_info:
        await config_router.put_agents_llm_routing(
            request=None,
            body=AgentsLLMRoutingConfig(
                enabled=True,
                mode="local_first",
                local=ModelSlotConfig(
                    provider_id="missing-provider",
                    model="local-model",
                ),
            ),
        )

    assert exc_info.value.status_code == 400
    assert "not found" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_put_agent_llm_routing_rejects_local_provider_in_cloud_slot(
    monkeypatch,
):
    monkeypatch.setattr(
        providers_module.ProviderManager,
        "get_instance",
        staticmethod(_dummy_provider_manager),
    )

    with pytest.raises(HTTPException) as exc_info:
        await config_router.put_agents_llm_routing(
            request=None,
            body=AgentsLLMRoutingConfig(
                enabled=True,
                mode="cloud_first",
                local=ModelSlotConfig(
                    provider_id="local-provider",
                    model="local-model",
                ),
                cloud=ModelSlotConfig(
                    provider_id="local-provider",
                    model="other-local-model",
                ),
            ),
        )

    assert exc_info.value.status_code == 400
    assert "Cloud slot must use a non-local provider." in str(
        exc_info.value.detail,
    )
