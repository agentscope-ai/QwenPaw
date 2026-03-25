# -*- coding: utf-8 -*-
"""Shared task board for Agent Teams.

File-based task management with locking to prevent race conditions
when multiple agents claim tasks concurrently.

State machine:
  pending → claimed → in_progress → submitted → completed
                          ↓                      ↓
                       rework ←←←←←←←←←←←←← submitted
  Any agent → blocked (special status, not in main flow)

Illegal transitions return None (no state change).
"""

import json
import logging
import time
import fcntl
from datetime import datetime
from pathlib import Path
from typing import List, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

TaskStatus = Literal["pending", "claimed", "in_progress", "submitted", "rework", "completed", "blocked"]
TaskPriority = Literal["urgent", "high", "normal", "low"]

# Valid state transitions: current_status → set of allowed next statuses
_VALID_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    "pending":    {"claimed", "blocked"},
    "claimed":    {"in_progress", "blocked"},      # can be blocked from claimed (e.g. dependency unsatisfied)
    "in_progress":{"submitted", "completed", "blocked"},
    "submitted":  {"rework", "completed"},          # review decides direction
    "rework":     {"submitted"},                   # rework must re-submit, cannot complete directly
    "completed":  {},                               # terminal
    "blocked":    {"pending", "claimed"},          # unblock can reset or reassign
}

# Orphan reclaim threshold: claimed tasks with no start for > N seconds
_CLAIM_ORPHAN_THRESHOLD_SEC = 1800   # 30 minutes

# Default in-progress timeout for alert (seconds), ~2 hours
_IN_PROGRESS_TIMEOUT_SEC = 7200


def _check_transition(current: TaskStatus, next_: TaskStatus) -> bool:
    """Return True if transition is allowed."""
    allowed = _VALID_TRANSITIONS.get(current, set())
    return next_ in allowed


class TeamTask(BaseModel):
    """A task on the shared board."""

    id: str = Field(default_factory=lambda: str(uuid4())[:8])
    title: str
    description: str = ""
    status: TaskStatus = "pending"
    priority: TaskPriority = "normal"
    assigned_to: Optional[str] = None  # None = public task, anyone can claim
    claimed_by: Optional[str] = None
    required_skills: List[str] = Field(default_factory=list)  # Skills needed to claim
    depends_on: List[str] = Field(default_factory=list)
    created_by: str = ""
    created_at: float = Field(default_factory=time.time)
    # State tracking: who and when
    claimed_at: Optional[float] = None
    started_at: Optional[float] = None
    submitted_at: Optional[float] = None
    completed_at: Optional[float] = None
    reviewed_by: Optional[str] = None
    review_note: Optional[str] = None
    reviewed_at: Optional[float] = None
    # C1: blocked_by — if set, this task auto-resumes when blocking task completes
    blocked_by: Optional[str] = None
    blocked_at: Optional[float] = None
    # C2: timeout_minutes — alert when in_progress exceeds this duration (0 = use default)
    timeout_minutes: int = 0
    # C3: history — full audit log of state transitions
    history: List[dict] = Field(default_factory=list)
    # C4: orphan_timeout_minutes — override global orphan reclaim threshold (0 = use global)
    orphan_timeout_minutes: int = 0
    # B3: subtasks — list of subtask specs to auto-create when task starts
    subtasks: List[dict] = Field(default_factory=list)
    # B3/B4: workflow_id — links tasks belonging to same workflow for progress summary
    workflow_id: str = ""
    # E1: context_dir — path to task-scoped context directory (set on task creation)
    context_dir: str = ""
    # Result
    result_summary: Optional[str] = None

    def is_blocked(self, board: "TaskBoard") -> bool:
        """Check if this task is blocked by unfinished dependencies."""
        if not self.depends_on:
            return False
        for dep_id in self.depends_on:
            dep = board.get_task(dep_id)
            if dep and dep.status != "completed":
                return True
        return False


class TaskBoard:
    """File-based shared task board with file locking.

    Storage: {team_dir}/tasks.json
    """

    def __init__(self, team_dir: Path):
        self._team_dir = team_dir
        self._team_dir.mkdir(parents=True, exist_ok=True)
        self._tasks_file = team_dir / "tasks.json"
        if not self._tasks_file.exists():
            self._save([])

    def _load(self) -> List[TeamTask]:
        """Load tasks from file with shared lock."""
        try:
            with open(self._tasks_file, "r", encoding="utf-8") as f:
                fcntl.flock(f, fcntl.LOCK_SH)
                try:
                    data = json.load(f)
                    return [TeamTask(**t) for t in data]
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)
        except (json.JSONDecodeError, FileNotFoundError):
            return []

    def _save(self, tasks: List[TeamTask]) -> None:
        """Save tasks to file with exclusive lock."""
        with open(self._tasks_file, "w", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                json.dump(
                    [t.model_dump() for t in tasks],
                    f, ensure_ascii=False, indent=2,
                )
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    @staticmethod
    def _append_history(task: "TeamTask", from_status: str, to_status: str, actor: str, note: str = "") -> None:
        """C3: Append a state transition record to task.history."""
        task.history.append({
            "from": from_status,
            "to": to_status,
            "actor": actor,
            "at": datetime.utcnow().isoformat() + "Z",
            "note": note,
        })

    def _archive_context(self, task: "TeamTask") -> None:
        """E2: Archive task context directory when task completes.

        Packs context_dir into a .tar.gz under team archive/, then removes original.
        Skips silently if context_dir is empty or doesn't exist.
        """
        import shutil
        if not task.context_dir:
            return
        context_path = Path(task.context_dir)
        if not context_path.exists() or not any(context_path.iterdir()):
            return
        archive_dir = self._team_dir / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_name = archive_dir / f"{task.id}-context"
        try:
            shutil.make_archive(str(archive_name), "gztar", root_dir=context_path.parent, base_dir=context_path.name)
            shutil.rmtree(context_path, ignore_errors=True)
            logger.info("E2: context archived for task %s → %s.tar.gz", task.id, archive_name)
        except Exception as e:
            logger.warning("E2: failed to archive context for task %s: %s", task.id, e)

    def add_task(
        self,
        title: str,
        description: str = "",
        created_by: str = "",
        assigned_to: Optional[str] = None,
        depends_on: Optional[List[str]] = None,
        priority: TaskPriority = "normal",
        required_skills: Optional[List[str]] = None,
        subtasks: Optional[List[dict]] = None,
        workflow_id: str = "",
        timeout_minutes: int = 0,
        orphan_timeout_minutes: int = 0,
    ) -> "TeamTask":
        """Add a new task to the board."""
        task = TeamTask(
            title=title,
            description=description,
            created_by=created_by,
            assigned_to=assigned_to,
            depends_on=depends_on or [],
            priority=priority,
            required_skills=required_skills or [],
            subtasks=subtasks or [],
            workflow_id=workflow_id,
            timeout_minutes=timeout_minutes,
            orphan_timeout_minutes=orphan_timeout_minutes,
        )
        # E1: create task-scoped context directory
        context_dir = self._team_dir / "contexts" / task.id
        context_dir.mkdir(parents=True, exist_ok=True)
        task.context_dir = str(context_dir)
        tasks = self._load()
        tasks.append(task)
        self._save(tasks)
        logger.info("Task added: %s (id=%s, by=%s, context=%s)", title, task.id, created_by, context_dir)
        return task

    def get_task(self, task_id: str) -> Optional[TeamTask]:
        """Get a task by ID."""
        for t in self._load():
            if t.id == task_id:
                return t
        return None

    def list_tasks(
        self,
        status: Optional[TaskStatus] = None,
        assigned_to: Optional[str] = None,
    ) -> List[TeamTask]:
        """List tasks, optionally filtered by status or assignee."""
        tasks = self._load()
        if status:
            tasks = [t for t in tasks if t.status == status]
        if assigned_to:
            tasks = [t for t in tasks if t.assigned_to == assigned_to or t.claimed_by == assigned_to]
        return tasks

    def claim_task(
        self,
        task_id: str,
        agent_id: str,
        agent_skills: Optional[List[str]] = None,
        workspace_dir: Optional[Path] = None,
    ) -> Optional["TeamTask"]:
        """Claim a pending task.

        Args:
            task_id: Task ID to claim
            agent_id: Agent attempting to claim
            agent_skills: Skills the agent has (for skill-gated tasks)

        Returns:
            The task if successful, None if cannot claim.
        """
        tasks = self._load()
        for t in tasks:
            if t.id == task_id:
                # State machine guard: only pending tasks can be claimed
                if not _check_transition(t.status, "claimed"):
                    logger.warning(
                        "Cannot claim task %s: status=%s (need 'pending')",
                        task_id, t.status,
                    )
                    return None
                if t.is_blocked(self):
                    logger.warning("Cannot claim task %s: blocked by deps", task_id)
                    return None
                # Check assignment: if assigned_to is set, only that agent can claim
                if t.assigned_to and t.assigned_to != agent_id:
                    logger.warning(
                        "Cannot claim task %s: assigned to %s, not %s",
                        task_id, t.assigned_to, agent_id,
                    )
                    return None
                # Check required skills
                if t.required_skills:
                    # D3: auto-detect skills from workspace if agent_skills not provided
                    if agent_skills is None and workspace_dir is not None:
                        try:
                            from copaw.agents.skills_manager import check_agent_has_skills
                            ok, missing_skills = check_agent_has_skills(workspace_dir, t.required_skills)
                            if not ok:
                                logger.warning(
                                    "Cannot claim task %s: missing skills %s (D3 auto-check)",
                                    task_id, missing_skills,
                                )
                                return None
                        except Exception as _e:
                            logger.debug("D3 skill check failed, falling back: %s", _e)
                            has_skills = set()
                            needed = set(t.required_skills)
                            if needed - has_skills:
                                return None
                    else:
                        has_skills = set(agent_skills or [])
                        needed = set(t.required_skills)
                        missing = needed - has_skills
                        if missing:
                            logger.warning(
                                "Cannot claim task %s: missing skills %s",
                                task_id, missing,
                            )
                            return None
                # B1: depends_on check — all dependencies must be completed
                if t.depends_on:
                    completed_ids = {x.id for x in tasks if x.status == "completed"}
                    unfinished = [dep for dep in t.depends_on if dep not in completed_ids]
                    if unfinished:
                        logger.warning(
                            "Cannot claim task %s: depends_on unfinished %s",
                            task_id, unfinished,
                        )
                        return None
                t.status = "claimed"
                t.claimed_by = agent_id
                t.claimed_at = time.time()
                self._append_history(t, "pending", "claimed", agent_id)  # C3
                self._save(tasks)
                logger.info("Task %s claimed by %s", task_id, agent_id)
                return t
        return None

    def start_task(self, task_id: str, agent_id: str) -> Optional[TeamTask]:
        """Move a claimed task to in_progress.

        Guard: only claimed tasks owned by agent_id can be started.
        If claimed but never started for > orphan threshold, owner can be reset.
        """
        tasks = self._load()
        for t in tasks:
            if t.id == task_id and t.claimed_by == agent_id:
                if not _check_transition(t.status, "in_progress"):
                    # Orphan guard: if claimed too long with no start, allow re-claim
                    if t.status == "claimed" and t.claimed_at:
                        elapsed = time.time() - t.claimed_at
                    # C4: orphan threshold — use task-level if set, else global
                    orphan_threshold = (
                        t.orphan_timeout_minutes * 60 if t.orphan_timeout_minutes > 0
                        else _CLAIM_ORPHAN_THRESHOLD_SEC
                    )
                    if elapsed > orphan_threshold:
                        logger.info(
                            "Task %s orphan reclaim: claimed %.0fs ago, resetting to pending",
                            task_id, elapsed,
                        )
                        prev = t.status
                        t.status = "pending"
                        t.claimed_by = None
                        t.claimed_at = None
                        self._append_history(t, prev, "pending", "system", "orphan reclaim")  # C3
                        self._save(tasks)
                        return None   # tell caller to re-claim
                    logger.warning(
                        "Cannot start task %s: status=%s (need 'claimed')",
                        task_id, t.status,
                    )
                    return None
                t.status = "in_progress"
                t.started_at = time.time()
                self._append_history(t, "claimed", "in_progress", agent_id)  # C3
                self._save(tasks)  # save parent state first before creating subtasks
                # B3: auto-create subtasks if defined
                subtask_created = []
                if t.subtasks:
                    for sub in t.subtasks:
                        sub_task = self.add_task(
                            title=sub.get("title", f"子任务 of {t.title}"),
                            description=sub.get("description", ""),
                            created_by=agent_id,
                            assigned_to=sub.get("assigned_to"),
                            depends_on=[t.id],
                            priority=sub.get("priority", t.priority),
                            required_skills=sub.get("required_skills", []),
                            workflow_id=t.workflow_id,
                        )
                        subtask_created.append(sub_task.id)
                        logger.info(
                            "B3: subtask %s auto-created for task %s, assigned_to=%s",
                            sub_task.id, t.id, sub.get("assigned_to"),
                        )
                logger.info("Task %s started by %s (subtasks=%s)", task_id, agent_id, subtask_created)
                return t
        return None

    def submit_task(
        self,
        task_id: str,
        agent_id: str,
        result_summary: str = "",
    ) -> Optional[TeamTask]:
        """Submit an in-progress/rework task for review."""
        tasks = self._load()
        for t in tasks:
            if t.id == task_id and t.claimed_by == agent_id:
                if not _check_transition(t.status, "submitted"):
                    logger.warning(
                        "Cannot submit task %s: status=%s (need 'in_progress' or 'rework')",
                        task_id, t.status,
                    )
                    return None
                t.status = "submitted"
                t.submitted_at = time.time()
                t.result_summary = result_summary or t.result_summary
                self._append_history(t, "in_progress", "submitted", agent_id)  # C3
                self._save(tasks)
                logger.info("Task %s submitted by %s", task_id, agent_id)
                return t
        return None

    def review_task(
        self,
        task_id: str,
        reviewer_id: str,
        approve: bool,
        review_note: str = "",
    ) -> Optional[TeamTask]:
        """Review a submitted task. approve=True => completed, else rework."""
        tasks = self._load()
        for t in tasks:
            if t.id == task_id:
                # State machine guard: only submitted tasks can be reviewed
                if t.status != "submitted":
                    logger.warning(
                        "Cannot review task %s: status=%s (need 'submitted')",
                        task_id, t.status,
                    )
                    return None
                t.reviewed_by = reviewer_id
                t.review_note = review_note
                t.reviewed_at = time.time()
                if approve:
                    if not _check_transition("submitted", "completed"):
                        return None
                    t.status = "completed"
                    t.completed_at = time.time()
                    self._append_history(t, "submitted", "completed", reviewer_id, review_note)  # C3
                    self._archive_context(t)  # E2
                else:
                    if not _check_transition("submitted", "rework"):
                        return None
                    t.status = "rework"
                    self._append_history(t, "submitted", "rework", reviewer_id, review_note)  # C3
                self._save(tasks)
                logger.info(
                    "Task %s reviewed by %s: %s",
                    task_id,
                    reviewer_id,
                    "approved" if approve else "rework",
                )
                return t
        return None

    def complete_task(
        self,
        task_id: str,
        agent_id: str,
        result_summary: str = "",
    ) -> Optional[TeamTask]:
        """Backward-compatible completion shortcut (no review).

        Only allowed from in_progress. From submitted must go through review.
        """
        tasks = self._load()
        for t in tasks:
            if t.id == task_id and t.claimed_by == agent_id:
                if not _check_transition(t.status, "completed"):
                    logger.warning(
                        "Cannot complete task %s directly: status=%s "
                        "(use review flow for submitted tasks)",
                        task_id, t.status,
                    )
                    return None
                t.status = "completed"
                t.completed_at = time.time()
                t.result_summary = result_summary or t.result_summary
                self._append_history(t, "in_progress", "completed", agent_id)  # C3
                self._archive_context(t)  # E2
                self._save(tasks)
                logger.info("Task %s completed by %s", task_id, agent_id)
                return t
        return None

    def check_blocked_tasks(self) -> list[TeamTask]:
        """C1: Auto-resume blocked tasks whose blocking task is now completed.

        Returns list of tasks that were auto-resumed to pending.
        """
        tasks = self._load()
        completed_ids = {t.id for t in tasks if t.status == "completed"}
        resumed = []
        changed = False
        for t in tasks:
            if t.status == "blocked" and t.blocked_by and t.blocked_by in completed_ids:
                prev = t.status
                t.status = "pending"
                t.blocked_by = None
                t.blocked_at = None
                self._append_history(t, prev, "pending", "system", "auto-resumed: blocking task completed")  # C3
                changed = True
                resumed.append(t)
                logger.info(
                    "Task %s auto-resumed: blocking task completed", t.id
                )
        if changed:
            self._save(tasks)
        return resumed

    def get_timed_out_tasks(self) -> list[TeamTask]:
        """C2: Return in_progress tasks that have exceeded their timeout.

        Uses task.timeout_minutes if set, else falls back to _IN_PROGRESS_TIMEOUT_SEC.
        """
        tasks = self._load()
        now = time.time()
        timed_out = []
        for t in tasks:
            if t.status == "in_progress" and t.started_at:
                threshold = (
                    t.timeout_minutes * 60 if t.timeout_minutes > 0
                    else _IN_PROGRESS_TIMEOUT_SEC
                )
                elapsed = now - t.started_at
                if elapsed > threshold:
                    timed_out.append(t)
                    logger.warning(
                        "Task %s timed out: in_progress for %.0f min (threshold=%d min)",
                        t.id, elapsed / 60, threshold // 60,
                    )
        return timed_out

    def get_summary(self) -> dict:
        """Get a summary of the task board."""
        tasks = self._load()
        by_status = {}
        for t in tasks:
            by_status.setdefault(t.status, []).append(t.title)
        return {
            "total": len(tasks),
            "by_status": by_status,
        }

    def get_workflow_summary(self) -> list[dict]:
        """B4: Return progress summary grouped by workflow_id.

        Returns list of dicts per workflow:
          workflow_id, total, completed, in_progress, blocked (titles), summary (str)
        Tasks without workflow_id are excluded.
        """
        tasks = self._load()
        workflows: dict[str, list] = {}
        for t in tasks:
            if t.workflow_id:
                workflows.setdefault(t.workflow_id, []).append(t)

        result = []
        for wf_id, wf_tasks in workflows.items():
            total = len(wf_tasks)
            completed = sum(1 for t in wf_tasks if t.status == "completed")
            in_progress = sum(1 for t in wf_tasks if t.status == "in_progress")
            blocked_titles = [t.title for t in wf_tasks if t.status == "blocked"]
            current = next((t.title for t in wf_tasks if t.status == "in_progress"), None)
            summary_parts = [f"{completed}/{total} 完成"]
            if current:
                summary_parts.append(f"进行中：{current}")
            if blocked_titles:
                summary_parts.append(f"阻塞：{'、'.join(blocked_titles)}")
            result.append({
                "workflow_id": wf_id,
                "total": total,
                "completed": completed,
                "in_progress": in_progress,
                "blocked": blocked_titles,
                "summary": "，".join(summary_parts),
            })
        return result
