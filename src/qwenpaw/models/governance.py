"""Authorize runtime models against the database, never against client claims."""

from uuid import NAMESPACE_URL, uuid5

from ..access.capabilities import Capability
from ..access.service import AuthorizationService
from ..providers.api_projection import project_provider_info
from .records import CatalogModel


class ModelAccessError(ValueError):
    pass


class ModelGovernanceService:
    def __init__(self, repository, provider_manager):
        self.repository = repository
        self.manager = provider_manager

    @staticmethod
    def require_manage(actor):
        AuthorizationService().require(actor, Capability.MODELS_MANAGE)

    async def _runtime_catalog(self, manager):
        result = []
        for provider in await manager.list_provider_info():
            if provider.require_api_key and not provider.api_key:
                continue
            if not provider.require_api_key and not provider.base_url:
                continue
            runtime = manager.get_provider(provider.id)
            if runtime is None:
                continue
            safe_info = project_provider_info(provider)
            provider_uuid = uuid5(
                NAMESPACE_URL, "qwenpaw:model-provider:" + provider.id
            )
            for model in safe_info.models + safe_info.extra_models:
                if not runtime.has_model(model.id):
                    continue
                result.append(
                    CatalogModel(
                        id=str(uuid5(provider_uuid, model.id)),
                        provider_id=provider.id,
                        provider_name=safe_info.name,
                        model=model.id,
                        name=model.name,
                        supports_image=model.supports_image,
                        supports_video=model.supports_video,
                        max_input_length=(
                            runtime.get_context_size(model.id)
                            if hasattr(runtime, "get_context_size")
                            else model.max_input_length
                        ),
                    ).model_dump()
                )
        return list({row["id"]: row for row in result}.values())

    async def preview_import(self, actor, provider_manager):
        self.require_manage(actor)
        return await self._runtime_catalog(provider_manager)

    async def import_metadata(self, actor, provider_manager):
        rows = await self.preview_import(actor, provider_manager)
        await self.repository.import_metadata(rows, actor.user_id)
        return rows

    async def list_catalog(self, actor, agent_id):
        AuthorizationService().require(actor, Capability.PLATFORM_USE)
        status = await self.repository.get_status()
        runtime = await self._runtime_catalog(self.manager)
        stored = {str(row["id"]): row for row in await self.repository.list_models()}
        if not status["enforced"]:
            return {
                "enforced": False,
                "models": [
                    row
                    for row in runtime
                    if row["id"] not in stored
                    or (
                        stored[row["id"]]["status"] == "active"
                        and stored[row["id"]]["provider_status"] == "active"
                    )
                ],
            }
        admin = AuthorizationService().is_allowed(actor, Capability.MODELS_MANAGE)
        allowed = (
            await self.repository.allowed_models(actor.user_id, agent_id)
            if not admin
            else set(stored)
        )
        return {
            "enforced": True,
            "models": [
                row
                for row in runtime
                if row["id"] in allowed
                and row["id"] in stored
                and stored[row["id"]]["status"] == "active"
                and stored[row["id"]]["provider_status"] == "active"
            ],
        }

    async def require_model(self, actor, agent_id, provider_id, model_key):
        catalog = await self.list_catalog(actor, agent_id)
        for row in catalog["models"]:
            if row["provider_id"] == provider_id and row["model"] == model_key:
                return row
        raise ModelAccessError("model_unavailable_or_forbidden")

    async def set_user_grant(self, actor, model_id, user_id, enabled):
        self.require_manage(actor)
        return await self.repository.set_user_grant(
            model_id, user_id, enabled, actor.user_id
        )

    async def set_model_status(self, actor, model_id, enabled):
        self.require_manage(actor)
        return await self.repository.set_model_status(model_id, enabled)

    async def set_enforced(self, actor, enabled, expected_version, reason):
        self.require_manage(actor)
        return await self.repository.set_enforced(
            enabled, expected_version, reason, actor.user_id
        )

    async def preview_enforcement(self, actor, defaults):
        self.require_manage(actor)
        runtime = {row["id"]: row for row in await self._runtime_catalog(self.manager)}
        active = {
            row["id"]
            for row in await self.repository.list_models()
            if row["status"] == "active"
            and row["provider_status"] == "active"
            and row["id"] in runtime
        }
        uncovered, affected = [], []
        for user in await self.repository.list_users():
            allowed = await self.repository.allowed_models(user["id"], None)
            if not active.intersection(allowed):
                uncovered.append({"id": str(user["id"]), "username": user["username"]})
            for default in defaults:
                permitted = await self.repository.allowed_models(
                    user["id"], default.get("agent_id")
                )
                if not any(
                    row["provider_id"] == default["provider_id"]
                    and row["model"] == default["model"]
                    and mid in permitted
                    and mid in active
                    for mid, row in runtime.items()
                ):
                    affected.append({"username": user["username"], **default})
        return {"uncovered_users": uncovered, "affected_defaults": affected}
