# -*- coding: utf-8 -*-
"""A Manager class to handle all providers, including built-in and custom ones.
It provides a unified interface to manage providers, such as listing available
providers, adding/removing custom providers, and fetching provider details."""

import os
from typing import Dict, List
import logging
import json

from pydantic import BaseModel, Field

from agentscope.model import ChatModelBase

from copaw.providers.provider import (
    ModelInfo,
    DefaultProvider,
    Provider,
    ProviderInfo,
)
from copaw.providers.openai_provider import OpenAIProvider
from copaw.providers.anthropic_provider import AnthropicProvider
from copaw.providers.ollama_provider import OllamaProvider
from copaw.constant import SECRET_DIR
from copaw.local_models import create_local_chat_model

logger = logging.getLogger(__name__)


# -------------------------------------------------------
# Built-in provider definitions and their default models.
# -------------------------------------------------------

MODELSCOPE_MODELS: List[ModelInfo] = [
    ModelInfo(
        id="Qwen/Qwen3.5-122B-A10B",
        name="Qwen3.5-122B-A10B",
    ),
    ModelInfo(id="ZhipuAI/GLM-5", name="GLM-5"),
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

OPENAI_MODELS: List[ModelInfo] = [
    ModelInfo(id="gpt-5.2", name="GPT-5.2"),
    ModelInfo(id="gpt-5", name="GPT-5"),
    ModelInfo(id="gpt-5-mini", name="GPT-5 Mini"),
    ModelInfo(id="gpt-5-nano", name="GPT-5 Nano"),
    ModelInfo(id="gpt-4.1", name="GPT-4.1"),
    ModelInfo(id="gpt-4.1-mini", name="GPT-4.1 Mini"),
    ModelInfo(id="gpt-4.1-nano", name="GPT-4.1 Nano"),
    ModelInfo(id="o3", name="o3"),
    ModelInfo(id="o4-mini", name="o4-mini"),
    ModelInfo(id="gpt-4o", name="GPT-4o"),
    ModelInfo(id="gpt-4o-mini", name="GPT-4o Mini"),
]

AZURE_OPENAI_MODELS: List[ModelInfo] = [
    ModelInfo(id="gpt-5-chat", name="GPT-5 Chat"),
    ModelInfo(id="gpt-5-mini", name="GPT-5 Mini"),
    ModelInfo(id="gpt-5-nano", name="GPT-5 Nano"),
    ModelInfo(id="gpt-4.1", name="GPT-4.1"),
    ModelInfo(id="gpt-4.1-mini", name="GPT-4.1 Mini"),
    ModelInfo(id="gpt-4.1-nano", name="GPT-4.1 Nano"),
    ModelInfo(id="gpt-4o", name="GPT-4o"),
    ModelInfo(id="gpt-4o-mini", name="GPT-4o Mini"),
]

ANTHROPIC_MODELS: List[ModelInfo] = []

PROVIDER_MODELSCOPE = OpenAIProvider(
    id="modelscope",
    name="ModelScope",
    base_url="https://api-inference.modelscope.cn/v1",
    api_key_prefix="ms",
    models=MODELSCOPE_MODELS,
    freeze_url=True,
)

PROVIDER_DASHSCOPE = OpenAIProvider(
    id="dashscope",
    name="DashScope",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    api_key_prefix="sk",
    models=DASHSCOPE_MODELS,
    freeze_url=True,
)

PROVIDER_ALIYUN_CODINGPLAN = OpenAIProvider(
    id="aliyun-codingplan",
    name="Aliyun Coding Plan",
    base_url="https://coding.dashscope.aliyuncs.com/v1",
    api_key_prefix="sk-sp",
    models=ALIYUN_CODINGPLAN_MODELS,
    freeze_url=True,
)

PROVIDER_LLAMACPP = DefaultProvider(
    id="llamacpp",
    name="llama.cpp (Local)",
    is_local=True,
    require_api_key=False,
)

PROVIDER_MLX = DefaultProvider(
    id="mlx",
    name="MLX (Local, Apple Silicon)",
    is_local=True,
    require_api_key=False,
)

PROVIDER_OPENAI = OpenAIProvider(
    id="openai",
    name="OpenAI",
    base_url="https://api.openai.com/v1",
    api_key_prefix="sk-",
    models=OPENAI_MODELS,
    freeze_url=True,
)

PROVIDER_AZURE_OPENAI = OpenAIProvider(
    id="azure-openai",
    name="Azure OpenAI",
    api_key_prefix="",
    models=AZURE_OPENAI_MODELS,
)

PROVIDER_ANTHROPIC = AnthropicProvider(
    id="anthropic",
    name="Anthropic",
    base_url="https://api.anthropic.com",
    api_key_prefix="sk-ant-",
    models=ANTHROPIC_MODELS,
    chat_model="AnthropicChatModel",
    freeze_url=True,
)

PROVIDER_OLLAMA = OllamaProvider(
    id="ollama",
    name="Ollama",
    require_api_key=False,
)


class ModelSlotConfig(BaseModel):
    provider_id: str = Field(
        ...,
        description="ID of the provider to use for this model slot",
    )
    model: str = Field(
        ...,
        description="ID of the model to use for this model slot",
    )


class ActiveModelsInfo(BaseModel):
    active_llm: ModelSlotConfig | None


class ProviderManager:
    """A manager class to handle all providers,
    including built-in and custom ones."""

    _instance = None

    def __init__(self) -> None:
        # Initialize provider manager, load providers from registry and store
        # any necessary state (e.g., cached models).
        self.builtin_providers: Dict[str, Provider] = {}
        self.custom_providers: Dict[str, Provider] = {}
        self.active_model: ModelSlotConfig | None = None
        self.root_path = SECRET_DIR / "providers"
        self.builtin_path = self.root_path / "builtin"
        self.custom_path = self.root_path / "custom"
        self._prepare_disk_storage()
        self._init_builtins()
        try:
            self._migrate_legacy_providers()
        except Exception as e:
            logger.warning("Failed to migrate legacy providers: %s", e)
        self._init_from_storage()
        self.update_local_models()

    def _prepare_disk_storage(self):
        """Prepare directory structure"""
        for path in [self.root_path, self.builtin_path, self.custom_path]:
            path.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(path, 0o700)  # Restrict permissions for security
            except Exception:
                pass

    def _init_builtins(self):
        self._add_builtin(PROVIDER_MODELSCOPE)
        self._add_builtin(PROVIDER_DASHSCOPE)
        self._add_builtin(PROVIDER_ALIYUN_CODINGPLAN)
        self._add_builtin(PROVIDER_OPENAI)
        self._add_builtin(PROVIDER_AZURE_OPENAI)
        self._add_builtin(PROVIDER_ANTHROPIC)
        self._add_builtin(PROVIDER_OLLAMA)
        self._add_builtin(PROVIDER_LLAMACPP)
        self._add_builtin(PROVIDER_MLX)

    def _add_builtin(self, provider: Provider):
        self.builtin_providers[provider.id] = provider

    async def list_provider_info(self) -> List[ProviderInfo]:
        provider_infos = []
        for provider in self.builtin_providers.values():
            provider_infos.append(await provider.get_info())
        for provider in self.custom_providers.values():
            provider_infos.append(await provider.get_info())
        return provider_infos

    def get_provider(self, provider_id: str) -> Provider | None:
        # Return a provider instance by its ID. This will be used to create
        # chat model instances for the agent.
        if provider_id in self.builtin_providers:
            return self.builtin_providers[provider_id]
        if provider_id in self.custom_providers:
            return self.custom_providers[provider_id]
        return None

    async def get_provider_info(self, provider_id: str) -> ProviderInfo | None:
        provider = self.get_provider(provider_id)
        return await provider.get_info() if provider else None

    def get_active_model(self) -> ModelSlotConfig | None:
        # Return the currently active provider/model configuration.
        return self.active_model

    def update_provider(self, provider_id: str, config: Dict) -> bool:
        # Update the configuration of a provider (e.g., base URL, API key).
        # This will be called when the user edits a provider's settings in the
        # UI. It should update the in-memory provider instance and persist the
        # changes to providers.json.
        provider = self.get_provider(provider_id)
        if not provider:
            return False
        provider.update_config(config)
        self._save_provider(
            provider,
            is_builtin=provider_id in self.builtin_providers,
        )
        return True

    async def fetch_provider_models(
        self,
        provider_id: str,
        update_target: str,
    ) -> List[ModelInfo]:
        """Fetch the list of available models from a provider and optionally
        update the provider's model list in memory and on disk."""
        provider = self.get_provider(provider_id)
        if not provider:
            return []
        try:
            models = await provider.fetch_models()
            for model in models:
                await provider.add_model(
                    model,
                    target=update_target,
                )
            self._save_provider(
                provider,
                is_builtin=provider_id in self.builtin_providers,
            )
            return models
        except Exception as e:
            logger.warning(
                "Failed to fetch models for provider '%s': %s",
                provider_id,
                e,
            )
            return []

    async def add_custom_provider(self, provider_data: ProviderInfo):
        # Add a new custom provider with the given data. This will update the
        # providers.json file and make the new provider available in the UI.
        if provider_data.id in self.builtin_providers:
            raise ValueError(
                f"'{provider_data.id}' conflicts with a built-in provider.",
            )
        if provider_data.id in self.custom_providers:
            raise ValueError(
                f"Custom provider '{provider_data.id}' already exists.",
            )
        provider_data.is_custom = True
        provider = self._provider_from_data(
            provider_data.model_dump(),
        )  # Validate provider data
        self.custom_providers[provider.id] = provider
        self._save_provider(provider, is_builtin=False)
        return await provider.get_info()

    def remove_custom_provider(self, provider_id: str) -> bool:
        # Remove a custom provider by its ID. This will update the
        # providers.json file and remove the provider from the UI.
        if provider_id in self.custom_providers:
            del self.custom_providers[provider_id]
            provider_path = self.custom_path / f"{provider_id}.json"
            if provider_path.exists():
                os.remove(provider_path)
            return True
        return False

    async def activate_model(self, provider_id: str, model_id: str):
        # Set the active provider and model for the agent. This will update
        # providers.json and determine which provider/model is used when the
        # agent creates chat model instances.
        provider = self.get_provider(provider_id)
        if not provider:
            raise ValueError(f"Provider '{provider_id}' not found.")
        if not provider.has_model(model_id):
            raise ValueError(
                f"Model '{model_id}' not found in provider '{provider_id}'.",
            )
        self.active_model = ModelSlotConfig(
            provider_id=provider_id,
            model=model_id,
        )
        self.save_active_model(self.active_model)

    async def add_model_to_provider(
        self,
        provider_id: str,
        model_info: ModelInfo,
    ) -> ProviderInfo:
        provider = self.get_provider(provider_id)
        if not provider:
            raise ValueError(f"Provider '{provider_id}' not found.")
        await provider.add_model(model_info)
        self._save_provider(
            provider,
            is_builtin=provider_id in self.builtin_providers,
        )
        return await provider.get_info()

    async def delete_model_from_provider(
        self,
        provider_id: str,
        model_id: str,
    ) -> ProviderInfo:
        provider = self.get_provider(provider_id)
        if not provider:
            raise ValueError(f"Provider '{provider_id}' not found.")
        await provider.delete_model(model_id=model_id)
        self._save_provider(
            provider,
            is_builtin=provider_id in self.builtin_providers,
        )
        return await provider.get_info()

    def _save_provider(
        self,
        provider: Provider,
        is_builtin: bool = False,
        skip_if_exists: bool = False,
    ):
        """Save a provider configuration to disk."""
        provider_dir = self.builtin_path if is_builtin else self.custom_path
        provider_path = provider_dir / f"{provider.id}.json"
        if skip_if_exists and provider_path.exists():
            return
        with open(provider_path, "w", encoding="utf-8") as f:
            json.dump(provider.model_dump(), f, ensure_ascii=False, indent=2)
        try:
            os.chmod(provider_path, 0o600)
        except OSError:
            pass

    def load_provider(
        self,
        provider_id: str,
        is_builtin: bool = False,
    ) -> Provider | None:
        """Load a provider configuration from disk."""
        provider_dir = self.builtin_path if is_builtin else self.custom_path
        provider_path = provider_dir / f"{provider_id}.json"
        if not provider_path.exists():
            return None
        try:
            with open(provider_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return self._provider_from_data(data)
        except Exception as e:
            logger.warning(
                "Failed to load provider '%s' from %s: %s",
                provider_id,
                provider_path,
                e,
            )
            return None

    def _provider_from_data(self, data: Dict) -> Provider:
        """Deserialize provider data to a concrete provider type."""
        provider_id = str(data.get("id", ""))
        chat_model = str(data.get("chat_model", ""))

        if provider_id == "anthropic" or chat_model == "AnthropicChatModel":
            return AnthropicProvider.model_validate(data)
        if provider_id == "ollama" or chat_model == "OllamaChatModel":
            return OllamaProvider.model_validate(data)
        if data.get("is_local", False):
            return DefaultProvider.model_validate(data)
        return OpenAIProvider.model_validate(data)

    def save_active_model(self, active_model: ModelSlotConfig):
        """Save the active provider/model configuration to disk."""
        active_path = self.root_path / "active_model.json"
        with open(active_path, "w", encoding="utf-8") as f:
            json.dump(
                active_model.model_dump(),
                f,
                ensure_ascii=False,
                indent=2,
            )
        try:
            os.chmod(active_path, 0o600)
        except OSError:
            pass

    def load_active_model(self) -> ModelSlotConfig | None:
        """Load the active provider/model configuration from disk."""
        active_path = self.root_path / "active_model.json"
        if not active_path.exists():
            return None
        try:
            with open(active_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return ModelSlotConfig.model_validate(data)
        except Exception:
            return None

    def _migrate_legacy_providers(self):
        """Migrate from legacy providers.json format to the new structure."""
        legacy_path = SECRET_DIR / "providers.json"
        if legacy_path.exists() and legacy_path.is_file():
            with open(legacy_path, "r", encoding="utf-8") as f:
                legacy_data = json.load(f)
            builtin_providers = legacy_data.get("providers", {})
            custom_providers = legacy_data.get("custom_providers", {})
            active_model = legacy_data.get("active_llm", {})
            # Migrate built-in providers
            for provider_id, config in builtin_providers.items():
                provider = self.get_provider(provider_id)
                if not provider:
                    logger.warning(
                        "Legacy provider '%s' not found in"
                        " registry, skipping migration for this provider.",
                        provider_id,
                    )
                    continue
                if "api_key" in config:
                    provider.api_key = config["api_key"]
                if "extra_models" in config:
                    provider.extra_models = [
                        ModelInfo.model_validate(model)
                        for model in config["extra_models"]
                    ]
                if not provider.freeze_url and "base_url" in config:
                    provider.base_url = config["base_url"]
                self._save_provider(provider, is_builtin=True)
            # Migrate custom providers
            for provider_id, data in custom_providers.items():
                custom_provider = OpenAIProvider(
                    id=provider_id,
                    name=data.get("name", provider_id),
                    base_url=data.get("base_url", ""),
                    api_key=data.get("api_key", ""),
                    is_custom=True,
                )
                if "models" in data:
                    # migrate models to extra_models field
                    custom_provider.extra_models = [
                        ModelInfo.model_validate(model)
                        for model in data["models"]
                    ]
                if "chat_model" in data:
                    custom_provider.chat_model = data["chat_model"]
                self._save_provider(custom_provider, is_builtin=False)
            # Migrate active model
            if active_model:
                try:
                    self.active_model = ModelSlotConfig.model_validate(
                        active_model,
                    )
                    self.save_active_model(self.active_model)
                except Exception:
                    logger.warning(
                        "Failed to migrate active model, using default.",
                    )
            # Remove legacy file after migration
            try:
                os.remove(legacy_path)
            except Exception:
                logger.warning(
                    "Failed to remove legacy providers.json after migration.",
                )

    def _init_from_storage(self):
        """Initialize all providers and active model from disk storage."""
        # Load built-in providers
        for builtin in self.builtin_providers.values():
            provider = self.load_provider(builtin.id, is_builtin=True)
            if provider:
                builtin.base_url = provider.base_url
                builtin.api_key = provider.api_key
                builtin.extra_models = provider.extra_models
        # Load custom providers
        for provider_file in self.custom_path.glob("*.json"):
            provider = self.load_provider(provider_file.stem, is_builtin=False)
            if provider:
                self.custom_providers[provider.id] = provider
        # Load active model config
        active_model = self.load_active_model()
        if active_model:
            self.active_model = active_model

    def update_local_models(self):
        """Update the model list of a local provider."""
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

    @staticmethod
    def get_instance() -> "ProviderManager":
        """Get the singleton instance of ProviderManager."""
        if ProviderManager._instance is None:
            ProviderManager._instance = ProviderManager()
        return ProviderManager._instance

    @staticmethod
    def get_active_chat_model() -> ChatModelBase:
        """Get the currently active provider/model configuration."""
        manager = ProviderManager.get_instance()
        model = manager.get_active_model()
        if model is None or model.provider_id == "" or model.model == "":
            raise ValueError("No active model configured.")
        provider = manager.get_provider(model.provider_id)
        if provider is None:
            raise ValueError(
                f"Active provider '{model.provider_id}' not found.",
            )
        if provider.is_local:
            return create_local_chat_model(
                model_id=model.model,
                stream=True,
                generate_kwargs={"max_tokens": None},
            )
        return provider.get_chat_model_instance(model.model)
