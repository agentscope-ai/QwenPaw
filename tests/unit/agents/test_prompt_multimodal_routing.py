# -*- coding: utf-8 -*-
from types import SimpleNamespace

from qwenpaw.agents import prompt
import qwenpaw.app.agent_context as agent_context_module
import qwenpaw.config.config as config_module
import qwenpaw.config.utils as config_utils
from qwenpaw.providers.models import ModelSlotConfig
from qwenpaw.providers.provider import ModelInfo
import qwenpaw.providers.provider_manager as provider_manager_module


class FakeProvider:
    def __init__(self, *models: ModelInfo) -> None:
        self.models = list(models)
        self.extra_models = []


class FakeManager:
    def __init__(
        self,
        *,
        providers: dict[str, FakeProvider],
        active_model: ModelSlotConfig | None = None,
    ) -> None:
        self.providers = providers
        self.active_model = active_model

    def get_provider(self, provider_id: str):
        return self.providers.get(provider_id)

    def get_active_model(self) -> ModelSlotConfig | None:
        return self.active_model


def test_routing_cloud_slot_drives_multimodal_capability(
    monkeypatch,
) -> None:
    local_model = ModelInfo(
        id="local-model",
        name="Local",
        supports_multimodal=False,
        supports_image=False,
        supports_video=False,
    )
    cloud_model = ModelInfo(
        id="cloud-model",
        name="Cloud",
        supports_multimodal=True,
        supports_image=True,
        supports_video=True,
    )
    manager = FakeManager(
        providers={
            "local": FakeProvider(local_model),
            "cloud": FakeProvider(cloud_model),
        },
        active_model=ModelSlotConfig(provider_id="local", model="local-model"),
    )
    agent_config = SimpleNamespace(
        active_model=ModelSlotConfig(provider_id="local", model="local-model"),
        llm_routing=SimpleNamespace(
            enabled=True,
            local=ModelSlotConfig(provider_id="local", model="local-model"),
            cloud=ModelSlotConfig(provider_id="cloud", model="cloud-model"),
        ),
    )

    monkeypatch.setattr(
        provider_manager_module.ProviderManager,
        "get_instance",
        lambda: manager,
    )
    monkeypatch.setattr(
        agent_context_module,
        "get_current_agent_id",
        lambda: "agent-1",
    )
    monkeypatch.setattr(
        config_module,
        "load_agent_config",
        lambda agent_id: agent_config,
    )
    monkeypatch.setattr(
        config_utils,
        "load_config",
        lambda: SimpleNamespace(
            agents=SimpleNamespace(llm_routing=agent_config.llm_routing),
        ),
    )

    assert prompt.get_active_model_supports_multimodal() is True
    assert prompt.build_multimodal_hint() == ""


def test_unknown_multimodal_capability_is_treated_as_allowed(
    monkeypatch,
) -> None:
    manager = FakeManager(
        providers={
            "cloud": FakeProvider(
                ModelInfo(
                    id="cloud-model",
                    name="Cloud",
                    supports_multimodal=None,
                    supports_image=None,
                    supports_video=None,
                ),
            ),
        },
        active_model=ModelSlotConfig(provider_id="cloud", model="cloud-model"),
    )

    monkeypatch.setattr(
        provider_manager_module.ProviderManager,
        "get_instance",
        lambda: manager,
    )
    monkeypatch.setattr(
        agent_context_module,
        "get_current_agent_id",
        lambda: "agent-1",
    )
    monkeypatch.setattr(
        config_module,
        "load_agent_config",
        lambda agent_id: SimpleNamespace(
            active_model=ModelSlotConfig(
                provider_id="cloud",
                model="cloud-model",
            ),
            llm_routing=SimpleNamespace(enabled=False, local=None, cloud=None),
        ),
    )
    monkeypatch.setattr(
        config_utils,
        "load_config",
        lambda: SimpleNamespace(
            agents=SimpleNamespace(
                llm_routing=SimpleNamespace(
                    enabled=False,
                    local=None,
                    cloud=None,
                ),
            ),
        ),
    )

    assert prompt.get_active_model_supports_multimodal() is True
