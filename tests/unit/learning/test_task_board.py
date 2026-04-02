# -*- coding: utf-8 -*-
"""Tests for TaskBoardManager."""
import tempfile
from pathlib import Path

from copaw.app.learning.task_board import TaskBoardManager


class TestTaskBoardMarkdown:
    def test_add_and_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            board = TaskBoardManager(Path(tmpdir), fmt="markdown")
            task = board.add_task(
                "Test task",
                tags=("coding",),
                agent="default",
            )
            assert task.status == "pending"
            assert task.description == "Test task"
            assert "coding" in task.tags

            pending = board.list_pending()
            assert len(pending) == 1
            assert pending[0].description == "Test task"

    def test_mark_in_progress(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            board = TaskBoardManager(Path(tmpdir), fmt="markdown")
            task = board.add_task("Do something")
            result = board.mark_in_progress(task.id)
            assert result is not None
            assert result.status == "in_progress"
            assert result.started_at is not None

    def test_mark_done(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            board = TaskBoardManager(Path(tmpdir), fmt="markdown")
            task = board.add_task("Do something")
            board.mark_in_progress(task.id)
            result = board.mark_done(task.id, "all good")
            assert result is not None
            assert result.status == "done"
            assert result.completed_at is not None

    def test_mark_failed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            board = TaskBoardManager(Path(tmpdir), fmt="markdown")
            task = board.add_task("Risky task")
            board.mark_in_progress(task.id)
            result = board.mark_failed(task.id, "timeout")
            assert result is not None
            assert result.status == "failed"

    def test_empty_board(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            board = TaskBoardManager(Path(tmpdir), fmt="markdown")
            assert not board.list_all()
            assert not board.list_pending()

    def test_parse_existing_md(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            md_path = Path(tmpdir) / "TASKS.md"
            md_path.write_text(
                "# Task Board\n\n"
                "## Pending\n\n"
                "- [ ] Buy milk #shopping @default\n"
                "- [ ] Write tests #coding\n\n"
                "## Done\n\n"
                "- [x] Deploy app #devops (done: 2026-04-01)\n",
                encoding="utf-8",
            )
            board = TaskBoardManager(Path(tmpdir), fmt="markdown")
            all_tasks = board.list_all()
            assert len(all_tasks) == 3
            pending = board.list_pending()
            assert len(pending) == 2


class TestTaskBoardJSON:
    def test_add_and_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            board = TaskBoardManager(Path(tmpdir), fmt="json")
            task = board.add_task(
                "JSON task",
                tags=("data",),
            )
            assert task.status == "pending"

            pending = board.list_pending()
            assert len(pending) == 1
            assert pending[0].description == "JSON task"

    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            board = TaskBoardManager(Path(tmpdir), fmt="json")
            board.add_task("Task A", tags=("a",), agent="agent1")
            board.add_task("Task B", tags=("b",))

            # Re-read
            board2 = TaskBoardManager(Path(tmpdir), fmt="json")
            tasks = board2.list_all()
            assert len(tasks) == 2
            assert tasks[0].agent == "agent1"
            assert tasks[1].agent is None
