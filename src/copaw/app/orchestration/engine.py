# -*- coding: utf-8 -*-
"""Workflow orchestration engine.

Executes workflows by invoking agents sequentially and managing
variable substitution between steps.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import yaml

from agentscope.message import Msg
from agentscope_runtime.engine.schemas.agent_schemas import (
    AgentRequest,
    Message,
    MessageType,
    Role,
    TextContent,
    ContentType,
)

from ...config.config import load_agent_config
from .schema import (
    StepResult,
    StepStatus,
    WorkflowDefinition,
    WorkflowExecutionResult,
    WorkflowExecutionStatus,
    WorkflowStep,
)

if TYPE_CHECKING:
    from ..multi_agent_manager import MultiAgentManager

logger = logging.getLogger(__name__)


def _extract_text_from_content(content: Any) -> str:
    """Extract text from agent response content.

    Handles various content formats:
    - List of content blocks (thinking, text, etc.)
    - Plain string
    - Object with .text attribute

    Args:
        content: Response content from agent.

    Returns:
        Extracted text string.
    """
    if content is None:
        return ""

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        text_parts: List[str] = []
        for block in content:
            # Extract text from text blocks (object form)
            if (
                hasattr(block, "type")
                and getattr(block, "type", None) == "text"
            ):
                text_parts.append(getattr(block, "text", ""))
            # Extract text from text blocks (dict form)
            elif isinstance(block, dict) and block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            # Plain string in list
            elif isinstance(block, str):
                text_parts.append(block)
        return " ".join(text_parts) if text_parts else str(content)

    if hasattr(content, "text"):
        return content.text

    return str(content)


class WorkflowEngine:
    """Engine for executing workflows.

    The engine loads workflow definitions from YAML files and executes
    them step by step, invoking agents and passing results between steps.

    Example workflow YAML:
        name: research-and-summarize
        description: "Research a topic and create a summary"
        variables:
          tone: professional
        steps:
          - id: research
            agent: researcher
            prompt: "Research about {{topic}}"
          - id: summarize
            agent: writer
            prompt: "Summarize this in a {{tone}} tone: {{research.result}}"
    """

    # Pattern to match {{variable}} or {{step_id.result}} syntax
    VARIABLE_PATTERN = re.compile(r"\{\{([^}]+)\}\}")

    def __init__(
        self,
        workflows_dir: Path,
        multi_agent_manager: Optional[MultiAgentManager] = None,
    ):
        """Initialize the workflow engine.

        Args:
            workflows_dir: Directory containing workflow YAML files.
            multi_agent_manager: Manager for accessing agent workspaces.
        """
        self.workflows_dir = Path(workflows_dir)
        self.multi_agent_manager = multi_agent_manager
        self._workflow_cache: Dict[str, WorkflowDefinition] = {}

    def load_workflow(self, filename: str) -> WorkflowDefinition:
        """Load a workflow definition from a YAML file.

        Args:
            filename: Name of the workflow file (e.g., "research.yaml").

        Returns:
            WorkflowDefinition object.

        Raises:
            FileNotFoundError: If the workflow file doesn't exist.
            ValueError: If the YAML is invalid or missing required fields.
        """
        if filename in self._workflow_cache:
            return self._workflow_cache[filename]

        workflow_path = self.workflows_dir / filename

        if not workflow_path.exists():
            raise FileNotFoundError(f"Workflow file not found: {filename}")

        # Security: ensure the path is within workflows_dir
        if not workflow_path.resolve().is_relative_to(
            self.workflows_dir.resolve(),
        ):
            raise ValueError(f"Invalid workflow path: {filename}")

        with open(workflow_path, "r", encoding="utf-8") as f:
            try:
                data = yaml.safe_load(f)
            except yaml.YAMLError as e:
                raise ValueError(
                    f"Invalid YAML in workflow file {filename}: {e}",
                ) from e

        if not data:
            raise ValueError(f"Empty workflow file: {filename}")

        try:
            workflow = WorkflowDefinition(**data)
            self._workflow_cache[filename] = workflow
            return workflow
        except Exception as e:
            raise ValueError(
                f"Invalid workflow definition in {filename}: {e}",
            ) from e

    def list_workflows(self) -> list[str]:
        """List available workflow files.

        Returns:
            List of workflow filenames.
        """
        if not self.workflows_dir.exists():
            return []

        return [
            f.name
            for f in self.workflows_dir.iterdir()
            if f.suffix in (".yaml", ".yml") and f.is_file()
        ]

    def _substitute_variables(
        self,
        text: str,
        variables: Dict[str, Any],
        step_results: Dict[str, StepResult],
    ) -> str:
        """Substitute {{variable}} patterns in text.

        Supports:
        - {{variable_name}} - from workflow variables
        - {{step_id.result}} - result from a previous step
        - {{step_id.error}} - error from a previous step (if any)

        Args:
            text: Text containing {{...}} patterns.
            variables: Current workflow variables.
            step_results: Results from completed steps.

        Returns:
            Text with substitutions applied.
        """

        def replace(match: re.Match) -> str:
            expr = match.group(1).strip()

            # Check for step.result syntax
            if "." in expr:
                parts = expr.split(".", 1)
                step_id = parts[0]
                attr = parts[1]

                if step_id in step_results:
                    step = step_results[step_id]
                    if attr == "result":
                        return step.result or ""
                    elif attr == "error":
                        return step.error or ""
                    elif attr == "status":
                        return step.status.value

                logger.warning(f"Unknown step reference: {expr}")
                return match.group(0)  # Keep original if not found

            # Check for variable
            if expr in variables:
                return str(variables[expr])

            logger.warning(f"Unknown variable: {expr}")
            return match.group(0)  # Keep original if not found

        return self.VARIABLE_PATTERN.sub(replace, text)

    async def _check_spawn_permission(
        self,
        calling_agent_id: str,
        target_agent_id: str,
        spawn_depth: int,
    ) -> Optional[str]:
        # pylint: disable=too-many-return-statements
        """Check if the calling agent has permission to spawn the target agent.

        Args:
            calling_agent_id: ID of the agent initiating the spawn.
            target_agent_id: ID of the agent to be spawned.
            spawn_depth: Current nesting depth.

        Returns:
            Error message if permission denied, None if allowed.
        """
        if not self.multi_agent_manager:
            logger.warning(
                "MultiAgentManager not available, allowing spawn "
                "without permission check",
            )
            return None

        try:
            # Get the calling agent's workspace
            workspace = await self.multi_agent_manager.get_agent(
                calling_agent_id,
            )
            if not workspace:
                return f"Calling agent '{calling_agent_id}' not found"

            # Reload config from disk (bypass cache to get latest
            # orchestration settings)
            agent_config = load_agent_config(calling_agent_id)
            orchestration = agent_config.orchestration

            # Check if agent can spawn other agents
            if not orchestration.can_spawn_agents:
                return (
                    f"Agent '{calling_agent_id}' is not allowed "
                    f"to spawn other agents. Set "
                    f"orchestration.can_spawn_agents=true in "
                    f"agent.json to enable."
                )

            # Check max spawn depth
            if spawn_depth >= orchestration.max_spawn_depth:
                return (
                    f"Maximum spawn depth "
                    f"({orchestration.max_spawn_depth}) exceeded. "
                    f"Current depth: {spawn_depth}"
                )

            # Check if target agent is in allowed list (if list is
            # not empty)
            if (
                orchestration.allowed_agents
                and target_agent_id not in orchestration.allowed_agents
            ):
                return (
                    f"Agent '{calling_agent_id}' is not allowed "
                    f"to spawn '{target_agent_id}'. "
                    f"Allowed agents: {orchestration.allowed_agents}"
                )

            logger.info(
                f"Spawn permission granted: {calling_agent_id} "
                f"-> {target_agent_id} "
                f"(depth: {spawn_depth + 1}/"
                f"{orchestration.max_spawn_depth})",
            )
            return None

        except Exception as e:
            logger.error(f"Error checking spawn permission: {e}")
            # Fail-closed: deny spawn on error for security
            return (
                f"Permission check failed for agent '{calling_agent_id}': {e}"
            )

    async def _run_agent_query(
        self,
        agent_id: str,
        prompt: str,
        session_suffix: str,
    ) -> Tuple[str, Optional[str]]:
        """Execute a single agent query and extract the response text.

        Args:
            agent_id: ID of the agent to query.
            prompt: The prompt to send to the agent.
            session_suffix: Suffix for the session ID (e.g., step ID
                or retry attempt).

        Returns:
            Tuple of (extracted_text, error_message). error_message
            is None on success.
        """
        if not self.multi_agent_manager:
            return "", "Multi-agent manager not available"

        try:
            workspace = await self.multi_agent_manager.get_agent(agent_id)
            if not workspace:
                return "", f"Agent not found: {agent_id}"

            runner = workspace.runner

            # Create message for the agent
            msg = Msg(name="workflow", content=prompt, role="user")

            # Create AgentRequest with minimal valid input
            dummy_msg = Message(
                type=MessageType.MESSAGE,
                role=Role.USER,
                content=[TextContent(type=ContentType.TEXT, text=prompt)],
            )
            request = AgentRequest(
                session_id=f"workflow-{agent_id}-{session_suffix}",
                user_id="workflow",
                input=[dummy_msg],
                channel="workflow",
            )

            # Execute the agent query
            response = None
            async for response_msg, is_last in runner.query_handler(
                [msg],
                request=request,
            ):
                if is_last:
                    response = response_msg
                    break

            # Extract text from response
            if response is not None and hasattr(response, "content"):
                return _extract_text_from_content(response.content), None

            return "", None

        except Exception as e:
            return "", str(e)

    async def execute_step(
        self,
        step: WorkflowStep,
        variables: Dict[str, Any],
        step_results: Dict[str, StepResult],
    ) -> StepResult:
        """Execute a single workflow step.

        Args:
            step: The step to execute.
            variables: Current workflow variables.
            step_results: Results from previous steps.

        Returns:
            StepResult with the outcome.
        """
        start_time = time.time()
        started_at = datetime.now().isoformat()

        # Substitute variables in the prompt
        prompt = self._substitute_variables(
            step.prompt,
            variables,
            step_results,
        )

        result = StepResult(
            step_id=step.id,
            status=StepStatus.RUNNING,
            agent=step.agent,
            prompt=prompt,
            started_at=started_at,
        )

        # Execute the agent query
        text, error = await self._run_agent_query(step.agent, prompt, step.id)

        if error:
            logger.error(f"Step {step.id} failed: {error}")
            result.status = StepStatus.FAILED
            result.error = error

            # Retry logic
            if step.retries > 0:
                for attempt in range(step.retries):
                    logger.info(
                        f"Retrying step {step.id} "
                        f"(attempt {attempt + 1}/{step.retries})",
                    )
                    await asyncio.sleep(1)  # Brief delay before retry

                    retry_text, retry_error = await self._run_agent_query(
                        step.agent,
                        prompt,
                        f"{step.id}-retry{attempt}",
                    )

                    if retry_error:
                        result.error = retry_error
                    else:
                        result.result = retry_text
                        result.status = StepStatus.COMPLETED
                        result.error = None
                        break
        else:
            result.result = text
            result.status = StepStatus.COMPLETED

        completed_at = datetime.now().isoformat()
        result.completed_at = completed_at
        result.duration_ms = int((time.time() - start_time) * 1000)

        return result

    async def execute_workflow(
        self,
        workflow: WorkflowDefinition,
        variables: Optional[Dict[str, Any]] = None,
        calling_agent_id: Optional[str] = None,
        spawn_depth: int = 0,
    ) -> WorkflowExecutionResult:
        """Execute a complete workflow.

        Args:
            workflow: The workflow definition to execute.
            variables: Variables to pass to the workflow.
            calling_agent_id: ID of the agent initiating this workflow
                (for permission checks).
            spawn_depth: Current nesting depth for agent spawning.

        Returns:
            WorkflowExecutionResult with all step results.
        """
        start_time = time.time()
        started_at = datetime.now().isoformat()

        # Merge default variables with provided variables
        exec_variables = {**workflow.variables, **(variables or {})}

        execution_result = WorkflowExecutionResult(
            workflow_name=workflow.name,
            status=WorkflowExecutionStatus.RUNNING,
            variables=exec_variables,
            started_at=started_at,
        )

        step_results: Dict[str, StepResult] = {}

        try:
            for step in workflow.steps:
                logger.info(f"Executing step: {step.id}")

                # Check spawn permission if a calling agent is specified
                if calling_agent_id and step.agent != calling_agent_id:
                    permission_error = await self._check_spawn_permission(
                        calling_agent_id=calling_agent_id,
                        target_agent_id=step.agent,
                        spawn_depth=spawn_depth,
                    )
                    if permission_error:
                        logger.warning(
                            f"Spawn permission denied: {permission_error}",
                        )
                        failed_result = StepResult(
                            step_id=step.id,
                            status=StepStatus.FAILED,
                            agent=step.agent,
                            prompt=step.prompt,
                            error=permission_error,
                        )
                        step_results[step.id] = failed_result
                        execution_result.steps.append(failed_result)
                        execution_result.status = (
                            WorkflowExecutionStatus.FAILED
                        )
                        execution_result.error = permission_error
                        break

                # Check condition if present
                if step.condition:
                    # Simple condition evaluation
                    # In production, we'd use a proper expression evaluator
                    condition_result = self._evaluate_condition(
                        step.condition,
                        exec_variables,
                        step_results,
                    )
                    if not condition_result:
                        logger.info(
                            f"Skipping step {step.id} due to condition",
                        )
                        skipped_result = StepResult(
                            step_id=step.id,
                            status=StepStatus.SKIPPED,
                            agent=step.agent,
                            prompt=step.prompt,
                        )
                        step_results[step.id] = skipped_result
                        execution_result.steps.append(skipped_result)
                        continue

                # Execute the step
                result = await self.execute_step(
                    step,
                    exec_variables,
                    step_results,
                )
                step_results[step.id] = result
                execution_result.steps.append(result)

                # Stop on failure
                if result.status == StepStatus.FAILED:
                    execution_result.status = WorkflowExecutionStatus.FAILED
                    execution_result.error = (
                        f"Step {step.id} failed: {result.error}"
                    )
                    break

            # If all steps completed successfully
            if execution_result.status == WorkflowExecutionStatus.RUNNING:
                execution_result.status = WorkflowExecutionStatus.COMPLETED
                # Set final result to the last completed step's result
                for step_result in reversed(execution_result.steps):
                    if step_result.status == StepStatus.COMPLETED:
                        execution_result.final_result = step_result.result
                        break

        except Exception as e:
            logger.error(f"Workflow execution failed: {e}")
            execution_result.status = WorkflowExecutionStatus.FAILED
            execution_result.error = str(e)

        completed_at = datetime.now().isoformat()
        execution_result.completed_at = completed_at
        execution_result.duration_ms = int((time.time() - start_time) * 1000)

        return execution_result

    def _evaluate_condition(
        self,
        condition: str,
        variables: Dict[str, Any],
        step_results: Dict[str, StepResult],
    ) -> bool:
        """Evaluate a simple condition.

        Supports basic comparisons like:
        - "{{step_id.status}} == 'completed'"
        - "{{variable}} != 'skip'"

        Args:
            condition: Condition string to evaluate.
            variables: Current variables.
            step_results: Results from previous steps.

        Returns:
            Boolean result of the condition.
        """
        # Substitute variables in the condition
        substituted = self._substitute_variables(
            condition,
            variables,
            step_results,
        )

        # Simple evaluation for common patterns
        # This is a basic implementation - production would
        # use a proper evaluator

        # Check for == comparison
        if "==" in substituted:
            parts = substituted.split("==", 1)
            if len(parts) == 2:
                left = parts[0].strip().strip("\"'")
                right = parts[1].strip().strip("\"'")
                return left == right

        # Check for != comparison
        if "!=" in substituted:
            parts = substituted.split("!=", 1)
            if len(parts) == 2:
                left = parts[0].strip().strip("\"'")
                right = parts[1].strip().strip("\"'")
                return left != right

        # Default: treat non-empty string as True
        return bool(substituted.strip())
