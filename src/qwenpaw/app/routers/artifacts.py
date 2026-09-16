"""当前用户、当前 Agent 的已登记产物 API。"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ...access.dependencies import get_actor
from ...artifacts.repository import PostgresArtifactRepository
from ...artifacts.service import ArtifactNotFound, ArtifactService
from ...identity.runtime import get_identity_schema
from ..agent_context import get_agent_for_request

router = APIRouter(prefix="/console/artifacts", tags=["artifacts"])


class CollectArtifactsRequest(BaseModel):
    conversation_id: UUID | None = None


def _conversation_repository(user_id: UUID):
    from ..chats.repo.postgres_repo import PostgresConversationRepository

    return PostgresConversationRepository(
        schema=get_identity_schema(), request_user_id=user_id,
    )


@router.post("/collect")
async def collect_artifacts(request: Request, payload: CollectArtifactsRequest | None = None):
    """Retry only database-owned sessions in the selected agent's private tree."""
    from ...access.agent_repository import agent_database_id

    service, user_id, agent_key = await _scope(request)
    conversations = await _conversation_repository(user_id).list_conversations(owner_user_id=user_id)
    requested = payload.conversation_id if payload else None
    eligible = [
        item for item in conversations
        if item.owner_user_id == user_id and item.agent_id == agent_database_id(agent_key)
        and (requested is None or item.id == requested)
    ]
    if requested and not eligible:
        raise HTTPException(status_code=404, detail="chat_not_found")
    existing = {
        item.id for item in await service.list_active(owner_user_id=user_id, agent_key=agent_key)
    }
    collected = 0
    failures = []
    for conversation in eligible:
        result = await service.collect_session(
            owner_user_id=user_id, agent_key=agent_key, conversation_id=conversation.id,
        )
        fresh = {item.id for item in result.artifacts} - existing
        collected += len(fresh)
        existing.update(fresh)
        failures.extend({"path": item.path.name if item.path else "", "error": item.error} for item in result.failures)
    return {"collected": collected, "failures": failures}


class ArtifactResponse(BaseModel):
    id: UUID
    relative_path: str
    original_name: str
    media_type: str
    size: int
    sha256: str
    source_tool: str
    conversation_id: UUID | None
    status: str
    created_at: datetime
    deleted_at: datetime | None

    @classmethod
    def from_record(cls, artifact) -> "ArtifactResponse":
        return cls(**{field: getattr(artifact, field) for field in cls.model_fields})


async def _scope(request: Request):
    actor = get_actor(request)
    if actor.user_id is None:
        raise HTTPException(status_code=401, detail="not_authenticated")
    workspace = await get_agent_for_request(request)
    service = ArtifactService(repository=PostgresArtifactRepository(schema=get_identity_schema()))
    return service, actor.user_id, workspace.agent_id


@router.get("", response_model=list[ArtifactResponse])
async def list_artifacts(request: Request) -> list[ArtifactResponse]:
    service, user_id, agent_key = await _scope(request)
    return [ArtifactResponse.from_record(item) for item in await service.list_active(owner_user_id=user_id, agent_key=agent_key)]


@router.get("/{artifact_id}/download")
async def download_artifact(request: Request, artifact_id: UUID):
    service, user_id, agent_key = await _scope(request)
    try:
        artifact, path = await service.download_path(owner_user_id=user_id, agent_key=agent_key, artifact_id=artifact_id)
    except ArtifactNotFound as exc:
        raise HTTPException(status_code=404, detail="artifact_not_found") from exc
    return FileResponse(path, filename=artifact.original_name, media_type=artifact.media_type)


@router.delete("/{artifact_id}", response_model=ArtifactResponse)
async def delete_artifact(request: Request, artifact_id: UUID) -> ArtifactResponse:
    service, user_id, agent_key = await _scope(request)
    try:
        artifact = await service.delete(owner_user_id=user_id, agent_key=agent_key, artifact_id=artifact_id)
    except ArtifactNotFound as exc:
        raise HTTPException(status_code=404, detail="artifact_not_found") from exc
    return ArtifactResponse.from_record(artifact)
