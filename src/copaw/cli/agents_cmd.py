# -*- coding: utf-8 -*-
"""CLI commands for managing agents and inter-agent communication."""
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
    required=True,
    help="Source agent ID (the one making the request)",
)
@click.option(
    "--to-agent",
    required=True,
    help="Target agent ID (the one being asked)",
)
@click.option(
    "--text",
    required=True,
    help="Question or message text to send to the target agent",
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
    timeout: int,
    json_output: bool,
    base_url: Optional[str],
) -> None:
    """Chat with another agent (inter-agent communication).

    Sends a message to another agent via /api/agent/process endpoint
    and returns the response. By default generates unique session IDs
    to avoid concurrency issues.

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
    """
    base_url = resolve_base_url(ctx, base_url)

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

    with client(base_url) as c:
        headers = {"X-Agent-Id": to_agent}

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
