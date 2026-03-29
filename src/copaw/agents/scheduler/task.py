# -*- coding: utf-8 -*-
"""Task Models for Scheduler.

Defines Task and PausedTask models for tracking agent work
and supporting interruption/resumption.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional
import uuid

from agentscope.message import Msg


@dataclass
class Task:
    """Represents a task to be processed by an agent.

    Attributes:
        message: The message to process.
        task_id: Unique identifier for the task.
        priority: Task priority level.
        created_at: Task creation timestamp.
        context: Additional context for the task.
        progress: Task progress tracking (0-100).
        metadata: Additional metadata.
    """

    message: Msg
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    priority: int = 2  # NORMAL by default
    created_at: datetime = field(default_factory=datetime.now)
    context: Dict[str, Any] = field(default_factory=dict)
    progress: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate task after initialization."""
        if not isinstance(self.message, Msg):
            raise TypeError(f"Expected Msg, got {type(self.message)}")
        if not 0 <= self.progress <= 100:
            raise ValueError(f"Progress must be 0-100, got {self.progress}")

    def update_progress(self, progress: float) -> None:
        """Update task progress.

        Args:
            progress: New progress value (0-100).
        """
        if not 0 <= progress <= 100:
            raise ValueError(f"Progress must be 0-100, got {progress}")
        self.progress = progress

    def to_dict(self) -> Dict[str, Any]:
        """Convert task to dictionary for serialization.

        Returns:
            Dictionary representation of the task.
        """
        return {
            "task_id": self.task_id,
            "priority": self.priority,
            "created_at": self.created_at.isoformat(),
            "context": self.context,
            "progress": self.progress,
            "metadata": self.metadata,
            "message_type": type(self.message).__name__,
        }


@dataclass
class PausedTask:
    """Represents a task that was paused for interruption.

    Stores the state needed to resume a task after
    a higher-priority task completes.

    Attributes:
        original_task: The task that was paused.
        paused_at: When the task was paused.
        progress: Progress at pause time.
        saved_context: Context to restore when resuming.
        can_resume: Whether the task can be safely resumed.
        pause_reason: Reason for pausing.
    """

    original_task: Task
    paused_at: datetime = field(default_factory=datetime.now)
    progress: float = 0.0
    saved_context: Dict[str, Any] = field(default_factory=dict)
    can_resume: bool = True
    pause_reason: str = "interrupted"

    def __post_init__(self) -> None:
        """Initialize from original task if needed."""
        if self.progress == 0.0 and self.original_task:
            self.progress = self.original_task.progress
        if not self.saved_context and self.original_task:
            self.saved_context = dict(self.original_task.context)

    def mark_unresumable(self, reason: str) -> None:
        """Mark the task as not resumable.

        Args:
            reason: Why the task cannot be resumed.
        """
        self.can_resume = False
        self.pause_reason = reason

    def create_resume_task(self) -> Task:
        """Create a task for resuming the paused work.

        Returns:
            New Task configured to resume the paused work.

        Raises:
            ValueError: If the task cannot be resumed.
        """
        if not self.can_resume:
            raise ValueError(
                f"Cannot resume task: {self.pause_reason}"
            )
        
        return Task(
            message=self.original_task.message,
            task_id=f"{self.original_task.task_id}-resume",
            priority=self.original_task.priority,
            context=self.saved_context,
            progress=self.progress,
            metadata={
                **self.original_task.metadata,
                "resumed_from": self.original_task.task_id,
                "paused_at": self.paused_at.isoformat(),
            },
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization.

        Returns:
            Dictionary representation.
        """
        return {
            "original_task_id": self.original_task.task_id,
            "paused_at": self.paused_at.isoformat(),
            "progress": self.progress,
            "can_resume": self.can_resume,
            "pause_reason": self.pause_reason,
        }
