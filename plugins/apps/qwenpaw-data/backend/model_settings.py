# -*- coding: utf-8 -*-
"""Workspace model references. Credentials are resolved only for a new run."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ModelChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["inherit", "host", "local"] = "inherit"
    provider_id: str | None = Field(default=None, max_length=256)
    model_id: str | None = Field(default=None, max_length=256)

    @model_validator(mode="after")
    def reference(self):
        if self.source == "host":
            if not self.provider_id or not self.model_id:
                raise ValueError("Choose a provider and model")
        elif self.provider_id is not None or self.model_id is not None:
            raise ValueError(
                "Inherited/local choices do not accept model references",
            )
        return self


class ModelSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(default=0, ge=0)
    analysis: ModelChoice = Field(default_factory=ModelChoice)
    lightweight: ModelChoice = Field(default_factory=ModelChoice)
    databridge: ModelChoice = Field(default_factory=ModelChoice)


class ModelSettingsService:
    def __init__(self, root: Path):
        self.root = root
        self.lock = asyncio.Lock()

    def _path(self, scope):
        digest = hashlib.sha256(
            json.dumps(scope.model_dump(mode="json"), sort_keys=True).encode(),
        ).hexdigest()
        return self.root / f"{digest}.json"

    def load(self, scope):
        path = self._path(scope)
        if path.exists():
            return ModelSettings.model_validate_json(path.read_text())
        return ModelSettings()

    async def save(self, scope, settings: ModelSettings):
        async with self.lock:
            if settings.revision != self.load(scope).revision:
                raise HTTPException(
                    409,
                    "Settings changed. Reload before saving.",
                )
            settings = settings.model_copy(
                update={"revision": settings.revision + 1},
            )
            self.root.mkdir(parents=True, exist_ok=True)
            path = self._path(scope)
            temp = path.with_suffix(".tmp")
            temp.write_text(settings.model_dump_json(indent=2))
            os.replace(temp, path)
        return await self.describe(scope)

    @staticmethod
    def _manager():
        from qwenpaw.providers.provider_manager import ProviderManager

        return ProviderManager.get_instance()

    def _workspace_choice(self, scope):
        from qwenpaw.config.config import load_agent_config

        slot = load_agent_config(scope.workspace_id).active_model
        slot = slot or self._manager().get_active_model()
        return (
            ModelChoice(
                source="host",
                provider_id=slot.provider_id,
                model_id=slot.model,
            )
            if slot
            else None
        )

    def _host_model(self, choice):
        if choice is None:
            return None, "Choose a default model in main chat settings."
        provider = self._manager().get_provider(choice.provider_id)
        if provider is None or not provider.enabled:
            return None, "The selected provider is unavailable."
        if provider.chat_model not in {
            "OpenAIChatModel",
            "DashScopeChatModel",
        }:
            return (
                None,
                "Data requires an OpenAI-compatible or DashScope "
                "chat model.",
            )
        if not provider.get_model_info(choice.model_id):
            return None, "The selected model is no longer available."
        if not provider.api_key or not provider.base_url:
            return None, "Configure this provider in main chat settings."
        return {
            "provider_id": (
                "dashscope"
                if provider.chat_model == "DashScopeChatModel"
                else "openai"
            ),
            "model_id": choice.model_id,
            "api_key": provider.api_key,
            "base_url": provider.base_url,
        }, None

    def resolve(self, scope, settings=None):
        settings = settings or self.load(scope)
        workspace = self._workspace_choice(scope)
        selections = {}
        effective = {}
        for role in ("analysis", "lightweight", "databridge"):
            choice = getattr(settings, role)
            selection = choice
            if choice.source == "inherit":
                selection = (
                    workspace if role == "analysis" else selections["analysis"]
                )
            selections[role] = selection
            if selection is not None and selection.source == "local":
                effective[role] = (None, None)
            else:
                effective[role] = self._host_model(selection)
        return selections, effective

    async def runtime(self, scope):
        settings = self.load(scope)
        selections, effective = self.resolve(scope, settings)
        payload = {
            "inherit_analysis": [
                role
                for role in ("lightweight", "databridge")
                if getattr(settings, role).source == "inherit"
            ],
        }
        for role, (model, error) in effective.items():
            if error:
                raise HTTPException(409, error)
            if (
                selections[role] is not None
                and selections[role].source == "local"
            ):
                payload[role] = None
            else:
                payload[role] = model
        return payload

    async def describe(self, scope):
        settings = self.load(scope)
        selections, resolved = self.resolve(scope, settings)
        workspace = self._workspace_choice(scope)
        workspace_model, workspace_error = self._host_model(workspace)
        roles = {}
        for role, selection in selections.items():
            model, error = resolved[role]
            local = selection is not None and selection.source == "local"
            roles[role] = {
                "model_id": selection.model_id if selection else None,
                "provider_id": selection.provider_id if selection else None,
                "source": (
                    "app-local"
                    if local
                    else (
                        "workspace default"
                        if role == "analysis"
                        and settings.analysis.source == "inherit"
                        else (
                            "analysis model"
                            if getattr(settings, role).source == "inherit"
                            else "override"
                        )
                    )
                ),
                "configured": model is not None,
                "error": error,
            }
        providers = []
        for provider in await self._manager().list_provider_info():
            if provider.enabled and provider.chat_model in {
                "OpenAIChatModel",
                "DashScopeChatModel",
            }:
                models = {
                    m.id: m.name
                    for m in [
                        *provider.models,
                        *provider.extra_models,
                        *provider.discovered_models,
                    ]
                }
                providers.append(
                    {
                        "id": provider.id,
                        "name": provider.name,
                        "models": [
                            {"id": k, "name": v} for k, v in models.items()
                        ],
                    },
                )
        return {
            "workspace_id": scope.workspace_id,
            "workspace_default": {
                "model_id": workspace.model_id if workspace else None,
                "provider_id": workspace.provider_id if workspace else None,
                "configured": workspace_model is not None,
                "error": workspace_error,
            },
            "settings": settings.model_dump(),
            "effective": roles,
            "providers": providers,
        }
