# -*- coding: utf-8 -*-
"""
Provider Contract Tests

Ensures all Provider subclasses satisfy the base interface.

Usage:
    class TestOpenAIProviderContract(ProviderContractTest):
        def create_instance(self):
            return OpenAIProvider(id="openai", name="OpenAI", ...)
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any

import pytest

from .. import BaseContractTest


class ProviderContractTest(BaseContractTest):
    """
    Contract tests for Provider subclasses.

    All LLM providers (OpenAI, Anthropic, Ollama, etc.) must satisfy these contracts.
    """

    @abstractmethod
    def create_instance(self) -> Any:
        """Provide a configured provider instance."""

    # =========================================================================
    # Contract: Required Abstract Methods
    # =========================================================================

    def test_has_check_connection_method(self, instance):
        """Contract: All providers must implement check_connection()."""
        assert hasattr(
            instance,
            "check_connection",
        ), "Missing check_connection()"
        assert callable(getattr(instance, "check_connection"))

    def test_has_fetch_models_method(self, instance):
        """Contract: All providers must implement fetch_models()."""
        assert hasattr(instance, "fetch_models"), "Missing fetch_models()"
        assert callable(getattr(instance, "fetch_models"))

    def test_has_check_model_connection_method(self, instance):
        """Contract: All providers must implement check_model_connection()."""
        assert hasattr(
            instance,
            "check_model_connection",
        ), "Missing check_model_connection()"
        assert callable(getattr(instance, "check_model_connection"))

    # =========================================================================
    # Contract: Common Attributes
    # =========================================================================

    def test_has_provider_id(self, instance):
        """Contract: Providers must have id attribute."""
        assert hasattr(instance, "id"), "Missing id attribute"
        assert isinstance(instance.id, str), "id must be string"

    def test_has_provider_name(self, instance):
        """Contract: Providers must have name attribute."""
        assert hasattr(instance, "name"), "Missing name attribute"
        assert isinstance(instance.name, str), "name must be string"

    def test_has_base_url(self, instance):
        """Contract: Providers must have base_url attribute."""
        assert hasattr(instance, "base_url"), "Missing base_url attribute"

    def test_has_api_key(self, instance):
        """Contract: Providers must have api_key attribute."""
        assert hasattr(instance, "api_key"), "Missing api_key attribute"

    def test_has_models_list(self, instance):
        """Contract: Providers must have models list."""
        assert hasattr(instance, "models"), "Missing models attribute"

    def test_has_chat_model(self, instance):
        """Contract: Providers must have chat_model attribute."""
        assert hasattr(instance, "chat_model"), "Missing chat_model attribute"


# =============================================================================
# Example Implementations (TODO: Add real ones)
# =============================================================================

# Example usage:
# class TestOpenAIProviderContract(ProviderContractTest):
#     def create_instance(self):
#         from copaw.providers.openai_provider import OpenAIProvider
#         return OpenAIProvider(...)
