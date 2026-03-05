# -*- coding: utf-8 -*-
"""Definition of Provider."""

from abc import ABC, abstractmethod
from typing import Dict, List
from pydantic import BaseModel, Field


class ModelInfo(BaseModel):
    id: str = Field(..., description="Model identifier used in API calls")
    name: str = Field(..., description="Human-readable model name")


class Provider(BaseModel, ABC):
    """Represents a provider instance with its configuration."""

    id: str = Field(..., description="Provider identifier")
    name: str = Field(..., description="Human-readable provider name")
    base_url: str = Field(..., description="API base URL")
    api_key: str = Field(..., description="API key for authentication")
    chat_model: str = Field(
        ...,
        description="Chat model class name (e.g., 'OpenAIChatModel')",
    )
    models: List[ModelInfo] = Field(
        default_factory=list,
        description="List of available models",
    )
    api_key_prefix: str = Field(
        default="",
        description="Expected prefix for the API key (e.g., 'sk-')",
    )
    base_url_env_var: str = Field(
        default="",
        description=(
            "Environment variable name to override base URL "
            "(e.g., 'OLLAMA_HOST')"
        ),
    )

    @abstractmethod
    async def check_connection(self, timeout: float = 5) -> bool:
        """Check if the provider is reachable with the current config."""

    @abstractmethod
    async def fetch_models(self, timeout: float = 5) -> List[ModelInfo]:
        """Fetch the list of available models from the provider."""

    @abstractmethod
    async def check_model_connection(
        self,
        model_id: str,
        timeout: float = 5,
    ) -> bool:
        """Check if a specific model is reachable/usable."""

    @abstractmethod
    async def update_config(self, config: Dict) -> None:
        """Update provider configuration with the given dictionary."""

    async def add_model(
        self,
        model_info: ModelInfo,
        timeout: float = 10,
    ) -> None:
        """Add a model to the provider's model list."""
        raise NotImplementedError(
            "This provider does not support adding models.",
        )

    async def delete_model(self, model_id: str, timeout: float = 10) -> None:
        """Delete a model from the provider's model list."""
        raise NotImplementedError(
            "This provider does not support deleting models.",
        )
