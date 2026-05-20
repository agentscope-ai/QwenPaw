# -*- coding: utf-8 -*-
"""CLI commands for managing xAI OAuth credentials.

Provides ``qwenpaw xai login``, ``qwenpaw xai status``, and
``qwenpaw xai logout``.  The flow is a self-contained PKCE loopback
dance against ``auth.x.ai`` — no Hermes / Grok-CLI install required.
"""

from __future__ import annotations

import asyncio
import json
import time

import click

from ..providers.xai_auth import XaiAuth, XaiAuthError, _resolve_auth_path
from ..providers.xai_login import (
    LOOPBACK_PORT,
    is_port_free,
    run_loopback_login,
)


@click.group("xai", help="Manage xAI / Grok OAuth credentials.")
def xai_group() -> None:
    """Manage xAI / Grok OAuth credentials."""


@xai_group.command("login")
@click.option(
    "--no-browser",
    is_flag=True,
    default=False,
    help="Skip auto-opening the browser; just print the URL.",
)
@click.option(
    "--timeout",
    type=int,
    default=300,
    show_default=True,
    help="How many seconds to wait for the browser callback.",
)
def login_cmd(no_browser: bool, timeout: int) -> None:
    """Run the xAI OAuth PKCE loopback flow and store tokens."""
    if not is_port_free():
        raise click.ClickException(
            f"Port {LOOPBACK_PORT} on 127.0.0.1 is in use. "
            f"The xAI OAuth client is registered against this exact "
            f"port — close whatever else is using it and retry "
            f"(e.g. `ss -tlnp 'sport = :{LOOPBACK_PORT}'`).",
        )
    try:
        auth_path = asyncio.run(
            run_loopback_login(open_browser=not no_browser, timeout=timeout),
        )
    except TimeoutError as e:
        raise click.ClickException(str(e))
    except Exception as e:
        raise click.ClickException(f"xAI login failed: {e}")
    click.echo(f"✓ Wrote credentials to {auth_path}")
    click.echo("  Restart copaw.service to pick them up:")
    click.echo("    systemctl --user restart copaw.service")


@xai_group.command("status")
def status_cmd() -> None:
    """Show the current xAI OAuth credential status."""
    path = _resolve_auth_path()
    if not path.exists():
        click.echo(f"No xAI credentials at {path}")
        click.echo("Run `qwenpaw xai login` to set up.")
        raise SystemExit(1)
    try:
        auth = XaiAuth()
    except Exception as e:
        raise click.ClickException(f"Failed to load {path}: {e}")
    try:
        creds = asyncio.run(auth.ensure_fresh())
    except XaiAuthError as e:
        click.echo(f"Auth file present but refresh failed: {e}")
        if e.relogin_required:
            click.echo("Run `qwenpaw xai login` to re-authenticate.")
        raise SystemExit(1) from e
    except Exception as e:
        raise click.ClickException(f"Refresh failed: {e}") from e
    click.echo(f"auth_path:  {creds.auth_path}")
    click.echo(f"auth_mode:  {creds.auth_mode}")
    click.echo(f"base_url:   {auth.base_url}")
    click.echo(f"expires_in: {creds.seconds_until_expiry}s")
    last = (
        json.loads(path.read_text()).get("last_refresh")
        if path.exists()
        else None
    )
    if last:
        click.echo(f"last_refresh: {last}")


@xai_group.command("logout")
@click.confirmation_option(
    prompt="This will delete ~/.xai/auth.json. Continue?",
)
def logout_cmd() -> None:
    """Delete the stored xAI OAuth credentials."""
    path = _resolve_auth_path()
    if not path.exists():
        click.echo(f"No credentials to remove at {path}")
        return
    path.unlink()
    click.echo(f"✓ Removed {path}")
    # Leave the parent ~/.xai dir in place — a subsequent login will
    # write straight into it and avoid a mkdir round-trip.  Touch the
    # mtime so any running XaiAuth instance hot-reloads on next call
    # and surfaces a clean "credentials missing" error instead of
    # using cached tokens that the user already revoked.
    try:
        path.parent.touch()
    except Exception:
        pass
    # Also: instruct the user to revoke the refresh_token server-side
    # if they want a hard logout — local deletion alone leaves the
    # token usable by anyone who exfiltrated it before deletion.
    click.echo(
        time.strftime(
            "%Y-%m-%dT%H:%M:%SZ — local logout only. "
            "Revoke the refresh_token at https://accounts.x.ai "
            "for a hard logout.",
            time.gmtime(),
        ),
    )
