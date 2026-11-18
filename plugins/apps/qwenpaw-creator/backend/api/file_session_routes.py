# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""File-native Creator Session, Conversation, Message, Event, and stop routes."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from hashlib import sha256
import json
import logging
import threading
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    Header,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import StreamingResponse
from pydantic import Field

from domain.enums import TERMINAL_SPECIALIST_STATUSES, TaskStatus
from domain.errors import (
    ConflictError,
    NotFoundError,
    StorageIntegrityError,
    ValidationError,
)
from schemas.common import StrictModel
from schemas.sessions import (
    ConversationCreated,
    ConversationPage,
    CreatorMessageAccepted,
    CreatorMessageRequest,
    CreatorSessionResponse,
    MessagePage,
)
from services.file_agent_runtime import (
    interrupt_creator_agent_runtime,
    notify_creator_agent_runtime,
)
from services.project_files.facade import CreatorFileServices
from services.runtime_files.errors import JsonlCorruptionError
from services.runtime_files.replay_filter import (
    filter_replay_events,
    make_replay_noise_line,
    replay_filter_enabled,
    replay_result_max_bytes,
)
from services.runtime_files.models import (
    MessageChannel,
    MessageClassification,
    SessionEventRecord,
)
from services.runtime_files.execution_store import (
    ExecutionStateConflict,
    ExecutionStoreError,
    ProjectExecutionStore,
)
from services.runtime_files.session_store import (
    MessagePayloadConflict,
    ProjectRuntimeSessionStore,
    RequestAdmissionConflict,
    RuntimeConversationNotFound,
    RuntimeSessionNotFound,
    SessionStateConflict,
    SessionStoreError,
)
from services.runtime_files.reconciliation import reconcile_terminal_task_runs
from services.runtime_files.status_projection import build_agent_status_bar

from .dependencies import (
    CreatorErrorRoute,
    project_file_services,
    resolve_idempotency_key,
)
from .file_execution_routes import _cancel_task_sync

logger = logging.getLogger("qwenpaw.creator.api.file_session_routes")

# Events scanned when looking for the admission's own ``message.accepted``.
# Generous next to a single send, bounded next to a session's whole history; a
# miss still falls back to the full scan.
_ACCEPTED_EVENT_TAIL_WINDOW = 200


def _log_safe(value: Any) -> str:
    """Neutralize CR/LF in user-provided values before logging."""
    return str(value).replace("\r", "\\r").replace("\n", "\\n")


router = APIRouter(
    prefix="/projects/{project_id}",
    tags=["creator-session-files"],
    route_class=CreatorErrorRoute,
)


class ConversationCreateRequest(StrictModel):
    title: str = Field(default="新对话", min_length=1, max_length=200)


def _store(services: CreatorFileServices) -> ProjectRuntimeSessionStore:
    return ProjectRuntimeSessionStore(services.root)


async def _cancel_active_project_tasks(
    services: CreatorFileServices,
    project_id: str,
) -> None:
    """Durably cancel every unfinished Task before Agent cancellation returns."""

    await asyncio.to_thread(
        _cancel_active_project_tasks_sync,
        services,
        project_id,
    )


def _cancel_active_project_tasks_sync(
    services: CreatorFileServices,
    project_id: str,
) -> None:
    """Filesystem-only terminalization used by detached hard-stop cleanup."""

    execution_store = ProjectExecutionStore(services.root)
    tasks = execution_store.list_tasks(project_id)
    for task in tasks:
        if task.status not in {TaskStatus.QUEUED, TaskStatus.RUNNING}:
            continue
        try:
            cancelled = _cancel_task_sync(
                services,
                project_id,
                task.task_id,
                "用户停止了当前项目的所有 Agent 活动",
            )
        except ExecutionStateConflict:
            # The worker reached a terminal state after the snapshot above.
            continue
        # Process-local workers were synchronously signalled before this
        # detached durable pass. No event-loop notification is needed here.
        _ = cancelled

    # Workers have already been cancelled and may never reach their normal
    # Run finalizer. Settle the derived execution heads too, including Tasks
    # cancelled by an earlier stop whose detached cleanup was interrupted.
    # This only reconciles durable terminal results; it cannot submit work.
    reconcile_terminal_task_runs(services.root, [project_id])


def _cancel_detached_project_tasks(
    services: CreatorFileServices,
    project_id: str,
) -> None:
    """Signal every process-local worker without waiting for its cleanup."""

    from services.media_files.image_execution import (
        file_image_execution_service,
    )
    from services.media_files.r2v_execution import file_r2v_execution_service
    from services.run_review.media_review import cancel_project_media_reviews
    from services.source_analysis.service import source_analysis_service

    file_image_execution_service(services).cancel_project(project_id)
    file_r2v_execution_service(services).cancel_project(project_id)
    source_analysis_service(services).cancel_project(project_id)
    cancel_project_media_reviews(project_id)


def _schedule_stop_cleanup(
    services: CreatorFileServices,
    project_id: str,
) -> None:
    def cleanup() -> None:
        try:
            _cancel_active_project_tasks_sync(services, project_id)
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "deferred stop cleanup failed for %s",
                _log_safe(project_id),
                exc_info=True,
            )

    threading.Thread(
        target=cleanup,
        name=f"creator-stop-cleanup:{project_id}",
        daemon=True,
    ).start()


def _translate_runtime_error(error: BaseException) -> None:
    if isinstance(
        error,
        (RuntimeSessionNotFound, RuntimeConversationNotFound),
    ):
        raise NotFoundError(str(error)) from error
    if isinstance(
        error,
        (
            MessagePayloadConflict,
            RequestAdmissionConflict,
            SessionStateConflict,
        ),
    ):
        raise ConflictError(str(error)) from error
    if isinstance(error, (ValueError, TypeError)):
        raise ValidationError(str(error)) from error
    if isinstance(error, (SessionStoreError, ExecutionStoreError)):
        raise StorageIntegrityError(str(error)) from error
    raise error


def _session_view(session: Any) -> dict[str, Any]:
    return {
        "id": session.session_id,
        "projectId": session.project_id,
        "status": session.status.value,
        "activeGoalId": session.active_goal_id,
        "lastMessageSeq": session.last_message_seq,
        "lastEventSeq": session.last_event_seq,
        "lastConsumedMessageSeq": session.last_consumed_message_seq,
        "error": session.error,
    }


def _message_parts(
    request: CreatorMessageRequest,
) -> tuple[list[dict[str, Any]], str]:
    parts = [
        item.model_dump(mode="json", exclude_none=True)
        for item in request.content
    ]
    if request.message is not None:
        if parts:
            raise ValidationError("message 与 content 不能同时提供")
        text = request.message.strip()
        if not text:
            raise ValidationError("message 不能为空")
        parts = [{"type": "text", "text": text}]
    if not parts:
        raise ValidationError("Creator message content 不能为空")
    intent = "\n".join(
        str(part.get("text") or "").strip()
        for part in parts
        if part.get("type") == "text" and str(part.get("text") or "").strip()
    )
    return parts, intent or "请处理本消息所附素材。"


def _event_payload(event: SessionEventRecord) -> dict[str, Any]:
    return {
        "eventId": event.event_id,
        "seq": event.event_seq,
        "type": event.event_type,
        "projectId": event.project_id,
        "creatorSessionId": event.creator_session_id,
        "at": event.created_at.isoformat(),
        "data": dict(event.payload),
    }


def _active_specialist_run_ids(
    services: CreatorFileServices,
    project_id: str,
) -> set[str] | None:
    """Runs still in flight, so their deltas are the only text they have.

    Taken once per connection and deliberately generous: a stale extra id
    costs a few deltas, a missing one blanks an in-flight message.
    """
    try:
        runs = ProjectExecutionStore(services.root).list_specialist_runs(
            project_id,
        )
    except Exception:  # noqa: BLE001 - preserve the raw replay on uncertainty
        return None
    return {
        run.run_id
        for run in runs
        if run.status not in TERMINAL_SPECIALIST_STATUSES
    }


def _sse(event: SessionEventRecord) -> str:
    body = json.dumps(
        _event_payload(event),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return (
        f"id: {event.event_seq}\nevent: {event.event_type}\ndata: {body}\n\n"
    )


@router.get(
    "/session",
    response_model=CreatorSessionResponse,
    response_model_exclude_none=True,
)
async def get_session(
    project_id: str,
    services: CreatorFileServices = Depends(project_file_services),
) -> dict[str, Any]:
    session_store = _store(services)
    execution_store = ProjectExecutionStore(services.root)
    try:
        session, tasks, runs = await asyncio.gather(
            asyncio.to_thread(
                session_store.get_project_session_snapshot,
                project_id,
            ),
            asyncio.to_thread(execution_store.list_tasks, project_id),
            asyncio.to_thread(
                execution_store.list_specialist_runs,
                project_id,
            ),
        )
    except BaseException as error:
        _translate_runtime_error(error)
    return {
        "session": _session_view(session),
        "agentStatusBar": build_agent_status_bar(
            session,
            tasks=tasks,
            runs=runs,
        ),
    }


@router.get(
    "/conversations",
    response_model=ConversationPage,
    response_model_exclude_none=True,
)
async def list_conversations(
    project_id: str,
    cursor: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    services: CreatorFileServices = Depends(project_file_services),
) -> dict[str, Any]:
    store = _store(services)
    try:
        session = await asyncio.to_thread(
            store.get_project_session_snapshot,
            project_id,
        )
        items = await asyncio.to_thread(
            store.list_conversations,
            project_id,
            session.session_id,
        )
    except BaseException as error:
        _translate_runtime_error(error)
    page = items[cursor : cursor + limit]
    next_cursor = (
        cursor + len(page) if cursor + len(page) < len(items) else None
    )
    return {
        "items": [
            {
                "conversationId": item.conversation_id,
                "title": item.title,
                "isDefault": item.is_default,
                "createdAt": item.created_at.isoformat(),
            }
            for item in page
        ],
        "nextCursor": next_cursor,
    }


@router.post(
    "/conversations",
    response_model=ConversationCreated,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation(
    project_id: str,
    request: ConversationCreateRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    services: CreatorFileServices = Depends(project_file_services),
) -> dict[str, Any]:
    key = resolve_idempotency_key(idempotency_key)
    conversation_id = (
        "conversation-" + sha256(key.encode("utf-8")).hexdigest()[:24]
    )
    store = _store(services)
    try:
        session = await asyncio.to_thread(
            store.get_project_session,
            project_id,
        )
        try:
            conversation = await asyncio.to_thread(
                store.get_conversation,
                project_id,
                session.session_id,
                conversation_id,
            )
            if conversation.title != request.title.strip():
                raise ConflictError(
                    "Idempotency-Key 已用于不同的 Conversation 请求",
                )
        except RuntimeConversationNotFound:
            conversation = await asyncio.to_thread(
                store.create_conversation,
                project_id,
                session.session_id,
                conversation_id=conversation_id,
                title=request.title.strip(),
            )
    except BaseException as error:
        _translate_runtime_error(error)
    return {
        "conversationId": conversation.conversation_id,
        "creatorSessionId": session.session_id,
        "title": conversation.title,
        "createdAt": conversation.created_at.isoformat(),
    }


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=MessagePage,
    response_model_exclude_none=True,
)
async def list_messages(
    project_id: str,
    conversation_id: str,
    after: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    before: int | None = Query(None, ge=1),
    tail: bool = Query(False),
    services: CreatorFileServices = Depends(project_file_services),
) -> dict[str, Any]:
    # ``after`` pages forward (live catch-up); ``before``/``tail`` page
    # backward through history.  Mixing the two directions in one request
    # has no coherent cursor, so it is rejected outright.
    backward = before is not None or tail
    if backward and after:
        raise ValidationError("after 与 before/tail 不能同时使用")
    store = _store(services)
    try:
        session = await asyncio.to_thread(
            store.get_project_session_snapshot,
            project_id,
        )
        await asyncio.to_thread(
            store.get_conversation,
            project_id,
            session.session_id,
            conversation_id,
        )
        # Over-fetch by one so "is there an older/newer page" stays answerable
        # without reading the whole stream: the cursor reads below stop as soon
        # as the window is full.
        if backward:
            messages = await asyncio.to_thread(
                store.list_recent_messages,
                project_id,
                session.session_id,
                limit=limit + 1,
                conversation_id=conversation_id,
                before_seq=before,
            )
        else:
            messages = await asyncio.to_thread(
                store.list_messages,
                project_id,
                session.session_id,
                after_seq=after,
                limit=limit + 1,
                conversation_id=conversation_id,
            )
    except BaseException as error:
        _translate_runtime_error(error)
    has_more = len(messages) > limit
    if has_more:
        # Backward paging wants the newest `limit` of what it read, forward
        # wants the oldest, and the extra record tells both that more exist.
        messages = messages[:limit] if not backward else messages[-limit:]
    page = messages
    next_after: int | None = (
        page[-1].message_seq if has_more and not backward and page else None
    )
    next_before: int | None = (
        page[0].message_seq if has_more and backward and page else None
    )
    return {
        "items": [
            {
                "messageId": item.message_id,
                "messageSeq": item.message_seq,
                "role": item.role,
                "content": [
                    part.model_dump(mode="json", exclude_none=True)
                    for part in item.content_parts
                ],
                "source": item.source,
                "metadata": item.metadata,
                "createdAt": item.created_at.isoformat(),
            }
            for item in page
        ],
        "nextAfter": next_after,
        "nextBefore": next_before,
    }


@router.post(
    "/messages",
    response_model=CreatorMessageAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def post_message(
    project_id: str,
    request: CreatorMessageRequest,
    response: Response,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    services: CreatorFileServices = Depends(project_file_services),
) -> dict[str, Any]:
    parts, intent = _message_parts(request)
    logger.info(
        "agent dock message: conversation=%s client_message_id=%s content=%s",
        _log_safe(request.conversation_id),
        _log_safe(request.client_message_id),
        _log_safe(intent),
    )
    key = resolve_idempotency_key(
        idempotency_key,
        stable_client_id=request.client_message_id,
    )
    store = _store(services)
    try:
        session = await asyncio.to_thread(
            store.get_project_session_snapshot,
            project_id,
        )
        if request.creator_session_id not in {None, session.session_id}:
            raise ValidationError("creatorSessionId 不属于 Project")
        await asyncio.to_thread(
            store.get_conversation,
            project_id,
            session.session_id,
            request.conversation_id,
        )
        admitted = await asyncio.to_thread(
            store.admit_user_request,
            project_id,
            session.session_id,
            request.conversation_id,
            request_id=key,
            client_message_id=request.client_message_id,
            content_parts=parts,
            channel=MessageChannel.AGENTDOCK,
            classification=MessageClassification.MUTATION_INSTRUCTION,
            source="user",
            metadata={
                "context": request.context,
                "assetVersionRefs": request.asset_version_refs,
            },
        )
        refreshed = await asyncio.to_thread(
            store.get_project_session_snapshot,
            project_id,
        )
        if refreshed.active_goal_id is None:
            await asyncio.to_thread(
                store.create_goal,
                project_id,
                session.session_id,
                request.conversation_id,
                root_message_seq=admitted.message.message_seq,
                intent=intent,
                goal_id="goal-" + sha256(key.encode("utf-8")).hexdigest()[:24],
                metadata={"source": "agentdock"},
            )
        # The admission just happened, so its event sits at the durable tail.
        # Reading the whole stream per message cost the session's full history
        # (99 MB observed). The full scan remains as an explicit fallback so a
        # window that was too small can never turn into a duplicate
        # ``message.accepted`` write.
        window = await asyncio.to_thread(
            store.list_recent_events,
            project_id,
            session.session_id,
            limit=1,
            event_type="message.accepted",
            message_id=admitted.message.message_id,
            max_scan=_ACCEPTED_EVENT_TAIL_WINDOW,
        )
        event = window[-1] if window else None
        if event is None:
            # Exhaustive, but bounded in memory: walk the stream backwards one
            # record at a time instead of materializing it.  The fallback used
            # to parse every event the Session ever wrote -- and the send path
            # runs it per message -- which is exactly what a long session
            # cannot afford.  The answer is unchanged: a miss here still means
            # the admission has no ``message.accepted`` anywhere.
            found = await asyncio.to_thread(
                store.list_recent_events,
                project_id,
                session.session_id,
                limit=1,
                event_type="message.accepted",
                message_id=admitted.message.message_id,
                max_scan=None,
            )
            event = found[-1] if found else None
            if event is not None:
                logger.warning(
                    "message.accepted found beyond the %d-event tail window "
                    "project=%s message=%s",
                    _ACCEPTED_EVENT_TAIL_WINDOW,
                    _log_safe(project_id),
                    admitted.message.message_id,
                )
        if event is None:
            event = await asyncio.to_thread(
                store.append_event,
                project_id,
                session.session_id,
                event_type="message.accepted",
                actor="user",
                message_id=admitted.message.message_id,
                payload={
                    "messageId": admitted.message.message_id,
                    "messageSeq": admitted.message.message_seq,
                    "classification": admitted.message.classification.value,
                    "reviewPolicy": admitted.review_policy.value,
                },
            )
    except BaseException as error:
        _translate_runtime_error(error)
    # Only a boundary that actually captured a running mainline may
    # supersede it. An idle-goal boundary interrupts nothing — firing the
    # supersede anyway can cancel the run the dispatcher already started
    # for this very message, whose cleanup then consumes the message and
    # leaves the Session in RESUMING with no pending input to recover it.
    if (
        admitted.review_boundary is not None
        and admitted.review_boundary.interrupted_run_id is not None
    ):
        await interrupt_creator_agent_runtime(
            project_id,
            superseded=True,
            reason="agentdock_interrupt",
            expected_run_id=admitted.review_boundary.interrupted_run_id,
        )
    notify_creator_agent_runtime(project_id)
    response.headers["X-Idempotent-Replay"] = (
        "true" if admitted.replayed else "false"
    )
    logger.info(
        "message posted: project=%s session=%s seq=%d replayed=%s",
        _log_safe(project_id),
        session.session_id,
        admitted.message.message_seq,
        admitted.replayed,
    )
    return {
        "messageSeq": admitted.message.message_seq,
        "eventSeq": event.event_seq,
        "classification": admitted.message.classification.value,
        "appendState": "appended",
        "creatorSessionId": session.session_id,
        "conversationId": request.conversation_id,
    }


@router.get("/events")
async def stream_events(
    project_id: str,
    request: Request,
    after: int = Query(0, ge=0),
    last_event_id: str | None = Header(None, alias="Last-Event-ID"),
    services: CreatorFileServices = Depends(project_file_services),
) -> StreamingResponse:
    cursor = after
    if last_event_id is not None:
        try:
            cursor = max(cursor, int(last_event_id))
        except ValueError as error:
            raise ValidationError("Last-Event-ID 必须是 event seq") from error
    store = _store(services)
    try:
        session = await asyncio.to_thread(
            store.get_project_session_snapshot,
            project_id,
        )
    except BaseException as error:
        _translate_runtime_error(error)

    async def body() -> AsyncIterator[str]:
        # Historical streaming deltas are dropped and oversized tool results
        # summarized, because the client discards both by design while it
        # genuinely needs every lifecycle event. See replay_filter's module
        # docstring for the measured breakdown. The drop also happens inside
        # the reader: parsing 70,942 deltas only to discard them held the
        # interpreter for 90+ seconds per replay and starved every other
        # endpoint in the process.
        #
        # Two correctness guards frame the drop.
        #
        # * Replay boundary: anything appended after connect is a live
        #   event and must reach the client (review #243 blocking #1).
        # * Active-run exemption: deltas belonging to a run that was
        #   still in flight when this connection opened have no durable
        #   message yet, so dropping them blanks a partially written
        #   reply (review #243 P2). The exemption used to live only in
        #   the post-parse filter, but the byte-level classifier fired
        #   first and the exempt events never reached it -- a returning
        #   user still lost the prefix. Computing the active set before
        #   constructing the reader lets both layers agree on what to
        #   spare.
        filter_enabled = replay_filter_enabled()
        active_run_ids: set[str] = set()
        if filter_enabled:
            specialist_ids = await asyncio.to_thread(
                _active_specialist_run_ids,
                services,
                project_id,
            )
            if specialist_ids is None:
                filter_enabled = False
            else:
                active_run_ids = specialist_ids
            # The mainline agent run carries ``agent.message_delta``
            # events with its own runId, and session.status stays
            # non-terminal for the whole turn. Terminal states
            # (IDLE / CANCELLED / ERROR) do clear active_run_id soon
            # enough that this guard is on the safe side of "too
            # large": including one extra run means a few extra bytes
            # on the wire, missing one blanks an in-flight reply.
            if session.active_run_id is not None and session.status not in {
                "IDLE",
                "CANCELLED",
                "ERROR",
            }:
                active_run_ids = active_run_ids | {session.active_run_id}
        reader = store.event_reader(
            project_id,
            session.session_id,
            after_seq=cursor,
            skip_noise=(
                make_replay_noise_line(active_run_ids)
                if filter_enabled
                else None
            ),
            replay_boundary_seq=(
                session.last_event_seq if filter_enabled else None
            ),
        )
        result_max_bytes = replay_result_max_bytes()
        idle_ticks = 0
        while not await request.is_disconnected():
            try:
                events = await asyncio.to_thread(
                    reader.read,
                    limit=200,
                )
            except SessionStoreError:
                return
            except JsonlCorruptionError:
                # The response has already started. Close this replay so the
                # client can reconnect with its last delivered cursor; never
                # skip a corrupt line or silently follow a replacement file.
                logger.warning(
                    "Event replay stopped for project=%s session=%s",
                    _log_safe(project_id),
                    _log_safe(session.session_id),
                    exc_info=True,
                )
                return
            if events:
                idle_ticks = 0
                if filter_enabled:
                    # ``filter_replay_events`` shares skip_noise's scope:
                    # it drops historical deltas for runs that are not
                    # currently active, and summarizes oversized tool
                    # results. Applied past the boundary it would silently
                    # discard live deltas from a run that started after
                    # connect -- the same defect review #243 blocking #1
                    # named for the byte-level filter. Split the batch
                    # along the replay boundary and only filter the left
                    # half.
                    boundary = session.last_event_seq
                    replayed = [
                        event
                        for event in events
                        if event.event_seq <= boundary
                    ]
                    live = [
                        event for event in events if event.event_seq > boundary
                    ]
                    events = (
                        filter_replay_events(
                            replayed,
                            active_run_ids=active_run_ids,
                            result_max_bytes=result_max_bytes,
                        )
                        + live
                    )
                for event in events:
                    yield _sse(event)
                continue
            idle_ticks += 1
            if idle_ticks >= 30:
                idle_ticks = 0
                yield ": keep-alive\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/interrupt", status_code=status.HTTP_202_ACCEPTED)
async def interrupt(
    project_id: str,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    services: CreatorFileServices = Depends(project_file_services),
) -> dict[str, Any]:
    resolve_idempotency_key(idempotency_key)
    store = _store(services)
    try:
        # Snapshot read (shared lock): the full get_project_session recovery
        # replays the whole event stream under the exclusive Runtime lock and
        # loses the lock race against steady UI polling on large sessions, so
        # the stop request itself stalled while the dock showed 「正在停止」
        # forever.  Only the status + head pointers are needed here.
        session = await asyncio.to_thread(
            store.get_project_session_snapshot,
            project_id,
        )
        if session.status.value not in {"INTERRUPT_REQUESTED", "CANCELLED"}:
            session = await asyncio.to_thread(
                store.set_session_status,
                project_id,
                session.session_id,
                "INTERRUPT_REQUESTED",
            )
            await asyncio.to_thread(
                store.append_event,
                project_id,
                session.session_id,
                event_type="session.status_changed",
                actor="user",
                payload={
                    "status": "INTERRUPT_REQUESTED",
                    "stopRequested": True,
                },
            )
        await interrupt_creator_agent_runtime(
            project_id,
            superseded=False,
            reason="user_interrupt",
        )
        _cancel_detached_project_tasks(services, project_id)
        session = await asyncio.to_thread(
            store.hard_stop_session,
            project_id,
            session.session_id,
        )
        _schedule_stop_cleanup(services, project_id)
    except BaseException as error:
        _translate_runtime_error(error)
    return {
        "creatorSessionId": session.session_id,
        "status": session.status.value,
        "stopRequested": True,
    }


__all__ = ["router"]
