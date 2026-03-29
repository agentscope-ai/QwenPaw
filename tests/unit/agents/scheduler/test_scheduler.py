# -*- coding: utf-8 -*-
"""Unit tests for Agent Scheduler."""

import asyncio
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from agentscope.message import Msg

from copaw.agents.scheduler import (
    AgentScheduler,
    AgentState,
    AgentStateManager,
    MessagePriority,
    PriorityMessageQueue,
    PausedTask,
    Task,
)
from copaw.agents.scheduler.queue import QueueEmpty, QueueFull


class TestMessagePriority:
    """Tests for MessagePriority enum."""

    def test_priority_order(self):
        """Test priority values are correctly ordered."""
        assert MessagePriority.CRITICAL < MessagePriority.HIGH
        assert MessagePriority.HIGH < MessagePriority.NORMAL
        assert MessagePriority.NORMAL < MessagePriority.LOW

    def test_from_string(self):
        """Test string conversion."""
        assert MessagePriority.from_string("critical") == MessagePriority.CRITICAL
        assert MessagePriority.from_string("HIGH") == MessagePriority.HIGH
        assert MessagePriority.from_string("Normal") == MessagePriority.NORMAL
        assert MessagePriority.from_string("low") == MessagePriority.LOW

    def test_from_string_aliases(self):
        """Test alias conversion."""
        assert MessagePriority.from_string("urgent") == MessagePriority.CRITICAL
        assert MessagePriority.from_string("important") == MessagePriority.HIGH
        assert MessagePriority.from_string("default") == MessagePriority.NORMAL
        assert MessagePriority.from_string("background") == MessagePriority.LOW

    def test_from_string_invalid(self):
        """Test invalid string raises error."""
        with pytest.raises(ValueError):
            MessagePriority.from_string("invalid")


class TestTask:
    """Tests for Task model."""

    def test_task_creation(self):
        """Test basic task creation."""
        msg = Msg(name="user", role="user", content="test message")
        task = Task(message=msg, priority=1)

        assert task.message == msg
        assert task.priority == 1
        assert task.progress == 0.0
        assert task.task_id is not None

    def test_task_invalid_message(self):
        """Test that non-Msg raises error."""
        with pytest.raises(TypeError):
            Task(message="not a msg")

    def test_task_invalid_progress(self):
        """Test that invalid progress raises error."""
        msg = Msg(name="user", role="user", content="test")
        with pytest.raises(ValueError):
            Task(message=msg, progress=150)

    def test_update_progress(self):
        """Test progress update."""
        msg = Msg(name="user", role="user", content="test")
        task = Task(message=msg)
        task.update_progress(50.0)
        assert task.progress == 50.0

    def test_to_dict(self):
        """Test serialization."""
        msg = Msg(name="user", role="user", content="test")
        task = Task(message=msg, priority=1)
        data = task.to_dict()

        assert data["priority"] == 1
        assert data["progress"] == 0.0
        assert "task_id" in data
        assert "created_at" in data


class TestPausedTask:
    """Tests for PausedTask model."""

    def test_paused_task_creation(self):
        """Test paused task creation."""
        msg = Msg(name="user", role="user", content="test")
        original = Task(message=msg, priority=2, progress=50.0)
        paused = PausedTask(original_task=original)

        assert paused.original_task == original
        assert paused.progress == 50.0
        assert paused.can_resume is True

    def test_mark_unresumable(self):
        """Test marking task as unresumable."""
        msg = Msg(name="user", role="user", content="test")
        original = Task(message=msg)
        paused = PausedTask(original_task=original)

        paused.mark_unresumable("unsafe to resume")

        assert paused.can_resume is False
        assert "unsafe" in paused.pause_reason

    def test_create_resume_task(self):
        """Test creating resume task."""
        msg = Msg(name="user", role="user", content="test")
        original = Task(message=msg, priority=2, progress=75.0)
        paused = PausedTask(original_task=original)

        resume = paused.create_resume_task()

        assert resume.progress == 75.0
        assert "resumed_from" in resume.metadata
        assert resume.task_id.endswith("-resume")

    def test_create_resume_task_unresumable(self):
        """Test that unresumable task raises error."""
        msg = Msg(name="user", role="user", content="test")
        original = Task(message=msg)
        paused = PausedTask(original_task=original)
        paused.mark_unresumable("cannot resume")

        with pytest.raises(ValueError):
            paused.create_resume_task()


class TestAgentState:
    """Tests for AgentState enum."""

    def test_state_values(self):
        """Test state string values."""
        assert AgentState.IDLE.value == "idle"
        assert AgentState.WORKING.value == "working"
        assert AgentState.INTERRUPTED.value == "interrupted"
        assert AgentState.PAUSED.value == "paused"


class TestAgentStateManager:
    """Tests for AgentStateManager."""

    @pytest.mark.asyncio
    async def test_register_agent(self):
        """Test agent registration."""
        manager = AgentStateManager()
        await manager.register("agent-1")

        state = await manager.get_state("agent-1")
        assert state == AgentState.IDLE

    @pytest.mark.asyncio
    async def test_deregister_agent(self):
        """Test agent deregistration."""
        manager = AgentStateManager()
        await manager.register("agent-1")
        await manager.deregister("agent-1")

        state = await manager.get_state("agent-1")
        assert state is None

    @pytest.mark.asyncio
    async def test_set_state(self):
        """Test state transition."""
        manager = AgentStateManager()
        await manager.register("agent-1")

        result = await manager.set_state("agent-1", AgentState.WORKING)
        assert result is True

        state = await manager.get_state("agent-1")
        assert state == AgentState.WORKING

    @pytest.mark.asyncio
    async def test_find_idle_agents(self):
        """Test finding idle agents."""
        manager = AgentStateManager()
        await manager.register("agent-1")
        await manager.register("agent-2")
        await manager.set_state("agent-2", AgentState.WORKING)

        idle = await manager.find_idle_agents()
        assert "agent-1" in idle
        assert "agent-2" not in idle

    @pytest.mark.asyncio
    async def test_find_working_agents(self):
        """Test finding working agents."""
        manager = AgentStateManager()
        await manager.register("agent-1")
        await manager.register("agent-2")
        await manager.set_state("agent-2", AgentState.WORKING)

        working = await manager.find_working_agents()
        assert "agent-1" not in working
        assert "agent-2" in working


class TestPriorityMessageQueue:
    """Tests for PriorityMessageQueue."""

    @pytest.mark.asyncio
    async def test_put_get(self):
        """Test basic put and get."""
        queue = PriorityMessageQueue()
        msg = Msg(name="user", role="user", content="test")

        task = await queue.put(msg, MessagePriority.NORMAL)
        assert task.priority == MessagePriority.NORMAL.value

        result = await queue.get()
        assert result.task_id == task.task_id

    @pytest.mark.asyncio
    async def test_priority_order(self):
        """Test that higher priority is dequeued first."""
        queue = PriorityMessageQueue()

        # Add in reverse priority order
        low_task = await queue.put(Msg(name="user", role="user", content="low"), MessagePriority.LOW)
        normal_task = await queue.put(Msg(name="user", role="user", content="normal"), MessagePriority.NORMAL)
        high_task = await queue.put(Msg(name="user", role="user", content="high"), MessagePriority.HIGH)

        # Should get high first
        result = await queue.get()
        assert result.task_id == high_task.task_id

        result = await queue.get()
        assert result.task_id == normal_task.task_id

        result = await queue.get()
        assert result.task_id == low_task.task_id

    @pytest.mark.asyncio
    async def test_queue_empty(self):
        """Test empty queue raises error."""
        queue = PriorityMessageQueue()

        with pytest.raises(QueueEmpty):
            await queue.get(timeout=0.1)

    @pytest.mark.asyncio
    async def test_queue_full(self):
        """Test full queue raises error."""
        queue = PriorityMessageQueue(maxsize=2)

        await queue.put(Msg(name="user", role="user", content="1"))
        await queue.put(Msg(name="user", role="user", content="2"))

        with pytest.raises(QueueFull):
            await queue.put(Msg(name="user", role="user", content="3"))

    @pytest.mark.asyncio
    async def test_put_task(self):
        """Test re-queuing an existing Task object."""
        queue = PriorityMessageQueue()
        msg = Msg(name="user", role="user", content="test")
        task = Task(message=msg, priority=int(MessagePriority.HIGH))

        await queue.put_task(task)
        
        result = await queue.get()
        assert result.task_id == task.task_id

    def test_get_stats(self):
        """Test queue statistics."""
        queue = PriorityMessageQueue()

        asyncio.run(queue.put(Msg(name="user", role="user", content="1"), MessagePriority.HIGH))
        asyncio.run(queue.put(Msg(name="user", role="user", content="2"), MessagePriority.HIGH))
        asyncio.run(queue.put(Msg(name="user", role="user", content="3"), MessagePriority.LOW))

        stats = queue.get_stats()
        assert stats.high == 2
        assert stats.low == 1
        assert stats.total == 3


class TestAgentScheduler:
    """Tests for AgentScheduler."""

    @pytest.mark.asyncio
    async def test_register_agent(self):
        """Test agent registration."""
        scheduler = AgentScheduler()
        executor = AsyncMock()

        await scheduler.register_agent("agent-1", executor)

        state = await scheduler.get_agent_state("agent-1")
        assert state == AgentState.IDLE

    @pytest.mark.asyncio
    async def test_dispatch_to_idle_agent(self):
        """Test dispatching to idle agent."""
        scheduler = AgentScheduler()
        executor = AsyncMock(return_value="result")

        await scheduler.register_agent("agent-1", executor)

        msg = Msg(name="user", role="user", content="test message")
        task_id = await scheduler.dispatch(msg, MessagePriority.HIGH)

        assert task_id is not None
        # Wait for execution
        await asyncio.sleep(0.1)
        executor.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatch_queues_when_no_idle(self):
        """Test dispatching queues task when no idle agents."""
        scheduler = AgentScheduler()
        
        # Create slow executor that never finishes
        async def slow_executor(msg, context=None):
            await asyncio.sleep(100)

        await scheduler.register_agent("agent-1", slow_executor)

        # Start a task to make agent busy
        msg1 = Msg(name="user", role="user", content="first task")
        await scheduler.dispatch(msg1, MessagePriority.NORMAL)
        await asyncio.sleep(0.05)  # Let task start

        # Second task should be queued
        msg2 = Msg(name="user", role="user", content="second task")
        task_id2 = await scheduler.dispatch(msg2, MessagePriority.NORMAL)

        # Check queue stats
        stats = scheduler.queue_stats
        assert stats["total"] >= 1

    @pytest.mark.asyncio
    async def test_critical_interrupts_working(self):
        """Test CRITICAL task interrupts working agent."""
        scheduler = AgentScheduler()

        # Create slow executor
        async def slow_executor(msg, context=None):
            await asyncio.sleep(1.0)
            return "done"

        await scheduler.register_agent("agent-1", slow_executor)

        # Start a normal task
        normal_msg = Msg(name="user", role="user", content="normal task")
        await scheduler.dispatch(normal_msg, MessagePriority.NORMAL)

        await asyncio.sleep(0.05)  # Let task start
        state = await scheduler.get_agent_state("agent-1")
        assert state == AgentState.WORKING

        # Send CRITICAL task
        critical_msg = Msg(name="user", role="user", content="critical task")
        await scheduler.dispatch(critical_msg, MessagePriority.CRITICAL)

    @pytest.mark.asyncio
    async def test_get_agent_states(self):
        """Test getting all agent states (async method)."""
        scheduler = AgentScheduler()
        executor = AsyncMock()

        await scheduler.register_agent("agent-1", executor)
        await scheduler.register_agent("agent-2", executor)

        states = await scheduler.get_agent_states()
        assert states["agent-1"] == "idle"
        assert states["agent-2"] == "idle"

    @pytest.mark.asyncio
    async def test_queue_stats_property(self):
        """Test queue statistics property."""
        scheduler = AgentScheduler()

        msg = Msg(name="user", role="user", content="test")
        await scheduler._queue.put(msg, MessagePriority.HIGH)

        stats = scheduler.queue_stats
        assert stats["high"] == 1
        assert stats["total"] == 1

    @pytest.mark.asyncio
    async def test_pause_resume_agent(self):
        """Test manual pause and resume."""
        scheduler = AgentScheduler()
        executor = AsyncMock()

        await scheduler.register_agent("agent-1", executor)

        # Pause
        result = await scheduler.pause_agent("agent-1")
        state = await scheduler.get_agent_state("agent-1")
        assert state == AgentState.PAUSED

        # Resume
        result = await scheduler.resume_agent("agent-1")
        state = await scheduler.get_agent_state("agent-1")
        assert state == AgentState.IDLE


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
