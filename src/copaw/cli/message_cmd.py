# -*- coding: utf-8 -*-
"""CLI commands for agent messaging - send to channels and inter-agent."""
from __future__ import annotations

import json
import re
import time
from typing import Optional, Dict, List, Any
from uuid import uuid4

import click

from .http import client, print_json


def _base_url(ctx: click.Context, base_url: Optional[str]) -> str:
    """Resolve base_url with priority:
    1) command --base-url
    2) global --host/--port (from ctx.obj)
    """
    if base_url:
        return base_url.rstrip("/")
    host = (ctx.obj or {}).get("host", "127.0.0.1")
    port = (ctx.obj or {}).get("port", 8088)
    return f"http://{host}:{port}"


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


@click.group("message")
def message_group() -> None:
    """Send messages to channels or other agents.

    \b
    Commands:
      list-agents     List all available agents
      list-sessions   List available sessions and users
      send            Send text message to a channel
      ask-agent       Ask another agent and get response

    \b
    Examples:
      copaw message list-agents
      copaw message list-sessions --agent-id my_bot
      copaw message send --agent-id bot --channel console ...
      copaw message ask-agent --from-agent a --to-agent b --text "..."
    """


# ===== Query Commands =====


@message_group.command("list-agents")
@click.option(
    "--base-url",
    default=None,
    help="Override the API base URL. Defaults to global --host/--port.",
)
@click.pass_context
def list_agents_cmd(ctx: click.Context, base_url: Optional[str]) -> None:
    """List all available agents for inter-agent communication.

    Returns a JSON list of all configured agents with their ID, name,
    description, and workspace directory.

    \b
    Examples:
      copaw message list-agents
      copaw message list-agents --base-url http://192.168.1.100:8088

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
    base_url = _base_url(ctx, base_url)
    with client(base_url) as c:
        r = c.get("/agents")
        r.raise_for_status()
        print_json(r.json())


@message_group.command("list-sessions")
@click.option(
    "--agent-id",
    required=True,
    help="Agent ID to list sessions for",
)
@click.option(
    "--channel",
    default=None,
    help="Filter by channel (e.g., console, dingtalk, feishu)",
)
@click.option(
    "--user-id",
    default=None,
    help="Filter by user ID",
)
@click.option(
    "--limit",
    default=20,
    type=int,
    help="Maximum number of sessions to return (default 20)",
)
@click.option(
    "--base-url",
    default=None,
    help="Override the API base URL. Defaults to global --host/--port.",
)
@click.pass_context
def list_sessions_cmd(
    ctx: click.Context,
    agent_id: str,
    channel: Optional[str],
    user_id: Optional[str],
    limit: int,
    base_url: Optional[str],
) -> None:
    """List available sessions and users for sending messages.

    IMPORTANT: Session ID determines conversation history.
    - Same session_id = Continuous conversation with context
    - Different session_id = Brand new conversation (no history)
    - Use returned session_id with --session-id flag to continue chatting

    Returns:
    - sessions: All chat sessions (with session_id for reuse)
    - unique_users: Aggregated user information with channels and counts
    - inter_agent_sessions: Sessions for communication with other agents

    \b
    Examples:
      # Basic usage
      copaw message list-sessions --agent-id my_bot

      # Find existing inter-agent sessions to continue conversation
      copaw message list-sessions --agent-id my_bot | \\
        jq '.inter_agent_sessions[] | select(.to_agent=="finance_expert")'

      # Filter by channel
      copaw message list-sessions --agent-id my_bot --channel dingtalk

      # Filter by user and limit results
      copaw message list-sessions --agent-id my_bot --user-id alice --limit 10

    \b
    Output format:
      {
        "agent_id": "my_bot",
        "sessions": [...],
        "unique_users": [
          {
            "user_id": "alice",
            "channels": ["dingtalk", "console"],
            "session_count": 3,
            "last_active": "2024-03-20T10:30:00Z"
          }
        ],
        "inter_agent_sessions": [
          {
            "from_agent": "my_bot",
            "to_agent": "finance_expert",
            "session_id": "my_bot:to:finance_expert:1710912345:a1b2c3d4",
            "last_active": "2024-03-20T09:00:00Z"
          }
        ]
      }

    \b
    Session ID Usage:
      To continue an existing conversation, copy the session_id from output
      and use it with ask-agent:

        SESSION_ID=$(copaw message list-sessions --agent-id bot_a | \\
          jq -r '.inter_agent_sessions[0].session_id')

        copaw message ask-agent --from-agent bot_a --to-agent bot_b \\
          --session-id "$SESSION_ID" --text "Continue our discussion..."
    """
    base_url = _base_url(ctx, base_url)

    params: Dict[str, str] = {}
    if channel:
        params["channel"] = channel
    if user_id:
        params["user_id"] = user_id

    with client(base_url) as c:
        headers = {"X-Agent-Id": agent_id}
        r = c.get("/chats", params=params, headers=headers)
        r.raise_for_status()

        chats = r.json()
        sessions = chats[:limit] if limit > 0 else chats

        # Aggregate unique users with metadata
        users_map: Dict[str, Dict[str, Any]] = {}
        inter_agent_sessions: List[Dict[str, Any]] = []

        for chat in sessions:
            uid = chat.get("user_id", "")
            sid = chat.get("session_id", "")
            ch = chat.get("channel", "")
            updated_at = chat.get("updated_at")

            # Check if this is an inter-agent session
            # Format: {from_agent}:to:{to_agent}:...
            if ":to:" in sid:
                parts = sid.split(":to:", 1)
                if len(parts) == 2:
                    from_part = parts[0]
                    # Extract to_agent (before next colon if exists)
                    to_part = (
                        parts[1].split(":", 1)[0]
                        if ":" in parts[1]
                        else parts[1]
                    )

                    inter_agent_sessions.append(
                        {
                            "from_agent": from_part,
                            "to_agent": to_part,
                            "session_id": sid,
                            "last_active": updated_at,
                            "chat_id": chat.get("id"),
                            "chat_name": chat.get("name"),
                        },
                    )

            # Aggregate user info
            if uid:
                if uid not in users_map:
                    users_map[uid] = {
                        "user_id": uid,
                        "channels": set(),
                        "session_count": 0,
                        "last_active": updated_at,
                    }

                users_map[uid]["channels"].add(ch)
                users_map[uid]["session_count"] += 1

                # Update last_active to the most recent
                if updated_at and (
                    not users_map[uid]["last_active"]
                    or updated_at > users_map[uid]["last_active"]
                ):
                    users_map[uid]["last_active"] = updated_at

        # Convert sets to sorted lists for JSON serialization
        unique_users = [
            {
                "user_id": u["user_id"],
                "channels": sorted(list(u["channels"])),
                "session_count": u["session_count"],
                "last_active": u["last_active"],
            }
            for u in users_map.values()
        ]

        # Sort by last_active (most recent first)
        unique_users.sort(
            key=lambda x: x["last_active"] or "",
            reverse=True,
        )
        inter_agent_sessions.sort(
            key=lambda x: x["last_active"] or "",
            reverse=True,
        )

        result = {
            "agent_id": agent_id,
            "total_sessions": len(chats),
            "sessions": sessions,
            "unique_users": unique_users,
            "inter_agent_sessions": inter_agent_sessions,
        }

        print_json(result)


# ===== Sending Commands =====


@message_group.command("send")
@click.option(
    "--agent-id",
    required=True,
    help="Agent ID sending the message",
)
@click.option(
    "--channel",
    required=True,
    help=(
        "Target channel (e.g., console, dingtalk, feishu, discord, "
        "imessage, qq)"
    ),
)
@click.option(
    "--target-user",
    required=True,
    help=("Target user ID (REQUIRED, get from 'list-sessions' query)"),
)
@click.option(
    "--target-session",
    required=True,
    help=("Target session ID (REQUIRED, get from 'list-sessions' query)"),
)
@click.option(
    "--text",
    required=True,
    help="Text message to send",
)
@click.option(
    "--base-url",
    default=None,
    help="Override the API base URL. Defaults to global --host/--port.",
)
@click.pass_context
def send_cmd(
    ctx: click.Context,
    agent_id: str,
    channel: str,
    target_user: str,
    target_session: str,
    text: str,
    base_url: Optional[str],
) -> None:
    """Send a text message to a channel.

    This command allows an agent to proactively send messages to users
    via configured channels (console, dingtalk, feishu, etc.).

    IMPORTANT: All 5 parameters are REQUIRED. You MUST query first to get
    valid target-user and target-session values.

    \b
    Complete Usage Flow:
      Step 1 - Query available sessions (REQUIRED):
        copaw message list-sessions --agent-id my_bot --channel console

      Step 2 - Extract parameters from query output:
        user_id: "alice"
        session_id: "alice_session_001"

      Step 3 - Send message using queried parameters:
        copaw message send --agent-id my_bot --channel console \\
          --target-user alice --target-session alice_session_001 \\
          --text "Hello!"

    \b
    Examples with jq automation:
      # Query and auto-extract parameters
      SESSIONS=$(copaw message list-sessions --agent-id bot --channel console)
      USER=$(echo "$SESSIONS" | jq -r '.sessions[0].user_id')
      SESSION=$(echo "$SESSIONS" | jq -r '.sessions[0].session_id')

      # Send message
      copaw message send --agent-id bot --channel console \\
        --target-user "$USER" --target-session "$SESSION" \\
        --text "Automated notification"

    \b
    Prerequisites:
      1. MUST use 'list-sessions' to get valid target-user and target-session
      2. Ensure the channel is properly configured
      3. All 5 parameters are required (no defaults)

    \b
    Returns:
      JSON response with success status and message details.
    """
    base_url = _base_url(ctx, base_url)

    payload = {
        "channel": channel,
        "target_user": target_user,
        "target_session": target_session,
        "text": text,
    }

    with client(base_url) as c:
        headers = {"X-Agent-Id": agent_id}
        r = c.post("/messages/send", json=payload, headers=headers)
        r.raise_for_status()
        print_json(r.json())


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


def _handle_stream_mode(
    c: Any,
    request_payload: Dict[str, Any],
    headers: Dict[str, str],
    timeout: int,
    from_agent: str,
    channel: Optional[str],
    target_user: Optional[str],
    target_session: Optional[str],
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
                if channel and target_user and target_session:
                    _forward_to_channel(
                        c,
                        from_agent,
                        channel,
                        target_user,
                        target_session,
                        line,
                    )


def _parse_sse_line(line: str) -> Optional[Dict[str, Any]]:
    """Parse a single SSE line and return JSON data if valid."""
    line = line.strip()
    if line.startswith("data: "):
        try:
            return json.loads(line[6:])
        except json.JSONDecodeError:
            pass
    return None


def _handle_final_mode(
    c: Any,
    request_payload: Dict[str, Any],
    headers: Dict[str, str],
    timeout: int,
    from_agent: str,
    channel: Optional[str],
    target_user: Optional[str],
    target_session: Optional[str],
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
        # Include session_id in JSON output for easy reuse
        if "session_id" not in response_data:
            response_data["session_id"] = request_payload.get("session_id")
        print_json(response_data)
    else:
        # Print text with metadata header containing session_id
        _extract_and_print_text(
            response_data,
            session_id=request_payload.get("session_id"),
        )

    if channel and target_user and target_session and not json_output:
        text_content = _extract_text_content(response_data)
        if text_content:
            _forward_to_channel(
                c,
                from_agent,
                channel,
                target_user,
                target_session,
                text_content,
            )


@message_group.command("ask-agent")
@click.option(
    "--from-agent",
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
    "--channel",
    default=None,
    help=(
        "Optional: Channel to send response to (e.g., console, dingtalk). "
        "If specified, requires --target-user and --target-session."
    ),
)
@click.option(
    "--target-user",
    default=None,
    help="Required when --channel is specified: target user ID",
)
@click.option(
    "--target-session",
    default=None,
    help="Required when --channel is specified: target session ID",
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
def ask_agent_cmd(
    ctx: click.Context,
    from_agent: str,
    to_agent: str,
    text: str,
    session_id: Optional[str],
    new_session: bool,
    channel: Optional[str],
    target_user: Optional[str],
    target_session: Optional[str],
    mode: str,
    timeout: int,
    json_output: bool,
    base_url: Optional[str],
) -> None:
    """Ask another agent and get response (inter-agent communication).

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
      # Simple ask (new conversation each time)
      copaw message ask-agent \\
        --from-agent bot_a \\
        --to-agent bot_b \\
        --text "What is the weather today?"
      # Output: [SESSION: xxx]\\nThe weather is...

      # Continue conversation (use session_id from previous output)
      copaw message ask-agent \\
        --from-agent bot_a \\
        --to-agent bot_b \\
        --session-id "bot_a:to:bot_b:1773998835:abc123" \\
        --text "What about tomorrow?"
      # Output: [SESSION: xxx] (same!)\\nTomorrow will be...

    \b
    Prerequisites:
      1. Use 'copaw message list-agents' to discover available agents
      2. Ensure target agent (--to-agent) is configured and running
      3. If using --channel, verify with 'copaw channels list'

    \b
    Returns:
      - Default: Text with [META] block containing session_id
      - With --json-output: Full JSON with metadata and content
      - With --mode stream: Incremental updates (SSE)
    """
    base_url = _base_url(ctx, base_url)

    if channel and (not target_user or not target_session):
        raise click.UsageError(
            "--channel requires both --target-user and --target-session",
        )

    final_session_id = _resolve_session_id(
        from_agent,
        to_agent,
        session_id,
        new_session,
    )

    # Always output session_id so it can be reused
    click.echo(f"INFO: Using session_id: {final_session_id}", err=True)

    # Auto-add agent identity prefix if missing to prevent confusion
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
                from_agent,
                channel,
                target_user,
                target_session,
            )
        else:
            _handle_final_mode(
                c,
                request_payload,
                headers,
                timeout,
                from_agent,
                channel,
                target_user,
                target_session,
                json_output,
            )


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
    # Print metadata header with session_id
    if session_id:
        click.echo(f"[SESSION: {session_id}]")
        click.echo()

    # Print response content
    text = _extract_text_content(response_data)
    if text:
        click.echo(text)
    else:
        click.echo("(No text content in response)", err=True)


def _forward_to_channel(
    c: Any,
    agent_id: str,
    channel: str,
    target_user: str,
    target_session: str,
    text: str,
) -> None:
    """Forward response to a channel."""
    payload = {
        "channel": channel,
        "target_user": target_user,
        "target_session": target_session,
        "text": text,
    }
    headers = {"X-Agent-Id": agent_id}
    r = c.post("/messages/send", json=payload, headers=headers)
    if r.status_code != 200:
        click.echo(
            f"WARNING: Failed to forward to channel: {r.status_code}",
            err=True,
        )
