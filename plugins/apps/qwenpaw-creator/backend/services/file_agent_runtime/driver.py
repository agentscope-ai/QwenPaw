# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=cell-var-from-loop,protected-access,too-many-branches
# pylint: disable=too-many-statements,unused-argument
"""SQLite-free Creator Agent loop over Project and Runtime files."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import mimetypes
from pathlib import Path, PurePosixPath
import secrets
import threading
import time
from typing import Any
from urllib.parse import unquote, urlparse
from uuid import NAMESPACE_URL, uuid4, uuid5

from domain.refs import workspace_asset_ref
from domain.enums import (
    CreatorGoalStatus,
    CreatorSessionStatus,
    SpecialistRole,
    SpecialistRunStatus,
    TaskStatus,
)
from domain.errors import ConflictError
from models.config import (
    EXECUTION_AUTHORIZATION_ALLOW_ALL,
    get_execution_authorization_mode,
    get_text_model_name,
    get_vlm_model_name,
    get_web_grounding_max_sources,
    get_web_grounding_timeout_seconds,
    get_image_model_name,
    get_video_backend,
    get_video_model_name,
)
from models.media_transport import validate_reference_image_bytes
from services.project_files.agent_tools import (
    AgentProjectToolContext,
    AgentProjectTools,
    agent_project_tool_manifest,
)
from services.project_files.commit import ProjectCommitBoundary
from services.project_files.facade import CreatorFileServices
from services.project_files.assets import AssetAlreadyExists, AssetFileStore
from services.project_files.models import (
    IndexedFile,
    Project,
    SourceAssetVersion,
)
from services.runtime_files.models import (
    ChangeOrigin,
    CreatorMessageRecord,
    MessageChannel,
    ReviewPolicy,
)
from services.runtime_files.execution_models import (
    ExecutionAuthorizationRecord,
    ExecutionAuthorizationStatus,
    SpecialistRunRecord,
)
from services.runtime_files.execution_store import ProjectExecutionStore
from services.execution_pricing import (
    CostEstimate,
    estimate_execution_cost,
)
from services.observability import trace_event, traced_async
from services.source_analysis import SourceAgentToolContext
from services.specialist_tools import (
    FileSpecialistToolRegistry,
    SpecialistToolSpec,
    SpecialistToolWait,
)
from services.runtime_files.session_store import (
    ProjectRuntimeSessionStore,
    RuntimeGoalNotFound,
    SessionStateConflict,
)
from services.web_grounding import ground_prompt_context

from .model_client import (
    AgentChatClient,
    AgentModelConfigurationError,
    AgentModelError,
    AgentStreamCallbackError,
    AgentStreamCallbackPassthrough,
    AgentModelTurn,
    AgentScopeAgentChatClient,
    AgentScopeVlmChatClient,
)
from .models import AgentRunStatus, CreatorAgentRunRecord
from .native_media import source_intelligence_content_parts
from .prompts import render_creator_system_prompt
from .run_store import AgentRunStateConflict, CreatorAgentRunStore
from .subagents import (
    DELEGATE_TOOL_NAME,
    DelegateToAgentInput,
    delegate_tool_manifest,
    specialist_system_prompt,
)

GROUND_PROMPT_CONTEXT_TOOL_NAME = "ground_prompt_context"
GROUNDING_VISUAL_MAX_BYTES = 16 * 1024 * 1024


def _grounding_stable_id(prefix: str, project_id: str, identity: str) -> str:
    value = uuid5(
        NAMESPACE_URL,
        f"qwenpaw-creator:grounding:{prefix}:{project_id}:{identity}",
    ).hex
    return f"{prefix}-{value}"


def _grounding_media_kind(media_type: str) -> str:
    main_type = media_type.split("/", 1)[0].casefold()
    if main_type in {"image", "video", "audio", "text"}:
        return main_type
    if media_type.casefold() in {"application/pdf"}:
        return "document"
    return "other"


def _grounding_extension(path: Path, media_type: str) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return suffix
    guessed = mimetypes.guess_extension(media_type)
    return (
        guessed
        if guessed in {".jpg", ".jpeg", ".png", ".webp", ".gif"}
        else ".img"
    )


def _grounding_local_path(source: Mapping[str, Any]) -> Path | None:
    raw_path = str(source.get("local_path") or "").strip()
    if raw_path:
        return Path(raw_path)
    raw_url = str(source.get("local_url") or "").strip()
    if not raw_url:
        return None
    parsed = urlparse(raw_url)
    if parsed.scheme != "file":
        return None
    return Path(unquote(parsed.path))


def _grounding_visual_is_usable(source: Mapping[str, Any]) -> bool:
    verification = source.get("verification")
    return (
        isinstance(verification, Mapping)
        and str(verification.get("status") or "").casefold() == "accepted"
    )


def _ground_prompt_context_tool_manifest() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": GROUND_PROMPT_CONTEXT_TOOL_NAME,
            "description": (
                "对用户目标中的真实人物、品牌、地点、赛事、IP、视觉风格或文化/服饰/材质引用"
                "执行 web grounding；返回 source-backed text context 和下载后的视觉参考。"
                "这是只读工具，不修改 Project。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "projectId": {"type": "string", "minLength": 1},
                    "prompt": {"type": "string"},
                    "queries": {
                        "type": "array",
                        "description": (
                            "可选的简短检索建议，按实际检索目标生成最少必要数量，最多 6 条；6 是上限而非配额。"
                            "每个独立人物、节目/舞台或风格目标至多一条，不得为了凑数制造 query。"
                            "真实人物身份检索只使用规范姓名和稳定身份词，"
                            "例如 'Erling Haaland official profile portrait'；除非用户明确要求特定时期，"
                            "或所查事实本身具有时效性，否则不得添加年份或 current/latest，也不得添加 "
                            "personality、fashion、style、look 等宽泛修饰词。"
                            "舞台、节目和视觉风格必须作为单独的 context query。"
                        ),
                        "items": {"type": "string"},
                    },
                    "includeVisuals": {"type": "boolean"},
                    "context": {
                        "type": "object",
                        "additionalProperties": True,
                    },
                    "force": {"type": "boolean"},
                    "detectOnly": {"type": "boolean"},
                    "detector": {
                        "type": "string",
                        "enum": ["hybrid", "llm", "heuristic"],
                    },
                },
                "required": ["projectId"],
                "additionalProperties": False,
            },
        },
    }


class FileAgentRuntimeError(RuntimeError):
    pass


class ToolArgumentsJSONError(FileAgentRuntimeError):
    """The model streamed tool arguments that never became a JSON object.

    Raised per tool call and fed back to the model as a failed tool result;
    it must never terminate the whole run.
    """


class StaleAgentRun(FileAgentRuntimeError, AgentStreamCallbackPassthrough):
    """Raised when a revoked run reaches a model/tool/commit fence."""


@dataclass(slots=True)
class _ProjectTask:
    project_id: str
    run_id: str
    message_seq: int
    epoch: int
    task: asyncio.Task[None]
    superseded: bool = False
    interrupting: bool = False


@dataclass(frozen=True, slots=True)
class _LoopResult:
    summary: str
    tool_call_count: int
    review_ids: tuple[str, ...]


class _FencedCommitBoundary:
    """Hold the run fence throughout publication.

    Interrupt revocation uses the same process lock.  If publication already
    began, interrupt waits for that local atomic commit to finish; once the
    interrupt returns, the old run cannot begin another commit.
    """

    def __init__(
        self,
        driver: FileCreatorAgentRuntime,
        project_id: str,
        run_id: str,
        epoch: int,
        delegate: ProjectCommitBoundary,
    ) -> None:
        self.driver = driver
        self.project_id = project_id
        self.run_id = run_id
        self.epoch = epoch
        self.delegate = delegate

    def commit(self, **kwargs: Any):
        with self.driver._publication_lock:
            self.driver._assert_epoch(self.project_id, self.run_id, self.epoch)
            return self.delegate.commit(**kwargs)


class FileCreatorAgentRuntime:
    """One process coordinator consuming durable user messages per Project."""

    def __init__(
        self,
        services: CreatorFileServices,
        *,
        model_client: AgentChatClient | None = None,
        source_model_client: AgentChatClient | None = None,
        poll_interval_seconds: float = 1.0,
        max_model_turns: int = 16,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        if max_model_turns <= 0:
            raise ValueError("max_model_turns must be positive")
        self.services = services
        self.sessions = ProjectRuntimeSessionStore(services.root)
        self.runs = CreatorAgentRunStore(services.root)
        self.executions = ProjectExecutionStore(services.root)
        self.specialist_tools = FileSpecialistToolRegistry(services)
        injected_model_client = model_client is not None
        self.model_client = model_client or AgentScopeAgentChatClient()
        self.source_model_client = source_model_client or (
            self.model_client
            if injected_model_client
            else AgentScopeVlmChatClient()
        )
        self.poll_interval_seconds = poll_interval_seconds
        self.max_model_turns = max_model_turns
        self._loop: asyncio.AbstractEventLoop | None = None
        self._dispatcher: asyncio.Task[None] | None = None
        self._wake = asyncio.Event()
        self._stopping = False
        self._active: dict[str, _ProjectTask] = {}
        self._blocked_heads: dict[str, int] = {}
        self._epochs: dict[str, int] = {}
        self._publication_lock = threading.RLock()

    @property
    def started(self) -> bool:
        return self._dispatcher is not None and not self._dispatcher.done()

    async def start(self) -> None:
        if self.started:
            return
        self._loop = asyncio.get_running_loop()
        self._stopping = False
        self._dispatcher = asyncio.create_task(
            self._dispatch_loop(),
            name="creator-file-agent-dispatcher",
        )
        self._wake.set()

    async def stop(self) -> None:
        self._stopping = True
        dispatcher = self._dispatcher
        self._dispatcher = None
        if dispatcher is not None:
            dispatcher.cancel()
        handles = list(self._active.values())
        for handle in handles:
            await asyncio.to_thread(
                self._revoke_epoch,
                handle.project_id,
                handle.run_id,
                handle.epoch,
            )
            handle.task.cancel()
        if handles:
            await asyncio.gather(
                *(handle.task for handle in handles),
                return_exceptions=True,
            )
        if dispatcher is not None:
            await asyncio.gather(dispatcher, return_exceptions=True)
        self._active.clear()
        self._loop = None

    def notify(self, project_id: str) -> None:
        """Wake the coordinator after a Project/message is durably published."""

        self._blocked_heads.pop(project_id, None)
        loop = self._loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(self._wake.set)

    async def interrupt(
        self,
        project_id: str,
        *,
        superseded: bool = False,
        reason: str = "user_interrupt",
    ) -> bool:
        """Cancel one Project's current task and revoke all later commits."""

        handle = self._active.get(project_id)
        if handle is None or handle.task.done():
            # Superseding an old AgentDock run is not a hard stop.  The API
            # path and the dispatcher may both observe the same durable
            # ReviewBoundary.  If the first caller already cancelled and
            # cleaned up the old handle, a second caller must leave the
            # replacement message pending for reconciliation instead of
            # consuming it through the idle-interrupt cleanup path.
            if superseded:
                self.notify(project_id)
                return False
            await self._record_idle_interrupt(project_id, reason=reason)
            self.notify(project_id)
            return False
        handle.superseded = superseded
        if handle.interrupting:
            # The durable INTERRUPT_REQUESTED status stays visible until the
            # cancellation cleanup persists the terminal session state, so the
            # dispatcher polls this path again.  Re-cancelling the task here
            # would abort that cleanup and leave the Session interrupted
            # forever; the first cancellation already owns the shutdown.
            self.notify(project_id)
            return True
        handle.interrupting = True
        # Revoke in a worker because an already-started local publication holds
        # this lock until its atomic commit finishes.
        await asyncio.to_thread(
            self._revoke_epoch,
            project_id,
            handle.run_id,
            handle.epoch,
        )
        handle.task.cancel()
        self.notify(project_id)
        return True

    async def wait_until_idle(
        self,
        project_id: str,
        *,
        timeout_seconds: float = 5.0,
    ) -> None:
        deadline = time.monotonic() + timeout_seconds
        while True:
            handle = self._active.get(project_id)
            if handle is None or handle.task.done():
                return
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Creator Agent did not become idle: {project_id}",
                )
            await asyncio.sleep(0.01)

    async def _dispatch_loop(self) -> None:
        try:
            while not self._stopping:
                try:
                    await asyncio.wait_for(
                        self._wake.wait(),
                        timeout=self.poll_interval_seconds,
                    )
                except TimeoutError:
                    pass
                self._wake.clear()
                try:
                    # Reconciliation only needs Project identities, not their
                    # loaded data.  ``list()`` fully reads every Project
                    # (parse + validate + canonicalize + deepcopy + resolve every
                    # indexed asset path) on each tick; with several Projects
                    # that pinned a core constantly.  ``discover_project_ids``
                    # is a directory scan with no payload load.  Per-Project load
                    # errors are handled inside ``_reconcile_project``.
                    project_ids = await asyncio.to_thread(
                        self.services.projects.discover_project_ids,
                    )
                except Exception:
                    # Storage integrity remains visible through health/recovery;
                    # one failed scan must not terminate the process driver.
                    continue
                for project_id in project_ids:
                    if self._stopping:
                        return
                    try:
                        await self._reconcile_project(project_id)
                    except Exception:
                        # A per-Project failure is persisted by its run whenever
                        # possible and must not starve unrelated Projects.
                        continue
        except asyncio.CancelledError:
            return

    async def _reconcile_project(self, project_id: str) -> None:
        handle = self._active.get(project_id)
        if handle is not None and handle.task.done():
            self._active.pop(project_id, None)
            handle = None
        # Snapshot read (shared lock, session.json only): reconcile only needs
        # status + head pointers to decide whether to launch a run, and the
        # full event-stream recovery of get_project_session costs ~1s on large
        # sessions (it reparses the whole events.jsonl under an exclusive lock,
        # which also starves every reader and causes lock timeouts).  Head
        # reconciliation is left to the next writer (_run_message).
        session = await asyncio.to_thread(
            self.sessions.get_project_session_snapshot,
            project_id,
        )
        if session.status is CreatorSessionStatus.INTERRUPT_REQUESTED:
            if handle is not None:
                await self.interrupt(project_id, reason="durable_interrupt")
            elif session.active_run_id is None:
                await self._record_idle_interrupt(
                    project_id,
                    reason="durable_interrupt",
                )
            return
        session = await self._converge_resolved_review(project_id, session)
        pending = await asyncio.to_thread(
            self.sessions.list_messages,
            project_id,
            session.session_id,
            after_seq=session.last_consumed_message_seq,
            limit=None,
        )
        user_messages = [item for item in pending if item.role == "user"]

        # The durable Session, not this process-local coordinator, owns the
        # cross-process run lease. A second QwenPaw process may observe the same
        # filesystem, but it must not start a duplicate Agent run. An explicit
        # AgentDock interruption is the sole exception: it supersedes the old
        # lease before the replacement request is admitted.
        if session.active_run_id is not None and handle is None:
            interrupted = any(
                item.review_boundary is not None
                and item.review_boundary.interrupted_run_id
                == session.active_run_id
                for item in user_messages
            )
            if not interrupted:
                return
            session = await asyncio.to_thread(
                self.sessions.clear_active_run,
                project_id,
                session.session_id,
                expected_run_id=session.active_run_id,
                status=CreatorSessionStatus.RESUMING,
            )

        if handle is not None:
            if any(
                item.review_boundary is not None
                and item.review_boundary.interrupted_run_id == handle.run_id
                for item in user_messages
            ):
                await self.interrupt(
                    project_id,
                    superseded=True,
                    reason="agentdock_interrupt",
                )
            return
        if not user_messages:
            return
        message = user_messages[0]
        if self._blocked_heads.get(project_id) == message.message_seq:
            return
        # Durable variant of the in-memory guard above: sessions written
        # before failures consumed their request (or a crash between the
        # FAILED transition and the consumption) can still expose a failed
        # head message after a restart.  Relaunching it would auto-start the
        # Agent without any new user input, so consume it instead and let
        # AgentDock surface the persisted session error.
        head_runs = [
            record
            for record in await asyncio.to_thread(self.runs.list, project_id)
            if record.caused_by_message_seq == message.message_seq
        ]
        if head_runs and head_runs[-1].status is AgentRunStatus.FAILED:
            try:
                await asyncio.to_thread(
                    self.sessions.mark_messages_consumed,
                    project_id,
                    session.session_id,
                    through_seq=message.message_seq,
                    goal_id=head_runs[-1].goal_id,
                )
            except SessionStateConflict:
                pass
            return
        run_id = f"agent-run-{uuid4().hex}"
        epoch = self._begin_epoch(project_id, run_id)
        task = asyncio.create_task(
            self._run_message(project_id, message, run_id=run_id, epoch=epoch),
            name=f"creator-file-agent:{project_id}:{run_id}",
        )
        handle = _ProjectTask(
            project_id=project_id,
            run_id=run_id,
            message_seq=message.message_seq,
            epoch=epoch,
            task=task,
        )
        self._active[project_id] = handle

        def completed(_task: asyncio.Task[None]) -> None:
            current = self._active.get(project_id)
            if current is handle:
                self._active.pop(project_id, None)
            self._wake.set()

        task.add_done_callback(completed)

    @traced_async(
        "creator.agent.execution",
        component="creator.file_agent_runtime",
        context=lambda _self, project_id, message, *, run_id, epoch: {
            "projectId": project_id,
            "sessionId": message.creator_session_id,
            "conversationId": message.conversation_id,
            "runId": run_id,
        },
        attributes=lambda _self, project_id, message, *, run_id, epoch: {
            "messageId": message.message_id,
            "messageSeq": message.message_seq,
            "epoch": epoch,
        },
    )
    async def _run_message(
        self,
        project_id: str,
        message: CreatorMessageRecord,
        *,
        run_id: str,
        epoch: int,
    ) -> None:
        # Snapshot read: _run_message only needs session identity (session_id,
        # active_goal_id) to build the run record and resolve its goal; the
        # durable writes that follow (activate_run, runs.create, ...) take the
        # exclusive lock and reconcile the head themselves.  Avoiding the full
        # event-stream recovery here matters under concurrent runs.
        session = await asyncio.to_thread(
            self.sessions.get_project_session_snapshot,
            project_id,
        )
        goal = await self._goal_for_message(session, message)
        snapshot = await asyncio.to_thread(
            self.services.projects.read,
            project_id,
        )
        context = self._tool_context(message, run_id=run_id)
        round_id = context.round_id or f"agent-round-{run_id}"
        record = CreatorAgentRunRecord(
            run_id=run_id,
            project_id=project_id,
            session_id=session.session_id,
            goal_id=goal.goal_id,
            conversation_id=message.conversation_id,
            round_id=round_id,
            caused_by_message_id=message.message_id,
            caused_by_message_seq=message.message_seq,
            caused_by_request_id=context.caused_by_request_id,
            origin=context.origin,
            review_policy=context.review_policy,
            review_boundary=context.review_boundary,
            input_generation=snapshot.generation,
            input_etag=snapshot.etag,
        )
        await asyncio.to_thread(self.runs.create, record)
        await asyncio.to_thread(
            self.sessions.activate_run,
            project_id,
            session.session_id,
            goal_id=goal.goal_id,
            run_id=run_id,
            status=CreatorSessionStatus.RUNNING,
        )
        await asyncio.to_thread(
            self.sessions.set_goal_status,
            project_id,
            goal.goal_id,
            CreatorGoalStatus.ACTIVE,
        )
        await asyncio.to_thread(
            self.runs.transition,
            project_id,
            run_id,
            expected_status=AgentRunStatus.QUEUED,
            status=AgentRunStatus.RUNNING,
        )
        await self._event(
            project_id,
            session.session_id,
            "agent.run.started",
            run_id,
            message,
            {
                "runId": run_id,
                "goalId": goal.goal_id,
                "reviewPolicy": context.review_policy.value,
                "origin": context.origin.value,
            },
        )

        commits = _FencedCommitBoundary(
            self,
            project_id,
            run_id,
            epoch,
            ProjectCommitBoundary(self.services.projects),
        )
        tools = AgentProjectTools(
            self.services.projects,
            context=context,
            transformer=self.services.jq,
            commits=commits,
        )
        try:
            result = await self._model_loop(
                project_id=project_id,
                session_id=session.session_id,
                run_id=run_id,
                epoch=epoch,
                request=message,
                tools=tools,
            )
            self._assert_epoch(project_id, run_id, epoch)
            await asyncio.to_thread(
                self.runs.transition,
                project_id,
                run_id,
                expected_status=AgentRunStatus.RUNNING,
                status=AgentRunStatus.SUCCEEDED,
                updates={
                    "tool_call_count": result.tool_call_count,
                    "review_ids": list(result.review_ids),
                    "final_summary": result.summary,
                },
            )
            await asyncio.to_thread(
                self.sessions.mark_messages_consumed,
                project_id,
                session.session_id,
                through_seq=message.message_seq,
                goal_id=goal.goal_id,
            )
            needs_review = bool(result.review_ids)
            await asyncio.to_thread(
                self.sessions.set_goal_status,
                project_id,
                goal.goal_id,
                (
                    CreatorGoalStatus.WAITING_REVIEW
                    if needs_review
                    else CreatorGoalStatus.COMPLETED
                ),
            )
            await asyncio.to_thread(
                self.sessions.clear_active_run,
                project_id,
                session.session_id,
                expected_run_id=run_id,
                status=(
                    CreatorSessionStatus.PENDING_REVIEW
                    if needs_review
                    else CreatorSessionStatus.IDLE
                ),
            )
            await self._event(
                project_id,
                session.session_id,
                "agent.run.completed",
                run_id,
                message,
                {
                    "runId": run_id,
                    "goalId": goal.goal_id,
                    "reviewIds": list(result.review_ids),
                    "summary": result.summary,
                },
            )
            if (
                context.review_boundary is not None
                and context.review_boundary.interrupted_run_id is not None
            ):
                await self._queue_mainline_resume(
                    project_id=project_id,
                    session_id=session.session_id,
                    conversation_id=message.conversation_id,
                    intervention_run_id=run_id,
                    interrupted_run_id=(
                        context.review_boundary.interrupted_run_id
                    ),
                )
            self._blocked_heads.pop(project_id, None)
        except asyncio.CancelledError:
            await self._cancel_run(
                project_id,
                session.session_id,
                goal.goal_id,
                run_id,
                message,
            )
            raise
        except StaleAgentRun:
            await self._cancel_run(
                project_id,
                session.session_id,
                goal.goal_id,
                run_id,
                message,
            )
            return
        except AgentModelConfigurationError as exc:
            await self._fail_run(
                project_id,
                session.session_id,
                goal.goal_id,
                run_id,
                message,
                code="MODEL_CONFIG_MISSING",
                message_text=str(exc),
                retryable=False,
            )
            self._blocked_heads[project_id] = message.message_seq
        except AgentModelError as exc:
            await self._fail_run(
                project_id,
                session.session_id,
                goal.goal_id,
                run_id,
                message,
                code="MODEL_REQUEST_FAILED",
                message_text=str(exc),
                retryable=True,
            )
            self._blocked_heads[project_id] = message.message_seq
        except AgentStreamCallbackError as exc:
            cause = exc.cause
            await self._fail_run(
                project_id,
                session.session_id,
                goal.goal_id,
                run_id,
                message,
                code="STREAM_PERSISTENCE_FAILED",
                message_text=f"{type(cause).__name__}: {cause}",
                retryable=True,
            )
            self._blocked_heads[project_id] = message.message_seq
        except Exception as exc:
            await self._fail_run(
                project_id,
                session.session_id,
                goal.goal_id,
                run_id,
                message,
                code="AGENT_RUN_FAILED",
                message_text=f"{type(exc).__name__}: {exc}",
                retryable=False,
            )
            self._blocked_heads[project_id] = message.message_seq

    async def _model_loop(
        self,
        *,
        project_id: str,
        session_id: str,
        run_id: str,
        epoch: int,
        request: CreatorMessageRecord,
        tools: AgentProjectTools,
    ) -> _LoopResult:
        tool_manifest = [
            *agent_project_tool_manifest(),
            _ground_prompt_context_tool_manifest(),
            delegate_tool_manifest(),
        ]
        conversation_records = await asyncio.to_thread(
            self.sessions.list_messages,
            project_id,
            session_id,
            after_seq=0,
            limit=None,
        )
        prior_context = [
            item
            for item in conversation_records
            if item.conversation_id == request.conversation_id
            and item.message_seq < request.message_seq
        ]
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": render_creator_system_prompt(
                    project_id=project_id,
                    workspace_schema=tools.schema_prompt.text,
                ),
            },
            {
                "role": "user",
                "content": _continuation_message_text(request, prior_context),
            },
        ]
        tool_call_count = 0
        review_ids: list[str] = []
        for _turn_number in range(1, self.max_model_turns + 1):
            self._assert_epoch(project_id, run_id, epoch)
            assistant_message_id = f"message-{uuid4().hex}"
            delta_index = 0
            # The authoritative assistant message is still persisted durably by
            # ``_persist_assistant_turn`` at turn end.

            async def persist_message_delta(
                stream_kind: str,
                delta: str,
            ) -> None:
                nonlocal delta_index
                if not delta:
                    return
                self._assert_epoch(project_id, run_id, epoch)
                await self._event(
                    project_id,
                    session_id,
                    "agent.message_delta",
                    run_id,
                    request,
                    {
                        "runId": run_id,
                        "messageId": assistant_message_id,
                        "deltaIndex": delta_index,
                        "delta": delta,
                        "streamKind": stream_kind,
                    },
                )
                delta_index += 1

            async def persist_text_delta(delta: str) -> None:
                await persist_message_delta("text", delta)

            async def persist_thinking_delta(delta: str) -> None:
                await persist_message_delta("thinking", delta)

            async def persist_tool_delta(
                tool_call_id: str,
                tool_name: str,
                arguments_delta: str,
            ) -> None:
                nonlocal delta_index
                if not arguments_delta:
                    return
                self._assert_epoch(project_id, run_id, epoch)
                await self._event(
                    project_id,
                    session_id,
                    "agent.tool_delta",
                    run_id,
                    request,
                    {
                        "runId": run_id,
                        "messageId": assistant_message_id,
                        "toolCallId": tool_call_id,
                        "tool": tool_name,
                        "deltaIndex": delta_index,
                        "argumentsDelta": arguments_delta,
                    },
                )
                delta_index += 1

            turn = await self.model_client.complete(
                messages=messages,
                tools=tool_manifest,
                on_text_delta=persist_text_delta,
                on_thinking_delta=persist_thinking_delta,
                on_tool_call_delta=persist_tool_delta,
            )
            self._assert_epoch(project_id, run_id, epoch)
            if len(turn.tool_calls) > 1:
                raise AgentModelError(
                    "Creator Agent returned more than one tool call in one turn",
                )
            await self._persist_assistant_turn(
                project_id,
                session_id,
                run_id,
                request,
                turn,
                message_id=assistant_message_id,
            )
            assistant_wire: dict[str, Any] = {
                "role": "assistant",
                "content": turn.content,
            }
            if turn.tool_calls:
                assistant_wire["tool_calls"] = [
                    call.history_dict() for call in turn.tool_calls
                ]
            messages.append(assistant_wire)
            if not turn.tool_calls:
                if turn.content is None:
                    raise AgentModelError(
                        "Creator Agent returned no final content or tool calls",
                    )
                return _LoopResult(
                    summary=turn.content,
                    tool_call_count=tool_call_count,
                    review_ids=tuple(review_ids),
                )

            for call in turn.tool_calls:
                tool_call_count += 1
                tool_failed = False
                self._assert_epoch(project_id, run_id, epoch)
                await self._event(
                    project_id,
                    session_id,
                    "agent.tool_started",
                    run_id,
                    request,
                    {
                        "runId": run_id,
                        "actionId": call.call_id,
                        "toolCallId": call.call_id,
                        "tool": call.name,
                        "messageId": assistant_message_id,
                    },
                )
                try:
                    if call.parse_error is not None:
                        raise ToolArgumentsJSONError(call.parse_error)
                    if (
                        call.name != DELEGATE_TOOL_NAME
                        and call.arguments.get("projectId") != project_id
                    ):
                        raise FileAgentRuntimeError(
                            "model tool call attempted another Project",
                        )
                    if call.name == DELEGATE_TOOL_NAME:
                        result = await self._run_subagent(
                            project_id=project_id,
                            session_id=session_id,
                            parent_run_id=run_id,
                            parent_action_id=call.call_id,
                            epoch=epoch,
                            request=request,
                            tools=tools,
                            arguments=call.arguments,
                        )
                    elif call.name == GROUND_PROMPT_CONTEXT_TOOL_NAME:
                        result = await self._run_ground_prompt_context(
                            request=request,
                            arguments=call.arguments,
                        )
                    else:
                        result = await asyncio.to_thread(
                            tools.invoke,
                            call.name,
                            call.arguments,
                        )
                    self._assert_epoch(project_id, run_id, epoch)
                    review_id = result.get("reviewId")
                    if (
                        isinstance(review_id, str)
                        and review_id
                        and review_id not in review_ids
                    ):
                        review_ids.append(review_id)
                    await self._persist_tool_result(
                        project_id,
                        session_id,
                        run_id,
                        request,
                        call_id=call.call_id,
                        tool_name=call.name,
                        result=result,
                    )
                    if call.name == "jq_project":
                        await self._workspace_changed(
                            project_id,
                            session_id,
                            run_id,
                            request,
                            result,
                            action_id=call.call_id,
                        )
                    tool_content = json.dumps(
                        result,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                except (asyncio.CancelledError, StaleAgentRun):
                    raise
                except Exception as exc:
                    tool_failed = True
                    error_result = {
                        "ok": False,
                        "error": {
                            "type": type(exc).__name__,
                            "message": str(exc),
                            "recovery": _specialist_tool_recovery(call.name),
                        },
                    }
                    await self._persist_tool_result(
                        project_id,
                        session_id,
                        run_id,
                        request,
                        call_id=call.call_id,
                        tool_name=call.name,
                        result=error_result,
                        failed=True,
                    )
                    tool_content = json.dumps(
                        error_result,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.call_id,
                        "name": call.name,
                        "content": tool_content,
                        "failed": tool_failed,
                    },
                )
        raise AgentModelError(
            f"Creator Agent exceeded {self.max_model_turns} model turns",
        )

    async def _run_ground_prompt_context(
        self,
        *,
        request: CreatorMessageRecord,
        arguments: Mapping[str, Any],
    ) -> dict[str, Any]:
        prompt = str(arguments.get("prompt") or _message_text(request)).strip()
        if not prompt:
            raise FileAgentRuntimeError(
                "ground_prompt_context requires prompt text",
            )

        raw_queries = arguments.get("queries")
        queries: list[str] | None = None
        if raw_queries is not None:
            if not isinstance(raw_queries, list) or not all(
                isinstance(item, str) for item in raw_queries
            ):
                raise FileAgentRuntimeError(
                    "ground_prompt_context queries must be a string array",
                )
            queries = [item for item in raw_queries if item.strip()]

        raw_context = arguments.get("context")
        if raw_context is not None and not isinstance(raw_context, dict):
            raise FileAgentRuntimeError(
                "ground_prompt_context context must be an object",
            )

        detector = arguments.get("detector")
        if detector is not None and detector not in {
            "hybrid",
            "llm",
            "heuristic",
        }:
            raise FileAgentRuntimeError(
                "ground_prompt_context detector is invalid",
            )

        include_visuals = arguments.get("includeVisuals")
        if include_visuals is not None and not isinstance(
            include_visuals,
            bool,
        ):
            raise FileAgentRuntimeError(
                "ground_prompt_context includeVisuals must be boolean",
            )
        force = arguments.get("force", False)
        if not isinstance(force, bool):
            raise FileAgentRuntimeError(
                "ground_prompt_context force must be boolean",
            )
        detect_only = arguments.get("detectOnly", False)
        if not isinstance(detect_only, bool):
            raise FileAgentRuntimeError(
                "ground_prompt_context detectOnly must be boolean",
            )

        result = await ground_prompt_context(
            prompt,
            context=raw_context,
            queries=queries,
            force=force,
            detect_only=detect_only,
            detector=detector,
            max_sources=get_web_grounding_max_sources(),
            timeout=float(get_web_grounding_timeout_seconds()),
            include_visuals=include_visuals,
        )
        return await self._promote_grounding_visuals(
            project_id=request.project_id,
            request_id=request.message_id,
            result=result,
        )

    async def _promote_grounding_visuals(
        self,
        *,
        project_id: str,
        request_id: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        visual_sources = result.get("visual_sources")
        if not isinstance(visual_sources, list) or not visual_sources:
            return result
        promoted = await asyncio.to_thread(
            self._promote_grounding_visuals_sync,
            project_id,
            request_id,
            visual_sources,
        )
        if not promoted["promoted"]:
            result["grounding_asset_promotion"] = promoted
            return result
        by_index = {
            item["index"]: item
            for item in promoted["promoted"]
            if isinstance(item.get("index"), int)
        }
        for index, source in enumerate(visual_sources):
            if not isinstance(source, dict):
                continue
            entry = by_index.get(index)
            if entry is None:
                continue
            source["workspace_ref"] = entry["workspace_ref"]
            source["assetVersionRef"] = entry["workspace_ref"]
            source["source_asset_version_id"] = entry[
                "source_asset_version_id"
            ]
            source["logical_asset_id"] = entry["logical_asset_id"]
            source["indexed_file_id"] = entry["file_id"]
        context_lines = [
            "",
            "Workspace Visual References:",
            *[
                (
                    f"[G{item['index'] + 1}] "
                    f"{item['workspace_ref']} "
                    f"asset_version_id={item['source_asset_version_id']} "
                    f"local={item.get('local_url') or ''}"
                ).rstrip()
                for item in promoted["promoted"]
            ],
        ]
        grounded_context = str(result.get("grounded_context") or "").rstrip()
        result["grounded_context"] = "\n".join(
            item for item in [grounded_context, *context_lines] if item
        )
        result["grounding_asset_promotion"] = promoted
        return result

    def _promote_grounding_visuals_sync(
        self,
        project_id: str,
        request_id: str,
        visual_sources: list[Any],
    ) -> dict[str, Any]:
        promoted: list[dict[str, Any]] = []
        issues: list[str] = []
        changed = False
        project_root = self.services.projects.project_root(project_id)
        file_store = AssetFileStore(project_root)
        with self.services.projects.lifecycle_lock(project_id):
            base = self.services.projects.read(project_id)
            candidate = base.project.model_dump(mode="json")
            files = candidate["assets"]["files_by_id"]
            versions = candidate["assets"]["source_versions_by_id"]
            created_at = datetime.now(UTC)
            for index, raw_source in enumerate(visual_sources):
                if not isinstance(raw_source, Mapping):
                    continue
                if not _grounding_visual_is_usable(raw_source):
                    continue
                local_path = _grounding_local_path(raw_source)
                if local_path is None:
                    issues.append(f"visual_source_missing_local_path:{index}")
                    continue
                try:
                    stat = local_path.stat()
                except OSError as exc:
                    issues.append(
                        f"visual_source_unavailable:{index}:{type(exc).__name__}",
                    )
                    continue
                if not local_path.is_file() or stat.st_size <= 0:
                    issues.append(f"visual_source_not_regular:{index}")
                    continue
                if stat.st_size > GROUNDING_VISUAL_MAX_BYTES:
                    issues.append(
                        f"visual_source_too_large:{index}:{stat.st_size}",
                    )
                    continue
                content = local_path.read_bytes()
                try:
                    validate_reference_image_bytes(content)
                except ValueError:
                    issues.append(f"visual_source_invalid_image:{index}")
                    continue
                checksum = hashlib.sha256(content).hexdigest()
                identity = str(raw_source.get("storage_sha256") or checksum)
                logical_asset_id = _grounding_stable_id(
                    "asset",
                    project_id,
                    identity,
                )
                version_id = _grounding_stable_id(
                    "asset-version",
                    project_id,
                    identity,
                )
                file_id = _grounding_stable_id("file", project_id, identity)
                media_type = str(
                    raw_source.get("media_type")
                    or (raw_source.get("download") or {}).get("media_type")
                    or mimetypes.guess_type(local_path.name)[0]
                    or "image/jpeg",
                )
                if not media_type.casefold().startswith("image/"):
                    issues.append(
                        f"visual_source_not_image:{index}:{media_type}",
                    )
                    continue
                relative_uri = PurePosixPath(
                    "assets",
                    "sources",
                    f"{file_id}{_grounding_extension(local_path, media_type)}",
                ).as_posix()
                indexed = IndexedFile(
                    file_id=file_id,
                    kind="source_original",
                    relative_uri=relative_uri,
                    sha256=checksum,
                    size_bytes=len(content),
                    media_type=media_type,
                    created_at=created_at,
                )
                version = SourceAssetVersion(
                    version_id=version_id,
                    logical_asset_id=logical_asset_id,
                    name=str(
                        raw_source.get("title")
                        or f"Grounding visual {index + 1}",
                    )[:160],
                    file_id=file_id,
                    checksum=checksum,
                    media_kind=_grounding_media_kind(media_type),  # type: ignore[arg-type]
                    media_type=media_type,
                    provenance_refs=[
                        item
                        for item in (
                            str(raw_source.get("url") or ""),
                            str(raw_source.get("source_url") or ""),
                            str(raw_source.get("grounding_ref") or ""),
                        )
                        if item
                    ],
                    created_at=created_at,
                    metadata={
                        "sourceKind": "web_grounding_visual",
                        "requestId": request_id,
                        "provider": str(raw_source.get("provider") or ""),
                        "query": str(raw_source.get("query") or ""),
                        "entityName": str(raw_source.get("entity_name") or ""),
                        "usage": str(
                            raw_source.get("usage")
                            or raw_source.get("usage_hint")
                            or "",
                        ),
                        "localUrl": str(
                            raw_source.get("local_url") or local_path.as_uri(),
                        ),
                    },
                )
                indexed_json = indexed.model_dump(mode="json")
                version_json = version.model_dump(mode="json")
                existing_file = files.get(file_id)
                existing_version = versions.get(version_id)
                if existing_file is not None:
                    existing_created_at = existing_file.get("created_at")
                    if existing_created_at is not None:
                        indexed_json["created_at"] = existing_created_at
                    if existing_file != indexed_json:
                        raise ConflictError(
                            "Grounding visual file id collision",
                        )
                if existing_version is not None:
                    existing = SourceAssetVersion.model_validate(
                        existing_version,
                    )
                    if (
                        existing.logical_asset_id != logical_asset_id
                        or existing.checksum != checksum
                        or existing.file_id != file_id
                    ):
                        raise ConflictError(
                            "Grounding visual asset version collision",
                        )
                if existing_file is None:
                    staged = file_store.stage_bytes(
                        content,
                        staging_id=f"grounding-{file_id[:48]}",
                    )
                    try:
                        file_store.publish(
                            staged,
                            relative_uri,
                            expected_sha256=checksum,
                            expected_size_bytes=len(content),
                        )
                    except AssetAlreadyExists:
                        file_store.abandon(staged)
                    files[file_id] = indexed_json
                    changed = True
                if existing_version is None:
                    versions[version_id] = version_json
                    changed = True
                promoted.append(
                    {
                        "index": index,
                        "workspace_ref": workspace_asset_ref(
                            logical_asset_id,
                            version_id,
                        ),
                        "logical_asset_id": logical_asset_id,
                        "source_asset_version_id": version_id,
                        "file_id": file_id,
                        "local_url": str(
                            raw_source.get("local_url") or local_path.as_uri(),
                        ),
                    },
                )
            if changed:
                commit = self.services.commits.commit(
                    base=base,
                    candidate=candidate,
                    origin=ChangeOrigin.RUNTIME_TASK,
                    review_policy=ReviewPolicy.AUTO_FIX,
                    caused_by_request_id=request_id,
                    round_id=_grounding_stable_id(
                        "round",
                        project_id,
                        request_id,
                    ),
                    transaction_id=_grounding_stable_id(
                        "transaction",
                        project_id,
                        request_id,
                    ),
                    advance_accepted_baseline=True,
                    _lifecycle_lock_held=True,
                )
                self.services.poller.note_commit(commit.snapshot)
        return {
            "status": "success" if promoted else "skipped",
            "promoted_count": len(promoted),
            "promoted": promoted,
            "issues": issues,
        }

    async def _run_subagent(
        self,
        *,
        project_id: str,
        session_id: str,
        parent_run_id: str,
        parent_action_id: str,
        epoch: int,
        request: CreatorMessageRecord,
        tools: AgentProjectTools,
        arguments: Mapping[str, Any],
    ) -> dict[str, Any]:
        delegated = DelegateToAgentInput.model_validate(dict(arguments))
        delegated.validate_contract(project_id=project_id)
        role = delegated.role
        role_name = role.value
        snapshot = await asyncio.to_thread(
            self.services.projects.read,
            project_id,
        )
        specialist_run_id = f"specialist-run-{uuid4().hex}"
        round_id = tools.context.round_id or f"agent-round-{parent_run_id}"
        prompt = specialist_system_prompt(
            role,
            project_id=project_id,
            project=snapshot.project,
            workspace_schema=tools.schema_prompt.text,
        )
        record = SpecialistRunRecord(
            run_id=specialist_run_id,
            project_id=project_id,
            round_id=round_id,
            role=role,
            target_refs=list(delegated.target_refs),
            input_generation=snapshot.generation,
            input_etag=snapshot.etag,
            related_run_id=parent_run_id,
            prompt_spec_id=f"file_project_json.{role_name}.v1",
            caused_by_request_id=tools.context.caused_by_request_id,
            caused_by_message_id=request.message_id,
            caused_by_message_seq=request.message_seq,
            review_policy=tools.context.review_policy,
            metadata={"parentActionId": parent_action_id},
        )
        await asyncio.to_thread(self.executions.create_specialist_run, record)
        common = {
            "parentActionId": parent_action_id,
            "parentRunId": parent_run_id,
            "runId": specialist_run_id,
            "role": role_name,
            "displayName": role_name,
            "targetRefs": list(delegated.target_refs),
        }
        await self._event(
            project_id,
            session_id,
            "subagent.accepted",
            parent_run_id,
            request,
            {**common, "task": delegated.task},
        )
        await asyncio.to_thread(
            self.executions.transition_specialist_run,
            project_id,
            specialist_run_id,
            expected_status=SpecialistRunStatus.QUEUED,
            status=SpecialistRunStatus.RUNNING_MODEL,
        )
        await self._event(
            project_id,
            session_id,
            "subagent.started",
            parent_run_id,
            request,
            common,
        )

        user_text = (
            f"父任务的用户原始要求：\n{_message_text(request)}\n\n"
            f"本次委派：\n{delegated.task}\n\n"
            f"目标对象：{', '.join(delegated.target_refs)}"
        )
        native_media_parts: list[dict[str, Any]] = []
        if role is SpecialistRole.SOURCE_INTELLIGENCE:
            native_media_parts = await source_intelligence_content_parts(
                self.services,
                project_id=project_id,
                request=request,
            )
            user_text += (
                "\n\n本消息附有本轮用户输入的全部原生图片/视频，"
                f"共 {len(native_media_parts)} 份。必须基于这些原生媒体进行观察，"
                "不能把消息中的 URL 文本当作已经完成素材理解。"
            )
            runtime_media_facts = []
            for part in native_media_parts:
                video = part.get("video_url")
                if (
                    isinstance(video, Mapping)
                    and video.get("durationMs") is not None
                ):
                    runtime_media_facts.append(
                        {
                            "assetVersionId": video.get("versionId"),
                            "durationMs": video.get("durationMs"),
                        },
                    )
            if runtime_media_facts:
                user_text += (
                    "\n\nRuntime 已通过本地缓存和 ffprobe 核验以下媒体事实；"
                    "时间段必须落在这些真实时长内：\n"
                    + json.dumps(
                        runtime_media_facts,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                )
        user_content: list[dict[str, Any]] = [
            {"type": "text", "text": user_text},
            *native_media_parts,
        ]
        await asyncio.to_thread(
            self.executions.append_specialist_message,
            project_id,
            specialist_run_id,
            message_id=f"specialist-message-{uuid4().hex}",
            role="user",
            content_parts=user_content,
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_content},
        ]
        tool_manifest = list(
            self.specialist_tools.manifest_for(
                role,
                admitted_target_refs=delegated.target_refs,
            ),
        )
        tool_call_count = 0
        review_ids: list[str] = []
        try:
            for _turn_number in range(1, self.max_model_turns + 1):
                self._assert_epoch(project_id, parent_run_id, epoch)
                message_id = f"specialist-message-{uuid4().hex}"
                delta_index = 0

                async def message_delta(stream_kind: str, delta: str) -> None:
                    nonlocal delta_index
                    if not delta:
                        return
                    self._assert_epoch(project_id, parent_run_id, epoch)
                    await self._event(
                        project_id,
                        session_id,
                        "subagent.message_delta",
                        parent_run_id,
                        request,
                        {
                            **common,
                            "messageId": message_id,
                            "deltaIndex": delta_index,
                            "delta": delta,
                            "streamKind": stream_kind,
                        },
                    )
                    delta_index += 1

                async def text_delta(delta: str) -> None:
                    await message_delta("text", delta)

                async def thinking_delta(delta: str) -> None:
                    await message_delta("thinking", delta)

                async def tool_delta(
                    tool_call_id: str,
                    tool_name: str,
                    arguments_delta: str,
                ) -> None:
                    nonlocal delta_index
                    if not arguments_delta:
                        return
                    self._assert_epoch(project_id, parent_run_id, epoch)
                    await self._event(
                        project_id,
                        session_id,
                        "subagent.tool_delta",
                        parent_run_id,
                        request,
                        {
                            **common,
                            "messageId": message_id,
                            "toolCallId": tool_call_id,
                            "tool": tool_name,
                            "deltaIndex": delta_index,
                            "argumentsDelta": arguments_delta,
                        },
                    )
                    delta_index += 1

                model_client = (
                    self.source_model_client
                    if role is SpecialistRole.SOURCE_INTELLIGENCE
                    else self.model_client
                )
                turn = await model_client.complete(
                    messages=messages,
                    tools=tool_manifest,
                    on_text_delta=text_delta,
                    on_thinking_delta=thinking_delta,
                    on_tool_call_delta=tool_delta,
                )
                if len(turn.tool_calls) > 1:
                    raise AgentModelError(
                        f"{role_name} returned more than one tool call in one turn",
                    )
                metadata: dict[str, Any] = {
                    "parentActionId": parent_action_id,
                    "providerMessageId": turn.provider_message_id,
                    "providerThinking": turn.thinking,
                }
                if turn.tool_calls:
                    call = turn.tool_calls[0]
                    metadata["toolCall"] = {
                        "id": call.call_id,
                        "name": call.name,
                        "arguments": dict(call.arguments),
                    }
                await asyncio.to_thread(
                    self.executions.append_specialist_message,
                    project_id,
                    specialist_run_id,
                    message_id=message_id,
                    role="assistant",
                    content_parts=[
                        {"type": "text", "text": turn.content or ""},
                    ],
                    provider_message_id=turn.provider_message_id,
                    metadata=metadata,
                )
                await self._event(
                    project_id,
                    session_id,
                    "subagent.message_completed",
                    parent_run_id,
                    request,
                    {
                        **common,
                        "messageId": message_id,
                        "text": turn.content or "",
                    },
                )
                assistant_wire: dict[str, Any] = {
                    "role": "assistant",
                    "content": turn.content,
                }
                if turn.tool_calls:
                    assistant_wire["tool_calls"] = [
                        call.history_dict() for call in turn.tool_calls
                    ]
                messages.append(assistant_wire)
                if not turn.tool_calls:
                    if turn.content is None:
                        raise AgentModelError(
                            f"{role_name} returned no final content or tool calls",
                        )
                    marker, summary = _specialist_terminal(turn.content)
                    latest = None
                    if (
                        marker == "SUCCESS"
                        and role is SpecialistRole.SOURCE_INTELLIGENCE
                    ):
                        latest = await asyncio.to_thread(
                            self.services.projects.read,
                            project_id,
                        )
                        try:
                            _require_source_intelligence_associations(
                                latest.project,
                                delegated.target_refs,
                            )
                        except FileAgentRuntimeError as error:
                            correction = (
                                "你刚才直接输出了 [SUCCESS]，但没有通过 "
                                "commit_source_intelligence 写入素材理解文件，"
                                f"因此该成功被 Runtime 拒绝：{error}。"
                                "现在禁止再次返回自然语言分析或 [SUCCESS]；"
                                "请把你已经观察到的完整视觉理解转换成工具要求的"
                                "结构化 summary、shots、entities、semanticEntries，"
                                "并在本回合调用 commit_source_intelligence。"
                            )
                            await asyncio.to_thread(
                                self.executions.append_specialist_message,
                                project_id,
                                specialist_run_id,
                                message_id=f"specialist-message-{uuid4().hex}",
                                role="user",
                                content_parts=[
                                    {"type": "text", "text": correction},
                                ],
                                metadata={"parentActionId": parent_action_id},
                            )
                            messages.append(
                                {"role": "user", "content": correction},
                            )
                            continue
                    status = {
                        "SUCCESS": SpecialistRunStatus.SUCCEEDED,
                        "BLOCKED": SpecialistRunStatus.BLOCKED,
                        "FAILED": SpecialistRunStatus.FAILED,
                    }[marker]
                    await asyncio.to_thread(
                        self.executions.transition_specialist_run,
                        project_id,
                        specialist_run_id,
                        expected_status=SpecialistRunStatus.RUNNING_MODEL,
                        status=status,
                        updates={
                            "final_marker": marker,
                            "final_summary_text": summary,
                        },
                    )
                    terminal_event = {
                        SpecialistRunStatus.SUCCEEDED: "subagent.completed",
                        SpecialistRunStatus.BLOCKED: "subagent.blocked",
                        SpecialistRunStatus.FAILED: "subagent.failed",
                    }[status]
                    await self._event(
                        project_id,
                        session_id,
                        terminal_event,
                        parent_run_id,
                        request,
                        {**common, "summary": summary},
                    )
                    if latest is None:
                        latest = await asyncio.to_thread(
                            self.services.projects.read,
                            project_id,
                        )
                    return {
                        "ok": status is SpecialistRunStatus.SUCCEEDED,
                        "runId": specialist_run_id,
                        "role": role_name,
                        "status": status.value,
                        "summary": summary,
                        "toolCallCount": tool_call_count,
                        "generation": latest.generation,
                        "etag": latest.etag,
                        "reviewId": review_ids[-1] if review_ids else None,
                    }

                call = turn.tool_calls[0]
                tool_call_count += 1
                if (
                    call.parse_error is None
                    and call.arguments.get("projectId") != project_id
                ):
                    raise FileAgentRuntimeError(
                        "specialist tool call attempted another Project",
                    )
                await self._event(
                    project_id,
                    session_id,
                    "subagent.tool_started",
                    parent_run_id,
                    request,
                    {
                        **common,
                        "messageId": message_id,
                        "toolCallId": call.call_id,
                        "tool": call.name,
                    },
                )
                failed = False
                try:
                    if call.parse_error is not None:
                        raise ToolArgumentsJSONError(call.parse_error)
                    result = await self._invoke_specialist_tool(
                        project_id=project_id,
                        session_id=session_id,
                        parent_run_id=parent_run_id,
                        specialist_run_id=specialist_run_id,
                        round_id=round_id,
                        role=role,
                        admitted_target_refs=delegated.target_refs,
                        epoch=epoch,
                        request=request,
                        common=common,
                        call_id=call.call_id,
                        assistant_message_id=message_id,
                        provider_message_id=turn.provider_message_id,
                        name=call.name,
                        arguments=call.arguments,
                        tools=tools,
                    )
                    review_id = result.get("reviewId")
                    if (
                        isinstance(review_id, str)
                        and review_id
                        and review_id not in review_ids
                    ):
                        review_ids.append(review_id)
                    if call.name == "jq_project":
                        await self._workspace_changed(
                            project_id,
                            session_id,
                            parent_run_id,
                            request,
                            result,
                            action_id=call.call_id,
                            specialist=common,
                        )
                except (asyncio.CancelledError, StaleAgentRun):
                    raise
                except Exception as exc:
                    failed = True
                    result = {
                        "ok": False,
                        "error": {
                            "type": type(exc).__name__,
                            "message": str(exc),
                            "recovery": _specialist_tool_recovery(call.name),
                        },
                    }
                await asyncio.to_thread(
                    self.executions.append_specialist_message,
                    project_id,
                    specialist_run_id,
                    message_id=f"specialist-message-{uuid4().hex}",
                    role="tool",
                    content_parts=[
                        {
                            "type": "text",
                            "text": json.dumps(result, ensure_ascii=False),
                        },
                    ],
                    metadata={
                        "parentActionId": parent_action_id,
                        "toolCallId": call.call_id,
                        "tool": call.name,
                        "failed": failed,
                    },
                )
                await self._event(
                    project_id,
                    session_id,
                    "subagent.tool_completed",
                    parent_run_id,
                    request,
                    {
                        **common,
                        "messageId": message_id,
                        "toolCallId": call.call_id,
                        "tool": call.name,
                        "failed": failed,
                        "result": result,
                    },
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.call_id,
                        "name": call.name,
                        "content": json.dumps(
                            result,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                        "failed": failed,
                    },
                )
            raise AgentModelError(
                f"{role_name} exceeded {self.max_model_turns} model turns",
            )
        except (asyncio.CancelledError, StaleAgentRun):
            await asyncio.to_thread(
                self.executions.transition_specialist_run,
                project_id,
                specialist_run_id,
                expected_status=SpecialistRunStatus.RUNNING_MODEL,
                status=SpecialistRunStatus.CANCELLED,
                updates={"final_marker": "CANCELLED"},
            )
            # Emit subagent.failed so the frontend can disarm.
            await self._event(
                project_id,
                session_id,
                "subagent.failed",
                parent_run_id,
                request,
                {
                    **common,
                    "cancelled": True,
                    "error": "specialist run cancelled",
                },
            )
            raise
        except Exception as exc:
            await asyncio.to_thread(
                self.executions.transition_specialist_run,
                project_id,
                specialist_run_id,
                expected_status=SpecialistRunStatus.RUNNING_MODEL,
                status=SpecialistRunStatus.FAILED,
                updates={
                    "final_marker": "FAILED",
                    "final_summary_text": f"{type(exc).__name__}: {exc}",
                },
            )
            await self._event(
                project_id,
                session_id,
                "subagent.failed",
                parent_run_id,
                request,
                {**common, "error": f"{type(exc).__name__}: {exc}"},
            )
            raise

    async def _invoke_specialist_tool(
        self,
        *,
        project_id: str,
        session_id: str,
        parent_run_id: str,
        specialist_run_id: str,
        round_id: str,
        role: SpecialistRole,
        admitted_target_refs: list[str],
        epoch: int,
        request: CreatorMessageRecord,
        common: Mapping[str, Any],
        call_id: str,
        assistant_message_id: str,
        provider_message_id: str | None,
        name: str,
        arguments: Mapping[str, Any],
        tools: AgentProjectTools,
    ) -> dict[str, Any]:
        """Invoke one role-owned tool through generic guard/wait protocols."""

        spec = self.specialist_tools.spec_for(role, name)
        authorization_id: str | None = None
        if (
            spec is not None
            and spec.requires_execution_authorization
            and get_execution_authorization_mode()
            != EXECUTION_AUTHORIZATION_ALLOW_ALL
        ):
            authorization_id = await self._await_execution_authorization(
                project_id=project_id,
                session_id=session_id,
                parent_run_id=parent_run_id,
                specialist_run_id=specialist_run_id,
                round_id=round_id,
                epoch=epoch,
                request=request,
                common=common,
                call_id=call_id,
                spec=spec,
                arguments=arguments,
                tools=tools,
            )
            authorization = await asyncio.to_thread(
                self.executions.get_execution_authorization,
                project_id,
                authorization_id,
            )
            active_provider, active_model = _execution_provider_model(spec)
            if (
                active_provider != authorization.requested_provider
                or active_model != authorization.requested_model
            ):
                raise FileAgentRuntimeError(
                    "execution model configuration changed after authorization; "
                    "request a new authorization",
                )

        waiting_runtime = bool(spec and spec.long_running)
        if waiting_runtime:
            await asyncio.to_thread(
                self.executions.transition_specialist_run,
                project_id,
                specialist_run_id,
                expected_status=SpecialistRunStatus.RUNNING_MODEL,
                status=SpecialistRunStatus.WAITING_RUNTIME,
            )
            await self._event(
                project_id,
                session_id,
                "subagent.waiting_runtime",
                parent_run_id,
                request,
                {**dict(common), "toolCallId": call_id, "tool": name},
            )
        try:
            idempotency_key = _specialist_tool_invocation_id(
                specialist_run_id,
                name,
                arguments,
                call_id=call_id,
            )
            invoked = await self.specialist_tools.invoke(
                role=role,
                name=name,
                arguments=arguments,
                project_id=project_id,
                admitted_target_refs=admitted_target_refs,
                project_tools=tools,
                idempotency_key=idempotency_key,
                context=SourceAgentToolContext(
                    specialist_run_id=specialist_run_id,
                    tool_call_id=call_id,
                    assistant_message_id=assistant_message_id,
                    provider_message_id=provider_message_id,
                    provider=(
                        "configured_vlm"
                        if role is SpecialistRole.SOURCE_INTELLIGENCE
                        else "configured_text"
                    ),
                    model=(
                        get_vlm_model_name()
                        if role is SpecialistRole.SOURCE_INTELLIGENCE
                        else get_text_model_name()
                    ),
                ),
            )
            result = dict(invoked.payload)
            if spec is not None and spec.wait is SpecialistToolWait.TASK:
                if not invoked.task_id:
                    raise FileAgentRuntimeError(
                        f"{name} declared Task wait without a task id",
                    )
                task = await self._await_specialist_task(
                    project_id=project_id,
                    parent_run_id=parent_run_id,
                    epoch=epoch,
                    task_id=invoked.task_id,
                )
                result.update(
                    {
                        "status": task.status.value,
                        "taskId": task.task_id,
                        "outputRefs": list(task.output_refs),
                        "result": task.result,
                    },
                )
            if authorization_id is not None:
                result["executionAuthorizationId"] = authorization_id
            return result
        finally:
            if waiting_runtime:
                current = await asyncio.to_thread(
                    self.executions.get_specialist_run,
                    project_id,
                    specialist_run_id,
                )
                if current.status is SpecialistRunStatus.WAITING_RUNTIME:
                    await asyncio.to_thread(
                        self.executions.transition_specialist_run,
                        project_id,
                        specialist_run_id,
                        expected_status=SpecialistRunStatus.WAITING_RUNTIME,
                        status=SpecialistRunStatus.RUNNING_MODEL,
                    )
                    await self._event(
                        project_id,
                        session_id,
                        "subagent.continuation_started",
                        parent_run_id,
                        request,
                        {**dict(common), "toolCallId": call_id, "tool": name},
                    )

    async def _await_execution_authorization(
        self,
        *,
        project_id: str,
        session_id: str,
        parent_run_id: str,
        specialist_run_id: str,
        round_id: str,
        epoch: int,
        request: CreatorMessageRecord,
        common: Mapping[str, Any],
        call_id: str,
        spec: SpecialistToolSpec,
        arguments: Mapping[str, Any],
        tools: AgentProjectTools,
    ) -> str:
        execution_request_id = _specialist_tool_request_id(
            specialist_run_id,
            spec.name,
            arguments,
        )
        authorization_id = (
            "authorization-"
            + uuid5(
                NAMESPACE_URL,
                f"qwenpaw-creator:file-tool-authorization:{project_id}:{execution_request_id}",
            ).hex
        )
        target_ref = str(arguments.get("targetRef") or "project:unknown")
        provider, model = _execution_provider_model(spec)
        tool_arguments = dict(arguments.get("arguments") or {})
        estimate = estimate_execution_cost(
            provider_kind=spec.provider_kind,
            provider=provider,
            model=model,
            arguments=tool_arguments,
        )
        record = ExecutionAuthorizationRecord(
            authorization_id=authorization_id,
            project_id=project_id,
            round_id=round_id,
            run_id=specialist_run_id,
            execution_request_id=execution_request_id,
            operation=spec.name,
            target_scope=[target_ref],
            authorization_token=secrets.token_urlsafe(32),
            summary=_authorization_summary(
                spec,
                target_ref=target_ref,
                provider=provider,
                model=model,
                tool_arguments=tool_arguments,
                estimate=estimate,
            ),
            scope={
                "operation": spec.name,
                "targetRefs": [target_ref],
                "parameters": tool_arguments,
                "promptPreview": _prompt_preview(tool_arguments, limit=200),
                "billing": estimate.as_payload() if estimate else None,
            },
            requested_provider=provider,
            requested_model=model,
            requested_candidates=1,
            estimated_cost=estimate.estimated_cost if estimate else None,
            caused_by_request_id=tools.context.caused_by_request_id,
            caused_by_message_id=request.message_id,
            caused_by_message_seq=request.message_seq,
            review_policy=tools.context.review_policy,
            metadata={"toolCallId": call_id, "parentRunId": parent_run_id},
        )
        authorization = await asyncio.to_thread(
            self.executions.create_execution_authorization,
            record,
        )
        await asyncio.to_thread(
            self.executions.transition_specialist_run,
            project_id,
            specialist_run_id,
            expected_status=SpecialistRunStatus.RUNNING_MODEL,
            status=SpecialistRunStatus.WAITING_AUTHORIZATION,
        )
        await self._event(
            project_id,
            session_id,
            "execution.authorization_required",
            parent_run_id,
            request,
            {
                **dict(common),
                "authorizationId": authorization.authorization_id,
                "authorizationToken": authorization.authorization_token,
                "executionRequestId": authorization.execution_request_id,
                "operation": authorization.operation,
                "targetRef": target_ref,
                "provider": provider,
                "model": model,
                "summary": authorization.summary,
                "estimatedCost": authorization.estimated_cost,
                "billing": estimate.as_payload() if estimate else None,
                "toolCallId": call_id,
            },
        )
        try:
            while authorization.status is ExecutionAuthorizationStatus.PENDING:
                self._assert_epoch(project_id, parent_run_id, epoch)
                await asyncio.sleep(min(self.poll_interval_seconds, 0.5))
                authorization = await asyncio.to_thread(
                    self.executions.get_execution_authorization,
                    project_id,
                    authorization.authorization_id,
                )
        finally:
            current = await asyncio.to_thread(
                self.executions.get_specialist_run,
                project_id,
                specialist_run_id,
            )
            if current.status is SpecialistRunStatus.WAITING_AUTHORIZATION:
                await asyncio.to_thread(
                    self.executions.transition_specialist_run,
                    project_id,
                    specialist_run_id,
                    expected_status=SpecialistRunStatus.WAITING_AUTHORIZATION,
                    status=SpecialistRunStatus.RUNNING_MODEL,
                )
        await self._event(
            project_id,
            session_id,
            "execution.authorization_decided",
            parent_run_id,
            request,
            {
                **dict(common),
                "authorizationId": authorization.authorization_id,
                "status": authorization.status.value,
                "toolCallId": call_id,
            },
        )
        if authorization.status is not ExecutionAuthorizationStatus.APPROVED:
            raise FileAgentRuntimeError(
                f"execution authorization {authorization.status.value.lower()}",
            )
        return authorization.authorization_id

    async def _await_specialist_task(
        self,
        *,
        project_id: str,
        parent_run_id: str,
        epoch: int,
        task_id: str,
    ) -> Any:
        while True:
            self._assert_epoch(project_id, parent_run_id, epoch)
            task = await asyncio.to_thread(
                self.executions.get_task,
                project_id,
                task_id,
            )
            if task.status is TaskStatus.SUCCEEDED:
                return task
            if task.status in {
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
                TaskStatus.QUARANTINED,
            }:
                detail = task.error or task.result or {}
                raise FileAgentRuntimeError(
                    f"Task {task_id} ended as {task.status.value}: {detail}",
                )
            await asyncio.sleep(min(self.poll_interval_seconds, 0.5))

    async def _workspace_changed(
        self,
        project_id: str,
        session_id: str,
        run_id: str,
        request: CreatorMessageRecord,
        result: Mapping[str, Any],
        *,
        action_id: str,
        specialist: Mapping[str, Any] | None = None,
    ) -> None:
        changed = result.get("changedPointers")
        if not isinstance(changed, list) or not changed:
            return
        await self._event(
            project_id,
            session_id,
            "workspace.head_changed",
            run_id,
            request,
            {
                "runId": run_id,
                "actionId": action_id,
                "generation": result.get("generation"),
                "etag": result.get("etag"),
                "changedPointers": changed,
                **dict(specialist or {}),
            },
        )

    async def _persist_assistant_turn(
        self,
        project_id: str,
        session_id: str,
        run_id: str,
        request: CreatorMessageRecord,
        turn: AgentModelTurn,
        *,
        message_id: str,
    ) -> None:
        metadata: dict[str, Any] = {
            "runId": run_id,
            "providerMessageId": turn.provider_message_id,
            "providerThinking": turn.thinking,
        }
        open_action_ids: list[str] = []
        if turn.tool_calls:
            call = turn.tool_calls[0]
            open_action_ids.append(call.call_id)
            metadata.update(
                {
                    "actionId": call.call_id,
                    "actionDispatchStatus": "OPEN_ACTION",
                    "toolCall": {
                        "id": call.call_id,
                        "name": call.name,
                        "arguments": dict(call.arguments),
                    },
                },
            )
        appended = await asyncio.to_thread(
            self.sessions.append_message,
            project_id,
            session_id,
            request.conversation_id,
            role="assistant",
            content_parts=[{"type": "text", "text": turn.content or ""}],
            message_id=message_id,
            source="creator_agent",
            metadata=metadata,
        )
        await self._event(
            project_id,
            session_id,
            "message.completed",
            run_id,
            request,
            {
                "runId": run_id,
                "messageId": appended.message.message_id,
                "messageSeq": appended.message.message_seq,
                "openActionIds": open_action_ids,
            },
        )

    async def _persist_tool_result(
        self,
        project_id: str,
        session_id: str,
        run_id: str,
        request: CreatorMessageRecord,
        *,
        call_id: str,
        tool_name: str,
        result: Mapping[str, Any],
        failed: bool = False,
    ) -> None:
        raw_result = json.dumps(
            result,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        appended = await asyncio.to_thread(
            self.sessions.append_message,
            project_id,
            session_id,
            request.conversation_id,
            role="tool",
            content_parts=[{"type": "text", "text": raw_result}],
            source="runtime_action_result",
            metadata={
                "runId": run_id,
                "actionId": call_id,
                "toolCallId": call_id,
                "toolName": tool_name,
                "tool": tool_name,
                **(
                    {"resultKind": "web_grounding"}
                    if tool_name == GROUND_PROMPT_CONTEXT_TOOL_NAME
                    else {}
                ),
                "failed": failed,
                "generation": result.get("generation"),
                "etag": result.get("etag"),
                "transactionId": result.get("transactionId"),
                "changedPointers": result.get("changedPointers"),
                "reviewId": result.get("reviewId"),
            },
        )
        await self._event(
            project_id,
            session_id,
            "agent.tool_completed",
            run_id,
            request,
            {
                "runId": run_id,
                "actionId": call_id,
                "toolCallId": call_id,
                "tool": tool_name,
                "messageSeq": appended.message.message_seq,
                "failed": failed,
                **(
                    {
                        "error": str(
                            (
                                result.get("error", {}).get("message")
                                if isinstance(result.get("error"), Mapping)
                                else "Tool execution failed"
                            ),
                        ),
                        "errorType": str(
                            (
                                result.get("error", {}).get("type")
                                if isinstance(result.get("error"), Mapping)
                                else "ToolError"
                            ),
                        ),
                    }
                    if failed
                    else {}
                ),
            },
        )

    async def _goal_for_message(
        self,
        session: Any,
        message: CreatorMessageRecord,
    ):
        if session.active_goal_id is not None:
            try:
                return await asyncio.to_thread(
                    self.sessions.get_goal,
                    message.project_id,
                    session.active_goal_id,
                )
            except RuntimeGoalNotFound:
                pass
        return await asyncio.to_thread(
            self.sessions.create_goal,
            message.project_id,
            session.session_id,
            message.conversation_id,
            root_message_seq=message.message_seq,
            intent=_message_text(message),
            goal_id=f"goal-{uuid4().hex}",
            metadata={"source": "file_agent_runtime"},
        )

    MAINLINE_RESUME_SOURCE = "mainline_resume"

    async def _queue_mainline_resume(
        self,
        *,
        project_id: str,
        session_id: str,
        conversation_id: str,
        intervention_run_id: str,
        interrupted_run_id: str,
    ) -> None:
        """Return the Agent to its interrupted mainline after an intervention.

        An AgentDock interrupt cancels the running mainline and gates every
        branch change behind a Review.  Once the branch run has finished, the
        Session would otherwise sit still and the original task would never
        complete.  Queue one runtime-channel user message — never AgentDock,
        so it can never capture a ReviewBoundary — that tells the Agent to
        continue the mainline.  Everything the resumed run produces is plain
        auto-fix mainline work again and does not require review.
        """

        try:
            interrupted = await asyncio.to_thread(
                self.runs.get,
                project_id,
                interrupted_run_id,
            )
        except Exception:
            interrupted = None
        # Only a run that never reached its own terminal success/failure
        # left unfinished mainline work behind.  A run that succeeded or
        # failed on its own terms must not be relaunched automatically —
        # restarting a failed mainline could loop forever.  A CANCELLED (or
        # still RUNNING/QUEUED after a cross-process takeover) record is the
        # superseded mainline we return to.
        if interrupted is None or interrupted.status in {
            AgentRunStatus.SUCCEEDED,
            AgentRunStatus.FAILED,
        }:
            return
        messages = await asyncio.to_thread(
            self.sessions.list_messages,
            project_id,
            session_id,
            after_seq=0,
            limit=None,
        )
        if any(
            item.source == self.MAINLINE_RESUME_SOURCE
            and item.metadata.get("resumeAfterRunId") == intervention_run_id
            for item in messages
        ):
            return
        mainline_request = next(
            (
                item
                for item in messages
                if item.message_seq == interrupted.caused_by_message_seq
            ),
            None,
        )
        mainline_goal = (
            _message_text(mainline_request)
            if mainline_request is not None
            else ""
        )
        text = (
            "【系统自动消息 · 主线恢复】用户提出的修改意见（支线任务）已处理完成。"
            "请回顾本会话的历史上下文，找到此前被中断的主线任务，并从中断处继续"
            "执行主线工作，直到主线目标完成。\n"
            "注意：\n"
            "1. 不要重复已经完成的步骤；\n"
            "2. 本消息不是新的修改意见，只是提醒你继续之前的主线；\n"
            "3. 如果主线任务实际上已全部完成，请直接确认完成状态，不要进行任何新的修改。"
        )
        if mainline_goal:
            text += f"\n\n被中断的主线任务原始请求：\n{mainline_goal}"
        appended = await asyncio.to_thread(
            self.sessions.append_message,
            project_id,
            session_id,
            conversation_id,
            role="user",
            content_parts=[{"type": "text", "text": text}],
            source=self.MAINLINE_RESUME_SOURCE,
            channel=MessageChannel.RUNTIME,
            metadata={
                "resumeAfterRunId": intervention_run_id,
                "interruptedRunId": interrupted_run_id,
            },
        )
        await self._event(
            project_id,
            session_id,
            "agent.mainline.resumed",
            intervention_run_id,
            appended.message,
            {
                "runId": intervention_run_id,
                "interruptedRunId": interrupted_run_id,
                "messageSeq": appended.message.message_seq,
            },
        )
        self._wake.set()

    async def _converge_resolved_review(self, project_id: str, session: Any):
        """Recover Session/Goal projections after a Review becomes terminal."""

        if session.status is not CreatorSessionStatus.PENDING_REVIEW:
            return session
        active_review = await asyncio.to_thread(
            self.services.reviews.active,
            project_id,
        )
        if active_review is not None:
            return session
        try:
            return await asyncio.to_thread(
                self.sessions.resolve_pending_review,
                project_id,
                session.session_id,
            )
        except (RuntimeGoalNotFound, SessionStateConflict):
            return await asyncio.to_thread(
                self.sessions.get_project_session,
                project_id,
            )

    @staticmethod
    def _tool_context(
        message: CreatorMessageRecord,
        *,
        run_id: str,
    ) -> AgentProjectToolContext:
        boundary = message.review_boundary
        if boundary is not None:
            # A boundary captured while a Run was active is an interrupt; one
            # captured on an idle Session is post-run feedback.  Both gate all
            # related changes behind the same review flow.
            origin = (
                ChangeOrigin.AGENTDOCK_INTERRUPT
                if boundary.interrupted_run_id is not None
                else ChangeOrigin.AGENTDOCK_IDLE_GOAL
            )
            policy = ReviewPolicy.REQUIRE_REVIEW
            request_id = boundary.request_id
            message_seq = boundary.request_message_seq
        else:
            initial = bool(message.metadata.get("initialCreation")) or (
                message.source == "initial_goal"
            )
            origin = (
                ChangeOrigin.INITIAL_CREATION
                if initial
                else (
                    ChangeOrigin.AGENTDOCK_IDLE_GOAL
                    if message.channel is MessageChannel.AGENTDOCK
                    else ChangeOrigin.RUNTIME_TASK
                )
            )
            policy = ReviewPolicy.AUTO_FIX
            request_id = message.client_message_id or message.message_id
            message_seq = message.message_seq
        return AgentProjectToolContext(
            origin=origin,
            review_policy=policy,
            review_boundary=boundary,
            caused_by_request_id=request_id,
            caused_by_message_seq=message_seq,
            round_id=f"agent-round-{run_id}",
        )

    async def _cancel_run(
        self,
        project_id: str,
        session_id: str,
        goal_id: str,
        run_id: str,
        message: CreatorMessageRecord,
    ) -> None:
        handle = self._active.get(project_id)
        superseded = bool(
            handle is not None
            and handle.run_id == run_id
            and handle.superseded,
        )
        try:
            await asyncio.to_thread(
                self.runs.transition,
                project_id,
                run_id,
                expected_status={
                    AgentRunStatus.QUEUED,
                    AgentRunStatus.RUNNING,
                },
                status=AgentRunStatus.CANCELLED,
                updates={
                    "error": {
                        "code": "SUPERSEDED" if superseded else "INTERRUPTED",
                        "message": (
                            "Run superseded by an AgentDock request"
                            if superseded
                            else "Run interrupted by the user"
                        ),
                    },
                },
            )
        except AgentRunStateConflict:
            pass
        if superseded:
            try:
                await asyncio.to_thread(
                    self.sessions.mark_messages_consumed,
                    project_id,
                    session_id,
                    through_seq=message.message_seq,
                    goal_id=goal_id,
                )
            except SessionStateConflict:
                pass
        else:
            # A hard stop is a durable input boundary, not a process-local
            # retry guard.  Consume every message that existed when cleanup
            # reached this point before releasing active_run_id.  Other
            # QwenPaw processes can then observe the same stop and cannot
            # immediately relaunch the cancelled request.
            try:
                current_session = await asyncio.to_thread(
                    self.sessions.get_project_session,
                    project_id,
                )
                await asyncio.to_thread(
                    self.sessions.mark_messages_consumed,
                    project_id,
                    session_id,
                    through_seq=current_session.last_message_seq,
                    goal_id=goal_id,
                )
            except SessionStateConflict:
                pass
        try:
            await asyncio.to_thread(
                self.sessions.set_goal_status,
                project_id,
                goal_id,
                (
                    CreatorGoalStatus.RESUME_REQUIRED
                    if superseded
                    else CreatorGoalStatus.CANCELLED
                ),
            )
            await asyncio.to_thread(
                self.sessions.clear_active_run,
                project_id,
                session_id,
                expected_run_id=run_id,
                status=(
                    CreatorSessionStatus.RESUMING
                    if superseded
                    else CreatorSessionStatus.CANCELLED
                ),
            )
        except SessionStateConflict:
            pass
        await self._event(
            project_id,
            session_id,
            "agent.run.cancelled",
            run_id,
            message,
            {"runId": run_id, "superseded": superseded},
        )

    async def _fail_run(
        self,
        project_id: str,
        session_id: str,
        goal_id: str,
        run_id: str,
        request: CreatorMessageRecord,
        *,
        code: str,
        message_text: str,
        retryable: bool,
    ) -> None:
        try:
            await asyncio.to_thread(
                self.runs.transition,
                project_id,
                run_id,
                expected_status={
                    AgentRunStatus.QUEUED,
                    AgentRunStatus.RUNNING,
                },
                status=AgentRunStatus.FAILED,
                updates={
                    "error": {
                        "code": code,
                        "message": message_text,
                        "retryable": retryable,
                    },
                },
            )
        except AgentRunStateConflict:
            pass
        # A failure is a durable input boundary, not a process-local retry
        # guard.  Consume the failed request before releasing active_run_id so
        # that neither a process restart nor an unrelated ``notify`` (which
        # clears the in-memory ``_blocked_heads``) relaunches the Agent on the
        # same message.  Recovery requires a new explicit user request; the
        # persisted session error keeps the failure visible to AgentDock.
        try:
            await asyncio.to_thread(
                self.sessions.mark_messages_consumed,
                project_id,
                session_id,
                through_seq=request.message_seq,
                goal_id=goal_id,
            )
        except SessionStateConflict:
            pass
        try:
            await asyncio.to_thread(
                self.sessions.set_goal_status,
                project_id,
                goal_id,
                CreatorGoalStatus.FAILED,
            )
            await asyncio.to_thread(
                self.sessions.clear_active_run,
                project_id,
                session_id,
                expected_run_id=run_id,
            )
        except SessionStateConflict:
            pass
        await asyncio.to_thread(
            self.sessions.set_session_error,
            project_id,
            session_id,
            code=code,
            message=message_text,
            retryable=retryable,
            details={"runId": run_id, "messageSeq": request.message_seq},
        )
        await self._event(
            project_id,
            session_id,
            "agent.run.failed",
            run_id,
            request,
            {
                "runId": run_id,
                "error": {
                    "code": code,
                    "message": message_text,
                    "retryable": retryable,
                },
            },
        )

    async def _record_idle_interrupt(
        self,
        project_id: str,
        *,
        reason: str,
    ) -> None:
        try:
            session = await asyncio.to_thread(
                self.sessions.get_project_session,
                project_id,
            )
            # An active_run_id without a local handle is owned by another
            # process sharing this Runtime root.  Leave the durable interrupt
            # request in place so that owner cancels itself on its next poll.
            if session.active_run_id is not None:
                return
            if session.last_consumed_message_seq < session.last_message_seq:
                await asyncio.to_thread(
                    self.sessions.mark_messages_consumed,
                    project_id,
                    session.session_id,
                    through_seq=session.last_message_seq,
                    goal_id=session.active_goal_id,
                )
            await asyncio.to_thread(
                self.sessions.set_session_status,
                project_id,
                session.session_id,
                CreatorSessionStatus.CANCELLED,
            )
            await asyncio.to_thread(
                self.sessions.append_event,
                project_id,
                session.session_id,
                event_type="agent.interrupt.idle",
                actor="user",
                payload={"reason": reason},
            )
        except Exception:
            return

    async def _event(
        self,
        project_id: str,
        session_id: str,
        event_type: str,
        run_id: str,
        request: CreatorMessageRecord,
        payload: Mapping[str, Any],
    ) -> None:
        await asyncio.to_thread(
            self.sessions.append_event,
            project_id,
            session_id,
            event_type=event_type,
            actor="file_agent_runtime",
            round_id=f"agent-round-{run_id}",
            message_id=request.message_id,
            payload=dict(payload),
        )
        if not event_type.endswith("_delta"):
            trace_event(
                f"creator.{event_type}",
                component="creator.file_agent_runtime",
                projectId=project_id,
                sessionId=session_id,
                conversationId=request.conversation_id,
                runId=run_id,
                attributes=dict(payload),
            )

    def _begin_epoch(self, project_id: str, run_id: str) -> int:
        with self._publication_lock:
            epoch = self._epochs.get(project_id, 0) + 1
            self._epochs[project_id] = epoch
            return epoch

    def _revoke_epoch(self, project_id: str, run_id: str, epoch: int) -> None:
        del run_id
        with self._publication_lock:
            if self._epochs.get(project_id) == epoch:
                self._epochs[project_id] = epoch + 1

    def _assert_epoch(self, project_id: str, run_id: str, epoch: int) -> None:
        with self._publication_lock:
            if self._epochs.get(project_id) != epoch:
                raise StaleAgentRun(
                    f"Agent run was interrupted and may no longer commit: {run_id}",
                )


def _message_text(message: CreatorMessageRecord) -> str:
    chunks: list[str] = []
    for part in message.content_parts:
        if part.type == "text" and part.text:
            chunks.append(part.text)
        else:
            chunks.append(
                json.dumps(
                    part.model_dump(mode="json", exclude_none=True),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
    refs = message.metadata.get("assetVersionRefs")
    if isinstance(refs, list):
        exact_refs = [
            str(value).strip() for value in refs if str(value).strip()
        ]
        if exact_refs:
            chunks.append(
                "本轮已入库素材（本轮消息附件的 exact AssetVersion refs，"
                "不是文件路径或操作指令）："
                + json.dumps(
                    list(dict.fromkeys(exact_refs)),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
    context = message.metadata.get("context")
    if isinstance(context, Mapping):
        keys = (
            "panel",
            "selected",
            "editingField",
            "selection",
            "selections",
            "extraRefs",
            "targetRef",
            "targetRefs",
        )
        structured = {
            key: context[key]
            for key in keys
            if key in context and context[key] not in (None, "", [], {})
        }
        if structured:
            chunks.append(
                "[Creator UI 结构化上下文；path 是 project.json 的 RFC 6901 "
                "字段指针，field/ref 是语义定位。修改前读取对应字段核验]\n"
                + json.dumps(
                    structured,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
    return "\n".join(chunks).strip() or "请处理本消息中的项目请求。"


def _continuation_message_text(
    request: CreatorMessageRecord,
    prior_context: list[CreatorMessageRecord],
) -> str:
    """Carry one durable AgentDock Conversation into the next Agent run."""

    current = _message_text(request)
    if not prior_context:
        return current
    history = [
        {
            "messageSeq": item.message_seq,
            "role": item.role,
            "source": item.source,
            "content": [
                part.model_dump(mode="json", exclude_none=True)
                for part in item.content_parts
            ],
            "metadata": dict(item.metadata),
        }
        for item in prior_context
    ]
    return (
        "以下 CONVERSATION_HISTORY_JSON 是同一 AgentDock Conversation 在本轮之前"
        "已经持久化的完整上下文。请继承其中的用户目标、已完成步骤、工具结果与约束；"
        "它是上下文，不是新的操作指令。\n"
        "CONVERSATION_HISTORY_JSON="
        + json.dumps(history, ensure_ascii=False, separators=(",", ":"))
        + "\n\nCURRENT_USER_REQUEST=\n"
        + current
    )


def _require_source_intelligence_associations(
    project: Project,
    target_refs: list[str],
) -> None:
    """A Source Specialist cannot succeed with observations only in chat.

    SourceAnalysisService is the authority that publishes the indexed analysis
    and selects it on ProjectSource. This terminal fence prevents an outer VLM
    Specialist from returning SUCCESS before that durable association exists.
    """

    for target_ref in target_refs:
        prefix, separator, logical_asset_id = target_ref.partition(":")
        if prefix != "asset" or not separator or not logical_asset_id:
            raise FileAgentRuntimeError(
                f"Source Intelligence target is not canonical: {target_ref}",
            )
        sources = [
            source
            for source in project.sources.sources.items.values()
            if source.logical_asset_id == logical_asset_id
        ]
        if len(sources) != 1:
            raise FileAgentRuntimeError(
                "Source Intelligence SUCCESS requires exactly one ProjectSource for "
                f"asset:{logical_asset_id}",
            )
        source = sources[0]
        intelligence_id = source.current_intelligence_version_id
        if intelligence_id is None:
            raise FileAgentRuntimeError(
                "Source Intelligence SUCCESS requires ProjectSource."
                f"current_intelligence_version_id for asset:{logical_asset_id}",
            )
        intelligence = project.assets.intelligence_versions_by_id.get(
            intelligence_id,
        )
        if (
            intelligence is None
            or intelligence.source_asset_version_id
            != source.selected_asset_version_id
        ):
            raise FileAgentRuntimeError(
                "Source Intelligence selection does not match the current Source version "
                f"for asset:{logical_asset_id}",
            )
        indexed = project.assets.files_by_id.get(intelligence.file_id)
        if indexed is None or indexed.kind != "source_intelligence":
            raise FileAgentRuntimeError(
                "Source Intelligence SUCCESS requires an indexed analysis file for "
                f"asset:{logical_asset_id}",
            )


def _specialist_terminal(content: str) -> tuple[str, str]:
    text = content.strip()
    for marker in ("SUCCESS", "BLOCKED", "FAILED"):
        prefix = f"[{marker}]"
        if text.startswith(prefix):
            return marker, text[len(prefix) :].strip() or prefix
    raise AgentModelError(
        "Specialist final response must start with [SUCCESS], [BLOCKED], or [FAILED]",
    )


def _specialist_tool_recovery(name: str) -> str:
    if name == "jq_project":
        return (
            "Re-read project.json and retry jq_project with a transform that returns the "
            "complete Project root and preserves all Runtime-protected root fields. "
            "Never assign schema_version, project_id, generation, created_at, or updated_at; "
            "the Runtime maintains them. Start from the input Project `.`, not `$jsonArgs`. "
            "Put bulk objects in jsonArgs. If the failure was malformed or misnested argument "
            "JSON, regenerate the call with program as a top-level field and split an "
            "oversized jsonArgs into a few smaller jq_project calls. For every Edit item, "
            "set duration_tick to round((source_out_tick - source_in_tick) / playback_rate). "
            "Remove nonexistent references; not-yet-produced artifacts stay null. "
            "Parenthesize computed jq values before binding them, for example "
            '("source:" + $logicalId) as $sourceKey, and parenthesize expressions used as '
            "object values. Never finish with a saved pre-edit root such as $project "
            "because that discards mutations."
        )
    if name == "ai_edit":
        return (
            "Use the persisted Runtime Task error as the cause and retry ai_edit with "
            "a new tool call when appropriate. A URL-backed SourceAssetVersion with "
            "file_id=null remains executable when metadata.publicSourceUrl is valid; "
            "do not wait for or infer failure from the display cache."
        )
    return (
        "Use the reported tool or Runtime Task error as the cause, refresh Project "
        "state when relevant, and retry with a new tool call only when the operation "
        "is safe to repeat."
    )


def _specialist_tool_request_id(
    specialist_run_id: str,
    name: str,
    arguments: Mapping[str, Any],
    *,
    invocation_id: str | None = None,
) -> str:
    payload = json.dumps(
        arguments,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    identity = f"{specialist_run_id}\0{name}\0{payload}"
    if invocation_id is not None:
        identity = f"{identity}\0{invocation_id}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return f"specialist-tool-{digest}"


def _specialist_tool_invocation_id(
    specialist_run_id: str,
    name: str,
    arguments: Mapping[str, Any],
    *,
    call_id: str,
) -> str:
    return _specialist_tool_request_id(
        specialist_run_id,
        name,
        arguments,
        invocation_id=call_id if name == "ai_edit" else None,
    )


def _execution_provider_model(spec: SpecialistToolSpec) -> tuple[str, str]:
    """Snapshot model identity for an approval without loading a provider."""

    if spec.provider_kind == "image":
        from models.image import get_image_backend

        return get_image_backend().casefold(), get_image_model_name()
    if spec.provider_kind == "video":
        return get_video_backend(), get_video_model_name()
    return str(spec.provider_kind or "creator-tool"), "configured"


_AUTHORIZATION_OPERATION_LABELS = {
    "image_generation": "生成图片",
    "r2v_generation": "生成视频",
}


def _prompt_preview(tool_arguments: Mapping[str, Any], *, limit: int) -> str:
    prompt = str(tool_arguments.get("prompt") or "").strip()
    if len(prompt) <= limit:
        return prompt
    return prompt[: limit - 1] + "…"


def _authorization_summary(
    spec: SpecialistToolSpec,
    *,
    target_ref: str,
    provider: str,
    model: str,
    tool_arguments: Mapping[str, Any],
    estimate: CostEstimate | None,
) -> str:
    """One human-readable line telling the user exactly what will run."""

    label = _AUTHORIZATION_OPERATION_LABELS.get(spec.name, f"执行 {spec.name}")
    parts = [f"{label}：{target_ref}", f"模型 {provider}/{model}"]
    if spec.provider_kind == "image":
        ratio = str(tool_arguments.get("aspectRatio") or "16:9")
        parts.append(f"画幅 {ratio}")
    elif spec.provider_kind == "video":
        duration = tool_arguments.get("durationSeconds")
        if duration:
            parts.append(f"{duration}秒")
        resolution = tool_arguments.get("resolution")
        if resolution:
            parts.append(str(resolution).upper())
        ratio = tool_arguments.get("ratio")
        if ratio:
            parts.append(f"比例 {ratio}")
        if "generateAudio" in tool_arguments:
            parts.append(
                "有声" if tool_arguments.get("generateAudio") else "无声",
            )
    if estimate is not None:
        parts.append(f"预计费用 {estimate.display_text}（{estimate.formula}）")
    return " · ".join(parts)


__all__ = [
    "FileAgentRuntimeError",
    "FileCreatorAgentRuntime",
    "StaleAgentRun",
]
