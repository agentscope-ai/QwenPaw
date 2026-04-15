# -*- coding: utf-8 -*-
"""CLI commands for managing agents and inter-agent communication."""
# pylint:disable=too-many-branches,too-many-statements
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional, Dict, Any

import click
import httpx

from ..agents.tools import agent_management as agent_tools
from ..agents.templates import (
    DEFAULT_AGENT_TEMPLATE,
    build_agent_template,
    list_supported_agent_templates,
)
from ..config import load_config, save_config
from ..config.config import (
    AgentProfileRef,
    generate_short_agent_id,
    save_agent_config,
)
from ..constant import WORKING_DIR
from ..providers.models import ModelSlotConfig
from ..providers.provider_manager import ProviderManager
from .http import print_json, resolve_base_url

SUPPORTED_AGENT_TEMPLATES = list_supported_agent_templates()


def _extract_text_content(response_data: Dict[str, Any]) -> str:
    """Extract text content from agent response."""
    return agent_tools.extract_agent_text_content(response_data)


def _extract_and_print_text(
    response_data: Dict[str, Any],
    session_id: Optional[str] = None,
) -> None:
    """Extract and print text content with metadata header.

    Args:
        response_data: Response data from agent
        session_id: Session ID to include in metadata (for reuse)
    """
    if session_id:
        click.echo(f"[SESSION: {session_id}]")
        click.echo()

    text = _extract_text_content(response_data)
    if text:
        click.echo(text)
    else:
        click.echo("(No text content in response)", err=True)


def _handle_stream_mode(
    base_url: str,
    request_payload: Dict[str, Any],
    to_agent: str,
    timeout: int,
) -> None:
    """Handle streaming mode response."""
    agent_tools.stream_agent_chat(
        base_url,
        request_payload,
        to_agent,
        timeout,
        line_handler=click.echo,
    )


def _handle_final_mode(
    base_url: str,
    request_payload: Dict[str, Any],
    to_agent: str,
    timeout: int,
    json_output: bool,
) -> None:
    """Handle final mode response (collect all SSE events)."""
    response_data = agent_tools.collect_final_agent_chat_response(
        base_url,
        request_payload,
        to_agent,
        timeout,
    )

    if not response_data:
        click.echo("(No response received)", err=True)
        return

    if json_output:
        if "session_id" not in response_data:
            response_data["session_id"] = request_payload.get("session_id")
        print_json(response_data)
    else:
        _extract_and_print_text(
            response_data,
            session_id=request_payload.get("session_id"),
        )


def _submit_background_task(
    base_url: str,
    request_payload: Dict[str, Any],
    to_agent: str,
    session_id: str,
    timeout: int,
) -> None:
    """Submit background task and return task_id."""
    try:
        result = agent_tools.submit_agent_chat_task(
            base_url,
            request_payload,
            to_agent,
            timeout,
        )

        task_id = result.get("task_id")
        if not task_id:
            click.echo("ERROR: No task_id returned from server", err=True)
            return

        click.echo(f"[TASK_ID: {task_id}]")
        click.echo(f"[SESSION: {session_id}]")
        click.echo()
        click.echo("✅ Task submitted successfully")
        click.echo()
        click.echo("💡 Don't wait - continue with other tasks!")
        click.echo("   Check status later (10-60s depending on complexity):")
        click.echo(f"  qwenpaw agents chat --background --task-id {task_id}")

    except Exception as e:
        click.echo(f"ERROR: Failed to submit task: {e}", err=True)
        raise click.Abort()


def _validate_chat_parameters(
    ctx: click.Context,
    background: bool,
    task_id: Optional[str],
    from_agent: Optional[str],
    to_agent: Optional[str],
    text: Optional[str],
    mode: str,
) -> None:
    """Validate chat command parameters."""
    # When not checking task status, require from_agent, to_agent, and text
    if not (background and task_id):
        if not from_agent:
            click.echo(
                "ERROR: --from-agent is required "
                "(unless checking task status)",
                err=True,
            )
            ctx.exit(1)

        if not to_agent:
            click.echo(
                "ERROR: --to-agent is required "
                "(unless checking task status)",
                err=True,
            )
            ctx.exit(1)

        if not text:
            click.echo(
                "ERROR: --text is required (unless checking task status)",
                err=True,
            )
            ctx.exit(1)

    if task_id and not background:
        click.echo(
            "ERROR: --task-id requires --background flag",
            err=True,
        )
        ctx.exit(1)

    if background and mode == "stream":
        click.echo(
            "ERROR: --background and --mode stream are mutually exclusive",
            err=True,
        )
        ctx.exit(1)


def _check_task_status(
    base_url: Optional[str],
    task_id: str,
    json_output: bool,
    to_agent: Optional[str] = None,
) -> None:
    """Check background task status and display result."""
    try:
        result = agent_tools.get_agent_chat_task_status(
            base_url,
            task_id,
            to_agent=to_agent,
            timeout=10,
        )

        if json_output:
            print_json(result)
            return

        status = result.get("status", "unknown")
        click.echo(f"[TASK_ID: {task_id}]")
        click.echo(f"[STATUS: {status}]")
        click.echo()

        if status == "finished":
            task_result = result.get("result", {})
            task_status = task_result.get("status")

            if task_status == "completed":
                click.echo("✅ Task completed")
                click.echo()
                _extract_and_print_text(
                    task_result,
                    session_id=task_result.get("session_id"),
                )
            elif task_status == "failed":
                error_info = task_result.get("error", {})
                error_msg = error_info.get("message", "Unknown error")
                click.echo("❌ Task failed")
                click.echo()
                click.echo(f"Error: {error_msg}")
            else:
                click.echo(f"Status: {task_status}")
                if result:
                    print_json(result)

        elif status == "running":
            click.echo("⏳ Task is still running...")
            created_at = result.get("created_at", "N/A")
            click.echo(f"   Started at: {created_at}")
            click.echo()
            click.echo(
                "💡 Don't wait - continue with other tasks first!",
            )
            click.echo("   Check again later (10-30s):")
            click.echo(
                f"  qwenpaw agents chat --background --task-id {task_id}",
            )

        elif status == "pending":
            click.echo("⏸️  Task is pending in queue...")
            click.echo()
            click.echo(
                "💡 Don't wait - handle other work first!",
            )
            click.echo("   Check again in a few seconds:")
            click.echo(
                f"  qwenpaw agents chat --background --task-id {task_id}",
            )

        elif status == "submitted":
            click.echo("📤 Task submitted, waiting to start...")
            click.echo()
            click.echo(
                "💡 Don't wait - continue with other work!",
            )
            click.echo("   Check again in a few seconds:")
            click.echo(
                f"  qwenpaw agents chat --background --task-id {task_id}",
            )

        else:
            click.echo(f"Unknown status: {status}")
            if result:
                print_json(result)

    except Exception as e:
        if isinstance(e, httpx.HTTPStatusError):
            response = e.response
            if response is not None and response.status_code == 404:
                click.echo(f"❌ Task not found: {task_id}", err=True)
                click.echo(
                    "   Task may have expired or never existed",
                    err=True,
                )
            else:
                click.echo(f"ERROR: {e}", err=True)
        else:
            click.echo(f"ERROR: {e}", err=True)
        raise click.Abort()


def _normalized_agent_order(config) -> list[str]:
    """Return a deduplicated agent order covering every configured agent."""
    profile_ids = list(config.agents.profiles.keys())
    ordered_ids: list[str] = []

    for agent_id in config.agents.agent_order:
        if agent_id in config.agents.profiles and agent_id not in ordered_ids:
            ordered_ids.append(agent_id)

    for agent_id in profile_ids:
        if agent_id not in ordered_ids:
            ordered_ids.append(agent_id)

    return ordered_ids


def _generate_agent_id(config, agent_id: Optional[str]) -> str:
    """Return a user-provided agent ID or generate a unique one."""
    if agent_id:
        if agent_id in config.agents.profiles:
            raise click.ClickException(
                f"Agent '{agent_id}' already exists.",
            )
        return agent_id

    max_attempts = 10
    for _ in range(max_attempts):
        candidate_id = generate_short_agent_id()
        if candidate_id not in config.agents.profiles:
            return candidate_id

    raise click.ClickException(
        "Failed to generate unique agent ID after 10 attempts.",
    )


def _build_agent_workspace_dir(
    agent_id: str,
    workspace_dir: Optional[str],
) -> Path:
    """Resolve the agent workspace path."""
    if workspace_dir is not None:
        workspace_dir = workspace_dir.strip() or None

    if workspace_dir is not None:
        return Path(workspace_dir).expanduser()
    return (WORKING_DIR / "workspaces" / agent_id).expanduser()


def _normalize_optional_text(value: Optional[str]) -> Optional[str]:
    """Strip surrounding whitespace from optional CLI text inputs."""
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _initialize_new_agent_workspace(
    workspace_dir: Path,
    skill_names: list[str],
    md_template_id: str | None = None,
) -> None:
    """Initialize a new agent workspace using shared server logic."""
    from ..app.routers.agents import _initialize_agent_workspace

    _initialize_agent_workspace(
        workspace_dir,
        skill_names=skill_names,
        md_template_id=md_template_id,
    )


def _build_active_model_config(
    provider_id: Optional[str],
    model_id: Optional[str],
) -> ModelSlotConfig | None:
    """Validate and build an agent-scoped active model configuration."""
    provider_id = _normalize_optional_text(provider_id)
    model_id = _normalize_optional_text(model_id)

    if provider_id is None and model_id is None:
        return None

    if provider_id is None or model_id is None:
        raise click.ClickException(
            "--provider-id and --model-id must be provided together.",
        )

    manager = ProviderManager.get_instance()
    provider = manager.get_provider(provider_id)
    if provider is None:
        raise click.ClickException(f"Provider '{provider_id}' not found.")

    if not provider.has_model(model_id):
        raise click.ClickException(
            f"Model '{model_id}' not found in provider '{provider.id}'.",
        )

    return ModelSlotConfig(provider_id=provider.id, model=model_id)


def _fetch_agent_workspace_dir(
    client: httpx.Client,
    agent_id: str,
) -> Optional[Path]:
    """Load the configured workspace directory for an agent from the API."""
    response = client.get(f"/agents/{agent_id}")

    if response.status_code == 404:
        raise click.ClickException(f"Agent '{agent_id}' not found.")

    response.raise_for_status()
    workspace_dir = response.json().get("workspace_dir")
    if not workspace_dir:
        return None
    return Path(workspace_dir).expanduser()


def _ensure_workspace_within_working_dir(workspace_dir: Path) -> Path:
    """Validate that a workspace directory lives under WORKING_DIR."""
    resolved_working_dir = WORKING_DIR.resolve()
    resolved_workspace_dir = workspace_dir.expanduser().resolve()

    try:
        resolved_workspace_dir.relative_to(resolved_working_dir)
    except ValueError as exc:
        raise click.ClickException(
            "Cannot delete workspace outside WORKING_DIR: "
            f"'{resolved_workspace_dir}' is not under "
            f"'{resolved_working_dir}'.",
        ) from exc

    return resolved_workspace_dir


def _remove_agent_workspace(workspace_dir: Path) -> bool:
    """Delete the agent workspace directory if it exists."""
    resolved_workspace_dir = _ensure_workspace_within_working_dir(
        workspace_dir,
    )

    if not resolved_workspace_dir.exists():
        return False

    try:
        shutil.rmtree(resolved_workspace_dir)
    except OSError as exc:
        raise click.ClickException(
            f"Failed to delete workspace '{resolved_workspace_dir}': {exc}",
        ) from exc
    return True


@click.group("agents")
def agents_group() -> None:
    """Manage agents and inter-agent communication.

    \b
    Commands:
      chat    Communicate with another agent
      create  Create a new local agent
      delete  Delete a configured agent
      list    List all configured agents

    \b
    Examples:
      qwenpaw agents chat --from-agent bot_a --to-agent bot_b --text "..."
      qwenpaw agents create --name "Research Bot" --agent-id research_bot
      qwenpaw agents delete research_bot
      qwenpaw agents list
    """


@agents_group.command("list")
@click.option(
    "--base-url",
    default=None,
    help=(
        "Override the API base URL (e.g. http://127.0.0.1:8088). "
        "If omitted, uses global --host and --port from config."
    ),
)
@click.pass_context
def list_agents(ctx: click.Context, base_url: Optional[str]) -> None:
    """List all configured agents.

    Shows agent ID, name, description, and workspace directory.
    Useful for discovering available agents for inter-agent communication.

    \b
    Examples:
      qwenpaw agents list
      qwenpaw agents list --base-url http://192.168.1.100:8088

    \b
    Output format:
      {
        "agents": [
          {
            "id": "default",
            "name": "Default Assistant",
            "description": "...",
            "workspace_dir": "..."
          }
        ]
      }
    """
    base_url = resolve_base_url(ctx, base_url)
    print_json(agent_tools.list_agents_data(base_url))


@agents_group.command("create")
@click.option(
    "--name",
    required=True,
    help="Human-readable agent name.",
)
@click.option(
    "--agent-id",
    default=None,
    help=("Explicit agent ID. If omitted, a random unique ID is generated."),
)
@click.option(
    "--description",
    default=None,
    show_default=False,
    help="Optional agent description.",
)
@click.option(
    "--workspace-dir",
    default=None,
    help=(
        "Optional workspace directory. "
        "Defaults to WORKING_DIR/workspaces/<id>."
    ),
)
@click.option(
    "--language",
    default=None,
    show_default=False,
    help="Agent language stored in the profile config.",
)
@click.option(
    "--template",
    type=click.Choice(SUPPORTED_AGENT_TEMPLATES, case_sensitive=False),
    default=None,
    help=(
        "Create agent from builtin template: "
        f"{', '.join(SUPPORTED_AGENT_TEMPLATES)}."
    ),
)
@click.option(
    "--skill",
    "skills",
    multiple=True,
    help="Initial skill to install. Repeat to add multiple skills.",
)
@click.option(
    "--provider-id",
    default=None,
    show_default=False,
    help="Provider ID for the agent's default active model.",
)
@click.option(
    "--model-id",
    default=None,
    show_default=False,
    help="Model ID for the agent's default active model.",
)
def create_cmd(
    name: Optional[str],
    agent_id: Optional[str],
    description: Optional[str],
    workspace_dir: Optional[str],
    language: Optional[str],
    template: Optional[str],
    skills: tuple[str, ...],
    provider_id: Optional[str],
    model_id: Optional[str],
) -> None:
    """Create a new local agent configuration and workspace."""
    config = load_config()
    template = _normalize_optional_text(template)
    name = _normalize_optional_text(name)
    agent_id = _normalize_optional_text(agent_id)
    description = _normalize_optional_text(description)
    language = _normalize_optional_text(language)

    if not name:
        raise click.ClickException("--name is required.")

    new_id = _generate_agent_id(config, agent_id)
    active_model = _build_active_model_config(
        provider_id,
        model_id,
    )
    resolved_workspace_dir = _build_agent_workspace_dir(
        new_id,
        workspace_dir,
    )
    resolved_workspace_dir.mkdir(parents=True, exist_ok=True)

    effective_template = template or DEFAULT_AGENT_TEMPLATE
    try:
        template_result = build_agent_template(
            effective_template,
            agent_id=new_id,
            workspace_dir=resolved_workspace_dir,
            fallback_language=getattr(config.agents, "language", None) or "zh",
            name=name,
            description=description,
            language=language,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    agent_config = template_result.agent_config
    template_skill_names = list(template_result.initial_skill_names)
    md_template_id = template_result.md_template_id
    agent_config.active_model = active_model

    requested_skills = list(dict.fromkeys([*template_skill_names, *skills]))
    _initialize_new_agent_workspace(
        resolved_workspace_dir,
        skill_names=requested_skills,
        md_template_id=md_template_id,
    )

    agent_ref = AgentProfileRef(
        id=new_id,
        workspace_dir=str(resolved_workspace_dir),
        enabled=True,
    )
    config.agents.profiles[new_id] = agent_ref
    config.agents.agent_order = _normalized_agent_order(config)

    save_config(config)
    save_agent_config(new_id, agent_config)

    print_json(agent_ref.model_dump())


@agents_group.command("delete")
@click.argument("agent_id")
@click.option(
    "--remove-workspace",
    is_flag=True,
    default=False,
    help="Also remove the agent workspace directory from the local machine.",
)
@click.option(
    "--yes",
    is_flag=True,
    default=False,
    help="Skip warning messages and confirmation prompt.",
)
@click.option(
    "--base-url",
    default=None,
    help=(
        "Override the API base URL (e.g. http://127.0.0.1:8088). "
        "If omitted, uses global --host and --port from config."
    ),
)
@click.pass_context
def delete_cmd(
    ctx: click.Context,
    agent_id: str,
    remove_workspace: bool,
    yes: bool,
    base_url: Optional[str],
) -> None:
    """Delete a configured agent via the local API.

    Stops the target agent if it is running and removes it from the
    configured agent list. The default agent cannot be deleted.

    \b
    AGENT_ID  Configured agent ID, obtainable via `qwenpaw agents list`.

    \b
    Examples:
      qwenpaw agents delete research
      qwenpaw agents delete research --remove-workspace
      qwenpaw agents delete research --yes
    """
    resolved_base_url = resolve_base_url(ctx, base_url)

    if not yes:
        click.echo(f"WARNING: You are about to delete agent '{agent_id}'.")
        click.echo(
            "WARNING: This will stop the agent and remove it from agent list.",
        )
        if remove_workspace:
            click.echo(
                "WARNING: The local workspace directory will also be "
                "permanently deleted. This action cannot be undone.",
            )
        click.confirm("Continue with deletion?", abort=True)

    workspace_dir: Optional[Path] = None

    with agent_tools.create_agent_api_client(resolved_base_url) as client:
        if remove_workspace:
            workspace_dir = _fetch_agent_workspace_dir(client, agent_id)
            if workspace_dir is not None:
                workspace_dir = _ensure_workspace_within_working_dir(
                    workspace_dir,
                )
        response = client.delete(f"/agents/{agent_id}")

    if response.status_code == 404:
        raise click.ClickException(f"Agent '{agent_id}' not found.")

    if response.status_code == 400:
        detail = response.json().get("detail")
        raise click.ClickException(detail or "Failed to delete agent.")

    response.raise_for_status()
    result = response.json()

    if remove_workspace:
        if workspace_dir is None:
            raise click.ClickException(
                "Agent deleted, but workspace path could not be determined.",
            )
        result["workspace_dir"] = str(workspace_dir)
        result["workspace_removed"] = _remove_agent_workspace(workspace_dir)

    print_json(result)


@agents_group.command("chat")
@click.option(
    "--from-agent",
    "--agent-id",
    required=False,
    help="Source agent ID (required unless checking task with --task-id)",
)
@click.option(
    "--to-agent",
    required=False,
    help="Target agent ID (the one being asked, required unless checking "
    "task with --task-id)",
)
@click.option(
    "--text",
    required=False,
    help="Question or message text (required unless checking with --task-id)",
)
@click.option(
    "--session-id",
    default=None,
    help=(
        "Explicit session ID to reuse context. "
        "WARNING: Concurrent requests to the same session may fail. "
        "If omitted, a unique new session ID is generated automatically."
    ),
)
@click.option(
    "--mode",
    type=click.Choice(["stream", "final"], case_sensitive=False),
    default="final",
    help=(
        "Response mode: 'stream' for incremental updates, "
        "'final' for complete response only (default)"
    ),
)
@click.option(
    "--background",
    is_flag=True,
    default=False,
    help=(
        "Submit as background task (returns task_id immediately). "
        "Use with --task-id to check task status."
    ),
)
@click.option(
    "--task-id",
    default=None,
    help=(
        "Check status of existing background task. "
        "Must be used with --background flag."
    ),
)
@click.option(
    "--timeout",
    type=int,
    default=300,
    help="Request timeout in seconds (default 300)",
)
@click.option(
    "--json-output",
    is_flag=True,
    default=False,
    help="Output full JSON response instead of just text content",
)
@click.option(
    "--base-url",
    default=None,
    help="Override the API base URL. Defaults to global --host/--port.",
)
@click.pass_context
def chat_cmd(
    ctx: click.Context,
    from_agent: str,
    to_agent: str,
    text: str,
    session_id: Optional[str],
    mode: str,
    background: bool,
    task_id: Optional[str],
    timeout: int,
    json_output: bool,
    base_url: Optional[str],
) -> None:
    """Chat with another agent (inter-agent communication).

    Sends a message to another agent via /api/agent/process endpoint
    and returns the response. By default generates unique session IDs
    to avoid concurrency issues.

    \b
    Background Task Mode (NEW):
      # Submit complex task
      qwenpaw agents chat --background \\
        --from-agent bot_a --to-agent bot_b \\
        --text "Analyze large dataset"
      # Output: [TASK_ID: xxx] [SESSION: xxx]

      # Check task status (note --to-agent is optional here)
      qwenpaw agents chat --background --task-id <task_id>
      # Possible status: submitted → pending → running → finished
      # When finished, shows completed (success) or failed (error)

    \b
    Output Format (text mode):
      [SESSION: bot_a:to:bot_b:1773998835:abc123]

      Response content here...

    \b
        Session Management:
            - Default: Auto-generates unique session ID (new conversation)
            - To continue: See session_id in output first line
            - Pass with --session-id on next call to reuse context
            - Without --session-id: Always creates a new conversation

    \b
    Identity Prefix:
      - System auto-adds [Agent {from_agent} requesting] if missing
      - Prevents target agent from confusing message source

    \b
    Examples:
      # Simple chat (new conversation each time)
      qwenpaw agents chat \\
        --from-agent bot_a \\
        --to-agent bot_b \\
        --text "What is the weather today?"
      # Output: [SESSION: xxx]\\nThe weather is...

      # Continue conversation (use session_id from previous output)
      qwenpaw agents chat \\
        --from-agent bot_a \\
        --to-agent bot_b \\
        --session-id "bot_a:to:bot_b:1773998835:abc123" \\
        --text "What about tomorrow?"
      # Output: [SESSION: xxx] (same!)\\nTomorrow will be...

      # Background task (complex task)
      qwenpaw agents chat --background \\
        --from-agent bot_a \\
        --to-agent bot_b \\
        --text "Process complex data analysis"
      # Output: [TASK_ID: xxx] [SESSION: xxx]

      # Check background task status (note --to-agent is optional)
      qwenpaw agents chat --background --task-id <task_id>
      # Possible status: submitted → pending → running → finished
      # When finished, shows completed (success) or failed (error)

    \b
    Prerequisites:
      1. Use 'qwenpaw agents list' to discover available agents
      2. Ensure target agent (--to-agent) is configured and running
      3. Use 'qwenpaw chats list' to find existing sessions (optional)

    \b
    Returns:
      - Default: Text with [SESSION: xxx] header containing session_id
      - With --json-output: Full JSON with metadata and content
      - With --mode stream: Incremental updates (SSE)
      - With --background: Task ID and session ID for background task
      - With --background --task-id: Task status and result
        * Status flow: submitted → pending → running → finished
        * finished includes: completed (✅) or failed (❌)
"""
    resolved_base_url = resolve_base_url(ctx, base_url)

    # Validate parameters
    _validate_chat_parameters(
        ctx,
        background,
        task_id,
        from_agent,
        to_agent,
        text,
        mode,
    )

    # Check task status mode (early return)
    if background and task_id:
        _check_task_status(resolved_base_url, task_id, json_output, to_agent)
        return

    (
        final_session_id,
        request_payload,
        prefix_added,
    ) = agent_tools.build_agent_chat_request(
        to_agent,
        text,
        session_id=session_id,
        from_agent=from_agent,
    )

    click.echo(f"INFO: Using session_id: {final_session_id}", err=True)

    if prefix_added:
        click.echo(
            f"INFO: Auto-added identity prefix: [Agent {from_agent} "
            "requesting]",
            err=True,
        )

    if background:
        _submit_background_task(
            resolved_base_url,
            request_payload,
            to_agent,
            final_session_id,
            timeout,
        )
        return

    if mode == "stream":
        _handle_stream_mode(
            resolved_base_url,
            request_payload,
            to_agent,
            timeout,
        )
    else:
        _handle_final_mode(
            resolved_base_url,
            request_payload,
            to_agent,
            timeout,
            json_output,
        )
