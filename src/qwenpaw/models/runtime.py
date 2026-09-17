"""Runtime assembly and explicitly trusted selection boundaries."""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from ..agents.effective_model import resolve_effective_model
from ..config.config import ModelSlotConfig, load_agent_config
from ..identity.runtime import get_identity_schema, is_multi_user_enabled
from ..access.agent_repository import agent_database_id
from .governance import ModelGovernanceService, ModelAccessError
from .repository import PostgresModelRepository


class LegacyCatalogRepository:
    async def get_status(self):
        return {"enforced": False, "version": 0}

    async def list_models(self):
        return []


async def require_transcription_service(provider_id, model_key):
    """ASR is admin-enabled infrastructure; only registered disable flags apply."""
    if not is_multi_user_enabled():
        return
    from sqlalchemy import text

    repository = PostgresModelRepository(schema=get_identity_schema())
    async with repository.session_factory() as session:
        rows = (await session.execute(text(f"""
            SELECT p.status AS provider_status, m.model_key, m.status AS model_status
            FROM {repository.table('model_providers')} p
            LEFT JOIN {repository.table('models')} m ON m.provider_id=p.id
            WHERE p.name=:provider_id
        """), {"provider_id": provider_id})).mappings().all()
    for row in rows:
        if row["provider_status"] != "active" or (
            model_key is not None and row["model_key"] == model_key and row["model_status"] != "active"
        ):
            raise ModelAccessError("transcription_service_unavailable")


def get_model_service(manager):
    repository = (
        PostgresModelRepository(schema=get_identity_schema())
        if is_multi_user_enabled()
        else LegacyCatalogRepository()
    )
    return ModelGovernanceService(repository, manager)


@dataclass(frozen=True)
class TrustedPublication:
    """Only a future server publication resolver may construct this context."""

    provider_id: str
    model: str


def validate_candidate(payload):
    data = payload if isinstance(payload, dict) else payload.model_dump()
    context = data.get("request_context") or {}
    for source in (data, context):
        if any(
            key in source
            for key in (
                "shared_app_id",
                "published_model_id",
                "publication",
                "trusted_model",
            )
        ):
            raise ValueError("authority_unavailable")
    if data.get("model_slot_override") is not None:
        raise ValueError("model_slot_override_not_supported")
    if "requested_model" not in data:
        return False, None
    raw = data["requested_model"]
    if raw is None:
        return True, None
    slot = ModelSlotConfig.model_validate(raw)
    if not slot.provider_id or not slot.model:
        raise ValueError("invalid_requested_model")
    return True, slot.model_dump()


async def resolve_selection(
    service, actor, agent_id, config, manager, override, publication=None
):
    if publication is not None:
        if not isinstance(publication, TrustedPublication):
            raise ValueError("authority_unavailable")
        slot = ModelSlotConfig(
            provider_id=publication.provider_id, model=publication.model
        )
        source = "publication"
    elif override is not None:
        slot = ModelSlotConfig.model_validate(override)
        if not slot.provider_id or not slot.model:
            raise ModelAccessError("invalid_model_override")
        source = "conversation"
    else:
        slot = resolve_effective_model(config, manager)
        source = "agent" if getattr(config, "active_model", None) else "platform"
    row = await service.require_model(actor, agent_id, slot.provider_id, slot.model)
    return {
        "active_llm": slot.model_dump(),
        "source": source,
        "model_override": override,
        "effective_max_input_length": row["max_input_length"],
        "locked": publication is not None,
    }


async def conversation_override(service, actor, workspace, chat):
    if not is_multi_user_enabled():
        return chat.meta.get("model_override")
    record = await workspace.chat_manager.conversation_repository.with_user(
        actor.user_id
    ).get_conversation(UUID(chat.id))
    if (
        record is None
        or record.owner_user_id != actor.user_id
        or record.agent_id != agent_database_id(workspace.agent_id)
    ):
        raise ModelAccessError("conversation_not_found")
    if record.model_override_id is None:
        return None
    rows = await service.repository.list_models()
    for row in rows:
        if str(row["id"]) == str(record.model_override_id):
            return {"provider_id": row["provider_id"], "model": row["model"]}
    raise ModelAccessError("model_override_not_found")


async def trusted_publication_for_conversation(repository, conversation):
    """只从已持久化会话关系构造可信发布模型。"""
    if conversation.publication_id is None:
        return None
    publication = await repository.get_publication(conversation.publication_id)
    if publication is None or publication.shared_app_id != conversation.shared_app_id:
        raise ModelAccessError("publication_not_found")
    model = publication.immutable_manifest.get("model") or {}
    if not model.get("provider_id") or not model.get("model"):
        raise ModelAccessError("publication_model_unavailable")
    return TrustedPublication(
        provider_id=str(model["provider_id"]),
        model=str(model["model"]),
    )


async def persist_selection(service, actor, workspace, chat, selection):
    row = None
    if selection is not None:
        row = await service.require_model(
            actor, workspace.agent_id, selection["provider_id"], selection["model"]
        )
    if is_multi_user_enabled():
        # Compatibility still needs a registered FK; registration remains an explicit admin step.
        if row is not None:
            registered = {item["id"] for item in await service.repository.list_models()}
            if row["id"] not in registered:
                raise ModelAccessError("model_metadata_initialization_required")
        result = await workspace.chat_manager.conversation_repository.with_user(
            actor.user_id
        ).set_model_override(
            UUID(chat.id),
            expected_agent_id=agent_database_id(workspace.agent_id),
            model_override_id=UUID(row["id"]) if row else None,
            updated_at=datetime.now(UTC),
        )
        if result is None:
            raise ModelAccessError("conversation_not_found")
    else:
        await workspace.chat_manager.set_legacy_model_override(chat.id, selection)


async def prepare_console_model(request, workspace, chat, request_data, native_payload):
    from fastapi import HTTPException
    from sqlalchemy.exc import SQLAlchemyError
    from ..access.dependencies import get_actor

    actor = get_actor(request)
    service = get_model_service(request.app.state.provider_manager)
    try:
        present, selection = validate_candidate(request_data)
        publication = None
        if is_multi_user_enabled():
            conversation_repository = workspace.chat_manager.conversation_repository
            if conversation_repository is None or actor.user_id is None:
                raise ModelAccessError("conversation_authority_unavailable")
            conversation = await conversation_repository.with_user(
                actor.user_id
            ).get_conversation(UUID(chat.id))
            if conversation is None:
                raise ModelAccessError("conversation_not_found")
            if conversation.publication_id is not None:
                if present:
                    raise ModelAccessError("publication_model_locked")
                from ..publications.repository import PostgresSharedAppRepository

                publication_repository = PostgresSharedAppRepository(
                    schema=get_identity_schema()
                )
                app = await publication_repository.get_app(conversation.shared_app_id)
                if (
                    app is None
                    or app.status != "active"
                    or app.current_publication_id != conversation.publication_id
                ):
                    raise ModelAccessError("publication_retired")
                publication = await trusted_publication_for_conversation(
                    publication_repository,
                    conversation,
                )
        override = None if publication is not None else (
            selection
            if present
            else await conversation_override(service, actor, workspace, chat)
        )
        resolved = await resolve_selection(
            service,
            actor,
            workspace.agent_id,
            load_agent_config(workspace.agent_id),
            service.manager,
            override,
            publication=publication,
        )
        if present and publication is None:
            await persist_selection(service, actor, workspace, chat, selection)
    except (SQLAlchemyError, OSError) as exc:
        raise HTTPException(
            status_code=503, detail="model_authority_unavailable"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    native_payload["model_slot_override"] = resolved["active_llm"]
    # This object never comes from request JSON; the builder revalidates it immediately before construction.
    native_payload["_model_authority"] = (
        actor,
        workspace.agent_id,
        resolved["active_llm"],
    )
    return resolved


async def recheck_model_authority(request, manager):
    authority = getattr(request, "_model_authority", None)
    if authority is None:
        return None
    actor, agent_id, slot = authority
    from ..access.actor import ActorContext

    if not isinstance(actor, ActorContext):
        raise ModelAccessError("authority_unavailable")
    await get_model_service(manager).require_model(
        actor, agent_id, slot["provider_id"], slot["model"]
    )
    return ModelSlotConfig.model_validate(slot)


async def require_no_model_references(manager, provider_id, model_key=None):
    def matches(slot):
        return (
            slot is not None
            and slot.provider_id == provider_id
            and (model_key is None or slot.model == model_key)
        )

    if matches(manager.get_active_model()):
        raise ValueError("model_in_use: platform_default")
    from ..config.utils import load_config

    config = load_config()
    audio = config.agents
    if (
        getattr(audio, "transcription_provider_id", None) == provider_id
        and (
            model_key is None
            or getattr(audio, "transcription_model", None) == model_key
        )
    ):
        raise ValueError("model_in_use: voice_transcription")
    for agent_id in config.agents.profiles:
        if matches(load_agent_config(agent_id).active_model):
            raise ValueError("model_in_use: agent_default:" + agent_id)
    if not is_multi_user_enabled():
        from ..app.chats.repo import JsonChatRepository

        referenced_by = None
        try:
            for agent_id, profile in config.agents.profiles.items():
                chats = await JsonChatRepository(
                    Path(profile.workspace_dir) / "chats.json"
                ).load()
                for chat in chats.chats:
                    override = chat.meta.get("model_override")
                    if override is None:
                        continue
                    slot = ModelSlotConfig.model_validate(override)
                    if matches(slot):
                        referenced_by = f"{agent_id}:{chat.id}"
        except (OSError, TypeError, ValueError) as exc:
            raise ValueError("model_reference_authority_unavailable") from exc
        if referenced_by is not None:
            raise ValueError(
                "model_in_use: conversation_override:" + referenced_by
            )
    else:
        repo = PostgresModelRepository(schema=get_identity_schema())
        ids = [
            row["id"]
            for row in await repo.list_models()
            if row["provider_id"] == provider_id
            and (model_key is None or row["model"] == model_key)
        ]
        references = await repo.references(ids)
        if references:
            raise ValueError("model_in_use: " + str(references))
