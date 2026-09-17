# -*- coding: utf-8 -*-
"""完整会话契约的 Legacy 单文件 JSON 实现。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TypeVar

from ....utils.io_utils import read_json, run_sync_io, write_json_atomic
from .conversation import (
    AttachmentRecord,
    ConversationRecord,
    ConversationRepository,
    MessageRecord,
    RepositoryConflictError,
    RunEventRecord,
    RunRecord,
    ToolCallRecord,
)

RecordT = TypeVar("RecordT")


class JsonConversationRepository(ConversationRepository):

    async def bind_publication(
        self,
        conversation_id,
        *,
        expected_agent_id,
        shared_app_id,
        publication_id,
        updated_at,
    ):
        def operation(state):
            for index, item in enumerate(state["conversations"]):
                if item["id"] != str(conversation_id):
                    continue
                record = self._record(item, ConversationRecord)
                if record.agent_id != expected_agent_id:
                    return None
                if record.shared_app_id is not None or record.publication_id is not None:
                    if (
                        record.shared_app_id == shared_app_id
                        and record.publication_id == publication_id
                    ):
                        return record
                    raise RepositoryConflictError("conversation_publication_conflict")
                updated = record.model_copy(
                    update={
                        "shared_app_id": shared_app_id,
                        "publication_id": publication_id,
                        "model_override_id": None,
                        "updated_at": updated_at,
                    }
                )
                state["conversations"][index] = self._dump(updated)
                return updated
            return None

        return await self._mutate(operation)

    async def set_model_override(
        self, conversation_id, *, expected_agent_id, model_override_id, updated_at
    ):
        def operation(state):
            for index, item in enumerate(state["conversations"]):
                if item["id"] == str(conversation_id) and item["agent_id"] == str(
                    expected_agent_id
                ):
                    record = self._record(item, ConversationRecord).model_copy(
                        update={
                            "model_override_id": model_override_id,
                            "updated_at": updated_at,
                        }
                    )
                    state["conversations"][index] = self._dump(record)
                    return record
            return None

        return await self._mutate(operation)

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path).expanduser()
        self._lock = asyncio.Lock()

    def _load(self) -> dict:
        if not self.path.exists():
            return {
                key: []
                for key in (
                    "conversations",
                    "messages",
                    "runs",
                    "run_events",
                    "tool_calls",
                    "attachments",
                )
            }
        return read_json(self.path)

    def _save(self, state: dict) -> None:
        write_json_atomic(self.path, state, sort_keys=True)

    async def _read(self) -> dict:
        return await run_sync_io(self._load)

    async def _mutate(self, operation):
        async with self._lock:
            state = await self._read()
            result = operation(state)
            await run_sync_io(self._save, state)
            return result

    @staticmethod
    def _record(data: dict, model):
        return model.model_validate(data)

    @staticmethod
    def _dump(record) -> dict:
        return record.model_dump(mode="json")

    @staticmethod
    def _insert_idempotent(items: list[dict], record, *, keys, conflict: str):
        dump = JsonConversationRepository._dump(record)
        for item in items:
            if all(item[key] == dump[key] for key in keys):
                if item != dump:
                    raise RepositoryConflictError(conflict)
                return record
        items.append(dump)
        return record

    async def create_conversation(self, record):
        return await self._mutate(
            lambda state: self._insert_idempotent(
                state["conversations"],
                record,
                keys=("id",),
                conflict="conversation_conflict",
            )
        )

    async def get_conversation(self, conversation_id):
        state = await self._read()
        return next(
            (
                self._record(item, ConversationRecord)
                for item in state["conversations"]
                if item["id"] == str(conversation_id)
            ),
            None,
        )

    async def list_conversations(self, *, owner_user_id, include_deleted=False):
        state = await self._read()
        records = [
            self._record(item, ConversationRecord)
            for item in state["conversations"]
            if item["owner_user_id"] == str(owner_user_id)
            and (include_deleted or item["status"] != "deleted")
        ]
        return sorted(records, key=lambda item: item.updated_at, reverse=True)

    async def update_conversation(
        self, conversation_id, *, title=None, status=None, updated_at
    ):
        def operation(state):
            for index, item in enumerate(state["conversations"]):
                if item["id"] == str(conversation_id):
                    record = self._record(item, ConversationRecord)
                    updates = {"updated_at": updated_at}
                    if title is not None:
                        updates["title"] = title
                    if status is not None:
                        updates["status"] = status
                        if status == "deleted":
                            updates["deleted_at"] = updated_at
                    updated = record.model_copy(update=updates)
                    state["conversations"][index] = self._dump(updated)
                    return updated
            return None

        return await self._mutate(operation)

    async def save_message(self, record):
        return await self._mutate(
            lambda state: self._insert_idempotent(
                state["messages"],
                record,
                keys=("conversation_id", "sequence"),
                conflict="message_sequence_conflict",
            )
        )

    async def list_messages(self, conversation_id):
        state = await self._read()
        records = [
            self._record(item, MessageRecord)
            for item in state["messages"]
            if item["conversation_id"] == str(conversation_id)
        ]
        return sorted(records, key=lambda item: item.sequence)

    async def create_run(self, record):
        return await self._mutate(
            lambda state: self._insert_idempotent(
                state["runs"], record, keys=("id",), conflict="run_conflict"
            )
        )

    async def get_run(self, run_id):
        state = await self._read()
        return next(
            (
                self._record(item, RunRecord)
                for item in state["runs"]
                if item["id"] == str(run_id)
            ),
            None,
        )

    async def finish_run(self, run_id, *, status, finished_at, error_summary=None):
        def operation(state):
            for index, item in enumerate(state["runs"]):
                if item["id"] == str(run_id):
                    updated = self._record(item, RunRecord).model_copy(
                        update={
                            "status": status,
                            "finished_at": finished_at,
                            "error_summary": error_summary,
                        }
                    )
                    state["runs"][index] = self._dump(updated)
                    return updated
            return None

        return await self._mutate(operation)

    async def append_event(self, record):
        return await self._mutate(
            lambda state: self._insert_idempotent(
                state["run_events"],
                record,
                keys=("run_id", "sequence"),
                conflict="run_event_sequence_conflict",
            )
        )

    async def list_events(self, run_id):
        state = await self._read()
        records = [
            self._record(item, RunEventRecord)
            for item in state["run_events"]
            if item["run_id"] == str(run_id)
        ]
        return sorted(records, key=lambda item: item.sequence)

    async def upsert_tool_call(self, record):
        def operation(state):
            dump = self._dump(record)
            for index, item in enumerate(state["tool_calls"]):
                if (
                    item["run_id"] == dump["run_id"]
                    and item["call_id"] == dump["call_id"]
                ):
                    state["tool_calls"][index] = dump
                    return record
            state["tool_calls"].append(dump)
            return record

        return await self._mutate(operation)

    async def list_tool_calls(self, run_id):
        state = await self._read()
        return [
            self._record(item, ToolCallRecord)
            for item in state["tool_calls"]
            if item["run_id"] == str(run_id)
        ]

    async def add_attachment(self, record):
        return await self._mutate(
            lambda state: self._insert_idempotent(
                state["attachments"],
                record,
                keys=("storage_key",),
                conflict="attachment_conflict",
            )
        )

    async def get_attachment(self, *, attachment_id, owner_user_id):
        state = await self._read()
        for item in state["attachments"]:
            if (
                item["id"] == str(attachment_id)
                and item["owner_user_id"] == str(owner_user_id)
            ):
                return self._record(item, AttachmentRecord)
        return None

    async def bind_attachment(
        self,
        *,
        attachment_id,
        owner_user_id,
        agent_id,
        conversation_id,
        message_id,
    ):
        def operation(state):
            for index, item in enumerate(state["attachments"]):
                if item["id"] != str(attachment_id):
                    continue
                if item["owner_user_id"] != str(owner_user_id):
                    raise RepositoryConflictError("attachment_owner_mismatch")
                if item["agent_id"] != str(agent_id):
                    raise RepositoryConflictError("attachment_agent_mismatch")
                current_conversation_id = item.get("conversation_id")
                if current_conversation_id not in {
                    None,
                    str(conversation_id),
                }:
                    raise RepositoryConflictError(
                        "attachment_conversation_mismatch"
                    )
                current_message_id = item.get("message_id")
                if current_message_id not in {None, str(message_id)}:
                    raise RepositoryConflictError("attachment_message_mismatch")
                updated = {
                    **item,
                    "conversation_id": str(conversation_id),
                    "message_id": str(message_id),
                }
                state["attachments"][index] = updated
                return self._record(updated, AttachmentRecord)
            raise RepositoryConflictError("attachment_not_found")

        return await self._mutate(operation)

    async def list_attachments(self, conversation_id):
        state = await self._read()
        return [
            self._record(item, AttachmentRecord)
            for item in state["attachments"]
            if item["conversation_id"] == str(conversation_id)
        ]

    async def list_owned_attachments(
        self,
        *,
        owner_user_id,
        agent_id,
        lifecycle=None,
        conversation_id=None,
    ):
        state = await self._read()
        records = []
        for item in state["attachments"]:
            item_lifecycle = item.get("lifecycle", "temporary")
            if item["owner_user_id"] != str(owner_user_id):
                continue
            if item["agent_id"] != str(agent_id):
                continue
            if lifecycle is None and item_lifecycle == "deleted":
                continue
            if lifecycle is not None and item_lifecycle != lifecycle:
                continue
            if conversation_id is not None and item.get("conversation_id") != str(
                conversation_id
            ):
                continue
            records.append(self._record(item, AttachmentRecord))
        return sorted(records, key=lambda record: (record.created_at, str(record.id)))

    async def update_attachment_lifecycle(self, *, attachment_id, owner_user_id, lifecycle, storage_key, saved_path, saved_at, deleted_at, updated_at):
        def operation(state):
            for index, item in enumerate(state["attachments"]):
                if item["id"] == str(attachment_id) and item["owner_user_id"] == str(owner_user_id):
                    updated = {**item, "lifecycle": lifecycle, "storage_key": storage_key, "saved_path": saved_path, "saved_at": saved_at.isoformat() if saved_at else None, "deleted_at": deleted_at.isoformat() if deleted_at else None, "updated_at": updated_at.isoformat()}
                    state["attachments"][index] = updated
                    return self._record(updated, AttachmentRecord)
            return None
        return await self._mutate(operation)
