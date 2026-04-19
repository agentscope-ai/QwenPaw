# -*- coding: utf-8 -*-
"""Structured infer API for planner-like orchestrators."""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Optional
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from ...agents.model_factory import create_model_and_formatter
from ...app.agent_context import set_current_agent_id, set_current_session_id
from ...config.config import load_agent_config
from ...providers.provider_manager import ProviderManager
from ..agent_context import get_agent_for_request

logger = logging.getLogger(__name__)

PROMPT_VERSION = "qwenpaw-session-infer-v2"

router = APIRouter(prefix="/qwenpaw", tags=["qwenpaw"])


class SessionInferIntent(BaseModel):
    model_config = ConfigDict(extra="allow")

    intentCode: str = Field(default="")
    executionMode: str = Field(default="")
    description: str = Field(default="")
    roleCode: Optional[str] = None
    sqlTemplateCode: Optional[str] = None
    selectedTableId: Optional[int] = None
    slotKeys: list[str] = Field(default_factory=list)
    slotSchema: dict[str, Any] = Field(default_factory=dict)


class SessionInferRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    question: str = Field(..., min_length=1)
    traceId: str = Field(default="")
    intents: list[SessionInferIntent] = Field(default_factory=list)
    routingPolicy: dict[str, Any] = Field(default_factory=dict)
    outputSchema: dict[str, Any] = Field(default_factory=dict)
    sessionId: Optional[str] = None
    conversationId: Optional[str] = None
    chatId: Optional[str] = None
    agentId: Optional[str] = None


class CandidatePlan(BaseModel):
    intentCode: str
    executionMode: str
    confidence: float
    slots: dict[str, Any] = Field(default_factory=dict)
    needClarify: bool = False
    clarifyQuestion: Optional[str] = None
    roleCode: Optional[str] = None
    sqlTemplateCode: Optional[str] = None
    selectedTableId: Optional[int] = None


class ModelMeta(BaseModel):
    provider: str
    model: str
    promptVersion: str
    requestId: str


class SessionInferData(BaseModel):
    candidatePlan: CandidatePlan
    modelMeta: ModelMeta


class SessionInferResponse(BaseModel):
    code: int = 0
    message: str = "ok"
    data: Optional[SessionInferData] = None


class SessionInferStructuredCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intentCode: str = Field(..., min_length=1)
    executionMode: str = Field(..., min_length=1)
    confidence: float = Field(..., ge=0.0, le=1.0)
    slots: dict[str, Any]
    needClarify: bool
    clarifyQuestion: Optional[str] = None
    roleCode: Optional[str] = None
    sqlTemplateCode: Optional[str] = None
    selectedTableId: Optional[int] = None


class SessionInferStructuredOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidatePlan: SessionInferStructuredCandidate
    modelMeta: dict[str, Any] = Field(default_factory=dict)


def _extract_text_from_chunk(chunk: Any) -> str:
    content = getattr(chunk, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return ""


def _extract_text_from_response(response: Any) -> str:
    text = getattr(response, "text", None)
    if isinstance(text, str):
        return text
    content = getattr(response, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                item_text = item.get("text")
                if isinstance(item_text, str):
                    parts.append(item_text)
        return "".join(parts)
    if isinstance(response, str):
        return response
    return ""


async def _collect_model_text(response: Any) -> str:
    if hasattr(response, "__aiter__"):
        accumulated = ""
        async for chunk in response:  # type: ignore[union-attr]
            text = _extract_text_from_chunk(chunk)
            if not text:
                continue
            # Some providers emit cumulative text on each chunk.
            if len(text) >= len(accumulated) and text.startswith(accumulated):
                accumulated = text
            else:
                accumulated += text
        return accumulated
    return _extract_text_from_response(response)


def _normalize_structured_metadata(raw: Any) -> Optional[dict[str, Any]]:
    if isinstance(raw, dict):
        return raw
    model_dump = getattr(raw, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        if isinstance(dumped, dict):
            return dumped
    return None


def _extract_intent_code_from_metadata(metadata: dict[str, Any]) -> str:
    candidate_raw = metadata.get("candidatePlan")
    if isinstance(candidate_raw, dict):
        intent_code = str(candidate_raw.get("intentCode") or "").strip()
        if intent_code:
            return intent_code
    return str(metadata.get("intentCode") or "").strip()


def _metadata_is_usable(metadata: Optional[dict[str, Any]]) -> bool:
    if not isinstance(metadata, dict):
        return False
    candidate_raw = metadata.get("candidatePlan")
    if isinstance(candidate_raw, dict):
        intent_code = str(candidate_raw.get("intentCode") or "").strip()
        execution_mode = str(candidate_raw.get("executionMode") or "").strip()
        return bool(intent_code and execution_mode)
    intent_code = str(metadata.get("intentCode") or "").strip()
    execution_mode = str(metadata.get("executionMode") or "").strip()
    return bool(intent_code and execution_mode)


def _extract_candidate_from_tool_content(content: Any) -> Optional[dict[str, Any]]:
    if not isinstance(content, list):
        return None

    for block in reversed(content):
        if not isinstance(block, dict):
            continue
        if block.get("type") != "tool_use":
            continue

        block_input = block.get("input")
        if isinstance(block_input, dict):
            return block_input

        raw_input = block.get("raw_input")
        if isinstance(raw_input, str) and raw_input.strip():
            try:
                parsed = json.loads(raw_input)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
    return None


async def _collect_model_output(
    response: Any,
) -> tuple[str, Optional[dict[str, Any]], Optional[dict[str, Any]]]:
    if hasattr(response, "__aiter__"):
        accumulated = ""
        metadata: Optional[dict[str, Any]] = None
        tool_candidate: Optional[dict[str, Any]] = None
        async for chunk in response:  # type: ignore[union-attr]
            text = _extract_text_from_chunk(chunk)
            if text:
                # Some providers emit cumulative text on each chunk.
                if len(text) >= len(accumulated) and text.startswith(accumulated):
                    accumulated = text
                else:
                    accumulated += text
            chunk_metadata = _normalize_structured_metadata(
                getattr(chunk, "metadata", None),
            )
            if chunk_metadata:
                metadata = chunk_metadata
            candidate = _extract_candidate_from_tool_content(
                getattr(chunk, "content", None),
            )
            if candidate:
                tool_candidate = candidate
        return accumulated, metadata, tool_candidate

    response_text = _extract_text_from_response(response)
    metadata = _normalize_structured_metadata(getattr(response, "metadata", None))
    tool_candidate = _extract_candidate_from_tool_content(
        getattr(response, "content", None),
    )
    return response_text, metadata, tool_candidate


def _build_clarify_fallback_output(
    payload: SessionInferRequest,
) -> dict[str, Any]:
    first_intent = payload.intents[0]
    clarify_question = "请确认客户编号与产品后，我再为你查询。"
    return {
        "candidatePlan": {
            "intentCode": str(first_intent.intentCode or "").strip(),
            "executionMode": str(first_intent.executionMode or "").strip(),
            "confidence": 0.0,
            "slots": {},
            "needClarify": True,
            "clarifyQuestion": clarify_question,
            "roleCode": first_intent.roleCode,
            "sqlTemplateCode": first_intent.sqlTemplateCode,
            "selectedTableId": first_intent.selectedTableId,
        },
        "modelMeta": {},
    }


def _extract_first_json_object(raw_text: str) -> dict[str, Any]:
    text = raw_text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        parsed = json.loads(text[start : end + 1])
        if isinstance(parsed, dict):
            return parsed

    raise ValueError("Model output is not a valid JSON object")


def _build_messages(payload: SessionInferRequest) -> list[dict[str, Any]]:
    intents_json = json.dumps(
        [intent.model_dump() for intent in payload.intents],
        ensure_ascii=False,
        indent=2,
    )
    routing_policy_json = json.dumps(
        payload.routingPolicy or {},
        ensure_ascii=False,
        indent=2,
    )
    output_schema_json = json.dumps(
        payload.outputSchema or {},
        ensure_ascii=False,
        indent=2,
    )
    system_prompt = (
        "你是受控查询规划链路中的意图路由器。\n"
        "请从给定 intents 中只选择一个意图，并抽取可用 slots。\n"
        "仅返回 JSON，不要 markdown，不要解释说明。\n"
        "证据优先级：\n"
        "1) intentName/domain/triggerPhrases\n"
        "2) mustConditions/forbiddenConditions/disambiguation\n"
        "3) slotSchema + slotKeys\n"
        "4) description（仅辅助）\n"
        "硬约束：\n"
        "- intentCode 必须来自 intents.intentCode。\n"
        "- executionMode 必须与选中 intent 一致。\n"
        "- roleCode/sqlTemplateCode/selectedTableId 必须来自选中 intent。\n"
        "- 禁止编造选中 intent 之外的值。\n"
        "- 若信息不足，设置 needClarify=true，并给出最小澄清问题 clarifyQuestion。\n"
        "- confidence 必须是 [0, 1] 区间数值。\n"
        "当提供 outputSchema 时，必须严格按其结构输出。"
    )
    user_prompt = (
        f"traceId: {payload.traceId}\n"
        f"question: {payload.question}\n"
        f"routingPolicy: {routing_policy_json}\n"
        f"outputSchema: {output_schema_json}\n"
        f"intents: {intents_json}"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _resolve_effective_model_meta(agent_id: str, trace_id: str) -> ModelMeta:
    manager = ProviderManager.get_instance()
    provider_id = "unknown"
    model_name = "unknown"
    try:
        agent_config = load_agent_config(agent_id)
        active = agent_config.active_model
        if active and active.provider_id and active.model:
            provider_id = active.provider_id
            model_name = active.model
        else:
            global_model = manager.get_active_model()
            if global_model and global_model.provider_id and global_model.model:
                provider_id = global_model.provider_id
                model_name = global_model.model
    except Exception:
        logger.debug("Failed to resolve effective model meta", exc_info=True)

    request_id = trace_id.strip() or f"qwenpaw-{uuid4().hex[:12]}"
    return ModelMeta(
        provider=provider_id,
        model=model_name,
        promptVersion=PROMPT_VERSION,
        requestId=request_id,
    )


def _build_candidate_plan(
    output_raw: dict[str, Any],
    intents: list[SessionInferIntent],
) -> CandidatePlan:
    candidate_raw = output_raw.get("candidatePlan")
    if not isinstance(candidate_raw, dict):
        candidate_raw = output_raw

    intent_map = {
        str(intent.intentCode).strip(): intent
        for intent in intents
        if str(intent.intentCode).strip()
    }
    if not intent_map:
        raise ValueError("No intents provided")

    intent_code = str(candidate_raw.get("intentCode") or "").strip()
    if not intent_code:
        raise ValueError("Missing intentCode in model output")
    if intent_code not in intent_map:
        raise ValueError(
            f"intentCode '{intent_code}' is not in provided intents",
        )

    matched = intent_map[intent_code]
    matched_execution_mode = str(matched.executionMode or "").strip()
    model_execution_mode = str(candidate_raw.get("executionMode") or "").strip()
    if (
        matched_execution_mode
        and model_execution_mode
        and matched_execution_mode != model_execution_mode
    ):
        raise ValueError(
            "executionMode in model output does not match provided intent",
        )
    execution_mode = matched_execution_mode or model_execution_mode
    if not execution_mode:
        raise ValueError("Missing executionMode in model output")

    raw_conf = candidate_raw.get("confidence", 0.0)
    try:
        confidence = float(raw_conf)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid confidence in model output") from exc
    confidence = max(0.0, min(1.0, confidence))

    slots = candidate_raw.get("slots")
    if not isinstance(slots, dict):
        slots = {}

    role_code = candidate_raw.get("roleCode")
    if matched.roleCode and role_code and str(role_code).strip() != str(matched.roleCode).strip():
        raise ValueError("roleCode in model output does not match provided intent")
    resolved_role_code = matched.roleCode or role_code

    sql_template_code = candidate_raw.get("sqlTemplateCode")
    if (
        matched.sqlTemplateCode
        and sql_template_code
        and str(sql_template_code).strip() != str(matched.sqlTemplateCode).strip()
    ):
        raise ValueError("sqlTemplateCode in model output does not match provided intent")
    resolved_sql_template_code = matched.sqlTemplateCode or sql_template_code

    selected_table_id = candidate_raw.get("selectedTableId")
    if (
        matched.selectedTableId is not None
        and selected_table_id is not None
        and int(selected_table_id) != int(matched.selectedTableId)
    ):
        raise ValueError("selectedTableId in model output does not match provided intent")
    resolved_selected_table_id = matched.selectedTableId
    if resolved_selected_table_id is None and selected_table_id is not None:
        try:
            resolved_selected_table_id = int(selected_table_id)
        except (TypeError, ValueError):
            raise ValueError("Invalid selectedTableId in model output")

    raw_need_clarify = candidate_raw.get("needClarify", False)
    need_clarify = raw_need_clarify
    if isinstance(raw_need_clarify, str):
        need_clarify = raw_need_clarify.strip().lower() in {"true", "1", "yes", "y"}
    if not isinstance(need_clarify, bool):
        need_clarify = bool(need_clarify)

    clarify_question_raw = candidate_raw.get("clarifyQuestion")
    clarify_question = (
        str(clarify_question_raw).strip() if clarify_question_raw is not None else None
    )
    if not need_clarify:
        clarify_question = None

    return CandidatePlan(
        intentCode=intent_code,
        executionMode=execution_mode,
        confidence=confidence,
        slots=slots,
        needClarify=need_clarify,
        clarifyQuestion=clarify_question,
        roleCode=resolved_role_code,
        sqlTemplateCode=resolved_sql_template_code,
        selectedTableId=resolved_selected_table_id,
    )


async def _resolve_target_agent_id(
    request: Request,
    payload: SessionInferRequest,
    header_agent_id: Optional[str],
) -> str:
    target = (
        (payload.agentId or "").strip()
        or (header_agent_id or "").strip()
        or None
    )
    workspace = await get_agent_for_request(request, agent_id=target)
    return workspace.agent_id


@router.post(
    "/session/infer",
    response_model=SessionInferResponse,
    summary="Infer candidate plan using current agent effective model",
)
async def post_session_infer(
    payload: SessionInferRequest,
    request: Request,
    x_agent_id: Optional[str] = Header(default=None, alias="X-Agent-Id"),
) -> SessionInferResponse:
    stage_start = time.monotonic()
    trace_id = (payload.traceId or "").strip()
    try:
        resolve_start = time.monotonic()
        target_agent_id = await _resolve_target_agent_id(
            request=request,
            payload=payload,
            header_agent_id=x_agent_id,
        )
        resolve_ms = int((time.monotonic() - resolve_start) * 1000)
        set_current_agent_id(target_agent_id)
        if payload.sessionId:
            set_current_session_id(payload.sessionId.strip())

        if not payload.intents:
            return SessionInferResponse(code=1, message="No intents provided")

        model_create_start = time.monotonic()
        model, _ = create_model_and_formatter(agent_id=target_agent_id)
        model_create_ms = int((time.monotonic() - model_create_start) * 1000)

        build_prompt_start = time.monotonic()
        messages = _build_messages(payload)
        build_prompt_ms = int((time.monotonic() - build_prompt_start) * 1000)

        model_call_start = time.monotonic()
        structured_enabled = True
        try:
            response = await model(
                messages,
                structured_model=SessionInferStructuredOutput,
            )
        except Exception:
            structured_enabled = False
            logger.warning(
                "session infer structured model call failed, fallback to plain call",
                exc_info=True,
            )
            response = await model(messages)
        model_call_ms = int((time.monotonic() - model_call_start) * 1000)

        collect_start = time.monotonic()
        response_text, response_metadata, response_tool_candidate = await _collect_model_output(
            response,
        )
        collect_ms = int((time.monotonic() - collect_start) * 1000)

        parse_start = time.monotonic()
        metadata_keys: list[str] = (
            sorted(response_metadata.keys())
            if isinstance(response_metadata, dict)
            else []
        )
        metadata_usable = _metadata_is_usable(response_metadata)
        if response_metadata is not None and not metadata_usable:
            logger.warning(
                "session infer metadata incomplete, fallback to text parse trace_id=%s metadata_keys=%s",
                trace_id,
                metadata_keys,
            )

        tool_candidate_hit = isinstance(response_tool_candidate, dict)
        if metadata_usable and response_metadata is not None:
            response_json = response_metadata
        elif tool_candidate_hit and response_tool_candidate is not None:
            response_json = response_tool_candidate
        else:
            try:
                response_json = _extract_first_json_object(response_text)
            except ValueError:
                logger.warning(
                    "session infer text parse failed, fallback to clarify trace_id=%s text_len=%d",
                    trace_id,
                    len(response_text or ""),
                )
                response_json = _build_clarify_fallback_output(payload)
        parse_ms = int((time.monotonic() - parse_start) * 1000)

        candidate_start = time.monotonic()
        candidate = _build_candidate_plan(response_json, payload.intents)
        candidate_ms = int((time.monotonic() - candidate_start) * 1000)
        model_meta = _resolve_effective_model_meta(
            target_agent_id,
            payload.traceId,
        )
        total_ms = int((time.monotonic() - stage_start) * 1000)
        logger.info(
            "session infer timing trace_id=%s intents=%d resolve_agent_ms=%d model_create_ms=%d build_prompt_ms=%d model_call_ms=%d collect_ms=%d parse_ms=%d candidate_ms=%d total_ms=%d structured_enabled=%s metadata_hit=%s metadata_usable=%s metadata_keys=%s tool_candidate_hit=%s",
            trace_id,
            len(payload.intents),
            resolve_ms,
            model_create_ms,
            build_prompt_ms,
            model_call_ms,
            collect_ms,
            parse_ms,
            candidate_ms,
            total_ms,
            structured_enabled,
            response_metadata is not None,
            metadata_usable,
            metadata_keys,
            tool_candidate_hit,
        )
        return SessionInferResponse(
            code=0,
            message="ok",
            data=SessionInferData(
                candidatePlan=candidate,
                modelMeta=model_meta,
            ),
        )
    except HTTPException as exc:
        return SessionInferResponse(code=exc.status_code, message=str(exc.detail))
    except Exception as exc:
        total_ms = int((time.monotonic() - stage_start) * 1000)
        logger.exception(
            "Session infer failed, trace_id=%s intents=%d total_ms=%d",
            trace_id,
            len(payload.intents),
            total_ms,
        )
        return SessionInferResponse(code=1, message=str(exc))
