# -*- coding: utf-8 -*-
"""Tests for WorkflowEngine and orchestration logic."""
# pylint: disable=protected-access,redefined-outer-name

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.copaw.app.orchestration.engine import WorkflowEngine
from src.copaw.app.orchestration.schema import (
    StepStatus,
    WorkflowDefinition,
    WorkflowExecutionStatus,
    WorkflowStep,
)


@pytest.fixture
def temp_workflows_dir():
    """Create a temporary directory for workflow files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def workflow_engine(temp_workflows_dir):
    """Create a workflow engine with a temporary workflows directory."""
    return WorkflowEngine(temp_workflows_dir)


@pytest.fixture
def sample_workflow_yaml():
    """Sample workflow YAML content."""
    return """
name: test-workflow
description: "A test workflow"
version: "1.0"
variables:
  default_var: "default_value"
steps:
  - id: step1
    agent: agent1
    prompt: "Hello {{name}}"
  - id: step2
    agent: agent2
    prompt: "Process: {{step1.result}}"
"""


@pytest.fixture
def sample_workflow_definition():
    """Sample workflow definition object."""
    return WorkflowDefinition(
        name="test-workflow",
        description="A test workflow",
        version="1.0",
        variables={"default_var": "default_value"},
        steps=[
            WorkflowStep(
                id="step1",
                agent="agent1",
                prompt="Hello {{name}}",
            ),
            WorkflowStep(
                id="step2",
                agent="agent2",
                prompt="Process: {{step1.result}}",
            ),
        ],
    )


class TestWorkflowEngineInit:
    """Tests for WorkflowEngine initialization."""

    def test_init_with_path(self, temp_workflows_dir):
        """Test engine initialization with a path."""
        engine = WorkflowEngine(temp_workflows_dir)
        assert engine.workflows_dir == temp_workflows_dir
        assert engine.multi_agent_manager is None

    def test_init_with_multi_agent_manager(self, temp_workflows_dir):
        """Test engine initialization with multi-agent manager."""
        mock_manager = MagicMock()
        engine = WorkflowEngine(temp_workflows_dir, mock_manager)
        assert engine.multi_agent_manager == mock_manager


class TestLoadWorkflow:
    """Tests for loading workflow definitions."""

    def test_load_valid_workflow(
        self,
        workflow_engine,
        temp_workflows_dir,
        sample_workflow_yaml,
    ):
        """Test loading a valid workflow file."""
        workflow_path = temp_workflows_dir / "test.yaml"
        workflow_path.write_text(sample_workflow_yaml)

        workflow = workflow_engine.load_workflow("test.yaml")

        assert workflow.name == "test-workflow"
        assert workflow.description == "A test workflow"
        assert len(workflow.steps) == 2
        assert workflow.steps[0].id == "step1"
        assert workflow.steps[1].id == "step2"

    def test_load_nonexistent_workflow(self, workflow_engine):
        """Test loading a nonexistent workflow raises error."""
        with pytest.raises(FileNotFoundError):
            workflow_engine.load_workflow("nonexistent.yaml")

    def test_load_invalid_yaml(self, workflow_engine, temp_workflows_dir):
        """Test loading invalid YAML raises error."""
        workflow_path = temp_workflows_dir / "invalid.yaml"
        # This is actually valid YAML syntax but invalid workflow structure
        workflow_path.write_text("invalid: yaml: : :")

        # yaml.safe_load might actually parse this, so we expect ValueError
        # from workflow definition validation (missing required fields)
        with pytest.raises(ValueError):
            workflow_engine.load_workflow("invalid.yaml")

    def test_load_empty_file(self, workflow_engine, temp_workflows_dir):
        """Test loading empty file raises error."""
        workflow_path = temp_workflows_dir / "empty.yaml"
        workflow_path.write_text("")

        with pytest.raises(ValueError, match="Empty workflow file"):
            workflow_engine.load_workflow("empty.yaml")

    def test_load_workflow_caches(
        self,
        workflow_engine,
        temp_workflows_dir,
        sample_workflow_yaml,
    ):
        """Test that workflow loading is cached."""
        workflow_path = temp_workflows_dir / "cached.yaml"
        workflow_path.write_text(sample_workflow_yaml)

        workflow1 = workflow_engine.load_workflow("cached.yaml")
        workflow2 = workflow_engine.load_workflow("cached.yaml")

        assert workflow1 is workflow2  # Same object reference

    def test_path_traversal_protection(
        self,
        workflow_engine,
        temp_workflows_dir,
    ):
        """Test that path traversal attacks are blocked."""
        # Create a workflow outside the workflows dir
        outside_dir = temp_workflows_dir.parent
        outside_file = outside_dir / "outside.yaml"
        outside_file.write_text("name: outside")

        with pytest.raises(ValueError, match="Invalid workflow path"):
            workflow_engine.load_workflow("../outside.yaml")


class TestListWorkflows:
    """Tests for listing workflows."""

    def test_list_empty_directory(self, workflow_engine):
        """Test listing when directory is empty."""
        workflows = workflow_engine.list_workflows()
        assert workflows == []

    def test_list_workflows(
        self,
        workflow_engine,
        temp_workflows_dir,
        sample_workflow_yaml,
    ):
        """Test listing workflow files."""
        (temp_workflows_dir / "workflow1.yaml").write_text(
            sample_workflow_yaml,
        )
        (temp_workflows_dir / "workflow2.yml").write_text(sample_workflow_yaml)
        (temp_workflows_dir / "not-a-workflow.txt").write_text("text")

        workflows = workflow_engine.list_workflows()

        assert len(workflows) == 2
        assert "workflow1.yaml" in workflows
        assert "workflow2.yml" in workflows
        assert "not-a-workflow.txt" not in workflows


class TestVariableSubstitution:
    """Tests for variable substitution in prompts."""

    def test_substitute_simple_variable(self, workflow_engine):
        """Test substituting a simple variable."""
        result = workflow_engine._substitute_variables(
            "Hello {{name}}!",
            {"name": "World"},
            {},
        )
        assert result == "Hello World!"

    def test_substitute_multiple_variables(self, workflow_engine):
        """Test substituting multiple variables."""
        result = workflow_engine._substitute_variables(
            "{{greeting}} {{name}}!",
            {"greeting": "Hello", "name": "World"},
            {},
        )
        assert result == "Hello World!"

    def test_substitute_step_result(
        self,
        workflow_engine,
        _sample_workflow_definition,
    ):
        """Test substituting a step result reference."""
        from src.copaw.app.orchestration.schema import StepResult

        step_results = {
            "step1": StepResult(
                step_id="step1",
                status=StepStatus.COMPLETED,
                agent="agent1",
                prompt="Hello",
                result="Step 1 output",
            ),
        }

        result = workflow_engine._substitute_variables(
            "Previous: {{step1.result}}",
            {},
            step_results,
        )
        assert result == "Previous: Step 1 output"

    def test_substitute_step_error(self, workflow_engine):
        """Test substituting a step error reference."""
        from src.copaw.app.orchestration.schema import StepResult

        step_results = {
            "step1": StepResult(
                step_id="step1",
                status=StepStatus.FAILED,
                agent="agent1",
                prompt="Hello",
                error="Something went wrong",
            ),
        }

        result = workflow_engine._substitute_variables(
            "Error: {{step1.error}}",
            {},
            step_results,
        )
        assert result == "Error: Something went wrong"

    def test_substitute_unknown_variable(self, workflow_engine):
        """Test that unknown variables are kept as-is."""
        result = workflow_engine._substitute_variables(
            "Hello {{unknown}}!",
            {},
            {},
        )
        assert result == "Hello {{unknown}}!"


class TestExecuteWorkflow:
    """Tests for workflow execution."""

    @pytest.mark.asyncio
    async def test_execute_workflow_no_manager(
        self,
        workflow_engine,
        sample_workflow_definition,
    ):
        """Test that execution fails without multi-agent manager."""
        result = await workflow_engine.execute_workflow(
            sample_workflow_definition,
        )

        assert result.status == WorkflowExecutionStatus.FAILED
        assert "not available" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_workflow_with_mock_manager(
        self,
        workflow_engine,
        sample_workflow_definition,
    ):
        """Test workflow execution with mocked multi-agent manager."""
        # Create mock multi-agent manager
        mock_manager = AsyncMock()
        mock_workspace = MagicMock()

        # Create mock runner with query_handler method (async generator)
        mock_runner = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Mock response"

        async def mock_query_handler(_msgs, _request=None):
            yield mock_response, True

        mock_runner.query_handler = mock_query_handler

        mock_workspace.runner = mock_runner
        mock_manager.get_agent = AsyncMock(return_value=mock_workspace)

        workflow_engine.multi_agent_manager = mock_manager

        result = await workflow_engine.execute_workflow(
            sample_workflow_definition,
            variables={"name": "Test"},
        )

        assert result.status == WorkflowExecutionStatus.COMPLETED
        assert len(result.steps) == 2
        assert result.steps[0].status == StepStatus.COMPLETED
        assert result.steps[1].status == StepStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_execute_workflow_step_failure(
        self,
        workflow_engine,
        sample_workflow_definition,
    ):
        """Test that workflow stops on step failure."""
        mock_manager = AsyncMock()
        mock_manager.get_agent = AsyncMock(return_value=None)  # No workspace

        workflow_engine.multi_agent_manager = mock_manager

        result = await workflow_engine.execute_workflow(
            sample_workflow_definition,
        )

        assert result.status == WorkflowExecutionStatus.FAILED
        assert result.steps[0].status == StepStatus.FAILED

    @pytest.mark.asyncio
    async def test_execute_workflow_with_condition(
        self,
        workflow_engine,
    ):
        """Test workflow step with condition."""
        workflow_def = WorkflowDefinition(
            name="conditional-workflow",
            steps=[
                WorkflowStep(
                    id="step1",
                    agent="agent1",
                    prompt="First step",
                ),
                WorkflowStep(
                    id="step2",
                    agent="agent2",
                    prompt="Second step",
                    condition="{{skip_second}} != 'true'",
                ),
            ],
        )

        mock_manager = AsyncMock()
        mock_workspace = MagicMock()
        mock_runner = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Result"

        async def mock_query_handler(_msgs, _request=None):
            yield mock_response, True

        mock_runner.query_handler = mock_query_handler
        mock_workspace.runner = mock_runner
        mock_manager.get_agent = AsyncMock(return_value=mock_workspace)

        workflow_engine.multi_agent_manager = mock_manager

        # Test with skip_second = true
        result = await workflow_engine.execute_workflow(
            workflow_def,
            variables={"skip_second": "true"},
        )

        assert result.status == WorkflowExecutionStatus.COMPLETED
        assert result.steps[1].status == StepStatus.SKIPPED


class TestConditionEvaluation:
    """Tests for condition evaluation."""

    def test_evaluate_equals_condition(self, workflow_engine):
        """Test == condition evaluation."""
        result = workflow_engine._evaluate_condition(
            "'completed' == 'completed'",
            {},
            {},
        )
        assert result is True

        result = workflow_engine._evaluate_condition(
            "'pending' == 'completed'",
            {},
            {},
        )
        assert result is False

    def test_evaluate_not_equals_condition(self, workflow_engine):
        """Test != condition evaluation."""
        result = workflow_engine._evaluate_condition(
            "'pending' != 'completed'",
            {},
            {},
        )
        assert result is True

    def test_evaluate_with_substitution(self, workflow_engine):
        """Test condition with variable substitution."""
        from src.copaw.app.orchestration.schema import StepResult

        step_results = {
            "step1": StepResult(
                step_id="step1",
                status=StepStatus.COMPLETED,
                agent="agent1",
                prompt="test",
            ),
        }

        result = workflow_engine._evaluate_condition(
            "{{step1.status}} == 'completed'",
            {},
            step_results,
        )
        assert result is True


class TestSpawnPermission:
    """Tests for spawn permission checking."""

    @pytest.mark.asyncio
    async def test_spawn_permission_disabled(self, workflow_engine):
        """Test that spawn fails when can_spawn_agents=False."""
        from src.copaw.config.config import OrchestrationConfig

        mock_manager = AsyncMock()

        with patch(
            "src.copaw.app.orchestration.engine.load_agent_config",
        ) as mock_load:
            mock_load.return_value = MagicMock(
                orchestration=OrchestrationConfig(can_spawn_agents=False),
            )

            workflow_engine.multi_agent_manager = mock_manager
            error = await workflow_engine._check_spawn_permission(
                "agent1",
                "agent2",
                0,
            )

            assert error is not None
            assert "can_spawn_agents=true" in error

    @pytest.mark.asyncio
    async def test_spawn_permission_max_depth_exceeded(self, workflow_engine):
        """Test that spawn fails when max depth exceeded."""
        from src.copaw.config.config import OrchestrationConfig

        mock_manager = AsyncMock()

        with patch(
            "src.copaw.app.orchestration.engine.load_agent_config",
        ) as mock_load:
            mock_load.return_value = MagicMock(
                orchestration=OrchestrationConfig(
                    can_spawn_agents=True,
                    max_spawn_depth=2,
                ),
            )

            workflow_engine.multi_agent_manager = mock_manager
            error = await workflow_engine._check_spawn_permission(
                "agent1",
                "agent2",
                2,
            )

            assert error is not None
            assert "Maximum spawn depth" in error

    @pytest.mark.asyncio
    async def test_spawn_permission_agent_not_allowed(self, workflow_engine):
        """Test that spawn fails when agent not in allowed list."""
        from src.copaw.config.config import OrchestrationConfig

        mock_manager = AsyncMock()

        with patch(
            "src.copaw.app.orchestration.engine.load_agent_config",
        ) as mock_load:
            mock_load.return_value = MagicMock(
                orchestration=OrchestrationConfig(
                    can_spawn_agents=True,
                    allowed_agents=["agent3", "agent4"],
                    max_spawn_depth=3,
                ),
            )

            workflow_engine.multi_agent_manager = mock_manager
            error = await workflow_engine._check_spawn_permission(
                "agent1",
                "agent2",
                0,
            )

            assert error is not None
            assert "not allowed" in error

    @pytest.mark.asyncio
    async def test_spawn_permission_allowed(self, workflow_engine):
        """Test that spawn succeeds when all checks pass."""
        from src.copaw.config.config import OrchestrationConfig

        mock_manager = AsyncMock()

        with patch(
            "src.copaw.app.orchestration.engine.load_agent_config",
        ) as mock_load:
            mock_load.return_value = MagicMock(
                orchestration=OrchestrationConfig(
                    can_spawn_agents=True,
                    allowed_agents=["agent2"],
                    max_spawn_depth=3,
                ),
            )

            workflow_engine.multi_agent_manager = mock_manager
            error = await workflow_engine._check_spawn_permission(
                "agent1",
                "agent2",
                0,
            )

            assert error is None

    @pytest.mark.asyncio
    async def test_spawn_permission_empty_allowed_list(self, workflow_engine):
        """Test that empty allowed_agents means all agents allowed."""
        from src.copaw.config.config import OrchestrationConfig

        mock_manager = AsyncMock()

        with patch(
            "src.copaw.app.orchestration.engine.load_agent_config",
        ) as mock_load:
            mock_load.return_value = MagicMock(
                orchestration=OrchestrationConfig(
                    can_spawn_agents=True,
                    allowed_agents=[],  # Empty = all allowed
                    max_spawn_depth=3,
                ),
            )

            workflow_engine.multi_agent_manager = mock_manager
            error = await workflow_engine._check_spawn_permission(
                "agent1",
                "any_agent",
                0,
            )

            assert error is None

    @pytest.mark.asyncio
    async def test_spawn_permission_depth_zero_allowed(self, workflow_engine):
        """Test that spawn_depth=0 is allowed when max_spawn_depth >= 1."""
        from src.copaw.config.config import OrchestrationConfig

        mock_manager = AsyncMock()

        with patch(
            "src.copaw.app.orchestration.engine.load_agent_config",
        ) as mock_load:
            mock_load.return_value = MagicMock(
                orchestration=OrchestrationConfig(
                    can_spawn_agents=True,
                    max_spawn_depth=1,  # Minimum depth
                ),
            )

            workflow_engine.multi_agent_manager = mock_manager
            error = await workflow_engine._check_spawn_permission(
                "agent1",
                "agent2",
                0,  # depth=0, max=1
            )

            assert error is None

    @pytest.mark.asyncio
    async def test_spawn_permission_depth_equals_max_denied(
        self,
        workflow_engine,
    ):
        """Test that spawn_depth=max_spawn_depth is denied (>= check)."""
        from src.copaw.config.config import OrchestrationConfig

        mock_manager = AsyncMock()

        with patch(
            "src.copaw.app.orchestration.engine.load_agent_config",
        ) as mock_load:
            mock_load.return_value = MagicMock(
                orchestration=OrchestrationConfig(
                    can_spawn_agents=True,
                    max_spawn_depth=3,
                ),
            )

            workflow_engine.multi_agent_manager = mock_manager
            error = await workflow_engine._check_spawn_permission(
                "agent1",
                "agent2",
                3,  # depth=3, max=3 → denied
            )

            assert error is not None
            assert "Maximum spawn depth" in error

    @pytest.mark.asyncio
    async def test_spawn_permission_depth_one_below_max_allowed(
        self,
        workflow_engine,
    ):
        """Test that spawn_depth=max-1 is allowed (last valid level)."""
        from src.copaw.config.config import OrchestrationConfig

        mock_manager = AsyncMock()

        with patch(
            "src.copaw.app.orchestration.engine.load_agent_config",
        ) as mock_load:
            mock_load.return_value = MagicMock(
                orchestration=OrchestrationConfig(
                    can_spawn_agents=True,
                    max_spawn_depth=3,
                ),
            )

            workflow_engine.multi_agent_manager = mock_manager
            error = await workflow_engine._check_spawn_permission(
                "agent1",
                "agent2",
                2,  # depth=2, max=3 → allowed
            )

            assert error is None

    @pytest.mark.asyncio
    async def test_spawn_permission_max_depth_ten(self, workflow_engine):
        """Test that max_spawn_depth=10 (maximum) works correctly."""
        from src.copaw.config.config import OrchestrationConfig

        mock_manager = AsyncMock()

        with patch(
            "src.copaw.app.orchestration.engine.load_agent_config",
        ) as mock_load:
            mock_load.return_value = MagicMock(
                orchestration=OrchestrationConfig(
                    can_spawn_agents=True,
                    max_spawn_depth=10,  # Maximum allowed
                ),
            )

            workflow_engine.multi_agent_manager = mock_manager
            # depth=9 should be allowed
            error = await workflow_engine._check_spawn_permission(
                "agent1",
                "agent2",
                9,
            )
            assert error is None

            # depth=10 should be denied
            error = await workflow_engine._check_spawn_permission(
                "agent1",
                "agent2",
                10,
            )
            assert error is not None

    @pytest.mark.asyncio
    async def test_spawn_permission_self_spawn_allowed(self, workflow_engine):
        """Test agent can spawn itself (if in allowed_agents or list empty)."""
        from src.copaw.config.config import OrchestrationConfig

        mock_manager = AsyncMock()

        with patch(
            "src.copaw.app.orchestration.engine.load_agent_config",
        ) as mock_load:
            # Empty allowed_agents = all agents allowed, including self
            mock_load.return_value = MagicMock(
                orchestration=OrchestrationConfig(
                    can_spawn_agents=True,
                    allowed_agents=[],
                    max_spawn_depth=3,
                ),
            )

            workflow_engine.multi_agent_manager = mock_manager
            error = await workflow_engine._check_spawn_permission(
                "agent1",
                "agent1",
                0,  # Same agent
            )

            assert error is None

    @pytest.mark.asyncio
    async def test_spawn_permission_self_spawn_explicit(self, workflow_engine):
        """Test that agent can explicitly add itself to allowed_agents."""
        from src.copaw.config.config import OrchestrationConfig

        mock_manager = AsyncMock()

        with patch(
            "src.copaw.app.orchestration.engine.load_agent_config",
        ) as mock_load:
            # Agent1 explicitly allows itself
            mock_load.return_value = MagicMock(
                orchestration=OrchestrationConfig(
                    can_spawn_agents=True,
                    allowed_agents=["agent1", "agent2"],
                    max_spawn_depth=3,
                ),
            )

            workflow_engine.multi_agent_manager = mock_manager
            error = await workflow_engine._check_spawn_permission(
                "agent1",
                "agent1",
                0,  # Self spawn
            )

            assert error is None
