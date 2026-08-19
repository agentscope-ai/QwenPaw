# -*- coding: utf-8 -*-
"""Declarative discovery and synchronization policy for built-in providers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .provider import Provider

DiscoveryStrategy = Literal[
    "openai_models",
    "anthropic_models",
    "gemini_models",
    "provider_specific",
    "catalog_only",
    "unsupported",
]
ModelSyncMode = Literal["startup", "manual", "disabled"]


@dataclass(frozen=True, slots=True)
class ProviderDiscoveryPolicy:
    """One provider's model catalog acquisition policy."""

    strategy: DiscoveryStrategy
    sync_mode: ModelSyncMode = "manual"
    requires_auth: bool = True
    reason: str = ""


_OPENAI_DYNAMIC = ProviderDiscoveryPolicy("openai_models")
_OPENAI_FREE = ProviderDiscoveryPolicy(
    "openai_models",
    sync_mode="startup",
    requires_auth=False,
)
_CATALOG_PLAN = ProviderDiscoveryPolicy(
    "catalog_only",
    reason="The service does not expose a stable model-list API.",
)

BUILTIN_DISCOVERY_POLICIES: dict[str, ProviderDiscoveryPolicy] = {
    "qwenpaw-local": ProviderDiscoveryPolicy(
        "unsupported",
        sync_mode="disabled",
        requires_auth=False,
        reason="Local model inventory is managed by the local model service.",
    ),
    "ollama": ProviderDiscoveryPolicy(
        "provider_specific",
        sync_mode="startup",
        requires_auth=False,
    ),
    "lmstudio": ProviderDiscoveryPolicy(
        "provider_specific",
        sync_mode="startup",
        requires_auth=False,
    ),
    "openrouter": ProviderDiscoveryPolicy(
        "provider_specific",
        sync_mode="startup",
    ),
    "github-models": _CATALOG_PLAN,
    "modelscope": ProviderDiscoveryPolicy("provider_specific"),
    "dashscope": ProviderDiscoveryPolicy("provider_specific"),
    "aliyun-codingplan": _CATALOG_PLAN,
    "aliyun-codingplan-intl": _CATALOG_PLAN,
    "aliyun-tokenplan": _CATALOG_PLAN,
    "aliyun-tokenplan-intl": _CATALOG_PLAN,
    "opencode": _OPENAI_FREE,
    "kilo": _OPENAI_FREE,
    "openai": _OPENAI_DYNAMIC,
    "openai-response": _OPENAI_DYNAMIC,
    "azure-openai": ProviderDiscoveryPolicy(
        "catalog_only",
        reason="Azure deployment discovery requires Azure Resource Manager.",
    ),
    "anthropic": ProviderDiscoveryPolicy("anthropic_models"),
    "gemini": ProviderDiscoveryPolicy(
        "gemini_models",
        sync_mode="startup",
    ),
    "deepseek": _OPENAI_DYNAMIC,
    "kimi-cn": _OPENAI_DYNAMIC,
    "kimi-intl": _OPENAI_DYNAMIC,
    "kimi-codingplan": _CATALOG_PLAN,
    "minimax-cn": _CATALOG_PLAN,
    "minimax": _CATALOG_PLAN,
    "zhipu-cn": _OPENAI_DYNAMIC,
    "zhipu-cn-codingplan": _CATALOG_PLAN,
    "zhipu-intl": _OPENAI_DYNAMIC,
    "zhipu-intl-codingplan": _CATALOG_PLAN,
    "siliconflow-cn": ProviderDiscoveryPolicy(
        "openai_models",
        sync_mode="startup",
    ),
    "siliconflow-intl": ProviderDiscoveryPolicy(
        "openai_models",
        sync_mode="startup",
    ),
    "volcengine-cn": _OPENAI_DYNAMIC,
    "volcengine-cn-codingplan": _CATALOG_PLAN,
    "mimo-tokenplan": _CATALOG_PLAN,
}


def apply_discovery_policy(provider: Provider) -> None:
    """Apply the declared built-in policy to one provider instance."""
    policy = BUILTIN_DISCOVERY_POLICIES[provider.id]
    provider.discovery_strategy = policy.strategy
    provider.discovery_support_reason = policy.reason
    provider.discovery_requires_auth = policy.requires_auth
    provider.model_sync_mode = policy.sync_mode
    provider.support_model_discovery = policy.strategy not in {
        "catalog_only",
        "unsupported",
    }
