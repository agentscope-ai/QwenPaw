# -*- coding: utf-8 -*-
"""Shared execution-authorization decision boundary."""

from __future__ import annotations

import secrets
from collections.abc import Mapping
from typing import Any

from domain.errors import ConflictError
from models.config import (
    get_image_model_name,
    get_video_backend,
    get_video_model_name,
)
from services.runtime_files.execution_models import (
    ExecutionAuthorizationRecord,
    ExecutionAuthorizationStatus,
)
from services.runtime_files.execution_store import ProjectExecutionStore
from services.specialist_tools import SpecialistToolSpec


def execution_provider_model(
    spec: SpecialistToolSpec,
    tool_arguments: Mapping[str, Any] | None = None,
) -> tuple[str, str]:
    """Resolve the exact provider/model identity covered by approval."""

    arguments = tool_arguments or {}
    mode = str(arguments.get("mode") or "").strip().casefold()
    if spec.provider_kind == "image":
        from models.image import get_image_backend

        if mode == "translate":
            from models.config import get_image_translate_model_name

            return "dashscope", get_image_translate_model_name()
        return get_image_backend().casefold(), get_image_model_name()
    if spec.provider_kind == "video":
        from models.video_capabilities import (
            effective_video_model_name,
            video_backend_key,
        )

        backend = get_video_backend()
        configured = get_video_model_name()
        return backend, effective_video_model_name(
            configured,
            mode,
            video_backend_key(configured, backend),
        )
    if spec.provider_kind == "tts":
        from models.config import get_tts_model_name

        return "dashscope", get_tts_model_name()
    if spec.provider_kind == "s2v":
        from models.config import get_s2v_model_name

        return "dashscope", get_s2v_model_name()
    return str(spec.provider_kind or "creator-tool"), "configured"


def decide_execution_authorization(
    store: ProjectExecutionStore,
    project_id: str,
    authorization_id: str,
    *,
    authorization_token: str,
    target_status: ExecutionAuthorizationStatus,
    decision: Mapping[str, Any] | None,
) -> ExecutionAuthorizationRecord:
    snapshot = store.get_authorization_snapshot(
        project_id,
        authorization_id,
    )
    current = snapshot.value
    if not secrets.compare_digest(
        current.authorization_token,
        authorization_token,
    ):
        raise ConflictError("execution authorization token 不匹配")
    if current.status is target_status:
        return current
    if current.status is not ExecutionAuthorizationStatus.PENDING:
        raise ConflictError("execution authorization was already decided")
    if target_status is ExecutionAuthorizationStatus.APPROVED:
        if decision is None:
            raise ConflictError("批准缺少执行参数")
        if (
            decision.get("provider") != current.requested_provider
            or decision.get("model") != current.requested_model
        ):
            raise ConflictError("批准的 provider/model 必须与原执行请求一致")
        requested_candidates = current.requested_candidates or 1
        if int(decision.get("maxCandidates") or 0) > requested_candidates:
            raise ConflictError("批准的候选数量不能超过原执行请求")
    return store.decide_execution_authorization(
        project_id,
        authorization_id,
        authorization_token=authorization_token,
        status=target_status,
        decision=decision,
        expected_checksum=snapshot.checksum,
    )


__all__ = ["decide_execution_authorization", "execution_provider_model"]
