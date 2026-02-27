# -*- coding: utf-8 -*-
"""CLI commands for managing chats via HTTP API (/chats)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import click

from .http import client, print_json
from ..app.channels.schema import DEFAULT_CHANNEL


def _base_url(ctx: click.Context, base_url: Optional[str]) -> str:
    """Resolve base_url with priority:
    1) command --base-url
    2) global --host/--port
        (already resolved in main.py, may come from config.json)
    """
    if base_url:
        return base_url.rstrip("/")
    host = (ctx.obj or {}).get("host", "127.0.0.1")
    port = (ctx.obj or {}).get("port", 8088)
    return f"http://{host}:{port}"


@click.group("chats")
def chats_group() -> None:
    """Manage chat sessions via the HTTP API (/chats).

    \b
    Common examples:
      copaw chats list                    # List all chats
      copaw chats list --user-id alice    # Filter by user
      copaw chats get <chat_id>           # View details
      copaw chats create --session-id s1 --user-id u1
      copaw chats delete <chat_id>        # Delete a chat
    """


@chats_group.command("list")
@click.option(
    "--user-id",
    default=None,
    help="Filter by user ID, e.g. alice",
)
@click.option(
    "--channel",
    default=None,
    help="Filter by channel: console/imessage/dingtalk/discord/qq",
)
@click.option(
    "--base-url",
    default=None,
    help="Override API base URL, e.g. http://127.0.0.1:8088",
)
@click.pass_context
def list_chats(
    ctx: click.Context,
    user_id: Optional[str],
    channel: Optional[str],
    base_url: Optional[str],
) -> None:
    """List all chats, optionally filtered by user_id or channel.

    \b
    Examples:
      copaw chats list
      copaw chats list --user-id alice
      copaw chats list --channel discord
      copaw chats list --user-id alice --channel discord
    """
    base_url = _base_url(ctx, base_url)
    params: dict[str, str] = {}
    if user_id:
        params["user_id"] = user_id
    if channel:
        params["channel"] = channel
    with client(base_url) as c:
        r = c.get("/chats", params=params)
        r.raise_for_status()
        print_json(r.json())


@chats_group.command("get")
@click.argument("chat_id")
@click.option("--base-url", default=None, help="Override API base URL")
@click.pass_context
def get_chat(
    ctx: click.Context,
    chat_id: str,
    base_url: Optional[str],
) -> None:
    """View details of a specific chat (including message history).

    \b
    CHAT_ID  Chat UUID, obtainable via `copaw chats list`.

    \b
    Examples:
      copaw chats get 823845fe-dd13-43c2-ab8b-d05870602fd8
    """
    base_url = _base_url(ctx, base_url)
    with client(base_url) as c:
        r = c.get(f"/chats/{chat_id}")
        if r.status_code == 404:
            raise click.ClickException(f"chat not found: {chat_id}")
        r.raise_for_status()
        print_json(r.json())


@chats_group.command("create")
@click.option(
    "-f",
    "--file",
    "file_",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Create from JSON file (mutually exclusive with inline args)",
)
@click.option(
    "--name",
    default="New Chat",
    help="Chat name (default 'New Chat')",
)
@click.option(
    "--session-id",
    default=None,
    help="Session identifier, format: channel:user_id (required inline)",
)
@click.option(
    "--user-id",
    default=None,
    help="User ID (required for inline creation)",
)
@click.option(
    "--channel",
    default=DEFAULT_CHANNEL,
    help=(
        f"Channel name: console/imessage/dingtalk/discord/qq "
        f"(default {DEFAULT_CHANNEL})"
    ),
)
@click.option("--base-url", default=None, help="Override API base URL")
@click.pass_context
def create_chat(
    ctx: click.Context,
    file_: Optional[Path],
    name: str,
    session_id: Optional[str],
    user_id: Optional[str],
    channel: str,
    base_url: Optional[str],
) -> None:
    """Create a new chat.

    Use -f to specify a JSON file, or use inline parameters.

    \b
    Inline creation examples:
      copaw chats create --session-id "discord:alice" \\
        --user-id alice --name "My Chat"
      copaw chats create --session-id s1 --user-id u1 \\
        --channel imessage

    \b
    JSON file creation example:
      copaw chats create -f chat.json
    """
    base_url = _base_url(ctx, base_url)
    if file_ is not None:
        payload = json.loads(file_.read_text(encoding="utf-8"))
    else:
        if not session_id:
            raise click.UsageError(
                "--session-id is required for inline creation",
            )
        if not user_id:
            raise click.UsageError(
                "--user-id is required for inline creation",
            )
        payload = {
            "id": "",
            "name": name,
            "session_id": session_id,
            "user_id": user_id,
            "channel": channel,
            "meta": {},
        }
    with client(base_url) as c:
        r = c.post("/chats", json=payload)
        r.raise_for_status()
        print_json(r.json())


@chats_group.command("update")
@click.argument("chat_id")
@click.option("--name", required=True, help="New chat name")
@click.option("--base-url", default=None, help="Override API base URL")
@click.pass_context
def update_chat(
    ctx: click.Context,
    chat_id: str,
    name: str,
    base_url: Optional[str],
) -> None:
    """Update chat name.

    \b
    CHAT_ID  Chat UUID, obtainable via `copaw chats list`.

    \b
    Examples:
      copaw chats update <chat_id> --name "Renamed Chat"
    """
    base_url = _base_url(ctx, base_url)

    # Fetch existing spec, then patch name
    with client(base_url) as c:
        r = c.get("/chats")
        r.raise_for_status()
        specs = r.json()

    payload = next((s for s in specs if s.get("id") == chat_id), None)
    if payload is None:
        raise click.ClickException(f"chat not found: {chat_id}")

    payload["name"] = name

    with client(base_url) as c:
        r = c.put(f"/chats/{chat_id}", json=payload)
        if r.status_code == 404:
            raise click.ClickException(f"chat not found: {chat_id}")
        r.raise_for_status()
        print_json(r.json())


@chats_group.command("delete")
@click.argument("chat_id")
@click.option("--base-url", default=None, help="Override API base URL")
@click.pass_context
def delete_chat(
    ctx: click.Context,
    chat_id: str,
    base_url: Optional[str],
) -> None:
    """Delete a specific chat.

    Only deletes Chat metadata; does not clear Redis session state.

    \b
    CHAT_ID  Chat UUID, obtainable via `copaw chats list`.

    \b
    Examples:
      copaw chats delete 823845fe-dd13-43c2-ab8b-d05870602fd8
    """
    base_url = _base_url(ctx, base_url)
    with client(base_url) as c:
        r = c.delete(f"/chats/{chat_id}")
        if r.status_code == 404:
            raise click.ClickException(f"chat not found: {chat_id}")
        r.raise_for_status()
        print_json(r.json())
