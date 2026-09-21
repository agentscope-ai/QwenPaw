"""Typed input admission for the one Agent run owned by a Chat."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from ...config.config import load_agent_config
from ...constant import QWENPAW_CLIENT_MESSAGE_ID_KEY, QWENPAW_RECEIVED_AT_KEY
from ...runtime.reply_cycle import TIMELINE_ORDER_METADATA_KEY
from ...services.project_directory import (
    resolve_effective_project_dir,
    session_project_dir,
)
from ..task_tracker import RunInput
from .models import ChatSpec, is_realtime_voice_chat
from .runtime_events import user_message_sse
from .timeline import ChatTimelineJournal


@dataclass(frozen=True)
class ChatInputRequest:
    """Provider- and transport-neutral input submitted to one Chat."""

    content_parts: tuple[Any, ...]
    client_message_id: str
    message_metadata: dict[str, Any] = field(default_factory=dict)
    request_context: dict[str, Any] = field(default_factory=dict)
    model_slot_override: Any = None
    origin: Literal["keyboard", "speech", "api"] = "api"
    mode: Literal["queue", "steer"] = "steer"

    def __post_init__(self) -> None:
        content_parts = tuple(self.content_parts)
        client_message_id = self.client_message_id.strip()
        origin = self.origin.strip()
        if (
            not content_parts
            or not client_message_id
            or origin not in {"keyboard", "speech", "api"}
            or self.mode not in {"queue", "steer"}
        ):
            raise ValueError(
                "invalid Chat input content, identity, origin or mode",
            )
        metadata = dict(self.message_metadata)
        metadata[QWENPAW_CLIENT_MESSAGE_ID_KEY] = client_message_id
        object.__setattr__(self, "content_parts", content_parts)
        object.__setattr__(self, "client_message_id", client_message_id)
        object.__setattr__(self, "message_metadata", metadata)
        object.__setattr__(self, "request_context", dict(self.request_context))
        object.__setattr__(self, "origin", origin)

    @classmethod
    def from_native_payload(
        cls,
        payload: dict[str, Any],
        *,
        origin: Literal["keyboard", "speech", "api"],
    ) -> ChatInputRequest:
        """Translate the Console adapter payload at the HTTP boundary."""
        metadata = dict(payload.get("message_metadata") or {})
        client_message_id = str(
            metadata.get(QWENPAW_CLIENT_MESSAGE_ID_KEY) or uuid4().hex,
        )
        meta = payload.get("meta") or {}
        return cls(
            content_parts=tuple(payload.get("content_parts") or ()),
            client_message_id=client_message_id,
            message_metadata=metadata,
            request_context=dict(meta.get("request_context") or {}),
            model_slot_override=payload.get("model_slot_override"),
            origin=origin,
        )

    def text(self) -> str:
        """Return visible text without dropping the original rich content."""
        fragments: list[str] = []
        for part in self.content_parts:
            if isinstance(part, str):
                text = part
            elif isinstance(part, dict):
                text = part.get("text", "")
            else:
                text = getattr(part, "text", "")
            if isinstance(text, str) and text.strip():
                fragments.append(text.strip())
        return "\n".join(fragments)


@dataclass(frozen=True)
class ChatInputSubmission:  # pylint: disable=too-few-public-methods
    """Result of accepting one input into a Chat's Agent run."""

    status: str
    events: asyncio.Queue
    run_id: str
    input_id: str


class ChatRunCoordinator:
    """The only start-or-steer decision owner for Chat input."""

    @staticmethod
    async def _console_payload(
        workspace: Any,
        chat: ChatSpec,
        request: ChatInputRequest,
    ) -> dict[str, Any]:
        agent_config = await asyncio.to_thread(
            load_agent_config,
            workspace.agent_id,
        )
        project_dir, project_source = await asyncio.to_thread(
            resolve_effective_project_dir,
            workspace.workspace_dir,
            agent_config.project_dir,
            session_project_dir(chat.meta),
        )
        request_context = dict(request.request_context)
        request_context["input_origin"] = request.origin
        request_context["project_dir"] = str(project_dir)
        request_context["project_dir_source"] = project_source
        if is_realtime_voice_chat(chat):
            request_context["source"] = "realtime_voice"

        payload = {
            "channel_id": chat.channel,
            "sender_id": chat.user_id,
            "content_parts": list(request.content_parts),
            "message_metadata": dict(request.message_metadata),
            "meta": {
                "session_id": chat.session_id,
                "user_id": chat.user_id,
                "request_context": request_context,
            },
        }
        if request.model_slot_override is not None:
            payload["model_slot_override"] = request.model_slot_override
        return payload

    @classmethod
    async def submit(
        cls,
        workspace: Any,
        chat: ChatSpec,
        request: ChatInputRequest,
    ) -> ChatInputSubmission:
        """Atomically start or steer the Chat's current Agent run."""
        workspace.task_tracker.input_context(chat.id).register_execution(
            request.client_message_id,
            request.text(),
        )
        context = workspace.task_tracker.input_context(chat.id)
        context.set_admission(request.client_message_id, "preparing")
        try:
            submission = await cls._submit_registered(workspace, chat, request)
        except asyncio.CancelledError:
            context.set_admission(request.client_message_id, "cancelled")
            raise
        except OverflowError:
            context.set_admission(request.client_message_id, "rejected")
            raise
        except Exception:
            context.set_admission(request.client_message_id, "failed")
            raise
        context.set_admission(request.client_message_id, "admitted")
        return submission

    @classmethod
    async def _submit_registered(
        cls,
        workspace: Any,
        chat: ChatSpec,
        request: ChatInputRequest,
    ) -> ChatInputSubmission:
        received_at = datetime.now(UTC).isoformat()
        console_channel = await workspace.channel_manager.get_channel(
            "console"
        )
        if console_channel is None:
            raise RuntimeError("Channel Console not found")

        timeline = ChatTimelineJournal(workspace, chat)
        timeline_order = await timeline.reserve_order()
        metadata = dict(request.message_metadata)
        metadata[QWENPAW_RECEIVED_AT_KEY] = received_at
        metadata[TIMELINE_ORDER_METADATA_KEY] = timeline_order
        request = replace(request, message_metadata=metadata)
        payload = await cls._console_payload(workspace, chat, request)
        # Do not recreate a background owner after deletion during preparation.
        workspace.task_tracker.input_context(chat.id)
        from .background_results import ChatBackgroundResults

        results = workspace.task_tracker.background_results.get(chat.id)
        if results is None:
            results = ChatBackgroundResults(workspace.task_tracker, chat.id)
            workspace.task_tracker.background_results[chat.id] = results
        payload["meta"]["request_context"]["_background_results"] = results
        results.payload = payload
        results.stream_fn = console_channel.stream_one
        results.workspace = workspace
        results.reserve_order = timeline.reserve_order
        accepted_event = user_message_sse(
            request.content_parts,
            request.client_message_id,
            metadata=request.message_metadata,
        )
        queue, status, run_id = await workspace.task_tracker.submit_or_start(
            chat.id,
            payload,
            console_channel.stream_one,
            RunInput(
                content_parts=request.content_parts,
                idempotency_key=request.client_message_id,
                message_metadata=request.message_metadata,
                request_context={
                    key: value
                    for key, value in payload["meta"][
                        "request_context"
                    ].items()
                    if key != "_background_results"
                },
                model_slot_override=request.model_slot_override,
                mode=request.mode,
                timeline_order=timeline_order,
            ),
            owner=workspace,
            accepted_sse=accepted_event,
            reserve_timeline_order=timeline.reserve_order,
        )
        if status == "full" or queue is None:
            raise OverflowError(
                "The current task has too many pending inputs."
            )
        conversation = workspace.task_tracker.conversation_views.get(chat.id)
        if conversation is not None and status != "duplicate":
            from .conversation_view import ConversationItem

            conversation.observe(
                (
                    ConversationItem(
                        request.client_message_id,
                        timeline_order,
                        "user",
                        request.text(),
                        (request.client_message_id,),
                        "user",
                    ),
                )
            )
        results.retry_pending()
        return ChatInputSubmission(
            status=status,
            events=queue,
            run_id=run_id,
            input_id=request.client_message_id,
        )


__all__ = [
    "ChatInputRequest",
    "ChatInputSubmission",
    "ChatRunCoordinator",
]
