# -*- coding: utf-8 -*-
"""把 Agent SSE 事件旁路持久化为可稳定回放的 PostgreSQL Run。"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4, uuid5

from .models import ChatSpec
from ...utils.io_utils import run_sync_io, write_text_atomic
from .repo import (
    AttachmentRecord,
    ConversationRecord,
    MessageRecord,
    PostgresConversationRepository,
    RunEventRecord,
    RunRecord,
    ToolCallRecord,
)

_EVENT_NAMESPACE = UUID("33c76c75-ea85-53e8-a931-34135efebbf7")


def _stable_uuid(kind: str, run_id: UUID, source_id: str) -> UUID:
    return uuid5(_EVENT_NAMESPACE, f"{kind}:{run_id}:{source_id}")


def _parse_sse_data(line: str) -> dict[str, Any] | None:
    for raw_line in line.splitlines():
        if not raw_line.startswith("data:"):
            continue
        try:
            value = json.loads(raw_line[5:].strip())
        except (json.JSONDecodeError, TypeError):
            return None
        return value if isinstance(value, dict) else None
    return None


def _content_data(wire: dict[str, Any]) -> dict[str, Any]:
    content = wire.get("content")
    if not isinstance(content, list):
        return {}
    for item in content:
        if isinstance(item, dict) and isinstance(item.get("data"), dict):
            return item["data"]
    return {}


def _event_type(wire: dict[str, Any]) -> str:
    obj = str(wire.get("object") or "")
    wire_type = str(wire.get("type") or "")
    if obj == "content" and wire.get("delta"):
        return "assistant_delta"
    if obj in {"approval_required", "approval_decided", "error"}:
        return obj
    if obj != "message":
        return wire_type or obj or "event"
    if wire_type == "reasoning":
        return "reasoning"
    if wire_type == "plugin_call_output":
        return "tool_output"
    if wire_type == "mcp_tool_call":
        return "mcp"
    if wire_type == "progress":
        return "progress"
    if wire_type == "result":
        return "final"
    data = _content_data(wire)
    tool_name = str(data.get("name") or "")
    if wire_type == "plugin_call":
        if tool_name == "materialize_skill":
            return "skill"
        if tool_name == "execute_shell_command":
            return "command" if wire.get("status") == "completed" else "tool_start"
        return "plugin"
    content = wire.get("content")
    if isinstance(content, list):
        item_types = {
            str(item.get("type")) for item in content if isinstance(item, dict)
        }
        if "image" in item_types:
            return "image"
        if "file" in item_types:
            return "file"
    return wire_type or "message"


def _tool_source(event_type: str) -> str:
    if event_type in {"mcp", "skill", "plugin"}:
        return event_type
    return "builtin"


class PostgresChatRunPersistence:
    """为一个 Agent 创建不改变 wire 数据的持久化事件源包装器。"""

    def __init__(
        self,
        *,
        repository: PostgresConversationRepository,
        agent_id: UUID,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        payload_storage_dir: Path | None = None,
        inline_payload_limit: int = 64 * 1024,
    ) -> None:
        self._repository = repository
        self._agent_id = agent_id
        self._clock = clock
        self._payload_storage_dir = payload_storage_dir
        self._inline_payload_limit = inline_payload_limit

    def wrap_stream(
        self,
        *,
        chat: ChatSpec,
        initiated_by: UUID,
        stream_fn: Callable[[Any], AsyncIterator[str]],
    ) -> Callable[[Any], AsyncIterator[str]]:
        async def persisted(payload: Any) -> AsyncIterator[str]:
            repository = self._repository.with_user(initiated_by)
            conversation_id = UUID(chat.id)
            requested_run_id = (
                payload.get("_qwenpaw_run_id")
                if isinstance(payload, dict)
                else None
            )
            try:
                run_id = UUID(str(requested_run_id))
            except (TypeError, ValueError, AttributeError):
                run_id = uuid4()
            if isinstance(payload, dict):
                meta = payload.setdefault("meta", {})
                request_context = dict(meta.get("request_context") or {})
                request_context["conversation_id"] = str(conversation_id)
                request_context["run_id"] = str(run_id)
                meta["request_context"] = request_context
            started_at = self._clock()
            conversation = ConversationRecord(
                id=conversation_id,
                agent_id=self._agent_id,
                owner_user_id=initiated_by,
                title=chat.name,
                status="active",
                created_at=chat.created_at,
                updated_at=chat.updated_at,
            )
            existing_conversation = await repository.get_conversation(
                conversation_id
            )
            if existing_conversation is None:
                await repository.create_conversation(conversation)
            elif (
                existing_conversation.title != chat.name
                or existing_conversation.status != "active"
                or existing_conversation.updated_at != chat.updated_at
            ):
                await repository.update_conversation(
                    conversation_id,
                    title=chat.name,
                    status="active",
                    updated_at=chat.updated_at,
                )
            await repository.create_run(
                RunRecord(
                    id=run_id,
                    conversation_id=conversation_id,
                    initiated_by=initiated_by,
                    status="running",
                    started_at=started_at,
                )
            )
            existing_messages = await repository.list_messages(conversation_id)
            message_sequence_offset = max(
                (message.sequence for message in existing_messages),
                default=0,
            )
            sequence = 0
            tool_calls: dict[str, ToolCallRecord] = {}
            try:
                user_message = self._user_message(
                    conversation_id=conversation_id,
                    run_id=run_id,
                    initiated_by=initiated_by,
                    sequence=message_sequence_offset + 1,
                    payload=payload,
                )
                if user_message is not None:
                    sequence += 1
                    await repository.persist_frame(
                        event=RunEventRecord(
                            id=_stable_uuid("event", run_id, f"user:{sequence}"),
                            run_id=run_id,
                            sequence=sequence,
                            event_type="user_message",
                            payload=user_message.content,
                            created_at=self._clock(),
                        ),
                        message=user_message,
                    )
                    for attachment_id in self._message_attachment_ids(user_message):
                        await repository.bind_attachment(
                            attachment_id=attachment_id,
                            owner_user_id=initiated_by,
                            agent_id=self._agent_id,
                            conversation_id=conversation_id,
                            message_id=user_message.id,
                        )
                async for line in stream_fn(payload):
                    wire = _parse_sse_data(line)
                    if wire is not None:
                        sequence += 1
                        event_type = _event_type(wire)
                        stored_payload = await self._store_payload(
                            wire, run_id, sequence
                        )
                        tool_call = self._tool_call(
                            run_id=run_id,
                            event_type=event_type,
                            wire=wire,
                            known=tool_calls,
                        )
                        if tool_call is not None:
                            tool_calls[tool_call.call_id] = tool_call
                        message = self._message(
                            conversation_id=conversation_id,
                            run_id=run_id,
                            initiated_by=initiated_by,
                            sequence=message_sequence_offset + sequence,
                            wire=wire,
                            stored_content=stored_payload,
                        )
                        attachments = self._attachments(
                            conversation_id=conversation_id,
                            message=message,
                            owner_user_id=initiated_by,
                            wire=wire,
                        )
                        payload_reference = stored_payload.get("qwenpaw_payload_ref")
                        if tool_call is not None and isinstance(
                            payload_reference, dict
                        ):
                            tool_call = tool_call.model_copy(
                                update={
                                    "output_ref": str(
                                        payload_reference.get("path") or ""
                                    )
                                }
                            )
                            tool_calls[tool_call.call_id] = tool_call
                        await repository.persist_frame(
                            event=RunEventRecord(
                                id=_stable_uuid("event", run_id, str(sequence)),
                                run_id=run_id,
                                sequence=sequence,
                                event_type=event_type,
                                payload=stored_payload,
                                tool_call_id=(tool_call.id if tool_call else None),
                                created_at=self._clock(),
                            ),
                            message=message,
                            tool_call=tool_call,
                            attachments=attachments,
                            terminal_status={
                                "final": "completed",
                                "error": "failed",
                            }.get(event_type),
                        )
                    yield line
            except asyncio.CancelledError:
                await repository.finish_run(
                    run_id,
                    status="cancelled",
                    finished_at=self._clock(),
                )
                raise
            except Exception as exc:
                await repository.finish_run(
                    run_id,
                    status="failed",
                    finished_at=self._clock(),
                    error_summary=str(exc)[:1000],
                )
                raise
            else:
                current = await repository.get_run(run_id)
                if current is not None and current.status == "running":
                    await repository.finish_run(
                        run_id,
                        status="completed",
                        finished_at=self._clock(),
                    )

        return persisted

    async def _store_payload(
        self, payload: dict[str, Any], run_id: UUID, sequence: int
    ) -> dict[str, Any]:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if (
            self._payload_storage_dir is None
            or len(encoded.encode("utf-8")) <= self._inline_payload_limit
        ):
            return payload
        target = self._payload_storage_dir / f"{run_id}-{sequence}.json"
        await run_sync_io(target.parent.mkdir, parents=True, exist_ok=True)
        await run_sync_io(write_text_atomic, target, encoded)
        return {
            "qwenpaw_payload_ref": {
                "path": target.name,
                "byte_size": len(encoded.encode("utf-8")),
                "sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
            }
        }

    async def load_event_payload(
        self, stored_payload: dict[str, Any]
    ) -> dict[str, Any]:
        reference = stored_payload.get("qwenpaw_payload_ref")
        if not isinstance(reference, dict):
            return stored_payload
        if self._payload_storage_dir is None:
            raise RuntimeError("payload_storage_unavailable")
        target = self._payload_storage_dir / Path(str(reference["path"])).name
        content = await run_sync_io(target.read_text, encoding="utf-8")
        return json.loads(content)

    def _user_message(
        self,
        *,
        conversation_id: UUID,
        run_id: UUID,
        initiated_by: UUID,
        sequence: int,
        payload: Any,
    ) -> MessageRecord | None:
        if not isinstance(payload, dict):
            return None
        parts = payload.get("content_parts")
        if not parts:
            return None
        normalized: list[dict[str, Any]] = []
        for part in parts:
            if isinstance(part, dict):
                item = dict(part)
            elif hasattr(part, "model_dump"):
                item = part.model_dump(mode="json")
            else:
                continue
            attachment_url = item.pop("attachment_url", None)
            if isinstance(attachment_url, str) and attachment_url:
                if item.get("type") == "image":
                    item["image_url"] = attachment_url
                elif item.get("type") == "file":
                    item["file_url"] = attachment_url
                elif item.get("type") == "audio":
                    item["data"] = attachment_url
            normalized.append(item)
        if not normalized:
            return None
        client_id = str(
            (payload.get("message_metadata") or {}).get("qwenpaw_client_message_id")
            or uuid4()
        )
        return MessageRecord(
            id=_stable_uuid("message", run_id, f"user:{client_id}"),
            conversation_id=conversation_id,
            run_id=run_id,
            sequence=sequence,
            role="user",
            message_type="message",
            content={"content": normalized},
            status="completed",
            created_by=initiated_by,
            created_at=self._clock(),
        )

    def _message(
        self,
        *,
        conversation_id: UUID,
        run_id: UUID,
        initiated_by: UUID,
        sequence: int,
        wire: dict[str, Any],
        stored_content: dict[str, Any],
    ) -> MessageRecord | None:
        if wire.get("object") != "message" or not wire.get("id"):
            return None
        wire_id = str(wire["id"])
        return MessageRecord(
            id=_stable_uuid("message", run_id, wire_id),
            conversation_id=conversation_id,
            run_id=run_id,
            sequence=sequence,
            role=str(wire.get("role") or "assistant"),
            message_type=str(wire.get("type") or "message"),
            content=stored_content,
            status=str(wire.get("status") or "completed"),
            created_by=initiated_by,
            created_at=self._clock(),
        )

    def _tool_call(
        self,
        *,
        run_id: UUID,
        event_type: str,
        wire: dict[str, Any],
        known: dict[str, ToolCallRecord],
    ) -> ToolCallRecord | None:
        data = _content_data(wire)
        if wire.get("object") in {"approval_required", "approval_decided"}:
            raw_data = wire.get("data")
            data = raw_data if isinstance(raw_data, dict) else {}
        call_id = str(data.get("call_id") or data.get("tool_call_id") or "")
        if not call_id:
            return None
        previous = known.get(call_id)
        arguments = data.get("arguments")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {"raw": arguments}
        if not isinstance(arguments, dict):
            arguments = previous.redacted_arguments if previous else {}
        approval_value = data.get("approval_id")
        approval_id = (
            _stable_uuid("approval", run_id, str(approval_value))
            if approval_value
            else (previous.approval_id if previous else None)
        )
        now = self._clock()
        status = str(wire.get("status") or "running")
        return ToolCallRecord(
            id=(previous.id if previous else _stable_uuid("tool", run_id, call_id)),
            run_id=run_id,
            call_id=call_id,
            source=(previous.source if previous else _tool_source(event_type)),
            tool_name=str(
                data.get("name") or (previous.tool_name if previous else "tool")
            ),
            status=status,
            redacted_arguments=arguments,
            approval_id=approval_id,
            output_ref=(previous.output_ref if previous else None),
            started_at=(previous.started_at if previous else now),
            finished_at=(now if status in {"completed", "failed"} else None),
        )

    def _attachments(
        self,
        *,
        conversation_id: UUID,
        message: MessageRecord | None,
        owner_user_id: UUID,
        wire: dict[str, Any],
    ) -> list[AttachmentRecord]:
        if message is None or not isinstance(wire.get("content"), list):
            return []
        records: list[AttachmentRecord] = []
        for index, item in enumerate(wire["content"]):
            if not isinstance(item, dict) or item.get("type") not in {
                "image",
                "file",
            }:
                continue
            storage_key = str(item.get("image_url") or item.get("file_url") or "")
            if not storage_key:
                continue
            digest = hashlib.sha256(storage_key.encode("utf-8")).hexdigest()
            created_at = self._clock()
            records.append(
                AttachmentRecord(
                    id=_stable_uuid(
                        "attachment",
                        message.run_id or uuid4(),
                        f"{message.id}:{index}",
                    ),
                    agent_id=self._agent_id,
                    conversation_id=conversation_id,
                    message_id=message.id,
                    owner_user_id=owner_user_id,
                    storage_key=storage_key,
                    original_name=Path(storage_key).name or "attachment",
                    media_type=(
                        "image/*"
                        if item.get("type") == "image"
                        else "application/octet-stream"
                    ),
                    size=0,
                    content_hash=f"sha256:{digest}",
                    created_at=created_at,
                    updated_at=created_at,
                )
            )
        return records

    @staticmethod
    def _message_attachment_ids(message: MessageRecord) -> list[UUID]:
        content = message.content.get("content")
        if not isinstance(content, list):
            return []
        result: list[UUID] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            try:
                attachment_id = UUID(str(part.get("attachment_id") or ""))
            except (TypeError, ValueError, AttributeError):
                continue
            if attachment_id not in result:
                result.append(attachment_id)
        return result
