# -*- coding: utf-8 -*-
"""Tests for workflow schema definitions."""

import pytest
from pydantic import ValidationError

from src.copaw.app.orchestration.schema import (
    StepStatus,
    WorkflowDefinition,
    WorkflowExecutionRequest,
    WorkflowExecutionResult,
    WorkflowExecutionStatus,
    WorkflowStep,
    StepResult,
)


class TestWorkflowStep:
    """Tests for WorkflowStep model."""

    def test_valid_step(self):
        """Test creating a valid workflow step."""
        step = WorkflowStep(
            id="step1",
            agent="researcher",
            prompt="Research about {{topic}}",
        )
        assert step.id == "step1"
        assert step.agent == "researcher"
        assert step.prompt == "Research about {{topic}}"
        assert step.condition is None
        assert step.timeout is None
        assert step.retries == 0

    def test_step_with_all_fields(self):
        """Test creating a step with all optional fields."""
        step = WorkflowStep(
            id="step1",
            agent="researcher",
            prompt="Research",
            condition="{{should_run}} == 'true'",
            timeout=60,
            retries=3,
        )
        assert step.condition == "{{should_run}} == 'true'"
        assert step.timeout == 60
        assert step.retries == 3

    def test_missing_required_fields(self):
        """Test that missing required fields raise validation error."""
        with pytest.raises(ValidationError):
            WorkflowStep(id="step1")  # Missing agent and prompt

        with pytest.raises(ValidationError):
            WorkflowStep(agent="researcher")  # Missing id and prompt


class TestWorkflowDefinition:
    """Tests for WorkflowDefinition model."""

    def test_valid_workflow(self):
        """Test creating a valid workflow definition."""
        workflow = WorkflowDefinition(
            name="test-workflow",
            steps=[
                WorkflowStep(id="s1", agent="a1", prompt="p1"),
                WorkflowStep(id="s2", agent="a2", prompt="p2"),
            ],
        )
        assert workflow.name == "test-workflow"
        assert len(workflow.steps) == 2
        assert workflow.version == "1.0"  # Default
        assert workflow.description is None
        assert workflow.variables == {}

    def test_workflow_with_variables(self):
        """Test workflow with default variables."""
        workflow = WorkflowDefinition(
            name="test",
            steps=[],
            variables={"key": "value", "number": 42},
        )
        assert workflow.variables["key"] == "value"
        assert workflow.variables["number"] == 42


class TestStepResult:
    """Tests for StepResult model."""

    def test_completed_result(self):
        """Test creating a completed step result."""
        result = StepResult(
            step_id="step1",
            status=StepStatus.COMPLETED,
            agent="researcher",
            prompt="Research AI",
            result="AI is artificial intelligence...",
        )
        assert result.status == StepStatus.COMPLETED
        assert result.error is None

    def test_failed_result(self):
        """Test creating a failed step result."""
        result = StepResult(
            step_id="step1",
            status=StepStatus.FAILED,
            agent="researcher",
            prompt="Research",
            error="Agent not found",
        )
        assert result.status == StepStatus.FAILED
        assert result.error == "Agent not found"

    def test_all_statuses(self):
        """Test all possible step statuses."""
        statuses = [
            StepStatus.PENDING,
            StepStatus.RUNNING,
            StepStatus.COMPLETED,
            StepStatus.FAILED,
            StepStatus.SKIPPED,
        ]
        for status in statuses:
            result = StepResult(
                step_id="test",
                status=status,
                agent="a",
                prompt="p",
            )
            assert result.status == status


class TestWorkflowExecutionRequest:
    """Tests for WorkflowExecutionRequest model."""

    def test_empty_request(self):
        """Test creating an empty execution request."""
        request = WorkflowExecutionRequest()
        assert request.variables == {}
        assert request.session_id is None

    def test_request_with_variables(self):
        """Test execution request with variables."""
        request = WorkflowExecutionRequest(
            variables={"topic": "AI", "tone": "professional"},
            session_id="session-123",
        )
        assert request.variables["topic"] == "AI"
        assert request.session_id == "session-123"


class TestWorkflowExecutionResult:
    """Tests for WorkflowExecutionResult model."""

    def test_successful_result(self):
        """Test creating a successful execution result."""
        result = WorkflowExecutionResult(
            workflow_name="test-workflow",
            status=WorkflowExecutionStatus.COMPLETED,
            steps=[
                StepResult(
                    step_id="s1",
                    status=StepStatus.COMPLETED,
                    agent="a1",
                    prompt="p1",
                    result="r1",
                ),
            ],
            final_result="Final output",
        )
        assert result.status == WorkflowExecutionStatus.COMPLETED
        assert result.error is None
        assert result.final_result == "Final output"

    def test_failed_result(self):
        """Test creating a failed execution result."""
        result = WorkflowExecutionResult(
            workflow_name="test-workflow",
            status=WorkflowExecutionStatus.FAILED,
            error="Step 2 failed",
        )
        assert result.status == WorkflowExecutionStatus.FAILED
        assert result.error == "Step 2 failed"

    def test_all_execution_statuses(self):
        """Test all possible execution statuses."""
        statuses = [
            WorkflowExecutionStatus.PENDING,
            WorkflowExecutionStatus.RUNNING,
            WorkflowExecutionStatus.COMPLETED,
            WorkflowExecutionStatus.FAILED,
            WorkflowExecutionStatus.CANCELLED,
        ]
        for status in statuses:
            result = WorkflowExecutionResult(
                workflow_name="test",
                status=status,
            )
            assert result.status == status
