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
SESSION_INFER_PROMPT_MAX_DESCRIPTION_CHARS = 160
SESSION_INFER_LOG_MAX_TEXT_CHARS = 200
SESSION_INFER_LOG_MAX_LIST_ITEMS = 5

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


def _truncate_for_log(value: Any, max_chars: int = SESSION_INFER_LOG_MAX_TEXT_CHARS) -> str:
    text = str(value or "")
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "...(truncated)"


def _json_default_for_log(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return value
    if isinstance(value, (list, tuple)):
        return list(value)
    if isinstance(value, set):
        return sorted(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        if isinstance(dumped, dict):
            return dumped
    if hasattr(value, "__dict__"):
        return value.__dict__
    return str(value)


def _json_for_log(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            default=_json_default_for_log,
        )
    except Exception:
        # Logging helper must never break request processing.
        try:
            return str(value)
        except Exception:
            return "<unserializable>"


def _candidate_log_summary(candidate: CandidatePlan) -> dict[str, Any]:
    slot_keys = sorted(str(key) for key in (candidate.slots or {}).keys())
    return {
        "intentCode": candidate.intentCode,
        "executionMode": candidate.executionMode,
        "confidence": candidate.confidence,
        "needClarify": candidate.needClarify,
        "clarifyQuestion": _truncate_for_log(candidate.clarifyQuestion or ""),
        "slotKeys": slot_keys[:SESSION_INFER_LOG_MAX_LIST_ITEMS],
        "slotCount": len(slot_keys),
        "slots": candidate.slots,
        "roleCode": candidate.roleCode,
        "sqlTemplateCode": candidate.sqlTemplateCode,
        "selectedTableId": candidate.selectedTableId,
    }


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
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, dict):
            return parsed
        return None
    model_dump = getattr(raw, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        if isinstance(dumped, dict):
            return dumped
    return None


def _extract_intent_code_from_metadata(metadata: dict[str, Any]) -> str:
    payload = _normalize_structured_payload(metadata)
    candidate_raw = payload.get("candidatePlan")
    if isinstance(candidate_raw, dict):
        intent_code = str(candidate_raw.get("intentCode") or "").strip()
        if intent_code:
            return intent_code
    return str(payload.get("intentCode") or "").strip()


def _normalize_structured_payload(raw: Any) -> dict[str, Any]:
    """
    Normalize provider-specific wrappers to a stable dict payload.
    Handles nested wrappers like {"structuredOutput": {...}} and {"candidatePlan": {...}}.
    """
    payload = _normalize_structured_metadata(raw)
    if not isinstance(payload, dict):
        return {}
    current = payload
    for _ in range(6):
        wrapped = _normalize_structured_metadata(current.get("structuredOutput"))
        if isinstance(wrapped, dict):
            current = wrapped
            continue
        nested = _normalize_structured_metadata(current.get("candidatePlan"))
        if isinstance(nested, dict) and not str(current.get("intentCode") or "").strip():
            current = nested
            continue
        break
    return current


def _metadata_is_usable(metadata: Optional[dict[str, Any]]) -> bool:
    payload = _normalize_structured_payload(metadata)
    if not isinstance(payload, dict) or not payload:
        return False
    candidate_raw = _normalize_structured_metadata(payload.get("candidatePlan"))
    if isinstance(candidate_raw, dict):
        intent_code = str(candidate_raw.get("intentCode") or "").strip()
        execution_mode = str(candidate_raw.get("executionMode") or "").strip()
        return bool(intent_code and execution_mode)
    intent_code = str(payload.get("intentCode") or "").strip()
    execution_mode = str(payload.get("executionMode") or "").strip()
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
    stop_on_usable_metadata: bool = False,
) -> tuple[
    str,
    Optional[dict[str, Any]],
    Optional[dict[str, Any]],
    Optional[int],
    int,
    Optional[int],
]:
    if hasattr(response, "__aiter__"):
        accumulated = ""
        metadata: Optional[dict[str, Any]] = None
        tool_candidate: Optional[dict[str, Any]] = None
        collect_started = time.monotonic()
        first_chunk_ms: Optional[int] = None
        chunk_count = 0
        valid_metadata_at_chunk_idx: Optional[int] = None
        async for chunk in response:  # type: ignore[union-attr]
            chunk_count += 1
            if first_chunk_ms is None:
                first_chunk_ms = int((time.monotonic() - collect_started) * 1000)
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
                if (
                    stop_on_usable_metadata
                    and _metadata_is_usable(metadata)
                    and valid_metadata_at_chunk_idx is None
                ):
                    valid_metadata_at_chunk_idx = chunk_count
                    break
            candidate = _extract_candidate_from_tool_content(
                getattr(chunk, "content", None),
            )
            if candidate:
                tool_candidate = candidate
        return (
            accumulated,
            metadata,
            tool_candidate,
            first_chunk_ms,
            chunk_count,
            valid_metadata_at_chunk_idx,
        )

    response_text = _extract_text_from_response(response)
    metadata = _normalize_structured_metadata(getattr(response, "metadata", None))
    tool_candidate = _extract_candidate_from_tool_content(
        getattr(response, "content", None),
    )
    has_payload = bool(response_text or metadata or tool_candidate)
    return (
        response_text,
        metadata,
        tool_candidate,
        0 if has_payload else None,
        1 if has_payload else 0,
        1 if (_metadata_is_usable(metadata)) else None,
    )


def _build_messages(payload: SessionInferRequest) -> list[dict[str, Any]]:
    compact_intents: list[dict[str, Any]] = []
    for intent in payload.intents:
        description = str(intent.description or "").strip()
        if len(description) > SESSION_INFER_PROMPT_MAX_DESCRIPTION_CHARS:
            description = description[:SESSION_INFER_PROMPT_MAX_DESCRIPTION_CHARS]
        compact_intents.append(
            {
                "intentCode": str(intent.intentCode or "").strip(),
                "executionMode": str(intent.executionMode or "").strip(),
                "description": description,
                "roleCode": intent.roleCode,
                "sqlTemplateCode": intent.sqlTemplateCode,
                "selectedTableId": intent.selectedTableId,
                "slotKeys": list(intent.slotKeys or []),
                "slotSchema": intent.slotSchema if isinstance(intent.slotSchema, dict) else {},
                "slotMapping": _intent_data(intent).get("slotMapping", {}),
                "enumValueHints": _intent_data(intent).get("enumValueHints", []),
                "triggerPhrases": _intent_data(intent).get("triggerPhrases", []),
                "mustConditions": _intent_data(intent).get("mustConditions", []),
                "forbiddenConditions": _intent_data(intent).get("forbiddenConditions", []),
                "intentName": _intent_data(intent).get("intentName", ""),
                "domain": _intent_data(intent).get("domain", ""),
            },
        )
    intents_json = json.dumps(
        compact_intents,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    routing_policy_json = json.dumps(
        payload.routingPolicy or {},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    output_schema_json = json.dumps(
        payload.outputSchema or {},
        ensure_ascii=False,
        separators=(",", ":"),
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


def _intent_data(intent: SessionInferIntent) -> dict[str, Any]:
    dumped = intent.model_dump()
    if isinstance(dumped, dict):
        return dumped
    return {}


def _slot_value_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict, tuple, set)):
        return bool(value)
    return True


def _required_slot_keys(intent: SessionInferIntent) -> list[str]:
    schema = intent.slotSchema if isinstance(intent.slotSchema, dict) else {}
    required_raw = schema.get("required")
    if not isinstance(required_raw, list):
        return []
    required: list[str] = []
    for item in required_raw:
        key = str(item or "").strip()
        if key:
            required.append(key)
    return required


def _slot_mapping(intent: SessionInferIntent) -> dict[str, list[str]]:
    slot_schema = intent.slotSchema if isinstance(intent.slotSchema, dict) else {}
    mapping_raw = slot_schema.get("slotMapping")
    if not isinstance(mapping_raw, dict):
        return {}
    normalized: dict[str, list[str]] = {}
    for key, value in mapping_raw.items():
        slot_key = str(key or "").strip()
        if not slot_key:
            continue
        aliases: list[str] = []
        if isinstance(value, list):
            for item in value:
                text = str(item or "").strip()
                if text:
                    aliases.append(text)
        normalized[slot_key] = aliases
    return normalized


def _enum_alias_map(intent: SessionInferIntent) -> dict[str, dict[str, set[str]]]:
    alias_map: dict[str, dict[str, set[str]]] = {}
    slot_schema = intent.slotSchema if isinstance(intent.slotSchema, dict) else {}
    properties = slot_schema.get("properties")
    if isinstance(properties, dict):
        for slot_key, prop_raw in properties.items():
            if not isinstance(prop_raw, dict):
                continue
            slot = str(slot_key or "").strip()
            if not slot:
                continue
            enum_aliases_raw = prop_raw.get("x-enum-aliases")
            if not isinstance(enum_aliases_raw, dict):
                continue
            per_slot = alias_map.setdefault(slot, {})
            for canonical_raw, aliases_raw in enum_aliases_raw.items():
                canonical = str(canonical_raw or "").strip()
                if not canonical:
                    continue
                values = per_slot.setdefault(canonical, set())
                values.add(canonical)
                if isinstance(aliases_raw, list):
                    for alias in aliases_raw:
                        text = str(alias or "").strip()
                        if text:
                            values.add(text)

    data = _intent_data(intent)
    hints_raw = data.get("enumValueHints")
    if isinstance(hints_raw, list):
        for hint in hints_raw:
            if not isinstance(hint, dict):
                continue
            slot = str(hint.get("slot") or "").strip()
            canonical = str(hint.get("value") or "").strip()
            if not slot or not canonical:
                continue
            per_slot = alias_map.setdefault(slot, {})
            values = per_slot.setdefault(canonical, set())
            values.add(canonical)
            aliases_raw = hint.get("aliases")
            if isinstance(aliases_raw, list):
                for alias in aliases_raw:
                    text = str(alias or "").strip()
                    if text:
                        values.add(text)
    return alias_map


def _normalize_enum_slot_value(
    slot: str,
    value: Any,
    enum_aliases: dict[str, dict[str, set[str]]],
) -> Any:
    if not isinstance(value, str):
        return value
    normalized_value = value.strip()
    if not normalized_value:
        return normalized_value
    per_slot = enum_aliases.get(slot, {})
    lowered = normalized_value.lower()
    for canonical, aliases in per_slot.items():
        for alias in aliases:
            alias_text = str(alias or "").strip()
            if not alias_text:
                continue
            if lowered == alias_text.lower():
                return canonical
    return normalized_value


def _extract_enum_slot_from_question(
    question: str,
    slot: str,
    enum_aliases: dict[str, dict[str, set[str]]],
) -> Optional[str]:
    question_text = str(question or "")
    if not question_text:
        return None
    per_slot = enum_aliases.get(slot, {})
    candidates: list[tuple[int, str]] = []
    question_lower = question_text.lower()
    for canonical, aliases in per_slot.items():
        for alias in aliases:
            alias_text = str(alias or "").strip()
            if not alias_text:
                continue
            alias_lower = alias_text.lower()
            idx = question_lower.find(alias_lower)
            if idx >= 0:
                candidates.append((idx, canonical))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def _extract_value_with_alias(question: str, alias: str) -> Optional[str]:
    alias_text = str(alias or "").strip()
    if not alias_text:
        return None
    pattern = (
        rf"(?i)(?:^|[\s，,。;；:：]){re.escape(alias_text)}"
        rf"\s*(?:是|为|=|:|：)?\s*([A-Za-z0-9][A-Za-z0-9_\-]*)"
    )
    matched = re.search(pattern, question)
    if not matched:
        return None
    value = str(matched.group(1) or "").strip()
    return value or None


def _extract_slot_from_question(
    question: str,
    slot: str,
    slot_aliases: list[str],
    enum_aliases: dict[str, dict[str, set[str]]],
) -> Optional[Any]:
    enum_value = _extract_enum_slot_from_question(question, slot, enum_aliases)
    if enum_value is not None:
        return enum_value

    for alias in slot_aliases:
        value = _extract_value_with_alias(question, alias)
        if value is not None:
            return value
    return None


def _complete_candidate_slots_from_question(
    candidate: CandidatePlan,
    intent: SessionInferIntent,
    question: str,
) -> tuple[CandidatePlan, int, list[str]]:
    slot_whitelist = {str(key).strip() for key in (intent.slotKeys or []) if str(key).strip()}
    slots = candidate.slots if isinstance(candidate.slots, dict) else {}
    if slot_whitelist:
        slots = {k: v for k, v in slots.items() if str(k).strip() in slot_whitelist}

    enum_aliases = _enum_alias_map(intent)
    normalized_slots: dict[str, Any] = {}
    for key, value in slots.items():
        slot_key = str(key or "").strip()
        if not slot_key:
            continue
        normalized_slots[slot_key] = _normalize_enum_slot_value(
            slot_key,
            value,
            enum_aliases,
        )

    required_keys = _required_slot_keys(intent)
    slot_aliases = _slot_mapping(intent)
    filled_count = 0
    for slot in required_keys:
        if _slot_value_present(normalized_slots.get(slot)):
            continue
        inferred = _extract_slot_from_question(
            question=question,
            slot=slot,
            slot_aliases=slot_aliases.get(slot, []),
            enum_aliases=enum_aliases,
        )
        if _slot_value_present(inferred):
            normalized_slots[slot] = inferred
            filled_count += 1

    missing_required = [slot for slot in required_keys if not _slot_value_present(normalized_slots.get(slot))]
    clarified = bool(missing_required)
    clarify_question: Optional[str]
    if clarified:
        clarify_question = "请补充以下必要参数：" + "、".join(missing_required)
    else:
        clarify_question = None

    confidence = candidate.confidence
    if not clarified and confidence <= 0.0 and filled_count > 0:
        confidence = 0.6

    repaired = CandidatePlan(
        intentCode=candidate.intentCode,
        executionMode=candidate.executionMode,
        confidence=confidence,
        slots=normalized_slots,
        needClarify=clarified,
        clarifyQuestion=clarify_question,
        roleCode=candidate.roleCode,
        sqlTemplateCode=candidate.sqlTemplateCode,
        selectedTableId=candidate.selectedTableId,
    )
    return repaired, filled_count, missing_required


def _enforce_slot_completion(
    candidate: CandidatePlan,
    intents: list[SessionInferIntent],
    question: str,
) -> tuple[CandidatePlan, bool, int, list[str]]:
    intent_map = {
        str(intent.intentCode or "").strip(): intent
        for intent in intents
        if str(intent.intentCode or "").strip()
    }
    matched = intent_map.get(str(candidate.intentCode or "").strip())
    if matched is None:
        return candidate, False, 0, []

    repaired, filled_count, missing_required = _complete_candidate_slots_from_question(
        candidate=candidate,
        intent=matched,
        question=question,
    )
    changed = (
        repaired.slots != candidate.slots
        or repaired.needClarify != candidate.needClarify
        or repaired.clarifyQuestion != candidate.clarifyQuestion
        or repaired.confidence != candidate.confidence
    )
    return repaired, changed, filled_count, missing_required


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
        logger.debug("解析生效模型元信息失败", exc_info=True)

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
    normalized_output = _normalize_structured_payload(output_raw)
    candidate_raw = _normalize_structured_metadata(normalized_output.get("candidatePlan"))
    if not isinstance(candidate_raw, dict):
        candidate_raw = normalized_output or output_raw
    for _ in range(5):
        intent_code_probe = str(candidate_raw.get("intentCode") or "").strip()
        execution_mode_probe = str(candidate_raw.get("executionMode") or "").strip()
        if intent_code_probe or execution_mode_probe:
            break
        nested_candidate = _normalize_structured_metadata(candidate_raw.get("candidatePlan"))
        if not isinstance(nested_candidate, dict):
            break
        candidate_raw = nested_candidate

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
    logger.info("会话推理请求载荷 payload=%s", payload.model_dump())
    try:
        resolve_start = time.monotonic()
        target_agent_id = await _resolve_target_agent_id(
            request=request,
            payload=payload,
            header_agent_id=x_agent_id,
        )
        resolve_ms = int((time.monotonic() - resolve_start) * 1000)
        logger.info(
            "会话推理阶段=解析agent trace_id=%s target_agent_id=%s resolve_ms=%d",
            trace_id,
            target_agent_id,
            resolve_ms,
        )
        set_current_agent_id(target_agent_id)
        if payload.sessionId:
            set_current_session_id(payload.sessionId.strip())

        if not payload.intents:
            logger.warning("会话推理请求缺少intents trace_id=%s", trace_id)
            return SessionInferResponse(code=1, message="No intents provided")

        model_create_start = time.monotonic()
        model, _ = create_model_and_formatter(agent_id=target_agent_id)
        model_create_ms = int((time.monotonic() - model_create_start) * 1000)
        logger.info(
            "会话推理阶段=创建模型 trace_id=%s model_create_ms=%d",
            trace_id,
            model_create_ms,
        )

        build_prompt_start = time.monotonic()
        messages = _build_messages(payload)
        build_prompt_ms = int((time.monotonic() - build_prompt_start) * 1000)
        logger.info(
            "会话推理阶段=构建提示词 trace_id=%s build_prompt_ms=%d system_len=%d user_len=%d",
            trace_id,
            build_prompt_ms,
            len(str(messages[0].get("content") or "")) if messages else 0,
            len(str(messages[1].get("content") or "")) if len(messages) > 1 else 0,
        )

        model_call_start = time.monotonic()
        structured_enabled = True
        non_stream_enforced = True
        structured_error_type = ""
        try:
            response = await model(
                messages,
                structured_model=SessionInferStructuredOutput,
            )
        except TypeError as exc:
            non_stream_enforced = False
            try:
                response = await model(
                    messages,
                    structured_model=SessionInferStructuredOutput,
                )
                structured_error_type = ""
            except Exception as fallback_exc:
                structured_enabled = False
                structured_error_type = type(fallback_exc).__name__
                logger.warning(
                    "会话推理结构化模型调用失败（fallback后）",
                    exc_info=True,
                )
                response = None
        except Exception as exc:
            structured_enabled = False
            structured_error_type = type(exc).__name__
            logger.warning(
                "会话推理结构化模型调用失败",
                exc_info=True,
            )
            response = None
        model_call_ms = int((time.monotonic() - model_call_start) * 1000)
        logger.info(
            "会话推理阶段=模型调用 trace_id=%s model_call_ms=%d structured_enabled=%s non_stream_enforced=%s structured_error_type=%s",
            trace_id,
            model_call_ms,
            structured_enabled,
            non_stream_enforced,
            structured_error_type,
        )

        if response is None:
            raise ValueError(
                f"Structured model call failed: {structured_error_type or 'unknown_error'}",
            )

        collect_start = time.monotonic()
        if response is not None:
            (
                response_text,
                response_metadata,
                response_tool_candidate,
                first_chunk_ms,
                stream_chunk_count,
                valid_metadata_at_chunk_idx,
            ) = await _collect_model_output(
                response,
                stop_on_usable_metadata=True,
            )
        else:
            (
                response_text,
                response_metadata,
                response_tool_candidate,
                first_chunk_ms,
                stream_chunk_count,
                valid_metadata_at_chunk_idx,
            ) = ("", None, None, None, 0, None)
        collect_ms = int((time.monotonic() - collect_start) * 1000)
        logger.info(
            "会话推理阶段=收集输出 trace_id=%s collect_ms=%d text_len=%d metadata_hit=%s metadata_keys=%s metadata_usable=%s tool_candidate_hit=%s first_chunk_ms=%s stream_chunk_count=%d valid_metadata_at_chunk_idx=%s",
            trace_id,
            collect_ms,
            len(response_text or ""),
            isinstance(response_metadata, dict),
            _json_for_log(
                sorted(response_metadata.keys()) if isinstance(response_metadata, dict) else []
            ),
            _metadata_is_usable(response_metadata),
            isinstance(response_tool_candidate, dict),
            first_chunk_ms,
            stream_chunk_count,
            valid_metadata_at_chunk_idx,
        )
        logger.info(
            "会话推理收集结果-metadata trace_id=%s metadata=%s",
            trace_id,
            _json_for_log(response_metadata),
        )
        logger.info(
            "会话推理收集结果-text trace_id=%s response_text=%s",
            trace_id,
            response_text,
        )
        logger.info(
            "会话推理收集结果-tool_candidate trace_id=%s tool_candidate=%s",
            trace_id,
            _json_for_log(response_tool_candidate),
        )

        parse_start = time.monotonic()
        metadata_keys: list[str] = (
            sorted(response_metadata.keys())
            if isinstance(response_metadata, dict)
            else []
        )
        metadata_usable = _metadata_is_usable(response_metadata)
        if response_metadata is not None and not metadata_usable:
            logger.warning(
                "会话推理metadata不完整 trace_id=%s metadata_keys=%s",
                trace_id,
                _json_for_log(metadata_keys),
            )

        tool_candidate_hit = isinstance(response_tool_candidate, dict)
        response_source = "none"
        source_candidates: list[tuple[str, dict[str, Any]]] = []
        if isinstance(response_metadata, dict):
            source_candidates.append(("metadata", response_metadata))
        if tool_candidate_hit and response_tool_candidate is not None:
            source_candidates.append(("tool_candidate", response_tool_candidate))
        if not source_candidates:
            raise ValueError(
                "Missing usable structured payload from model output: "
                f"trace_id={trace_id} text_len={len(response_text or '')}",
            )
        parse_ms = int((time.monotonic() - parse_start) * 1000)
        source_summaries = [
            {
                "source": source_name,
                "intentCode": _extract_intent_code_from_metadata(source_payload),
                "keys": sorted(source_payload.keys())[:SESSION_INFER_LOG_MAX_LIST_ITEMS],
            }
            for source_name, source_payload in source_candidates
        ]
        logger.info(
            "会话推理阶段=解析载荷 trace_id=%s parse_ms=%d source_candidates=%s",
            trace_id,
            parse_ms,
            _json_for_log(source_summaries),
        )

        candidate_start = time.monotonic()
        slot_completion_changed = False
        slot_completion_filled = 0
        slot_completion_missing_required: list[str] = []
        candidate: Optional[CandidatePlan] = None
        candidate_before_enforce: Optional[dict[str, Any]] = None
        candidate_errors: list[str] = []
        for source_name, source_payload in source_candidates:
            try:
                candidate = _build_candidate_plan(source_payload, payload.intents)
                response_source = source_name
                candidate_before_enforce = _candidate_log_summary(candidate)
                break
            except ValueError as exc:
                candidate_errors.append(f"{source_name}:{exc}")
                logger.warning(
                    "会话推理candidate解析失败 trace_id=%s source=%s reason=%s",
                    trace_id,
                    source_name,
                    str(exc),
                )
        if candidate is None:
            raise ValueError(
                "Failed to build candidatePlan from model output: "
                + "; ".join(candidate_errors)
            )
        (
            candidate,
            slot_completion_changed,
            slot_completion_filled,
            slot_completion_missing_required,
        ) = _enforce_slot_completion(
            candidate=candidate,
            intents=payload.intents,
            question=payload.question,
        )
        candidate_after_enforce = _candidate_log_summary(candidate)
        logger.info(
            "会话推理阶段=candidate处理 trace_id=%s response_source=%s candidate_before=%s candidate_after=%s slot_completion_changed=%s slot_completion_filled=%d slot_completion_missing_required=%s",
            trace_id,
            response_source,
            _json_for_log(candidate_before_enforce),
            _json_for_log(candidate_after_enforce),
            slot_completion_changed,
            slot_completion_filled,
            _json_for_log(slot_completion_missing_required),
        )
        if slot_completion_changed:
            logger.info(
                "会话推理槽位补全 trace_id=%s intent=%s filled=%d missing_required=%s need_clarify=%s",
                trace_id,
                candidate.intentCode,
                slot_completion_filled,
                _json_for_log(slot_completion_missing_required),
                candidate.needClarify,
            )
        candidate_ms = int((time.monotonic() - candidate_start) * 1000)
        model_meta = _resolve_effective_model_meta(
            target_agent_id,
            payload.traceId,
        )
        logger.info(
            "会话推理阶段=解析模型元信息 trace_id=%s model_meta=%s",
            trace_id,
            _json_for_log(model_meta.model_dump()),
        )
        total_ms = int((time.monotonic() - stage_start) * 1000)
        logger.info(
            "会话推理耗时汇总 trace_id=%s intents=%d resolve_agent_ms=%d model_create_ms=%d build_prompt_ms=%d model_call_ms=%d collect_ms=%d parse_ms=%d candidate_ms=%d response_source=%s slot_completion_changed=%s slot_completion_filled=%d slot_completion_missing_required=%s total_ms=%d structured_enabled=%s non_stream_enforced=%s metadata_hit=%s metadata_usable=%s metadata_keys=%s tool_candidate_hit=%s first_chunk_ms=%s stream_chunk_count=%d valid_metadata_at_chunk_idx=%s structured_error_type=%s",
            trace_id,
            len(payload.intents),
            resolve_ms,
            model_create_ms,
            build_prompt_ms,
            model_call_ms,
            collect_ms,
            parse_ms,
            candidate_ms,
            response_source,
            slot_completion_changed,
            slot_completion_filled,
            _json_for_log(slot_completion_missing_required),
            total_ms,
            structured_enabled,
            non_stream_enforced,
            response_metadata is not None,
            metadata_usable,
            _json_for_log(metadata_keys),
            tool_candidate_hit,
            first_chunk_ms,
            stream_chunk_count,
            valid_metadata_at_chunk_idx,
            structured_error_type,
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
            "会话推理失败 trace_id=%s intents=%d total_ms=%d",
            trace_id,
            len(payload.intents),
            total_ms,
        )
        return SessionInferResponse(code=1, message=str(exc))
