# -*- coding: utf-8 -*-
"""Shared validation for global and per-agent model selections."""

from fastapi import HTTPException

from ...config.config import ModelType
from ...exceptions import AppBaseException
from ...providers.provider_manager import ProviderManager
from ...providers.typesafe_provider import (
    TypeSafeEvaluationError,
    validate_decision_provider,
)


def validate_model_slot(
    manager: ProviderManager,
    provider_id: str,
    model_id: str,
    model_type: ModelType = "chat",
) -> None:
    """Validate that the provider and model exist without mutating state."""
    provider = manager.get_provider(provider_id)
    if provider is None:
        raise HTTPException(
            status_code=404,
            detail=f"Provider '{provider_id}' not found.",
        )
    try:
        provider.validate_model_selection(model_id, model_type)
        if model_type == "decision" and provider.is_custom:
            validate_decision_provider(provider_id, provider)
    except (AppBaseException, TypeSafeEvaluationError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
