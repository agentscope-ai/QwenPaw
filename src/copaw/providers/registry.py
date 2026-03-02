# -*- coding: utf-8 -*-
"""Built-in provider definitions and registry."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, List, Optional, Type

from agentscope.model import ChatModelBase, OpenAIChatModel

from .models import CustomProviderData, ModelInfo, ProviderDefinition

if TYPE_CHECKING:
    from .models import ProvidersData

MODELSCOPE_MODELS: List[ModelInfo] = [
    ModelInfo(
        id="Qwen/Qwen3-235B-A22B-Instruct-2507",
        name="Qwen3-235B-A22B-Instruct-2507",
    ),
    ModelInfo(id="deepseek-ai/DeepSeek-V3.2", name="DeepSeek-V3.2"),
]

DASHSCOPE_MODELS: List[ModelInfo] = [
    ModelInfo(id="qwen3-max", name="Qwen3 Max"),
    ModelInfo(
        id="qwen3-235b-a22b-thinking-2507",
        name="Qwen3 235B A22B Thinking",
    ),
    ModelInfo(id="deepseek-v3.2", name="DeepSeek-V3.2"),
]

ALIYUN_CODINGPLAN_MODELS: List[ModelInfo] = [
    ModelInfo(id="qwen3.5-plus", name="Qwen3.5 Plus"),
    ModelInfo(id="glm-5", name="GLM-5"),
    ModelInfo(id="glm-4.7", name="GLM-4.7"),
    ModelInfo(id="MiniMax-M2.5", name="MiniMax M2.5"),
    ModelInfo(id="kimi-k2.5", name="Kimi K2.5"),
    ModelInfo(id="qwen3-max-2026-01-23", name="Qwen3 Max 2026-01-23"),
    ModelInfo(id="qwen3-coder-next", name="Qwen3 Coder Next"),
    ModelInfo(id="qwen3-coder-plus", name="Qwen3 Coder Plus"),
]

PROVIDER_MODELSCOPE = ProviderDefinition(
    id="modelscope",
    name="ModelScope",
    default_base_url="https://api-inference.modelscope.cn/v1",
    api_key_prefix="ms",
    models=MODELSCOPE_MODELS,
)

PROVIDER_DASHSCOPE = ProviderDefinition(
    id="dashscope",
    name="DashScope",
    default_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    api_key_prefix="sk",
    models=DASHSCOPE_MODELS,
)

PROVIDER_ALIYUN_CODINGPLAN = ProviderDefinition(
    id="aliyun-codingplan",
    name="Aliyun Coding Plan",
    default_base_url="https://coding.dashscope.aliyuncs.com/v1",
    api_key_prefix="sk-sp",
    models=ALIYUN_CODINGPLAN_MODELS,
)

PROVIDER_LLAMACPP = ProviderDefinition(
    id="llamacpp",
    name="llama.cpp (Local)",
    default_base_url="",
    api_key_prefix="",
    models=[],
    is_local=True,
)

PROVIDER_MLX = ProviderDefinition(
    id="mlx",
    name="MLX (Local, Apple Silicon)",
    default_base_url="",
    api_key_prefix="",
    models=[],
    is_local=True,
)

PROVIDER_OLLAMA = ProviderDefinition(
    id="ollama",
    name="Ollama",
    default_base_url="http://localhost:11434/v1",
    api_key_prefix="",
    models=[],
)

_BUILTIN_IDS: frozenset[str] = frozenset(
    [
        "modelscope",
        "dashscope",
        "aliyun-codingplan",
        "ollama",
        "llamacpp",
        "mlx",
    ],
)

PROVIDERS: dict[str, ProviderDefinition] = {
    PROVIDER_MODELSCOPE.id: PROVIDER_MODELSCOPE,
    PROVIDER_DASHSCOPE.id: PROVIDER_DASHSCOPE,
    PROVIDER_ALIYUN_CODINGPLAN.id: PROVIDER_ALIYUN_CODINGPLAN,
    PROVIDER_OLLAMA.id: PROVIDER_OLLAMA,
    PROVIDER_LLAMACPP.id: PROVIDER_LLAMACPP,
    PROVIDER_MLX.id: PROVIDER_MLX,
}

_VALID_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


def get_provider(provider_id: str) -> Optional[ProviderDefinition]:
    return PROVIDERS.get(provider_id)


def get_provider_chat_model(
    provider_id: str,
    providers_data: Optional[ProvidersData] = None,
) -> str:
    """Get chat model name for a provider, checking JSON settings first.

    Args:
        provider_id: Provider identifier.
        providers_data: Optional ProvidersData. If None, will load from JSON.

    Returns:
        Chat model class name, defaults to "OpenAIChatModel".
    """
    if providers_data is None:
        from .store import load_providers_json

        providers_data = load_providers_json()

    cpd = providers_data.custom_providers.get(provider_id)
    if cpd is not None:
        return cpd.chat_model

    settings = providers_data.providers.get(provider_id)
    if settings and settings.chat_model:
        return settings.chat_model

    provider_def = get_provider(provider_id)
    if provider_def:
        return provider_def.chat_model

    return "OpenAIChatModel"


def list_providers() -> List[ProviderDefinition]:
    return list(PROVIDERS.values())


def is_builtin(provider_id: str) -> bool:
    return provider_id in _BUILTIN_IDS


def _custom_data_to_definition(cpd: CustomProviderData) -> ProviderDefinition:
    return ProviderDefinition(
        id=cpd.id,
        name=cpd.name,
        default_base_url=cpd.default_base_url,
        api_key_prefix=cpd.api_key_prefix,
        models=list(cpd.models),
        is_custom=True,
        chat_model=cpd.chat_model,
    )


def validate_custom_provider_id(provider_id: str) -> Optional[str]:
    """Return an error message if invalid, or None if valid."""
    if provider_id in _BUILTIN_IDS:
        return f"'{provider_id}' is a built-in provider id and cannot be used."
    if not _VALID_ID_RE.match(provider_id):
        return (
            f"Invalid provider id '{provider_id}'. "
            "Must start with a lowercase letter and contain only "
            "lowercase letters, digits, hyphens, and underscores "
            "(max 64 chars)."
        )
    return None


def register_custom_provider(cpd: CustomProviderData) -> ProviderDefinition:
    err = validate_custom_provider_id(cpd.id)
    if err:
        raise ValueError(err)
    defn = _custom_data_to_definition(cpd)
    PROVIDERS[cpd.id] = defn
    return defn


def unregister_custom_provider(provider_id: str) -> None:
    if provider_id in _BUILTIN_IDS:
        raise ValueError(f"Cannot remove built-in provider '{provider_id}'.")
    PROVIDERS.pop(provider_id, None)


def sync_custom_providers(
    custom_providers: dict[str, CustomProviderData],
) -> None:
    """Synchronise the in-memory registry with persisted custom providers."""
    stale = [
        pid
        for pid, defn in PROVIDERS.items()
        if defn.is_custom and pid not in custom_providers
    ]
    for pid in stale:
        del PROVIDERS[pid]
    for cpd in custom_providers.values():
        PROVIDERS[cpd.id] = _custom_data_to_definition(cpd)


def sync_local_models() -> None:
    """Refresh local provider model lists from the local models manifest."""
    try:
        from ..local_models.manager import list_local_models
        from ..local_models.schema import BackendType

        llamacpp_models: list[ModelInfo] = []
        mlx_models: list[ModelInfo] = []

        for model in list_local_models():
            info = ModelInfo(id=model.id, name=model.display_name)
            if model.backend == BackendType.LLAMACPP:
                llamacpp_models.append(info)
            elif model.backend == BackendType.MLX:
                mlx_models.append(info)

        PROVIDER_LLAMACPP.models = llamacpp_models
        PROVIDER_MLX.models = mlx_models
    except ImportError:
        # local_models dependencies not installed; leave model lists empty
        pass


def sync_ollama_models() -> None:
    """Refresh Ollama provider model list from the Ollama daemon.

    Models are derived from ``ollama.list()`` via :class:`OllamaModelManager`.
    If the SDK is not installed or the daemon is unavailable, the list is
    left unchanged.
    """
    try:
        from ..providers.ollama_manager import OllamaModelManager

        models: list[ModelInfo] = []
        for model in OllamaModelManager.list_models():
            models.append(ModelInfo(id=model.name, name=model.name))
        PROVIDER_OLLAMA.models = models
    except ImportError:
        # Ollama SDK not installed; treat as having no models
        PROVIDER_OLLAMA.models = []
    except Exception:
        # Any other error (e.g. daemon not running) — keep previous list.
        pass


_CHAT_MODEL_MAP: dict[str, Type[ChatModelBase]] = {
    "OpenAIChatModel": OpenAIChatModel,
}


def get_chat_model_class(chat_model_name: str) -> Type[ChatModelBase]:
    """Get chat model class by name.

    Args:
        chat_model_name: Name of the chat model class (e.g., "OpenAIChatModel")

    Returns:
        Chat model class, defaults to OpenAIChatModel if not found.
    """
    return _CHAT_MODEL_MAP.get(chat_model_name, OpenAIChatModel)
