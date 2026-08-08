# -*- coding: utf-8 -*-
"""Event-driven scheduler that fans out READY media nodes in parallel.

The model plans; the Runtime executes. Media generation parameters are
deterministically assembled from project.json, so once the work graph
marks a media node READY there is nothing left that needs a model turn
— the scheduler dispatches it directly, several at a time, bounded by
``media_parallelism`` on top of the global model_slot semaphores.

Safety posture:
- Only runs for projects in the unattended ladder
  (execution_authorization=allow_all); otherwise the graph stays a
  read-only view and behavior is unchanged.
- A node is dispatched at most once per input fingerprint: FAILED nodes
  are *not* retried until a prompt or upstream selection actually
  changes (no paid retry loops). Manual dispatch via the API bypasses
  this ledger deliberately.
- Write-back safety comes from the existing commit boundary (field-level
  merge over disjoint pointers) and the durable idempotency slots.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from domain.enums import CreatorCommandType
from models.config import (
    EXECUTION_AUTHORIZATION_ALLOW_ALL,
    get_execution_authorization_mode,
    get_media_parallelism,
)
from services.media_files.call_budget import (
    MediaCallBudgetExhausted,
    ensure_media_call_budget,
)
from services.media_files.transient_errors import is_transient_error_message
from services.file_agent_runtime.work_graph import (
    WorkGraph,
    WorkNode,
    derive_work_graph,
)
from services.project_files.facade import CreatorFileServices
from services.runtime_files.execution_store import ProjectExecutionStore
from utils.logger import setup_logger


logger = setup_logger("creator.work_scheduler")

# Loop exits after this long without a wake; any later wake restarts it.
_IDLE_EXIT_SECONDS = 300.0

# Transient dispatch failures (provider timeouts, 5xx, rate limits) may
# reopen the ledger this many times per (node, fingerprint); deterministic
# failures (safety rejections, validation) stay locked until inputs change.
_TRANSIENT_RETRY_LIMIT = 2

# Scheduler-only transient markers; the shared media-side classifier
# (is_transient_error_message) supplies the common ones (connection,
# timeout, service unavailable, bad file descriptor, status 5xx, ...).
_TRANSIENT_ERROR_MARKERS = (
    "rate limit",
    "429",
    "status 5",
    "temporarily",
)


def _is_transient_dispatch_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return is_transient_error_message(text) or any(
        marker in text for marker in _TRANSIENT_ERROR_MARKERS
    )


_R2V_COMMANDS = {CreatorCommandType.GENERATE_R2V_VIDEO.value}

DispatchHook = Callable[[str, WorkGraph], Awaitable[None]]


class WorkGraphScheduler:
    """Per-project event loops dispatching READY media nodes."""

    def __init__(
        self,
        services: CreatorFileServices,
        *,
        image_dispatch: Callable[..., Awaitable[Any]] | None = None,
        r2v_dispatch: Callable[..., Awaitable[Any]] | None = None,
        on_tick: DispatchHook | None = None,
    ) -> None:
        self.services = services
        self.executions = ProjectExecutionStore(services.root)
        self._image_dispatch = image_dispatch
        self._r2v_dispatch = r2v_dispatch
        self._on_tick = on_tick
        self._wakes: dict[str, asyncio.Event] = {}
        self._loops: dict[str, asyncio.Task[None]] = {}
        # (project_id, node_id, fingerprint) -> already dispatched once.
        self._dispatched: set[tuple[str, str, str]] = set()
        self._transient_retries: dict[tuple[str, str, str], int] = {}
        self._inflight: dict[str, set[str]] = {}

    # -- lifecycle -----------------------------------------------------

    def wake(self, project_id: str) -> None:
        """Signal that durable state changed; start the loop if needed."""

        event = self._wakes.setdefault(project_id, asyncio.Event())
        event.set()
        task = self._loops.get(project_id)
        if task is None or task.done():
            self._loops[project_id] = asyncio.create_task(
                self._project_loop(project_id),
            )

    async def shutdown(self) -> None:
        for task in self._loops.values():
            task.cancel()
        for task in list(self._loops.values()):
            try:
                await task
            except (
                asyncio.CancelledError,
                Exception,
            ):  # pylint: disable=broad-except
                pass
        self._loops.clear()

    # -- loop ----------------------------------------------------------

    async def _project_loop(self, project_id: str) -> None:
        event = self._wakes.setdefault(project_id, asyncio.Event())
        while True:
            # asyncio.timeout instead of wait_for: the pre-3.12 wait_for
            # could swallow an external cancellation that raced a completed
            # inner wait, leaving a zombie loop that ignored its cancel and
            # kept a 300s timer alive (observed as a CI teardown hang).
            try:
                async with asyncio.timeout(_IDLE_EXIT_SECONDS):
                    await event.wait()
            except TimeoutError:
                if not self._inflight.get(project_id):
                    return
                continue
            event.clear()
            try:
                await self.tick(project_id)
            except Exception:  # pylint: disable=broad-except
                logger.exception(
                    "work-graph tick failed for %s",
                    project_id,
                )

    # -- core ----------------------------------------------------------

    def enabled(self) -> bool:
        return (
            get_execution_authorization_mode()
            == EXECUTION_AUTHORIZATION_ALLOW_ALL
        )

    async def tick(self, project_id: str) -> WorkGraph | None:
        """Derive the graph once and dispatch what capacity allows."""

        if not self.enabled():
            return None
        try:
            snapshot = await asyncio.to_thread(
                self.services.projects.read,
                project_id,
            )
            tasks = await asyncio.to_thread(
                self.executions.list_tasks,
                project_id,
            )
        except Exception:  # pylint: disable=broad-except
            logger.exception("work-graph state read failed for %s", project_id)
            return None
        graph = derive_work_graph(snapshot.project, tasks=tasks)
        inflight = self._inflight.setdefault(project_id, set())
        try:
            # Wallet fuse: a spent budget pauses automatic dispatch; the
            # media entry points enforce it too, this just avoids creating
            # failed tasks.
            await asyncio.to_thread(
                ensure_media_call_budget,
                self.services,
                project_id,
            )
        except MediaCallBudgetExhausted as exc:
            logger.warning(
                "work-graph dispatch paused for %s: %s",
                project_id,
                exc,
            )
            if self._on_tick is not None:
                await self._on_tick(project_id, graph)
            return graph
        running = sum(
            1 for node in graph.nodes if node.status.value == "running"
        )
        capacity = get_media_parallelism() - running - len(inflight)
        for node in self._dispatch_candidates(project_id, graph):
            if capacity <= 0:
                break
            fingerprint = node.dispatch_fingerprint or node.node_id
            ledger_key = (project_id, node.node_id, fingerprint)
            if ledger_key in self._dispatched or node.node_id in inflight:
                continue
            self._dispatched.add(ledger_key)
            inflight.add(node.node_id)
            capacity -= 1
            asyncio.create_task(
                self._dispatch(project_id, node, fingerprint),
            )
        if self._on_tick is not None:
            await self._on_tick(project_id, graph)
        return graph

    def _dispatch_candidates(
        self,
        project_id: str,
        graph: WorkGraph,
    ) -> list[WorkNode]:
        """READY media nodes plus transiently-failed ones within budget.

        A node whose last task died of a provider timeout / 5xx / rate
        limit is FAILED on the graph but not deterministically so — the
        durable idempotency slot resumes the same task, so a bounded
        retry costs nothing extra. Deterministic failures (safety,
        validation) never re-enter.
        """

        candidates = list(graph.ready_media_nodes())
        for node in graph.nodes:
            if (
                node.status.value != "failed"
                or node.command is None
                or not node.error
            ):
                continue
            if not _is_transient_dispatch_error(RuntimeError(node.error)):
                continue
            fingerprint = node.dispatch_fingerprint or node.node_id
            ledger_key = (project_id, node.node_id, fingerprint)
            if self._transient_retries.get(ledger_key, 0) >= (
                _TRANSIENT_RETRY_LIMIT
            ):
                continue
            self._transient_retries[ledger_key] = (
                self._transient_retries.get(ledger_key, 0) + 1
            )
            self._dispatched.discard(ledger_key)
            candidates.append(node)
        return candidates

    async def _dispatch(
        self,
        project_id: str,
        node: WorkNode,
        fingerprint: str,
    ) -> None:
        logger.info(
            "work-graph dispatch project=%s node=%s command=%s",
            project_id,
            node.node_id,
            node.command,
        )
        try:
            await self.dispatch_node(project_id, node, fingerprint)
        except Exception as exc:  # pylint: disable=broad-except
            ledger_key = (project_id, node.node_id, fingerprint)
            if (
                _is_transient_dispatch_error(exc)
                and self._transient_retries.get(ledger_key, 0)
                < _TRANSIENT_RETRY_LIMIT
            ):
                # Field run 2026-08-06: the first live fan-out lost five
                # storyboards to provider timeouts and the ledger locked
                # them as if the failure were deterministic. Transient
                # faults reopen the ledger (bounded) so the next tick
                # retries; the durable idempotency slot resumes the same
                # task instead of paying twice.
                self._transient_retries[ledger_key] = (
                    self._transient_retries.get(ledger_key, 0) + 1
                )
                self._dispatched.discard(ledger_key)
                logger.warning(
                    "work-graph dispatch transient failure project=%s "
                    "node=%s (retry %d/%d): %s",
                    project_id,
                    node.node_id,
                    self._transient_retries[ledger_key],
                    _TRANSIENT_RETRY_LIMIT,
                    exc,
                )
            else:
                # The task record carries the durable failure; the graph
                # will surface it as FAILED and the ledger prevents a paid
                # retry until the node's inputs change.
                logger.warning(
                    "work-graph dispatch failed project=%s node=%s: %s",
                    project_id,
                    node.node_id,
                    exc,
                )
        finally:
            self._inflight.get(project_id, set()).discard(node.node_id)
            self.wake(project_id)

    async def dispatch_node(
        self,
        project_id: str,
        node: WorkNode,
        fingerprint: str | None = None,
    ) -> Any:
        """Execute one node through the shared media executors."""

        if node.command is None or node.target_ref is None:
            raise ValueError(f"node {node.node_id} is not dispatchable")
        idempotency_key = (
            f"dag-{node.node_id}-{fingerprint or node.dispatch_fingerprint}"
        )
        if node.command in _R2V_COMMANDS:
            dispatch = self._r2v_dispatch or _default_r2v_dispatch
        else:
            dispatch = self._image_dispatch or _default_image_dispatch
        return await dispatch(
            self.services,
            project_id=project_id,
            command=node.command,
            target_ref=node.target_ref,
            arguments=dict(node.dispatch_arguments),
            idempotency_key=idempotency_key,
        )


async def _default_image_dispatch(
    services: CreatorFileServices,
    *,
    project_id: str,
    command: str,
    target_ref: str,
    arguments: dict[str, Any],
    idempotency_key: str,
) -> Any:
    # Imported lazily: media executors pull heavy provider dependencies.
    # pylint: disable=import-outside-toplevel
    from services.media_files.image_execution import (
        execute_file_image_command,
    )

    return await execute_file_image_command(
        services,
        project_id=project_id,
        command=command,
        target_ref=target_ref,
        arguments=arguments,
        idempotency_key=idempotency_key,
    )


async def _default_r2v_dispatch(
    services: CreatorFileServices,
    *,
    project_id: str,
    command: str | None = None,
    target_ref: str,
    arguments: dict[str, Any],
    idempotency_key: str,
) -> Any:
    # pylint: disable=import-outside-toplevel
    from services.media_files.r2v_execution import (
        execute_file_r2v_command,
    )

    # The r2v entry point has a single command and takes no command kwarg.
    del command
    return await execute_file_r2v_command(
        services,
        project_id=project_id,
        target_ref=target_ref,
        arguments=arguments,
        idempotency_key=idempotency_key,
    )


__all__ = ["WorkGraphScheduler"]
