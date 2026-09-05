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
import hashlib
import time
from typing import Any, Awaitable, Callable, Mapping, Sequence

from domain.enums import CreatorCommandType
from models.config import (
    EXECUTION_AUTHORIZATION_ALLOW_ALL,
    get_execution_authorization_mode,
    get_image_model_name,
    get_media_parallelism,
    get_video_model_name,
    get_vlm_timeout_seconds,
)
from services.media_files.call_budget import (
    MediaCallBudgetExhausted,
    ensure_media_call_budget,
)
from services.media_files.transient_errors import is_transient_error_message
from services.file_agent_runtime.notifications import RuntimeEventKind
from services.file_agent_runtime.work_graph import (
    dispatch_key_predates_digest_ledger,
    WorkGraph,
    WorkNode,
    WorkNodeStatus,
    derive_work_graph,
)
from services.project_files import frontend_edit_hold
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
# A provider having a bad hour outlives the immediate retry budget.
# Field run 2026-08-12 (project 27dc): gpt-image-2 threw WriteTimeout /
# ReadError for ~40 minutes; every storyboard burned its 2 retries and
# FAILED terminally with nothing left to try once the provider recovered
# — a human nudge was the only way back. After the immediate budget is
# spent, one further retry is granted per cooldown window up to a hard
# cap, so the pipeline self-heals from provider weather while paid
# spend stays bounded.
_TRANSIENT_RETRY_HARD_CAP = 6
_TRANSIENT_RETRY_COOLDOWN_SECONDS = 300.0

# Scheduler-only transient markers; the shared media-side classifier
# (is_transient_error_message) supplies the common ones (connection,
# timeout, service unavailable, bad file descriptor, status 5xx, ...).
_TRANSIENT_ERROR_MARKERS = (
    "rate limit",
    "429",
    "status 5",
    "temporarily",
)

# Error codes that indicate permanent structural issues requiring explicit
# agent intervention. These errors will never resolve through project state
# changes alone — the agent must modify the project (e.g., reduce reference
# count) before retry is allowed.
_DETERMINISTIC_ERROR_CODES = frozenset(
    {
        "IMAGE_REFERENCE_BUDGET_EXCEEDED",
        "VIDEO_REFERENCE_BUDGET_EXCEEDED",
        "IMAGE_MODEL_CAPABILITY_UNKNOWN",
        "VIDEO_MODEL_CAPABILITY_UNKNOWN",
        "VALIDATION_ERROR",
    },
)


def _is_transient_dispatch_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return is_transient_error_message(text) or any(
        marker in text for marker in _TRANSIENT_ERROR_MARKERS
    )


def _quarantined_stale_targets(tasks: Sequence[Any]) -> set[str]:
    """Target refs holding a rescuable quarantined-stale result.

    Sibling commits in a parallel fan-out used to quarantine finished
    (billed) renders as PROJECT_INPUT_SNAPSHOT_STALE; the stored result
    on the terminal task is everything the executor needs to import
    without re-rendering. Only these targets may reopen the dispatch
    ledger — anything else keeps the no-paid-retry guarantee.
    """

    targets: set[str] = set()
    for task in tasks:
        status = getattr(task, "status", None)
        if getattr(status, "value", None) != "QUARANTINED":
            continue
        error = getattr(task, "error", None)
        if (
            not isinstance(error, Mapping)
            or str(error.get("code") or "") != "PROJECT_INPUT_SNAPSHOT_STALE"
        ):
            continue
        if not isinstance(getattr(task, "result", None), dict):
            continue
        metadata = getattr(task, "metadata", None) or {}
        input_refs = getattr(task, "input_refs", None) or []
        target = str(
            metadata.get("targetRef") or (input_refs[0] if input_refs else ""),
        )
        if target:
            targets.add(target)
    return targets


_R2V_COMMANDS = {CreatorCommandType.GENERATE_R2V_VIDEO.value}
_S2V_COMMANDS = {CreatorCommandType.GENERATE_S2V_VIDEO.value}
_COMPOSE_COMMANDS = {CreatorCommandType.COMPOSE_FINAL_VIDEO.value}
_SCRIPT_COMMANDS = {CreatorCommandType.GENERATE_TIMELINE_SCRIPT.value}

# Publication stays non-blocking, but dependent unattended work waits for the
# asynchronous reviewer to settle. Otherwise a short image review can replace
# a storyboard while a paid two-minute video is already running; that finished
# video is quarantined as stale and the provider gets billed a second time.
# Visual/lineup nodes are blocked only when targeting a slot under review,
# preventing double-generation that would invalidate the pending review.
_MEDIA_REVIEW_DEPENDENT_KINDS = frozenset(
    {"visual", "lineup", "storyboard", "video", "compose"},
)
# Heavy/billed nodes that need stable inputs: storyboard, video, and compose.
# These are unconditionally fenced by both media review (any active slot) and
# sync review (text review pending). Visual/lineup are lighter and only fenced
# when their specific target slot is under review.
_HEAVY_NODE_KINDS = frozenset({"storyboard", "video", "compose"})


def _blocked_by_active_media_review(
    node: WorkNode,
    active_slots: frozenset[str],
    active_owner_refs: frozenset[str],
) -> bool:
    if not active_slots or node.kind not in _MEDIA_REVIEW_DEPENDENT_KINDS:
        return False
    if node.kind in _HEAVY_NODE_KINDS:
        return True
    # ArtifactSlot ids are opaque (asset:{id}:variant:{vid}:image), while a
    # visual/lineup node's target_ref is the slot's owner_ref (asset:{id},
    # lineup:{id}); the caller resolves reviewing slots to owner refs so the
    # membership check compares like with like.
    if node.target_ref is not None:
        return node.target_ref in active_owner_refs
    return False


def _blocked_by_active_sync_review(
    node: WorkNode,
    *,
    sync_review_pending: bool,
) -> bool:
    """Fence storyboard/video/compose until pre-generation text review ends."""

    return sync_review_pending and node.kind in _HEAVY_NODE_KINDS


class WorkGraphScheduler:
    """Per-project event loops dispatching READY media nodes."""

    def __init__(
        self,
        services: CreatorFileServices,
        *,
        image_dispatch: Callable[..., Awaitable[Any]] | None = None,
        r2v_dispatch: Callable[..., Awaitable[Any]] | None = None,
        s2v_dispatch: Callable[..., Awaitable[Any]] | None = None,
        notifications: Any | None = None,
    ) -> None:
        self.services = services
        self.executions = ProjectExecutionStore(services.root)
        self._image_dispatch = image_dispatch
        self._r2v_dispatch = r2v_dispatch
        self._s2v_dispatch = s2v_dispatch
        self._notifications = notifications
        # Per-project last observed node states for edge-triggered
        # notifications: {project_id: {node_id: (status, fingerprint)}}.
        self._graph_progress: dict[str, dict[str, tuple[str, str]]] = {}
        self._wakes: dict[str, asyncio.Event] = {}
        self._loops: dict[str, asyncio.Task[None]] = {}
        # (project_id, node_id, fingerprint) -> already dispatched once.
        self._dispatched: set[tuple[str, str, str]] = set()
        self._transient_retries: dict[tuple[str, str, str], int] = {}
        self._transient_last: dict[tuple[str, str, str], float] = {}
        self._inflight: dict[str, set[str]] = {}
        self._dispatch_tasks: dict[str, set[asyncio.Task[None]]] = {}
        self._sync_gate_rechecks: dict[str, asyncio.TimerHandle] = {}
        self._cancelled_projects: set[str] = set()
        # Keyed by (project, node, fingerprint): a deterministic failure
        # locks exactly the inputs that produced it. Fixing the inputs
        # changes the fingerprint and unlocks dispatch; a (project, node)
        # key would deadlock the node forever, because the entry is only
        # popped after a successful dispatch that the entry itself blocks.
        self._deterministic_failure_nodes: dict[tuple[str, str, str], str] = {}

    def _transient_budget_available(
        self,
        ledger_key: tuple[str, str, str],
    ) -> bool:
        count = self._transient_retries.get(ledger_key, 0)
        if count < _TRANSIENT_RETRY_LIMIT:
            return True
        if count >= _TRANSIENT_RETRY_HARD_CAP:
            return False
        last = self._transient_last.get(ledger_key, 0.0)
        return (time.monotonic() - last) >= _TRANSIENT_RETRY_COOLDOWN_SECONDS

    def _note_transient_retry(
        self,
        ledger_key: tuple[str, str, str],
    ) -> None:
        self._transient_retries[ledger_key] = (
            self._transient_retries.get(ledger_key, 0) + 1
        )
        self._transient_last[ledger_key] = time.monotonic()

    @staticmethod
    def _ledger_fingerprint(node: WorkNode) -> str:
        """Ledger identity of one dispatch: node inputs + media models.

        The graph fingerprint covers the node's own inputs (prompt,
        references); the configured media models are equally part of what
        a dispatch means. Without them, switching to a model with a
        larger reference budget after IMAGE_REFERENCE_BUDGET_EXCEEDED
        left the node deterministically locked forever (same inputs,
        same fingerprint, no unlock path).

        The value is embedded in the dispatch idempotency key, which is
        persisted as a single filesystem path segment.  Model names carry
        characters outside that alphabet, and joining them raw with "|"
        made every dispatch fail path validation before reaching a
        provider, so inputs and models are folded into one digest.
        """

        base = node.dispatch_fingerprint or node.node_id
        # This value is interpolated into the dispatch idempotency key, which
        # becomes a Task's caused_by_request_id and must stay inside the
        # [A-Za-z0-9._:-] segment alphabet. Model names are opaque and may
        # carry "/" or other unsafe characters, so digest them rather than
        # interpolating them.
        models = hashlib.sha256(
            "\x1f".join(
                (
                    get_image_model_name().strip(),
                    get_video_model_name().strip(),
                ),
            ).encode("utf-8"),
        ).hexdigest()[:16]
        return f"{base}-m{models}"

    @staticmethod
    def _dispatch_slot(fingerprint: str) -> str:
        """Safe-segment slot id for one ledger fingerprint.

        The ledger fingerprint embeds the configured media model names
        ("...|img:<model>|vid:<model>") and "|" is not a safe Runtime
        path segment character. Media executors persist the dispatch
        idempotency key verbatim as Task idempotency_key /
        caused_by_request_id, so the raw fingerprint must never leak
        into the key — every store write would reject it and no media
        node could dispatch. Hash it down to a stable hex slot instead
        (same shape work_graph fingerprints already use).
        """

        return hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:16]

    # -- lifecycle -----------------------------------------------------

    def wake(self, project_id: str) -> None:
        """Signal that durable state changed; start the loop if needed."""

        # A real post-stop Project change/new run explicitly re-arms the
        # scheduler. Cancelled dispatch finalizers do not call this method (see
        # _dispatch), so they cannot resurrect a stopped project by themselves.
        self._cancelled_projects.discard(project_id)
        event = self._wakes.setdefault(project_id, asyncio.Event())
        event.set()
        task = self._loops.get(project_id)
        if task is None or task.done():
            self._loops[project_id] = asyncio.create_task(
                self._project_loop(project_id),
            )

    async def shutdown(self) -> None:
        tasks = [
            *self._loops.values(),
            *(
                task
                for project_tasks in self._dispatch_tasks.values()
                for task in project_tasks
            ),
        ]
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except (
                asyncio.CancelledError,
                Exception,
            ):  # pylint: disable=broad-except
                pass
        self._loops.clear()
        self._dispatch_tasks.clear()
        for handle in self._sync_gate_rechecks.values():
            handle.cancel()
        self._sync_gate_rechecks.clear()
        self._cancelled_projects.clear()

    def cancel_project(self, project_id: str) -> None:
        """Synchronously signal every scheduler-owned task for one Project."""

        self._cancelled_projects.add(project_id)
        loop = self._loops.pop(project_id, None)
        if loop is not None:
            loop.cancel()
        for task in self._dispatch_tasks.pop(project_id, set()):
            task.cancel()
        self._inflight.pop(project_id, None)
        self._wakes.pop(project_id, None)
        self._graph_progress.pop(project_id, None)
        recheck = self._sync_gate_rechecks.pop(project_id, None)
        if recheck is not None:
            recheck.cancel()
        self._dispatched = {
            key for key in self._dispatched if key[0] != project_id
        }
        self._transient_retries = {
            key: value
            for key, value in self._transient_retries.items()
            if key[0] != project_id
        }
        self._transient_last = {
            key: value
            for key, value in self._transient_last.items()
            if key[0] != project_id
        }
        self._deterministic_failure_nodes = {
            key: value
            for key, value in self._deterministic_failure_nodes.items()
            if key[0] != project_id
        }

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
                if self._inflight.get(project_id):
                    continue
                # A node can reach READY without a wake arriving here: a gate
                # clears, or a commit's wake was already consumed by an
                # earlier tick. wake() is only called from agent turns and
                # media review, so returning now would strand that node for
                # good and leave a permanent hole in the rendered timeline.
                # Confirm the graph is really drained before giving up.
                try:
                    await self.tick(project_id)
                except Exception:  # pylint: disable=broad-except
                    logger.exception(
                        "work-graph drain check failed for %s",
                        project_id,
                    )
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

    def deterministic_failure_nodes_for_project(
        self,
        project_id: str,
    ) -> dict[str, str]:
        """Nodes whose dispatch failed with a deterministic error.

        These nodes are stuck READY but cannot be re-dispatched until the
        agent modifies the project.  The driver uses this to decide whether
        a model turn is needed.
        """
        return {
            node_id: error
            for (
                pid,
                node_id,
                _fingerprint,
            ), error in self._deterministic_failure_nodes.items()
            if pid == project_id
        }

    # pylint: disable=too-many-statements
    # pylint: disable-next=too-many-branches
    async def tick(self, project_id: str) -> WorkGraph | None:
        """Derive the graph once and dispatch what capacity allows."""

        # enabled() stats the user-config file; commit-triggered wakes run
        # on the event loop, so the check must not block it.
        if not await asyncio.to_thread(self.enabled):
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

        # Auto-rereview stale scene locks before deriving the graph.
        # Without this, compose stays GATED (scene locks expired) but
        # auto_review_stale_scenes only runs inside compose execution —
        # a chicken-and-egg deadlock that halts the unattended pipeline.
        snapshot, tasks = await self._rereview_stale_scenes(
            project_id,
            snapshot,
            tasks,
        )

        graph = derive_work_graph(snapshot.project, tasks=tasks)
        from services.run_review import admission
        from services.run_review.media_review import active_media_review_slots

        reviewing_slots = active_media_review_slots(project_id)
        slots_by_id = snapshot.project.assets.artifact_slots_by_id
        reviewing_owners = frozenset(
            slot.owner_ref
            for slot_id in reviewing_slots
            if (slot := slots_by_id.get(slot_id)) is not None
        )
        reports_root = (
            self.services.projects.project_root(project_id)
            / "runtime"
            / "run-review"
        )
        sync_fences = await asyncio.to_thread(
            admission.active_sync_fences,
            reports_root,
        )
        sync_review_pending = bool(sync_fences)
        if sync_review_pending:
            delay = admission.sync_fence_expiry_delay(sync_fences)
            if delay is not None:
                self._schedule_sync_gate_recheck(project_id, delay)
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
            await self._emit_graph_transitions(
                project_id,
                graph,
                snapshot.generation,
            )
            return graph
        running = sum(
            1 for node in graph.nodes if node.status.value == "running"
        )
        capacity = get_media_parallelism() - running - len(inflight)
        # Auto-saved frontend edits open a short grace window per element;
        # dispatching inside it would hand a possibly half-finished prompt
        # to a paid provider. Recheck once the earliest window expires.
        held_recheck: float | None = None
        for node in self._dispatch_candidates(project_id, graph, tasks):
            if capacity <= 0:
                break
            target_ref = node.target_ref or ""
            if target_ref.startswith("element:"):
                held_for = frontend_edit_hold.hold_remaining(
                    project_id,
                    target_ref[len("element:") :],
                )
                if held_for > 0:
                    held_recheck = (
                        held_for
                        if held_recheck is None
                        else min(held_recheck, held_for)
                    )
                    continue
            if _blocked_by_active_sync_review(
                node,
                sync_review_pending=sync_review_pending,
            ):
                logger.info(
                    "work-graph node %s waits for synchronous text review",
                    node.node_id,
                )
                continue
            if _blocked_by_active_media_review(
                node,
                reviewing_slots,
                reviewing_owners,
            ):
                logger.info(
                    "work-graph node %s waits for async review of %s",
                    node.node_id,
                    sorted(reviewing_slots),
                )
                continue
            fingerprint = self._ledger_fingerprint(node)
            ledger_key = (project_id, node.node_id, fingerprint)
            if ledger_key in self._dispatched or node.node_id in inflight:
                continue
            self._dispatched.add(ledger_key)
            inflight.add(node.node_id)
            capacity -= 1
            task = asyncio.create_task(
                self._dispatch(project_id, node, fingerprint),
            )
            project_tasks = self._dispatch_tasks.setdefault(project_id, set())
            project_tasks.add(task)

            def discard(
                done: asyncio.Task[None],
                *,
                owner: str = project_id,
            ) -> None:
                owned = self._dispatch_tasks.get(owner)
                if owned is not None:
                    owned.discard(done)
                    if not owned:
                        self._dispatch_tasks.pop(owner, None)
                if not done.cancelled():
                    done.exception()

            task.add_done_callback(discard)
        if held_recheck is not None:
            # Same one-shot wake mechanics as the sync-gate recheck timer.
            self._schedule_sync_gate_recheck(project_id, held_recheck)
        await self._emit_graph_transitions(
            project_id,
            graph,
            snapshot.generation,
        )
        return graph

    async def _rereview_stale_scenes(
        self,
        project_id: str,
        snapshot: Any,
        tasks: Sequence[Any],
    ) -> tuple[Any, Sequence[Any]]:
        """Re-review expired scene locks, returning the state to derive on.

        Fail-open: any failure (timeout included) keeps the state that was
        read before, so a review outage only leaves the graph stale.
        """

        try:
            from services.render_review.scene_review import (
                auto_review_stale_scenes,
                collect_scene_review_targets,
            )

            for timeline_id in snapshot.project.timelines.order:
                timeline = snapshot.project.timelines.items[timeline_id]
                stale, drafts = collect_scene_review_targets(timeline)
                if not (stale or drafts):
                    continue
                review_timeout = min(
                    max(len(stale) + len(drafts), 1)
                    * int(get_vlm_timeout_seconds()),
                    600,
                )
                try:
                    await asyncio.wait_for(
                        auto_review_stale_scenes(
                            self.services,
                            project_id=project_id,
                            timeline_ref=f"timeline:{timeline_id}",
                            timeline=timeline,
                        ),
                        timeout=review_timeout,
                    )
                except asyncio.TimeoutError:
                    logger.warning(
                        "pre-compose auto-rereview timed out after "
                        "%ds for %s; proceeding with stale graph",
                        review_timeout,
                        project_id,
                    )
                    break
                fresh_snapshot, fresh_tasks = await asyncio.gather(
                    asyncio.to_thread(
                        self.services.projects.read,
                        project_id,
                    ),
                    asyncio.to_thread(
                        self.executions.list_tasks,
                        project_id,
                    ),
                )
                return fresh_snapshot, fresh_tasks
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "pre-compose auto-rereview failed for %s; proceeding "
                "with stale graph",
                project_id,
                exc_info=True,
            )
        return snapshot, tasks

    def _schedule_sync_gate_recheck(
        self,
        project_id: str,
        delay: float,
    ) -> None:
        """Wake once when a crash/abandoned-review fence becomes fail-open."""

        loop = asyncio.get_running_loop()
        due = loop.time() + delay
        current = self._sync_gate_rechecks.get(project_id)
        if current is not None and not current.cancelled():
            if current.when() <= due:
                return
            current.cancel()

        def recheck() -> None:
            self._sync_gate_rechecks.pop(project_id, None)
            self.wake(project_id)

        self._sync_gate_rechecks[project_id] = loop.call_later(
            delay,
            recheck,
        )

    def _dispatch_candidates(
        self,
        project_id: str,
        graph: WorkGraph,
        tasks: Sequence[Any] = (),
    ) -> list[WorkNode]:
        """READY media nodes plus transiently-failed ones within budget.

        A node whose last task died of a provider timeout / 5xx / rate
        limit is FAILED on the graph but not deterministically so — the
        durable idempotency slot resumes the same task, so a bounded
        retry costs nothing extra. Deterministic failures (safety,
        validation) never re-enter.
        """

        candidates = list(graph.ready_media_nodes())
        rescuable = _quarantined_stale_targets(tasks)
        inflight = self._inflight.get(project_id, set())
        if rescuable:
            for node in candidates:
                # A dispatched node that re-derives READY while a
                # quarantined-stale sibling result exists means its task
                # left the graph without a durable outcome (the graph
                # never indexes QUARANTINED tasks). Reopen the ledger
                # within the transient budget; the durable slot rescues
                # the stored result instead of paying a second render.
                if node.target_ref not in rescuable:
                    continue
                fingerprint = self._ledger_fingerprint(node)
                ledger_key = (project_id, node.node_id, fingerprint)
                if (
                    ledger_key not in self._dispatched
                    or node.node_id in inflight
                ):
                    continue
                if not self._transient_budget_available(ledger_key):
                    continue
                self._note_transient_retry(ledger_key)
                self._dispatched.discard(ledger_key)
        recorded_keys = tuple(
            str(getattr(task, "idempotency_key", "") or "") for task in tasks
        )
        self._reopen_recordless_ready_nodes(
            project_id,
            candidates,
            inflight,
            recorded_keys,
        )
        for node in graph.nodes:
            if (
                node.status.value != "failed"
                or node.command is None
                or not node.error
            ):
                continue
            # Compose is a free local ffmpeg pass: any failure (cache
            # race, transient fs state) is worth a bounded, unpaid
            # re-render. Paid media nodes only re-enter on recognised
            # transient provider faults.
            if node.kind != "compose" and not _is_transient_dispatch_error(
                RuntimeError(node.error),
            ):
                continue
            fingerprint = self._ledger_fingerprint(node)
            ledger_key = (project_id, node.node_id, fingerprint)
            if not self._transient_budget_available(ledger_key):
                continue
            self._note_transient_retry(ledger_key)
            self._dispatched.discard(ledger_key)
            candidates.append(node)
        return candidates

    def _reopen_recordless_ready_nodes(
        self,
        project_id: str,
        candidates: Sequence[WorkNode],
        inflight: set[str],
        recorded_keys: Sequence[str],
    ) -> None:
        """Reopen READY nodes whose last dispatch died before admission.

        READY + ledger-marked + not inflight + no durable task record
        means the last dispatch died before admitting a task — a
        pre-spend rejection (execution gate, validation) or a transport
        fault ahead of admission. Real executors admit the task before
        any provider spend, so no record ⇒ nothing paid; a marked ledger
        would otherwise strand the node READY-but-undispatchable forever
        (field run 2026-08-12, project 27dc: a single-character scene
        stalled 25 minutes behind a project-wide lineup gate until a
        restart cleared the ledger). The bounded budget — not the ledger
        — stops a graph/executor mismatch from hot-looping.
        """

        for node in candidates:
            fingerprint = self._ledger_fingerprint(node)
            if (
                project_id,
                node.node_id,
                fingerprint,
            ) in self._deterministic_failure_nodes:
                continue
            ledger_key = (project_id, node.node_id, fingerprint)
            if ledger_key not in self._dispatched or node.node_id in inflight:
                continue
            prefix = f"dag-{node.node_id}-{self._dispatch_slot(fingerprint)}"
            node_prefix = f"dag-{node.node_id}-"
            if any(
                key.startswith(prefix)
                # A record minted under the old plaintext-model ledger format
                # cannot match today's digest prefix. Treating it as absent
                # would reopen a node that already owns a durable task and
                # pay for the same render twice across an upgrade.
                or (
                    key.startswith(node_prefix)
                    and dispatch_key_predates_digest_ledger(key)
                )
                for key in recorded_keys
            ):
                # A durable record exists (running / failed / quarantined):
                # the record — not this reopen path — owns its lifecycle.
                continue
            if not self._transient_budget_available(ledger_key):
                continue
            self._note_transient_retry(ledger_key)
            self._dispatched.discard(ledger_key)

    async def _notify(
        self,
        project_id: str,
        *,
        kind: RuntimeEventKind,
        request_id: str,
        text: str,
        node: WorkNode | None = None,
        error_code: str | None = None,
    ) -> None:
        """Report one event to the Agent; delivery failures never propagate."""

        if self._notifications is None:
            return
        payload: dict[str, Any] = {}
        if node is not None:
            payload = {
                "nodeId": node.node_id,
                "nodeKind": node.kind,
                "targetRef": node.target_ref,
            }
        if error_code is not None:
            payload["errorCode"] = error_code
        try:
            await self._notifications.notify(
                project_id,
                kind=kind,
                request_id=request_id,
                text=text,
                payload=payload,
            )
        except Exception:  # pylint: disable=broad-except
            logger.exception(
                "work-graph notification failed project=%s event=%s",
                project_id,
                request_id,
            )

    async def _emit_graph_transitions(
        self,
        project_id: str,
        graph: WorkGraph,
        generation: int,
    ) -> None:
        """Edge-triggered progress events from consecutive graph snapshots.

        Covers completions the dispatch return cannot observe (r2v/s2v write
        their terminal state from a background poller; the commit listener
        wakes this scheduler and the next tick lands here). The first
        observed snapshot only establishes the baseline — replaying the
        whole historical graph as events after a restart would be noise;
        the request-id idempotency layers absorb any duplicates.
        """

        if self._notifications is None:
            return
        previous = self._graph_progress.get(project_id)
        current: dict[str, tuple[str, str]] = {}
        for node in graph.nodes:
            current[node.node_id] = (
                node.status.value,
                self._ledger_fingerprint(node),
            )
        self._graph_progress[project_id] = current
        for node in graph.nodes:
            fingerprint = current[node.node_id][1]
            prior = previous.get(node.node_id) if previous else None
            prior_status = prior[0] if prior is not None else None
            # A durably FAILED node the scheduler will not retry on its own
            # (deterministic refusals, interrupted provider claims, spent
            # budgets) needs the Agent. Unlike DONE/GATED progress this
            # fires even on the baseline-establishing tick: after a restart
            # the failure edge happened while nobody watched, and the
            # request-id idempotency absorbs re-emission.
            if (
                node.status is WorkNodeStatus.FAILED
                and prior_status != WorkNodeStatus.FAILED.value
                and node.node_id not in self._inflight.get(project_id, set())
            ):
                await self._notify(
                    project_id,
                    kind=RuntimeEventKind.NODE_DETERMINISTIC_FAILURE,
                    request_id=f"nodefail-{node.node_id}-{fingerprint}",
                    text=(
                        f"媒体节点 {node.label}（{node.node_id}）处于失败状态，"
                        f"调度器不会自动重试：{node.error or '未知原因'}\n"
                        "请检查该节点的输入（prompt、参考、上游选择），修复后"
                        "调度器会以新的输入指纹自动重新生成；如输入本身无误，"
                        "可通过重新触发该环节生成新的任务。"
                    ),
                    node=node,
                )
        if previous is not None:
            for node in graph.nodes:
                fingerprint = current[node.node_id][1]
                prior = previous.get(node.node_id)
                prior_status = prior[0] if prior is not None else None
                if (
                    node.status is WorkNodeStatus.DONE
                    and prior is not None
                    and prior_status != WorkNodeStatus.DONE.value
                ):
                    if node.kind == "compose":
                        await self._notify(
                            project_id,
                            kind=RuntimeEventKind.COMPOSE_COMPLETED,
                            request_id=f"compose-{node.node_id}-{fingerprint}",
                            text=(
                                f"成片合成完成：{node.label}。请读取 Project "
                                "核对最终产物与用户目标，确认交付状态。"
                            ),
                            node=node,
                        )
                    else:
                        await self._notify(
                            project_id,
                            kind=RuntimeEventKind.NODE_SUCCEEDED,
                            request_id=(
                                f"node_succeeded-{node.node_id}-{fingerprint}"
                            ),
                            text=f"生成完成：{node.label}",
                            node=node,
                        )
                elif (
                    node.status is WorkNodeStatus.GATED
                    and prior_status != WorkNodeStatus.GATED.value
                ):
                    reasons = "；".join(node.missing[:3]) or "等待依赖"
                    await self._notify(
                        project_id,
                        kind=RuntimeEventKind.NODE_GATED,
                        request_id=f"node_gated-{node.node_id}-{fingerprint}",
                        text=f"待条件满足：{node.label}（{reasons}）",
                        node=node,
                    )
        # Only a real unfinished→done edge is a milestone. An all-DONE
        # baseline (previous is None: restart, or first wake of a long-
        # completed project) must stay silent — emitting there would replay
        # one NEXT_STEP message and a paid model run per historical project
        # on every deploy without the outbox history.
        had_unfinished = previous is not None and any(
            status != WorkNodeStatus.DONE.value
            for status, _fingerprint in previous.values()
        )
        if graph.nodes and not graph.unfinished() and had_unfinished:
            await self._notify(
                project_id,
                kind=RuntimeEventKind.GRAPH_ALL_DONE,
                request_id=f"graphdone-g{generation}",
                text=(
                    f"当前工作图全部 {len(graph.nodes)} 个节点已完成"
                    f"（generation {generation}）。请核对产物是否达成用户"
                    "目标并进行收尾确认；不要重复生成。"
                ),
            )

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
        await self._notify(
            project_id,
            kind=RuntimeEventKind.NODE_DISPATCH_STARTED,
            request_id=f"node_dispatch_started-{node.node_id}-{fingerprint}",
            text=f"已开始生成：{node.label}",
            node=node,
        )
        try:
            await self.dispatch_node(project_id, node, fingerprint)
            self._deterministic_failure_nodes.pop(
                (project_id, node.node_id, fingerprint),
                None,
            )
            # r2v/s2v dispatch only admits the provider task (the background
            # poller writes its terminal state; the tick graph diff reports
            # it); compose completion is the COMPOSE_COMPLETED milestone.
            if (
                node.command not in _R2V_COMMANDS
                and node.command not in _S2V_COMMANDS
                and node.command not in _COMPOSE_COMMANDS
            ):
                await self._notify(
                    project_id,
                    kind=RuntimeEventKind.NODE_SUCCEEDED,
                    request_id=f"node_succeeded-{node.node_id}-{fingerprint}",
                    text=f"生成完成：{node.label}",
                    node=node,
                )
        except Exception as exc:  # pylint: disable=broad-except
            ledger_key = (project_id, node.node_id, fingerprint)
            if _is_transient_dispatch_error(
                exc,
            ) and self._transient_budget_available(ledger_key):
                # Field run 2026-08-06: the first live fan-out lost five
                # storyboards to provider timeouts and the ledger locked
                # them as if the failure were deterministic. Transient
                # faults reopen the ledger (bounded) so the next tick
                # retries; the durable idempotency slot resumes the same
                # task instead of paying twice.
                self._note_transient_retry(ledger_key)
                self._dispatched.discard(ledger_key)
                logger.warning(
                    "work-graph dispatch transient failure project=%s "
                    "node=%s (retry %d/%d): %s",
                    project_id,
                    node.node_id,
                    self._transient_retries[ledger_key],
                    _TRANSIENT_RETRY_HARD_CAP,
                    exc,
                )
            else:
                # The durable task record (real executors admit the task
                # before any provider spend) carries the failure: the
                # graph surfaces it as FAILED and the marked ledger
                # prevents a paid retry until the node's inputs change.
                # Failures without a record re-enter through the bounded
                # no-record reopen in _dispatch_candidates.
                # Only block retries for specific structural errors that
                # require explicit agent intervention (e.g., reference
                # budget exceeded). Other validation errors may resolve
                # when project state changes.
                error_code = getattr(exc, "code", None)
                if error_code in _DETERMINISTIC_ERROR_CODES:
                    self._deterministic_failure_nodes[
                        (project_id, node.node_id, fingerprint)
                    ] = str(exc)[:200]
                    await self._notify(
                        project_id,
                        kind=RuntimeEventKind.NODE_DETERMINISTIC_FAILURE,
                        request_id=(
                            f"detfail-{node.node_id}-{fingerprint}"
                            f"-{error_code}"
                        ),
                        text=(
                            f"媒体节点 {node.label}（{node.node_id}）生成失败，"
                            f"且在输入修改前不会自动重试：{exc}\n"
                            "请修复对应 Project 字段（如参考图数量、prompt "
                            "或引用）；修复后调度器会自动重新生成。"
                        ),
                        node=node,
                        error_code=str(error_code),
                    )
                elif (
                    _is_transient_dispatch_error(exc)
                    and self._transient_retries.get(ledger_key, 0)
                    >= _TRANSIENT_RETRY_HARD_CAP
                ):
                    await self._notify(
                        project_id,
                        kind=RuntimeEventKind.NODE_TRANSIENT_CAP_EXHAUSTED,
                        request_id=(
                            f"transientcap-{node.node_id}-{fingerprint}"
                        ),
                        text=(
                            f"媒体节点 {node.label}（{node.node_id}）连续多次"
                            f"瞬态失败，自动重试预算已用尽：{exc}\n"
                            "请检查供应商状态，或调整该节点的输入后再继续。"
                        ),
                        node=node,
                    )
                logger.warning(
                    "work-graph dispatch failed project=%s node=%s: %s",
                    project_id,
                    node.node_id,
                    exc,
                )
        finally:
            self._inflight.get(project_id, set()).discard(node.node_id)
            if project_id not in self._cancelled_projects:
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
        raw_fingerprint = fingerprint or self._ledger_fingerprint(node)
        # The key becomes a durable record's caused_by_request_id, so the
        # fingerprint (which carries "|"-separated model names) is hashed
        # into a safe path segment first.
        idempotency_key = (
            f"dag-{node.node_id}-{self._dispatch_slot(raw_fingerprint)}"
        )
        if node.command in _COMPOSE_COMMANDS:
            # A failed master render is retried without content changes
            # (free local pass), so the retry generation must mint a new
            # idempotency slot — reusing the old one would just replay
            # the recorded failure.
            ledger_key = (
                project_id,
                node.node_id,
                raw_fingerprint,
            )
            generation = self._transient_retries.get(ledger_key, 0)
            if generation:
                idempotency_key = f"{idempotency_key}-r{generation}"
        if node.command in _S2V_COMMANDS:
            dispatch = self._s2v_dispatch or _default_s2v_dispatch
        elif node.command in _R2V_COMMANDS:
            dispatch = self._r2v_dispatch or _default_r2v_dispatch
        elif node.command in _COMPOSE_COMMANDS:
            dispatch = _default_compose_dispatch
        elif node.command in _SCRIPT_COMMANDS:
            dispatch = _default_script_dispatch
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


async def _default_script_dispatch(
    services: CreatorFileServices,
    *,
    project_id: str,
    command: str | None = None,
    target_ref: str,
    arguments: dict[str, Any],
    idempotency_key: str,
) -> Any:
    """Draft one timeline's script via the text model (free of media spend)."""

    # pylint: disable=import-outside-toplevel
    from services.media_files.script_execution import (
        execute_file_script_command,
    )

    # The script entry point has a single command and takes no command kwarg.
    del command
    return await execute_file_script_command(
        services,
        project_id=project_id,
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


async def _default_s2v_dispatch(
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
        execute_file_s2v_command,
        preflight_s2v_face_detect,
    )

    del command
    await preflight_s2v_face_detect(
        services,
        project_id=project_id,
        target_ref=target_ref,
        arguments=arguments,
    )
    return await execute_file_s2v_command(
        services,
        project_id=project_id,
        target_ref=target_ref,
        arguments=arguments,
        idempotency_key=idempotency_key,
    )


async def _default_compose_dispatch(
    services: CreatorFileServices,
    *,
    project_id: str,
    command: str,
    target_ref: str,
    arguments: dict[str, Any],
    idempotency_key: str,
) -> Any:
    """Master render for an unattended project (same path as the UI button).

    Text overlays that never received a motion design get the automatic
    design pass first — losing the styling must never lose the cut — then
    the deterministic local composition runs.
    """

    # pylint: disable=import-outside-toplevel
    from services.media_files.local_execution import (
        _stable_id,
        execute_file_local_media_command,
    )
    from services.runtime_files.errors import RecordNotFoundError
    from services.runtime_files.execution_models import TaskStatus

    # A master render is a free local pass, so a failed attempt must not
    # freeze the slot: probe the durable ledger and mint the next retry
    # generation past any terminal-failed task. Succeeded slots keep
    # replaying (true idempotency); the bound stops runaway loops.
    executions = ProjectExecutionStore(services.root)
    for generation in range(0, 9):
        candidate_key = (
            idempotency_key
            if generation == 0
            else f"{idempotency_key}-r{generation}"
        )
        task_id = _stable_id("task", project_id, candidate_key)
        try:
            existing = await asyncio.to_thread(
                executions.get_task,
                project_id,
                task_id,
            )
        except RecordNotFoundError:
            idempotency_key = candidate_key
            break
        if existing.status not in {
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
            TaskStatus.QUARANTINED,
        }:
            # RUNNING/QUEUED/SUCCEEDED reuse the slot: an in-progress or
            # finished compose is idempotent and the caller converges on
            # the same durable task instead of paying for a second render.
            idempotency_key = candidate_key
            break
    else:
        idempotency_key = f"{idempotency_key}-r8"

    try:
        snapshot = await asyncio.to_thread(services.projects.read, project_id)
        timeline_id = target_ref.removeprefix("timeline:")
        timeline = snapshot.project.timelines.items.get(timeline_id)
        from services.media_files.motion_design import (
            _is_frame_overlay,
            _is_keyword_overlay,
            _is_trusted_caption_motion,
        )

        needs_design = timeline is not None and any(
            element.enabled
            and (
                (
                    getattr(element.creation, "type", "") == "overlay"
                    and (getattr(element.creation, "text", "") or "").strip()
                    # Hand-written css snippets fail the compose-time
                    # safety check and ship the fallback bubble; only a
                    # pipeline-designed document counts as styled.
                    and not _is_trusted_caption_motion(
                        getattr(element.creation, "motion", None),
                    )
                )
                # Variety frames own their visual through the blueprint:
                # a hand-written thin border would ship black letterbox
                # bars, so the design pass upgrades it before rendering.
                or _is_frame_overlay(element)
                # Keyword overlays (text="" but prompt describes a
                # styled keyword display) also need VLM design.
                or (
                    _is_keyword_overlay(element)
                    and not _is_trusted_caption_motion(
                        getattr(element.creation, "motion", None),
                    )
                )
            )
            for element in timeline.elements_by_id.values()
        )
        if needs_design:
            from services.media_files.motion_design import (
                design_motion_overlays,
            )

            await design_motion_overlays(
                services,
                project_id=project_id,
                target_ref=target_ref,
                arguments={},
                # Suffix with the (possibly generation-suffixed) compose
                # key so a retried compose never replays a failed design
                # attempt against the same idempotency slot.
                idempotency_key=f"auto-motion-design:{idempotency_key}",
            )
    except Exception:  # pylint: disable=broad-except
        logger.warning(
            "auto design_motion_overlays failed for %s; compose falls back "
            "to static templates",
            target_ref,
            exc_info=True,
        )
    return await execute_file_local_media_command(
        services,
        project_id=project_id,
        command=CreatorCommandType(command),
        target_ref=target_ref,
        arguments=arguments,
        idempotency_key=idempotency_key,
    )


__all__ = ["WorkGraphScheduler"]
