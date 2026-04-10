# -*- coding: utf-8 -*-
"""CLI commands for managing agents and inter-agent communication."""
# pylint:disable=too-many-branches,too-many-statements
from __future__ import annotations

import json
import re
import time
from typing import Optional, Dict, Any
from uuid import uuid4

import click

from .http import client, print_json, resolve_base_url


def _generate_unique_session_id(from_agent: str, to_agent: str) -> str:
    """Generate unique session_id (concurrency-safe).

    Format: {from}:to:{to}:{timestamp_ms}:{uuid_short}
    Example: bot_a:to:bot_b:1710912345678:a1b2c3d4

    This ensures each call gets a unique session, avoiding concurrent
    access to the same session which would cause errors.
    """
    timestamp = int(time.time() * 1000)
    uuid_short = str(uuid4())[:8]
    return f"{from_agent}:to:{to_agent}:{timestamp}:{uuid_short}"


def _resolve_session_id(
    from_agent: str,
    to_agent: str,
    session_id: Optional[str],
    new_session: bool,
) -> str:
    """Resolve final session_id with new_session flag handling."""
    if new_session or not session_id:
        final_session_id = _generate_unique_session_id(from_agent, to_agent)
        if session_id:
            click.echo(
                f"INFO: --new-session flag used, "
                f"generating new session: {final_session_id}",
                err=True,
            )
        return final_session_id
    return session_id


def _ensure_agent_identity_prefix(text: str, from_agent: str) -> str:
    """Ensure text has agent identity prefix to prevent confusion.

    Automatically adds [Agent {from_agent} requesting] prefix if missing.
    Detects existing prefixes: [Agent xxx] or [来自智能体 xxx].

    Args:
        text: Original message text
        from_agent: Source agent ID

    Returns:
        Text with identity prefix (added if missing)
    """
    patterns = [
        r"^\[Agent\s+\w+",
        r"^\[来自智能体\s+\w+",
    ]
    for pattern in patterns:
        if re.match(pattern, text.strip()):
            return text

    return f"[Agent {from_agent} requesting] {text}"


def _parse_sse_line(line: str) -> Optional[Dict[str, Any]]:
    """Parse a single SSE line and return JSON data if valid."""
    line = line.strip()
    if line.startswith("data: "):
        try:
            return json.loads(line[6:])
        except json.JSONDecodeError:
            pass
    return None


def _extract_text_content(response_data: Dict[str, Any]) -> str:
    """Extract text content from agent response."""
    try:
        output = response_data.get("output", [])
        if not output:
            return ""

        last_msg = output[-1]
        content = last_msg.get("content", [])

        text_parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(item.get("text", ""))

        return "\n".join(text_parts).strip()
    except (KeyError, IndexError, TypeError):
        return ""


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
    c: Any,
    request_payload: Dict[str, Any],
    headers: Dict[str, str],
    timeout: int,
) -> None:
    """Handle streaming mode response."""
    with c.stream(
        "POST",
        "/agent/process",
        json=request_payload,
        headers=headers,
        timeout=timeout,
    ) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if line:
                click.echo(line)


def _handle_final_mode(
    c: Any,
    request_payload: Dict[str, Any],
    headers: Dict[str, str],
    timeout: int,
    json_output: bool,
) -> None:
    """Handle final mode response (collect all SSE events)."""
    response_data: Optional[Dict[str, Any]] = None

    with c.stream(
        "POST",
        "/agent/process",
        json=request_payload,
        headers=headers,
        timeout=timeout,
    ) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if line:
                parsed = _parse_sse_line(line)
                if parsed:
                    response_data = parsed

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
    c: Any,
    request_payload: Dict[str, Any],
    headers: Dict[str, str],
    session_id: str,
    timeout: int,
) -> None:
    """Submit background task and return task_id."""
    try:
        r = c.post(
            "/agent/process/task",
            json=request_payload,
            headers=headers,
            timeout=timeout,
        )
        r.raise_for_status()
        result = r.json()

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
        click.echo(f"  copaw agents chat --background --task-id {task_id}")

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
    base_url: str,
    task_id: str,
    json_output: bool,
    to_agent: Optional[str] = None,
) -> None:
    """Check background task status and display result."""
    with client(base_url) as c:
        headers = {"X-Agent-Id": to_agent} if to_agent else {}

        try:
            r = c.get(
                f"/agent/process/task/{task_id}",
                headers=headers,
                timeout=10,
            )
            r.raise_for_status()
            result = r.json()

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
                    f"  copaw agents chat --background --task-id {task_id}",
                )

            elif status == "pending":
                click.echo("⏸️  Task is pending in queue...")
                click.echo()
                click.echo(
                    "💡 Don't wait - handle other work first!",
                )
                click.echo("   Check again in a few seconds:")
                click.echo(
                    f"  copaw agents chat --background --task-id {task_id}",
                )

            elif status == "submitted":
                click.echo("📤 Task submitted, waiting to start...")
                click.echo()
                click.echo(
                    "💡 Don't wait - continue with other work!",
                )
                click.echo("   Check again in a few seconds:")
                click.echo(
                    f"  copaw agents chat --background --task-id {task_id}",
                )

            else:
                click.echo(f"Unknown status: {status}")
                if result:
                    print_json(result)

        except Exception as e:
            if hasattr(e, "response") and e.response.status_code == 404:
                click.echo(f"❌ Task not found: {task_id}", err=True)
                click.echo(
                    "   Task may have expired or never existed",
                    err=True,
                )
            else:
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
      copaw agents list
      copaw agents chat --from-agent bot_a --to-agent bot_b --text "..."
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
      copaw agents list
      copaw agents list --base-url http://192.168.1.100:8088

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
    with client(base_url) as c:
        r = c.get("/agents")
        r.raise_for_status()
        print_json(r.json())


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
        "If omitted, generates unique session ID automatically."
    ),
)
@click.option(
    "--new-session",
    is_flag=True,
    default=False,
    help=(
        "Force create new session even if --session-id provided. "
        "Generates unique session ID with timestamp."
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
    new_session: bool,
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
      copaw agents chat --background \\
        --from-agent bot_a --to-agent bot_b \\
        --text "Analyze large dataset"
      # Output: [TASK_ID: xxx] [SESSION: xxx]

      # Check task status (note --to-agent is optional here)
      copaw agents chat --background --task-id <task_id>
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
      copaw agents chat \\
        --from-agent bot_a \\
        --to-agent bot_b \\
        --text "What is the weather today?"
      # Output: [SESSION: xxx]\\nThe weather is...

      # Continue conversation (use session_id from previous output)
      copaw agents chat \\
        --from-agent bot_a \\
        --to-agent bot_b \\
        --session-id "bot_a:to:bot_b:1773998835:abc123" \\
        --text "What about tomorrow?"
      # Output: [SESSION: xxx] (same!)\\nTomorrow will be...

      # Background task (complex task)
      copaw agents chat --background \\
        --from-agent bot_a \\
        --to-agent bot_b \\
        --text "Process complex data analysis"
      # Output: [TASK_ID: xxx] [SESSION: xxx]

      # Check background task status (note --to-agent is optional)
      copaw agents chat --background --task-id <task_id>
      # Possible status: submitted → pending → running → finished
      # When finished, shows completed (success) or failed (error)

    \b
    Prerequisites:
      1. Use 'copaw agents list' to discover available agents
      2. Ensure target agent (--to-agent) is configured and running
      3. Use 'copaw chats list' to find existing sessions (optional)

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

    final_session_id = _resolve_session_id(
        from_agent,
        to_agent,
        session_id,
        new_session,
    )

    click.echo(f"INFO: Using session_id: {final_session_id}", err=True)

    final_text = _ensure_agent_identity_prefix(text, from_agent)
    if final_text != text:
        click.echo(
            f"INFO: Auto-added identity prefix: [Agent {from_agent} "
            "requesting]",
            err=True,
        )

    request_payload = {
        "session_id": final_session_id,
        "input": [
            {
                "role": "user",
                "content": [{"type": "text", "text": final_text}],
            },
        ],
    }

    with client(resolved_base_url) as c:
        headers = {"X-Agent-Id": to_agent}

        if background:
            _submit_background_task(
                c,
                request_payload,
                headers,
                final_session_id,
                timeout,
            )
            return

        if mode == "stream":
            _handle_stream_mode(
                c,
                request_payload,
                headers,
                timeout,
            )
        else:
            _handle_final_mode(
                c,
                request_payload,
                headers,
                timeout,
                json_output,
            )
