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

    def add_task(
        self,
        title: str,
        description: str = "",
        created_by: str = "",
        assigned_to: Optional[str] = None,
        depends_on: Optional[List[str]] = None,
        priority: TaskPriority = "normal",
        required_skills: Optional[List[str]] = None,
    ) -> TeamTask:
        """Add a new task to the board."""
        task = TeamTask(
            title=title,
            description=description,
            created_by=created_by,
            assigned_to=assigned_to,
            depends_on=depends_on or [],
            priority=priority,
            required_skills=required_skills or [],
        )
        tasks = self._load()
        tasks.append(task)
        self._save(tasks)
        logger.info("Task added: %s (id=%s, by=%s)", title, task.id, created_by)
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
    ) -> Optional[TeamTask]:
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
                    has_skills = set(agent_skills or [])
                    needed = set(t.required_skills)
                    missing = needed - has_skills
                    if missing:
                        logger.warning(
                            "Cannot claim task %s: missing skills %s",
                            task_id, missing,
                        )
                        return None
                t.status = "claimed"
                t.claimed_by = agent_id
                t.claimed_at = time.time()
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
                        if elapsed > _CLAIM_ORPHAN_THRESHOLD_SEC:
                            logger.info(
                                "Task %s orphan reclaim: claimed %.0fs ago, resetting to pending",
                                task_id, elapsed,
                            )
                            t.status = "pending"
                            t.claimed_by = None
                            t.claimed_at = None
                            self._save(tasks)
                            return None   # tell caller to re-claim
                    logger.warning(
                        "Cannot start task %s: status=%s (need 'claimed')",
                        task_id, t.status,
                    )
                    return None
                t.status = "in_progress"
                t.started_at = time.time()
                self._save(tasks)
                logger.info("Task %s started by %s", task_id, agent_id)
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
                else:
                    if not _check_transition("submitted", "rework"):
                        return None
                    t.status = "rework"
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
                self._save(tasks)
                logger.info("Task %s completed by %s", task_id, agent_id)
                return t
        return None

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
