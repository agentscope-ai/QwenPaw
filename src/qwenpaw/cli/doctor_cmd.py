# -*- coding: utf-8 -*-
"""`copaw doctor` — read-only checks; `copaw doctor fix` — conservative repairs with backup."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import click
import httpx

from ..__version__ import __version__
from ..app.auth import has_registered_users, is_auth_enabled
from ..config import load_config
from ..config.utils import strict_validate_config_file
from ..constant import WORKING_DIR
from ..providers.provider import Provider
from ..providers.provider_manager import ProviderManager
from ..utils.console_static import CONSOLE_STATIC_ENV, resolve_console_static_dir
from .doctor_checks import (
    active_llm_local_failure_hint,
    api_target_mismatch_note,
    browser_automation_notes,
    check_agent_json_profiles,
    check_agent_profile_workspaces,
    check_agent_workspace_writable,
    check_copaw_log_writable,
    check_cron_jobs_files,
    check_enabled_agents_load_agent_config,
    check_enabled_agents_model_connections,
    console_static_diagnostic_notes,
    enabled_channel_notes,
    environment_summary_lines,
    legacy_single_agent_workspace_note,
    load_raw_config_dict,
    mcp_client_notes,
    memory_embedding_notes,
    provider_overview_notes,
    scan_unknown_config_keys,
    security_baseline_notes,
    skill_layout_notes,
    copaw_local_llm_deep_notes,
    startup_extra_volume_disk_notes,
    workspace_hygiene_notes,
)
from .doctor_connectivity import collect_deep_channel_connectivity_notes
from .doctor_registry import DoctorRunContext, run_extension_contributions
from .http import resolve_base_url


def _provider_is_configured(provider: Provider) -> tuple[bool, str]:
    if provider.is_local:
        return True, ""
    if not (provider.base_url or "").strip():
        return False, "base_url is not set"
    if provider.require_api_key and not (provider.api_key or "").strip():
        return False, "API key is required but not set"
    return True, ""


def _check_working_dir() -> tuple[bool, str]:
    if not WORKING_DIR.is_dir():
        return False, f"missing: {WORKING_DIR}"
    if not os.access(WORKING_DIR, os.W_OK):
        return False, f"not writable: {WORKING_DIR}"
    return True, str(WORKING_DIR)


def _check_console_static_files() -> tuple[bool, str]:
    static_dir = resolve_console_static_dir()
    index = Path(static_dir) / "index.html"
    if index.is_file():
        return True, f"{static_dir}"
    return (
        False,
        f"index.html missing under {static_dir}\n"
        "        Build: `npm ci && npm run build` in the `console/` directory, "
        f"or set {CONSOLE_STATIC_ENV} to a directory that contains index.html.",
    )


def _check_web_auth(base: str) -> tuple[bool, str]:
    if not is_auth_enabled():
        return True, "disabled (default) — open the console without logging in"
    if not has_registered_users():
        return (
            False,
            "enabled but no account registered yet.\n"
            f"        1) Start `copaw app`, open {base}/ in a browser.\n"
            "        2) Complete registration (single user) on the login page.\n"
            "        For automation, set COPAW_AUTH_USERNAME and "
            "COPAW_AUTH_PASSWORD — the server creates the user on startup.",
        )
    return (
        True,
        f"enabled — open {base}/ and sign in; the console stores your session. "
        "API clients must send Authorization: Bearer <token> from login.",
    )


def _classify_console_root_response(resp: httpx.Response) -> tuple[bool, str]:
    ct = (resp.headers.get("content-type") or "").lower()
    if "text/html" in ct:
        return True, f"HTTP GET / returns HTML (HTTP {resp.status_code})"
    text = (resp.text or "").lstrip()
    if text.startswith("<!DOCTYPE") or text.startswith("<html"):
        return True, f"HTTP GET / looks like HTML (HTTP {resp.status_code})"
    if "application/json" in ct or text.startswith("{"):
        try:
            payload = resp.json()
        except json.JSONDecodeError:
            return False, "HTTP GET / returned JSON that is not parseable"
        if isinstance(payload, dict):
            msg = str(payload.get("message", ""))
            if "Web Console is not available" in msg:
                return (
                    False,
                    "server is running but the console bundle is not installed — "
                    "build `console/` or set "
                    f"{CONSOLE_STATIC_ENV}, then restart `copaw app`.",
                )
        return False, "HTTP GET / returned JSON instead of the console page"
    return False, f"unexpected GET / response (content-type: {ct or 'unknown'})"


async def _check_active_llm(
    timeout: float,
    deep: bool,
) -> tuple[bool, str, list[str]]:
    manager = ProviderManager.get_instance()
    slot = manager.get_active_model()
    if (
        slot is None
        or not (slot.provider_id or "").strip()
        or not (slot.model or "").strip()
    ):
        return (
            False,
            "no active LLM slot — run `copaw models list` and configure "
            "an active model",
            [],
        )
    provider = manager.get_provider(slot.provider_id)
    if provider is None:
        return False, f"provider not found: {slot.provider_id!r}", []
    ok, reason = _provider_is_configured(provider)
    if not ok:
        return False, f"{slot.provider_id}: {reason}", []

    deep_notes: list[str] = []
    if deep and (slot.provider_id or "").strip() == "copaw-local":
        deep_notes = copaw_local_llm_deep_notes()

    if not getattr(provider, "support_connection_check", True):
        return (
            True,
            f"{slot.provider_id} / {slot.model} (live check skipped for "
            f"this provider)",
            deep_notes,
        )
    ping_ok, ping_msg = await provider.check_model_connection(
        slot.model,
        timeout=timeout,
    )
    if not ping_ok:
        detail = f": {ping_msg}" if ping_msg else ""
        body = f"{slot.provider_id} / {slot.model} unreachable{detail}"
        if getattr(provider, "is_local", False) or slot.provider_id in (
            "ollama",
            "lmstudio",
            "copaw-local",
        ):
            hint = active_llm_local_failure_hint(provider, slot.provider_id)
            if hint:
                body = f"{body}\n{hint}"
        return False, body, deep_notes
    return True, f"{slot.provider_id} / {slot.model} (reachable)", deep_notes


def run_doctor_checks(
    ctx: click.Context,
    timeout: float,
    llm_timeout: float,
    deep: bool,
) -> None:
    """Run read-only ``copaw doctor`` checks (no disk mutations)."""
    base = resolve_base_url(ctx, None).rstrip("/")
    failed = False

    click.echo("=== Environment ===")
    for line in environment_summary_lines():
        click.echo(f"  {line}")

    click.echo("\n=== Config ===")
    config_ok, detail = strict_validate_config_file()
    if config_ok:
        click.echo(click.style("OK", fg="green") + f" — {detail}")
    else:
        failed = True
        click.echo(click.style("FAIL", fg="red") + f"\n{detail}", err=True)

    raw_cfg = load_raw_config_dict()
    if raw_cfg is not None:
        unknown = scan_unknown_config_keys(raw_cfg)
        if unknown:
            click.echo("\n=== Config (unknown keys) ===")
            click.echo(
                click.style("Note:", fg="yellow")
                + " keys present on disk that are not on the current schema "
                "(informational only; doctor does not remove or rewrite them):",
            )
            for item in unknown:
                click.echo(f"  - {item}")

    if config_ok:
        cfg = load_config()
        legacy = legacy_single_agent_workspace_note(cfg)
        if legacy:
            click.echo("\n=== Multi-agent / workspace ===")
            click.echo(click.style("Note:", fg="yellow") + f" {legacy}")

        click.echo("\n=== Agents ===")
        click.echo("Workspaces")
        ws_ok, ws_detail = check_agent_profile_workspaces(cfg)
        if ws_ok:
            click.echo(click.style("OK", fg="green") + f" — {ws_detail}")
        else:
            failed = True
            click.echo(
                click.style("FAIL", fg="red") + f" — {ws_detail}",
                err=True,
            )

        click.echo("Profiles (agent.json)")
        aj_ok, aj_detail = check_agent_json_profiles(cfg)
        if aj_ok:
            click.echo(click.style("OK", fg="green") + f" — {aj_detail}")
        else:
            failed = True
            click.echo(
                click.style("FAIL", fg="red") + f" — {aj_detail}",
                err=True,
            )

        click.echo("Config load (enabled)")
        acl_ok, acl_detail = check_enabled_agents_load_agent_config(cfg)
        if acl_ok:
            click.echo(click.style("OK", fg="green") + f" — {acl_detail}")
        else:
            failed = True
            click.echo(
                click.style("FAIL", fg="red") + f" — {acl_detail}",
                err=True,
            )

        click.echo("\n=== Channels (enabled) ===")
        ch_notes = enabled_channel_notes(cfg)
        if ch_notes:
            for line in ch_notes:
                click.echo(click.style("Note:", fg="yellow") + f" {line}")
        else:
            click.echo(
                click.style("OK", fg="green")
                + " — no enabled-channel credential warnings",
            )

        click.echo("\n=== Doctor extensions ===")
        ext_ctx = DoctorRunContext(
            cfg=cfg,
            raw_cfg=raw_cfg,
            cli_base_url=base,
            timeout=timeout,
            deep=deep,
        )
        ext_results = run_extension_contributions(ext_ctx)
        ext_nonempty = [(c, ls) for c, ls in ext_results if ls]
        if not ext_nonempty:
            click.echo(
                click.style("OK", fg="green")
                + " — no extension notes (register via copaw.doctor entry points "
                "or register_doctor_contribution)",
            )
        else:
            for contrib_id, lines in ext_nonempty:
                click.echo(f"  [{contrib_id}]")
                for line in lines:
                    click.echo(
                        click.style("Note:", fg="yellow") + f" {line}",
                    )

        if deep:
            click.echo("\n=== Channels (connectivity, --deep) ===")
            conn_notes = collect_deep_channel_connectivity_notes(cfg, timeout)
            if conn_notes:
                click.echo(
                    click.style("Note:", fg="yellow")
                    + " reachability issues (firewalled/offline is common):",
                )
                for line in conn_notes:
                    click.echo(f"  - {line}")
            else:
                click.echo(
                    click.style("OK", fg="green")
                    + " — no connectivity warnings for enabled channels",
                )

        click.echo("\n=== MCP clients ===")
        mcp_notes = mcp_client_notes(cfg)
        if mcp_notes:
            for line in mcp_notes:
                click.echo(click.style("Note:", fg="yellow") + f" {line}")
        else:
            click.echo(
                click.style("OK", fg="green") + " — no MCP client warnings",
            )

        click.echo("\n=== Skills ===")
        sk_notes = skill_layout_notes(cfg)
        if sk_notes:
            for line in sk_notes:
                click.echo(click.style("Note:", fg="yellow") + f" {line}")
        else:
            click.echo(
                click.style("OK", fg="green") + " — no skill layout warnings",
            )

        click.echo("\n=== Browser (browser_use / Playwright) ===")
        br_notes = browser_automation_notes(cfg)
        if br_notes:
            for line in br_notes:
                click.echo(click.style("Note:", fg="yellow") + f" {line}")
        else:
            click.echo(
                click.style("OK", fg="green")
                + " — no browser automation warnings",
            )

        click.echo("\n=== Security (baseline) ===")
        sec_notes = security_baseline_notes(cfg)
        if sec_notes:
            click.echo(
                click.style("Note:", fg="yellow") + " review security posture:",
            )
            for line in sec_notes:
                click.echo(f"  - {line}")
        else:
            click.echo(
                click.style("OK", fg="green") + " — no baseline warnings",
            )

        click.echo("\n=== Memory / embedding ===")
        mem_notes = memory_embedding_notes(cfg)
        if mem_notes:
            for line in mem_notes:
                click.echo(click.style("Note:", fg="yellow") + f" {line}")
        else:
            click.echo(
                click.style("OK", fg="green") + " — no embedding warnings",
            )

        click.echo("\n=== Workspace hygiene ===")
        hy_notes = workspace_hygiene_notes(cfg)
        if hy_notes:
            for line in hy_notes:
                click.echo(click.style("Note:", fg="yellow") + f" {line}")
        else:
            click.echo(
                click.style("OK", fg="green") + " — no hygiene warnings",
            )

        click.echo("\n=== Cron (jobs.json) ===")
        cj_ok, cj_detail = check_cron_jobs_files(cfg)
        if cj_ok:
            click.echo(click.style("OK", fg="green") + f" — {cj_detail}")
        else:
            failed = True
            click.echo(click.style("FAIL", fg="red") + f" — {cj_detail}", err=True)
    else:
        click.echo("\n=== Agents ===")
        click.echo("Workspaces")
        click.echo(
            click.style("SKIP", fg="yellow")
            + " — fix root config validation first",
        )
        click.echo("Profiles (agent.json)")
        click.echo(
            click.style("SKIP", fg="yellow")
            + " — fix root config validation first",
        )
        click.echo("Config load (enabled)")
        click.echo(
            click.style("SKIP", fg="yellow")
            + " — fix root config validation first",
        )
        click.echo("\n=== Channels (enabled) ===")
        click.echo(
            click.style("SKIP", fg="yellow")
            + " — fix root config validation first",
        )
        click.echo("\n=== Doctor extensions ===")
        click.echo(
            click.style("SKIP", fg="yellow")
            + " — fix root config validation first",
        )
        if deep:
            click.echo("\n=== Channels (connectivity, --deep) ===")
            click.echo(
                click.style("SKIP", fg="yellow")
                + " — fix root config validation first",
            )
        click.echo("\n=== MCP clients ===")
        click.echo(
            click.style("SKIP", fg="yellow")
            + " — fix root config validation first",
        )
        click.echo("\n=== Skills ===")
        click.echo(
            click.style("SKIP", fg="yellow")
            + " — fix root config validation first",
        )
        click.echo("\n=== Browser (browser_use / Playwright) ===")
        br_skip = browser_automation_notes(None)
        if br_skip:
            for line in br_skip:
                click.echo(click.style("Note:", fg="yellow") + f" {line}")
        else:
            click.echo(
                click.style("OK", fg="green")
                + " — no browser automation warnings",
            )
        click.echo("\n=== Security (baseline) ===")
        click.echo(
            click.style("SKIP", fg="yellow")
            + " — fix root config validation first",
        )
        click.echo("\n=== Memory / embedding ===")
        click.echo(
            click.style("SKIP", fg="yellow")
            + " — fix root config validation first",
        )
        click.echo("\n=== Workspace hygiene ===")
        click.echo(
            click.style("SKIP", fg="yellow")
            + " — fix root config validation first",
        )
        click.echo("\n=== Cron (jobs.json) ===")
        click.echo(
            click.style("SKIP", fg="yellow")
            + " — fix root config validation first",
        )

    click.echo("\n=== Working directory ===")
    wd_ok, detail = _check_working_dir()
    if wd_ok:
        click.echo(click.style("OK", fg="green") + f" — {detail}")
    else:
        failed = True
        click.echo(click.style("FAIL", fg="red") + f" — {detail}", err=True)
        click.echo(
            "Hint: set COPAW_WORKING_DIR or run `copaw init`.",
            err=True,
        )

    click.echo("\n=== Startup paths ===")
    if not wd_ok:
        click.echo(
            click.style("SKIP", fg="yellow") + " — working directory not OK",
        )
    else:
        log_ok, log_detail = check_copaw_log_writable()
        if log_ok:
            click.echo(
                click.style("OK", fg="green")
                + f" — copaw.log appendable ({log_detail})",
            )
        else:
            failed = True
            click.echo(
                click.style("FAIL", fg="red") + f"\n{log_detail}",
                err=True,
            )
        if config_ok:
            cfg_sp = load_config()
            ws_w_ok, ws_w_detail = check_agent_workspace_writable(cfg_sp)
            if ws_w_ok:
                click.echo(
                    click.style("OK", fg="green") + f" — {ws_w_detail}",
                )
            else:
                failed = True
                click.echo(
                    click.style("FAIL", fg="red") + f"\n{ws_w_detail}",
                    err=True,
                )
            vol_notes = startup_extra_volume_disk_notes(cfg_sp)
        else:
            click.echo(
                click.style("SKIP", fg="yellow")
                + " — agent workspace writability (fix root config validation first)",
            )
            vol_notes = startup_extra_volume_disk_notes(None)
        for line in vol_notes:
            click.echo(click.style("Note:", fg="yellow") + f" {line}")

    click.echo("\n=== Console (static files) ===")
    cs_ok, detail = _check_console_static_files()
    if cs_ok:
        click.echo(click.style("OK", fg="green") + f" — {detail}")
    else:
        failed = True
        click.echo(click.style("FAIL", fg="red") + f"\n{detail}", err=True)
    for line in console_static_diagnostic_notes():
        click.echo(click.style("Note:", fg="yellow") + f" {line}")

    click.echo("\n=== Web authentication ===")
    auth_ok, detail = _check_web_auth(base)
    if auth_ok:
        click.echo(click.style("OK", fg="green") + f" — {detail}")
    else:
        failed = True
        click.echo(click.style("FAIL", fg="red") + f"\n{detail}", err=True)

    if config_ok:
        click.echo("\n=== Providers (custom) ===")
        try:
            prov_notes = provider_overview_notes()
        except Exception as exc:  # pylint: disable=broad-exception-caught
            prov_notes = [f"could not list providers: {exc}"]
        if prov_notes:
            for line in prov_notes:
                click.echo(click.style("Note:", fg="yellow") + f" {line}")
        else:
            click.echo(
                click.style("OK", fg="green")
                + " — no custom provider configuration warnings",
            )

    click.echo("\n=== Active LLM ===")
    llm_ok, llm_detail, llm_notes = asyncio.run(
        _check_active_llm(llm_timeout, deep),
    )
    if llm_ok:
        click.echo(click.style("OK", fg="green") + f" — {llm_detail}")
    else:
        failed = True
        click.echo(click.style("FAIL", fg="red") + f" — {llm_detail}", err=True)
    for line in llm_notes:
        click.echo(click.style("Note:", fg="yellow") + f" {line}")

    if config_ok:
        click.echo("\n=== Models (per agent) ===")
        aok, lines, extra_notes = asyncio.run(
            check_enabled_agents_model_connections(
                cfg,
                timeout=llm_timeout,
                deep=deep,
            ),
        )
        if aok:
            click.echo(click.style("OK", fg="green") + " — all enabled agents reachable")
        else:
            failed = True
            click.echo(
                click.style("FAIL", fg="red") + " — some enabled agents unreachable",
                err=True,
            )
        for ln in lines:
            first, *rest_lines = ln.split("\n")
            if " — " in first:
                left, right = first.split(" — ", 1)
                if ": OK" in left:
                    first = click.style(left, fg="green") + " — " + right
                elif ": FAIL" in left:
                    first = click.style(left, fg="red") + " — " + right
            merged = "\n".join([first, *rest_lines]) if rest_lines else first
            click.echo(merged, err=": FAIL" in ln)
        for ln in extra_notes:
            click.echo(click.style("Note:", fg="yellow") + f" {ln}")

    if config_ok:
        mismatch = api_target_mismatch_note(cfg, base)
        if mismatch:
            click.echo("\n=== API target ===")
            click.echo(click.style("Note:", fg="yellow") + f" {mismatch}")

    click.echo("\n=== API ===")
    health_url = f"{base}/api/agent/health"
    version_url = f"{base}/api/version"
    try:
        health_resp = httpx.get(health_url, timeout=timeout)
    except httpx.RequestError as exc:
        failed = True
        click.echo(
            click.style("FAIL", fg="red")
            + f" — health not reachable ({health_url})\n{exc}",
            err=True,
        )
        click.echo(
            f"Hint: start the server with `copaw app` (default {base}).",
            err=True,
        )
    else:
        if health_resp.status_code == 200:
            click.echo(
                click.style("OK", fg="green")
                + f" — health ({health_url}, HTTP 200)",
            )
        else:
            failed = True
            click.echo(
                click.style("FAIL", fg="red")
                + f" — health HTTP {health_resp.status_code} ({health_url})",
                err=True,
            )

        try:
            version_resp = httpx.get(version_url, timeout=timeout)
        except httpx.RequestError as exc:
            failed = True
            click.echo(
                click.style("FAIL", fg="red")
                + f" — version not reachable ({version_url})\n{exc}",
                err=True,
            )
        else:
            if version_resp.status_code != 200:
                failed = True
                click.echo(
                    click.style("FAIL", fg="red")
                    + f" — version HTTP {version_resp.status_code} "
                    f"({version_url})",
                    err=True,
                )
            else:
                try:
                    body = version_resp.json()
                except json.JSONDecodeError:
                    body = None
                server_ver = ""
                if isinstance(body, dict) and "version" in body:
                    server_ver = str(body.get("version", ""))
                line = (
                    click.style("OK", fg="green")
                    + f" — version ({version_url}"
                    + (f", server {server_ver!r}" if server_ver else "")
                    + ")"
                )
                click.echo(line)
                if server_ver and server_ver != __version__:
                    click.echo(
                        click.style(
                            f"Note: CLI is {__version__!r}, server reports "
                            f"{server_ver!r} (different installs or upgrade "
                            f"pending).",
                            fg="yellow",
                        ),
                    )

        if health_resp.status_code == 200:
            try:
                root_resp = httpx.get(
                    f"{base}/",
                    timeout=timeout,
                    follow_redirects=True,
                )
            except httpx.RequestError as exc:
                failed = True
                click.echo(
                    click.style("FAIL", fg="red")
                    + f" — could not GET / (console over HTTP): {exc}",
                    err=True,
                )
            else:
                root_ok, root_detail = _classify_console_root_response(root_resp)
                if root_ok:
                    click.echo(
                        click.style("OK", fg="green")
                        + f" — console over HTTP — {root_detail}",
                    )
                else:
                    failed = True
                    click.echo(
                        click.style("FAIL", fg="red")
                        + f" — console over HTTP — {root_detail}",
                        err=True,
                    )

    click.echo("")
    if failed:
        sys.exit(1)


@click.group(
    "doctor",
    invoke_without_command=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.option(
    "--timeout",
    default=5.0,
    type=float,
    show_default=True,
    help="HTTP timeout in seconds for API checks.",
)
@click.option(
    "--llm-timeout",
    default=15.0,
    type=float,
    show_default=True,
    help="Timeout in seconds for the active LLM ping (streaming completion).",
)
@click.option(
    "--deep",
    is_flag=True,
    help=(
        "Run extra checks: enabled-channel reachability (non-fatal notes; "
        "uses --timeout) and, when the active model is copaw-local, llama.cpp "
        "install/server status notes."
    ),
)
@click.pass_context
def doctor_cmd(
    ctx: click.Context,
    timeout: float,
    llm_timeout: float,
    deep: bool,
) -> None:
    """Local sanity checks. Subcommand ``fix`` applies conservative repairs (with backup)."""
    if ctx.invoked_subcommand is None:
        run_doctor_checks(ctx, timeout, llm_timeout, deep)


@doctor_cmd.command(
    "fix",
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="List planned operations only; do not modify files.",
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    help="Apply changes without confirmation (still creates backups unless --no-backup).",
)
@click.option(
    "--only",
    default=None,
    metavar="IDS",
    help=(
        "Comma-separated fix ids: ensure-working-dir, ensure-workspace-dirs, "
        "reconcile-workspace-skills, seed-missing-agent-json, "
        "reset-invalid-agent-json, write-empty-jobs-json, normalize-jobs-cron, "
        "rebuild-console-npm. "
        "Default: safe fixes only (first two). "
        "reconcile-workspace-skills syncs each workspace skill.json with skills/ "
        "(no --yes required)."
    ),
)
@click.option(
    "--no-backup",
    is_flag=True,
    help="Skip copying files to doctor-fix-backups/ (not recommended).",
)
@click.option(
    "--backup-dir",
    type=click.Path(path_type=Path, file_okay=False),
    default=None,
    help="Must be inside the working directory; default is the working directory root.",
)
@click.pass_context
def doctor_fix_cli(
    ctx: click.Context,
    dry_run: bool,
    yes: bool,
    only: str | None,
    no_backup: bool,
    backup_dir: Path | None,
) -> None:
    """Apply conservative filesystem fixes (default backup under doctor-fix-backups/)."""
    from .doctor_fix_runner import run_doctor_fix

    code = run_doctor_fix(
        dry_run=dry_run,
        yes=yes,
        only=only,
        no_backup=no_backup,
        backup_dir=backup_dir,
        working_dir=None,
        echo=click.echo,
        echo_err=lambda m: click.echo(click.style(m, fg="red"), err=True),
        confirm_fn=(lambda m: click.confirm(m)) if not yes else None,
    )
    if code != 0:
        sys.exit(code)
