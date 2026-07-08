# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from types import SimpleNamespace

from qwenpaw.cli import doctor_checks
from qwenpaw.config.config import AgentsLLMRoutingConfig, ModelSlotConfig


def test_resolve_agent_effective_model_slot_prefers_enabled_routing():
    slot, source = doctor_checks._resolve_agent_effective_model_slot(
        SimpleNamespace(
            active_model=ModelSlotConfig(
                provider_id="agent-provider",
                model="agent-model",
            ),
            llm_routing=AgentsLLMRoutingConfig(
                enabled=True,
                mode="local_first",
                local=ModelSlotConfig(
                    provider_id="local-provider",
                    model="local-model",
                ),
            ),
        ),
        active_slot=None,
    )

    assert slot == ModelSlotConfig(
        provider_id="local-provider",
        model="local-model",
    )
    assert source == "agent.llm_routing.local"


def test_resolve_agent_effective_model_slot_reports_missing_selected_slot():
    slot, source = doctor_checks._resolve_agent_effective_model_slot(
        SimpleNamespace(
            active_model=ModelSlotConfig(
                provider_id="agent-provider",
                model="agent-model",
            ),
            llm_routing=AgentsLLMRoutingConfig(
                enabled=True,
                mode="cloud_first",
                local=ModelSlotConfig(
                    provider_id="local-provider",
                    model="local-model",
                ),
                cloud=None,
            ),
        ),
        active_slot=None,
    )

    assert slot is None
    assert source == "agent routing enabled but cloud slot is not set"


def test_resolve_effective_model_slot_uses_global_routing():
    slot, source = doctor_checks._resolve_agent_effective_model_slot(
        SimpleNamespace(
            active_model=None,
            llm_routing=AgentsLLMRoutingConfig(),
        ),
        active_slot=ModelSlotConfig(
            provider_id="global-provider",
            model="global-model",
        ),
        global_routing=AgentsLLMRoutingConfig(
            enabled=True,
            mode="local_first",
            local=ModelSlotConfig(
                provider_id="local-provider",
                model="local-model",
            ),
        ),
    )

    assert slot == ModelSlotConfig(
        provider_id="local-provider",
        model="local-model",
    )
    assert source == "global.llm_routing.local"
