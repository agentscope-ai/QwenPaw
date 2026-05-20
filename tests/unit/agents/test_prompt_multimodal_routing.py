# -*- coding: utf-8 -*-
from types import SimpleNamespace

from qwenpaw.agents import prompt, routing_chat_model
from qwenpaw.config.config import ModelSlotConfig
from qwenpaw.providers.provider import ModelInfo
from qwenpaw.providers import provider_manager as provider_manager_module


class DummyProviderManager:
    def __init__(self) -> None:
        self.provider = SimpleNamespace(
            models=[
                ModelInfo(
                    id="routed-model",
                    name="Routed Model",
                    supports_multimodal=True,
                    supports_image=True,
                    supports_video=False,
                    generate_kwargs={},
                ),
            ],
            extra_models=[],
        )

    def get_provider(self, provider_id: str):
        if provider_id == "local":
            return self.provider
        return None


def _resolved_local_model():
    return ModelSlotConfig(provider_id="local", model="routed-model")


def test_prompt_multimodal_uses_effective_model_slot(monkeypatch):
    monkeypatch.setattr(
        routing_chat_model,
        "resolve_effective_model_slot",
        _resolved_local_model,
    )
    monkeypatch.setattr(
        provider_manager_module.ProviderManager,
        "get_instance",
        staticmethod(DummyProviderManager),
    )

    assert prompt.get_active_model_supports_multimodal() is True
