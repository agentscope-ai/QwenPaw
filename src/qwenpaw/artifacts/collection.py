"""运行时和工具结束时共享的会话产物收集入口。"""
from __future__ import annotations

from uuid import UUID

from ..config.context import get_current_request_context
from ..identity.runtime import get_identity_schema, is_multi_user_enabled
from .repository import PostgresArtifactRepository
from .service import ArtifactCollectionFailure, ArtifactCollectionResult, ArtifactService


async def collect_current_session_artifacts(context: dict | None = None) -> ArtifactCollectionResult:
    """单用户不登记；多用户缺身份或归档异常以可重试失败返回。"""
    if not is_multi_user_enabled():
        return ArtifactCollectionResult()
    context = get_current_request_context() if context is None else context
    try:
        context = context or {}
        user_id = UUID(str(context["user_id"]))
        conversation_id = UUID(str(context["conversation_id"]))
        agent_key = context["agent_id"]
        if not agent_key:
            raise ValueError("authenticated_artifact_context_required")
        return await ArtifactService(repository=PostgresArtifactRepository(schema=get_identity_schema())).collect_session(
            owner_user_id=user_id, agent_key=agent_key, conversation_id=conversation_id,
        )
    except Exception as exc:
        return ArtifactCollectionResult(failures=(ArtifactCollectionFailure(None, f"artifact_collection_failed_retryable: {exc}"),))
