# -*- coding: utf-8 -*-
"""CLI commands for managing agents and inter-agent communication."""
# pylint:disable=too-many-branches,too-many-statements
from __future__ import annotations

from pathlib import Path
from typing import Optional, Dict, Any, cast

import click
import httpx

from ..app.services.agent_communicate import (
    AgentChatPreparedRequest,
    AgentChatRequest,
    collect_agent_chat_final_response,
    extract_text_content,
    fetch_agents,
    get_agent_chat_task_status,
    prepare_agent_chat_request,
    stream_agent_chat_lines,
    submit_agent_chat_background_task,
)
from .http import print_json, resolve_base_url


def _load_chat_text(text: Optional[str], text_file: Optional[Path]) -> str:
    """Load chat text from inline text or file."""
    if text is not None:
        return text

    if text_file is None:
        return ""

    try:
        return text_file.read_text(encoding="utf-8")
    except OSError as exc:
        raise click.ClickException(
            f"Failed to read --text-file '{text_file}': {exc}",
        ) from exc


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

    text = extract_text_content(response_data)
    if text:
        click.echo(text)
    else:
        click.echo("(No text content in response)", err=True)


def _handle_stream_mode(
    base_url: str,
    prepared_request: AgentChatPreparedRequest,
    timeout: int,
) -> None:
    """Handle streaming mode response."""
    for line in stream_agent_chat_lines(base_url, prepared_request, timeout):
        click.echo(line)


def _handle_final_mode(
    base_url: str,
    prepared_request: AgentChatPreparedRequest,
    timeout: int,
    json_output: bool,
) -> None:
    """Handle final mode response (collect all SSE events)."""
    try:
        final_response = collect_agent_chat_final_response(
            base_url,
            prepared_request,
            timeout,
        )
    except ValueError:
        click.echo("(No response received)", err=True)
        return

    if json_output:
        print_json(final_response.response_data)
    else:
        _extract_and_print_text(
            final_response.response_data,
            session_id=final_response.session_id,
        )


def _submit_background_task(
    base_url: str,
    prepared_request: AgentChatPreparedRequest,
    timeout: int,
) -> None:
    """Submit background task and return task_id."""
    try:
        submission = submit_agent_chat_background_task(
            base_url,
            prepared_request,
            timeout,
        )

        click.echo(f"[TASK_ID: {submission.task_id}]")
        click.echo(f"[SESSION: {submission.session_id}]")
        click.echo()
        click.echo("✅ Task submitted successfully")
        click.echo()
        click.echo("💡 Don't wait - continue with other tasks!")
        click.echo("   Check status later (10-60s depending on complexity):")
        click.echo(
            "    qwenpaw agents chat --background --task-id "
            f"{submission.task_id}",
        )

    except (ValueError, httpx.HTTPError) as e:
        click.echo(f"ERROR: Failed to submit task: {e}", err=True)
        raise click.Abort()


def _validate_chat_parameters(
    ctx: click.Context,
    background: bool,
    task_id: Optional[str],
    from_agent: Optional[str],
    to_agent: Optional[str],
    text: Optional[str],
    text_file: Optional[Path],
    mode: str,
) -> None:
    """Validate chat command parameters."""
    text_source_count = int(text is not None) + int(text_file is not None)

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

        if text_source_count == 0:
            click.echo(
                "ERROR: one of --text or --text-file is required "
                "(unless checking task status)",
                err=True,
            )
            ctx.exit(1)

        if text_source_count > 1:
            click.echo(
                "ERROR: --text and --text-file are mutually exclusive",
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
    base_url: str,
    task_id: str,
    json_output: bool,
    to_agent: Optional[str] = None,
) -> None:
    """Check background task status and display result."""
    try:
        task_status = get_agent_chat_task_status(
            base_url,
            task_id,
            to_agent=to_agent,
            timeout=10,
        )

        if json_output:
            print_json(task_status.response_data)
            return

        status = task_status.status
        result = task_status.response_data
        click.echo(f"[TASK_ID: {task_id}]")
        click.echo(f"[STATUS: {status}]")
        click.echo()

        if status == "finished":
            task_result = cast(Dict[str, Any], result.get("result", {}))
            if task_status.task_status == "completed":
                click.echo("✅ Task completed")
                click.echo()
                _extract_and_print_text(
                    task_result,
                    session_id=task_result.get("session_id"),
                )
            elif task_status.task_status == "failed":
                error_info = cast(Dict[str, Any], task_result.get("error", {}))
                error_msg = error_info.get("message", "Unknown error")
                click.echo("❌ Task failed")
                click.echo()
                click.echo(f"Error: {error_msg}")
            else:
                click.echo(f"Status: {task_status.task_status}")
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

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            click.echo(f"❌ Task not found: {task_id}", err=True)
            click.echo(
                "   Task may have expired or never existed",
                err=True,
            )
        else:
            click.echo(f"ERROR: {e}", err=True)
        raise click.Abort()
    except Exception as e:
        click.echo(f"ERROR: {e}", err=True)
        raise click.Abort()


@click.group("agents")
def agents_group() -> None:
    """Manage agents and inter-agent communication.

    \b
    Commands:
      list    List all configured agents
      chat    Communicate with another agent

    \b
    Examples:
      qwenpaw agents list
      qwenpaw agents chat --from-agent bot_a \\
        --to-agent bot_b --text-file ./request.txt
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
    resolved_base_url = resolve_base_url(ctx, base_url)
    result = fetch_agents(resolved_base_url)
    print_json(result.response_data)


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
    help="Inline question or message text for short prompts.",
)
@click.option(
    "--text-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help=(
        "Read message text from file (recommended for prompts with quotes, "
        "newlines, or long context)."
    ),
)
@click.option(
    "--session-id",
    default=None,
    help=(
        "Explicit session ID to reuse context. "
        "WARNING: Concurrent requests to the same session may fail. "
        "If omitted, generates unique session ID automatically."
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
    text_file: Optional[Path],
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
        --text-file ./analyze_request.txt
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
      - Without --session-id: Always creates new conversation

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
        --text-file ./weather_request.txt
      # Output: [SESSION: xxx]\\nThe weather is...

      # Continue conversation (use session_id from previous output)
      qwenpaw agents chat \\
        --from-agent bot_a \\
        --to-agent bot_b \\
        --session-id "bot_a:to:bot_b:1773998835:abc123" \\
        --text-file ./follow_up.txt
      # Output: [SESSION: xxx] (same!)\\nTomorrow will be...

            # Short inline text is still supported
            qwenpaw agents chat \\
                --from-agent bot_a \\
                --to-agent bot_b \\
                --text "What is the weather today?"

      # Background task (complex task)
      qwenpaw agents chat --background \\
        --from-agent bot_a \\
        --to-agent bot_b \\
        --text-file ./complex_task.txt
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
            - Preferred input: --text-file for long or structured prompts
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
        text_file,
        mode,
    )

    # Check task status mode (early return)
    if background and task_id:
        _check_task_status(resolved_base_url, task_id, json_output, to_agent)
        return

    raw_text = _load_chat_text(text, text_file)
    prepared_request = prepare_agent_chat_request(
        AgentChatRequest(
            from_agent=from_agent,
            to_agent=to_agent,
            text=raw_text,
            session_id=session_id,
        ),
    )

    click.echo(
        f"INFO: Using session_id: {prepared_request.session_id}",
        err=True,
    )

    if prepared_request.identity_prefix_added:
        click.echo(
            f"INFO: Auto-added identity prefix: [Agent {from_agent} "
            "requesting]",
            err=True,
        )

    if background:
        _submit_background_task(
            resolved_base_url,
            prepared_request,
            timeout,
        )
        return

    if mode == "stream":
        _handle_stream_mode(
            resolved_base_url,
            prepared_request,
            timeout,
        )
    else:
        _handle_final_mode(
            resolved_base_url,
            prepared_request,
            timeout,
            json_output,
        )
