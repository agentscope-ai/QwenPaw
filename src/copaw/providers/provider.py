# -*- coding: utf-8 -*-
"""Definition of Provider."""

from abc import ABC, abstractmethod
from typing import Dict, List, Type, Any
from pydantic import BaseModel, Field

from agentscope.model import ChatModelBase


class ModelInfo(BaseModel):
    id: str = Field(..., description="Model identifier used in API calls")
    name: str = Field(..., description="Human-readable model name")


class ProviderInfo(BaseModel):
    id: str = Field(..., description="Provider identifier")
    name: str = Field(..., description="Human-readable provider name")
    base_url: str = Field(default="", description="API base URL")
    api_key: str = Field(default="", description="API key for authentication")
    chat_model: str = Field(
        default="OpenAIChatModel",
        description="AgentScope ChatModel name (e.g., 'OpenAIChatModel')",
    )
    models: List[ModelInfo] = Field(
        default_factory=list,
        description="List of pre-defined models",
    )
    extra_models: List[ModelInfo] = Field(
        default_factory=list,
        description="List of user-added models (not fetched from provider)",
    )
    api_key_prefix: str = Field(
        default="",
        description="Expected prefix for the API key (e.g., 'sk-')",
    )
    is_local: bool = Field(
        default=False,
        description="Whether this provider is for a local hosting platform",
    )
    freeze_url: bool = Field(
        default=False,
        description="Whether the base_url should be frozen (not editable)",
    )
    require_api_key: bool = Field(
        default=True,
        description="Whether this provider requires an API key",
    )
    is_custom: bool = Field(
        default=False,
        description=("Whether this provider is user-created (not built-in)."),
    )
    support_model_discovery: bool = Field(
        default=False,
        description=(
            "Whether this provider supports fetching available models"
            " from the provider's API"
        ),
    )
    support_connection_check: bool = Field(
        default=True,
        description=(
            "Whether this provider supports checking connection to the API "
            "without model configuration"
        ),
    )
    generate_kwargs: Dict[str, Any] = Field(
        default_factory=dict,
        description="Generation parameters for agentscope chat models.",
    )


class Provider(ProviderInfo, ABC):
    """Represents a provider instance with its configuration."""

    @abstractmethod
    async def check_connection(self, timeout: float = 5) -> tuple[bool, str]:
        """Check if the provider is reachable with the current config."""

    @abstractmethod
    async def fetch_models(self, timeout: float = 5) -> List[ModelInfo]:
        """Fetch the list of available models from the provider."""

    @abstractmethod
    async def check_model_connection(
        self,
        model_id: str,
        timeout: float = 5,  # pylint: disable=unused-argument
    ) -> tuple[bool, str]:
        """Check if a specific model is reachable/usable."""

    async def add_model(
        self,
        model_info: ModelInfo,
        target: str = "extra_models",
        timeout: float = 10,  # pylint: disable=unused-argument
    ) -> tuple[bool, str]:
        """Add a model to the provider's model list."""
        if model_info.id in {
            model.id for model in self.models + self.extra_models
        }:
            return False, f"Model '{model_info.id}' already exists"
        if target == "extra_models":
            self.extra_models.append(model_info)
        elif target == "models":
            self.models.append(model_info)
        else:
            return False, f"Invalid target '{target}' for adding model"
        return True, ""

    async def delete_model(
        self,
        model_id: str,
        timeout: float = 10,  # pylint: disable=unused-argument
    ) -> tuple[bool, str]:
        """Delete a model from the provider's model list."""
        self.extra_models = [
            model for model in self.extra_models if model.id != model_id
        ]
        return True, ""

    def update_config(self, config: Dict) -> None:
        """Update provider configuration with the given dictionary."""
        if "name" in config and config["name"] is not None:
            self.name = str(config["name"])
        if (
            not self.freeze_url
            and "base_url" in config
            and config["base_url"] is not None
        ):
            self.base_url = str(config["base_url"])
        if "api_key" in config and config["api_key"] is not None:
            self.api_key = str(config["api_key"])
        if (
            self.is_custom
            and "chat_model" in config
            and config["chat_model"] is not None
        ):
            self.chat_model = str(config["chat_model"])
        if "api_key_prefix" in config and config["api_key_prefix"] is not None:
            self.api_key_prefix = str(config["api_key_prefix"])
        if (
            "generate_kwargs" in config
            and config["generate_kwargs"] is not None
            and isinstance(config["generate_kwargs"], dict)
        ):
            self.generate_kwargs = config["generate_kwargs"]

    def get_chat_model_cls(self) -> Type[ChatModelBase]:
        """Return the chat model class associated with this provider."""
        import agentscope.model

        chat_model_cls = getattr(
            agentscope.model,
            self.chat_model,
            None,
        )
        if chat_model_cls is None:
            raise ValueError(
                f"Chat model class '{self.chat_model}' not found"
                f" for provider '{self.name}'.",
            )
        return chat_model_cls

    def has_model(self, model_id: str) -> bool:
        """Check if the provider has a model with the given ID."""
        return any(
            model.id == model_id for model in self.models + self.extra_models
        )

    @abstractmethod
    def get_chat_model_instance(self, model_id: str) -> ChatModelBase:
        """Return an instance of the chat model associated with this
        provider and model_id."""

    async def get_info(self, mock_secret: bool = True) -> ProviderInfo:
        """Return a ProviderInfo instance with the provider's details."""
        api_key = (
            self.api_key_prefix + "*" * 6
            if mock_secret and self.api_key
            else self.api_key
        )
        return ProviderInfo(
            id=self.id,
            name=self.name,
            base_url=self.base_url,
            api_key=api_key,
            chat_model=self.chat_model,
            models=self.models,
            extra_models=self.extra_models,
            api_key_prefix=self.api_key_prefix,
            is_local=self.is_local,
            is_custom=self.is_custom,
            support_model_discovery=self.support_model_discovery,
            # custom providers are assumed to not support connection check
            support_connection_check=self.support_connection_check
            and not self.is_custom,
            freeze_url=self.freeze_url,
            require_api_key=self.require_api_key,
            generate_kwargs=self.generate_kwargs,
        )


class DefaultProvider(Provider):
    """Default provider implementation with no-op methods."""

    async def check_connection(self, timeout: float = 5) -> tuple[bool, str]:
        if len(self.models) > 0:
            return True, ""
        return False, "No models available in the default provider"

    async def fetch_models(self, timeout: float = 5) -> List[ModelInfo]:
        return self.models

    async def check_model_connection(
        self,
        model_id: str,
        timeout: float = 5,
    ) -> tuple[bool, str]:
        if model_id in {model.id for model in self.models}:
            return True, ""
        return False, f"Model '{model_id}' not found"

    def update_config(self, config: Dict) -> None:
        pass

    def get_chat_model_instance(self, model_id: str) -> ChatModelBase:
        raise NotImplementedError(
            "DefaultProvider does not implement chat model",
        )
