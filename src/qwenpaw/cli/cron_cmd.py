# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

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


@click.group("cron")
def cron_group() -> None:
    """Manage scheduled cron jobs via the HTTP API (/cron).

    Use list/get/state to inspect jobs; create/update/delete to
    add, modify, or remove; pause/resume to toggle execution;
    run to trigger a one-off run.
    """


@cron_group.command("list")
@click.option(
    "--base-url",
    default=None,
    help=(
        "Override the API base URL (e.g. http://127.0.0.1:8088). "
        "If omitted, uses global --host and --port from config."
    ),
)
@click.option(
    "--agent-id",
    default="default",
    help="Agent ID (defaults to 'default')",
)
@click.pass_context
def list_jobs(
    ctx: click.Context,
    base_url: Optional[str],
    agent_id: str,
) -> None:
    """List all cron jobs. Output is JSON from GET /cron/jobs."""
    base_url = _base_url(ctx, base_url)
    with client(base_url) as c:
        headers = {"X-Agent-Id": agent_id}
        r = c.get("/cron/jobs", headers=headers)
        r.raise_for_status()
        print_json(r.json())


@cron_group.command("get")
@click.argument("job_id", metavar="JOB_ID")
@click.option(
    "--base-url",
    default=None,
    help="Override the API base URL. Defaults to global --host/--port.",
)
@click.option(
    "--agent-id",
    default="default",
    help="Agent ID (defaults to 'default')",
)
@click.pass_context
def get_job(
    ctx: click.Context,
    job_id: str,
    base_url: Optional[str],
    agent_id: str,
) -> None:
    """Fetch a cron job by ID. Returns JSON from GET /cron/jobs/<id>."""
    base_url = _base_url(ctx, base_url)
    with client(base_url) as c:
        headers = {"X-Agent-Id": agent_id}
        r = c.get(f"/cron/jobs/{job_id}", headers=headers)
        if r.status_code == 404:
            raise click.ClickException("Job not found.")
        r.raise_for_status()
        print_json(r.json())


@cron_group.command("state")
@click.argument("job_id", metavar="JOB_ID")
@click.option(
    "--base-url",
    default=None,
    help="Override the API base URL. Defaults to global --host/--port.",
)
@click.option(
    "--agent-id",
    default="default",
    help="Agent ID (defaults to 'default')",
)
@click.pass_context
def job_state(
    ctx: click.Context,
    job_id: str,
    base_url: Optional[str],
    agent_id: str,
) -> None:
    """Get the runtime state of a cron job (e.g. next run time, paused)."""
    base_url = _base_url(ctx, base_url)
    with client(base_url) as c:
        headers = {"X-Agent-Id": agent_id}
        r = c.get(f"/cron/jobs/{job_id}/state", headers=headers)
        if r.status_code == 404:
            raise click.ClickException("Job not found.")
        r.raise_for_status()
        print_json(r.json())


def _validate_and_apply_scheduled_repeat(
    schedule: dict,
    repeat_every_days: Optional[int],
    repeat_end_type: Optional[str],
    repeat_until: Optional[str],
    repeat_count: Optional[int],
) -> None:
    if repeat_end_type and repeat_every_days is None:
        raise click.UsageError(
            "--repeat-end-type requires --repeat-every-days",
        )
    if repeat_until and (
        repeat_end_type != "until" or repeat_every_days is None
    ):
        raise click.UsageError(
            "--repeat-until requires --repeat-every-days and "
            "--repeat-end-type until",
        )
    if repeat_count is not None and (
        repeat_end_type != "count" or repeat_every_days is None
    ):
        raise click.UsageError(
            "--repeat-count requires --repeat-every-days and "
            "--repeat-end-type count",
        )
    if repeat_every_days is None:
        return

    schedule["repeat_every_days"] = repeat_every_days
    end_type = repeat_end_type or "never"
    schedule["repeat_end_type"] = end_type
    if end_type == "until":
        if not (repeat_until and repeat_until.strip()):
            raise click.UsageError(
                "--repeat-until is required when --repeat-end-type is 'until'",
            )
        schedule["repeat_until"] = repeat_until.strip()
    elif end_type == "count":
        if repeat_count is None:
            raise click.UsageError(
                "--repeat-count is required when --repeat-end-type is 'count'",
            )
        schedule["repeat_count"] = repeat_count


def _build_schedule_from_cli(
    schedule_type: str,
    cron: str,
    run_at: Optional[str],
    timezone: str,
    repeat_every_days: Optional[int],
    repeat_end_type: Optional[str],
    repeat_until: Optional[str],
    repeat_count: Optional[int],
) -> dict:
    if schedule_type == "scheduled":
        if not (run_at and run_at.strip()):
            raise click.UsageError(
                "--run-at is required when schedule type is 'scheduled'",
            )
        schedule = {
            "type": "once",
            "run_at": run_at.strip(),
            "timezone": timezone,
        }
        _validate_and_apply_scheduled_repeat(
            schedule=schedule,
            repeat_every_days=repeat_every_days,
            repeat_end_type=repeat_end_type,
            repeat_until=repeat_until,
            repeat_count=repeat_count,
        )
        return schedule

    if not (cron and cron.strip()):
        raise click.UsageError(
            "--cron is required when schedule type is 'cron'",
        )
    if (
        repeat_every_days is not None
        or repeat_end_type is not None
        or repeat_until is not None
        or repeat_count is not None
    ):
        raise click.UsageError(
            "--repeat-* options are only supported when "
            "--schedule-type is 'scheduled'",
        )
    return {"type": "cron", "cron": cron, "timezone": timezone}


def _build_spec_from_cli(
    task_type: str,
    schedule_type: str,
    name: str,
    cron: str,
    run_at: Optional[str],
    repeat_every_days: Optional[int],
    repeat_end_type: Optional[str],
    repeat_until: Optional[str],
    repeat_count: Optional[int],
    channel: str,
    target_user: str,
    target_session: str,
    text: Optional[str],
    timezone: str,
    enabled: bool,
    mode: str,
    save_result_to_inbox: Optional[bool] = None,
    share_session: bool = True,
    timeout_seconds: int = 120,
    tool_safety: bool = False,
) -> dict:
    """Build CronJobSpec JSON payload from CLI args (no id)."""
    schedule = _build_schedule_from_cli(
        schedule_type=schedule_type,
        cron=cron,
        run_at=run_at,
        timezone=timezone,
        repeat_every_days=repeat_every_days,
        repeat_end_type=repeat_end_type,
        repeat_until=repeat_until,
        repeat_count=repeat_count,
    )
    dispatch = {
        "type": "channel",
        "channel": channel,
        "target": {"user_id": target_user, "session_id": target_session},
        "mode": mode,
        "meta": {},
    }
    runtime = {
        "share_session": share_session,
        "max_concurrency": 1,
        "timeout_seconds": timeout_seconds,
        "misfire_grace_seconds": 600,
        "tool_safety": tool_safety,
    }
    if task_type == "text":
        if not (text and text.strip()):
            raise click.UsageError(
                "--text is required when task type is 'text'",
            )
        payload = {
            "id": "",
            "name": name,
            "enabled": enabled,
            "schedule": schedule,
            "task_type": "text",
            "text": text.strip(),
            "dispatch": dispatch,
            "runtime": runtime,
            "meta": {},
        }
        if save_result_to_inbox is not None:
            payload["save_result_to_inbox"] = save_result_to_inbox
        return payload
    if task_type == "agent":
        if not (text and text.strip()):
            raise click.UsageError(
                "--text is required when task type is 'agent' "
                "(the question/prompt sent to the agent)",
            )
        payload = {
            "id": "",
            "name": name,
            "enabled": enabled,
            "schedule": schedule,
            "task_type": "agent",
            "request": {
                "input": [
                    {
                        "role": "user",
                        "type": "message",
                        "content": [{"type": "text", "text": text.strip()}],
                    },
                ],
            },
            "dispatch": dispatch,
            "runtime": runtime,
            "meta": {},
        }
        if save_result_to_inbox is not None:
            payload["save_result_to_inbox"] = save_result_to_inbox
        return payload
    raise click.UsageError(f"Unsupported task type: {task_type}")


@cron_group.command("create")
@click.option(
    "-f",
    "--file",
    "file_",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help=(
        "Path to a JSON file containing the full cron job spec. "
        "Mutually exclusive with inline options (--type, --name, etc.)."
    ),
)
@click.option(
    "--type",
    "task_type",
    type=click.Choice(["text", "agent"], case_sensitive=False),
    default=None,
    help=(
        "Task type: 'text' sends fixed content to the channel; "
        "'agent' sends a question to the agent and delivers the reply to the "
        "channel. Required when not using -f/--file."
    ),
)
@click.option(
    "--schedule-type",
    type=click.Choice(["cron", "scheduled"], case_sensitive=False),
    default="cron",
    show_default=True,
    help=(
        "Schedule type: 'cron' for recurring jobs, "
        "'scheduled' for calendar-style jobs."
    ),
)
@click.option(
    "--name",
    default=None,
    help="Display name for the job. Required when not using -f/--file.",
)
@click.option(
    "--cron",
    default=None,
    help=(
        "Cron expression (5 fields: minute hour day month weekday). "
        "Example: '0 9 * * *' for daily at 09:00. "
        "Required when --schedule-type is cron."
    ),
)
@click.option(
    "--run-at",
    default=None,
    help=(
        "Run time for one-time jobs in ISO 8601 format, e.g. "
        "'2026-04-21T15:30:00+08:00'. "
        "Required when --schedule-type is scheduled."
    ),
)
@click.option(
    "--repeat-every-days",
    type=click.IntRange(min=1),
    default=None,
    help=(
        "For --schedule-type scheduled only. "
        "Repeat every N days (>=1). "
        "If omitted, the job runs once."
    ),
)
@click.option(
    "--repeat-end-type",
    type=click.Choice(["never", "until", "count"], case_sensitive=False),
    default=None,
    help=(
        "For repeated scheduled jobs only. End condition: "
        "'never', 'until', or 'count'. Defaults to 'never' "
        "when --repeat-every-days is set."
    ),
)
@click.option(
    "--repeat-until",
    default=None,
    help=(
        "For repeated scheduled jobs. End date-time in ISO 8601 format. "
        "Required when --repeat-end-type is until."
    ),
)
@click.option(
    "--repeat-count",
    type=click.IntRange(min=1),
    default=None,
    help=(
        "For repeated scheduled jobs. Max run count (>=1). "
        "Required when --repeat-end-type is count."
    ),
)
@click.option(
    "--channel",
    default=None,
    help=(
        "Delivery channel: e.g. imessage, dingtalk, discord, qq, console. "
        "Required when not using -f/--file."
    ),
)
@click.option(
    "--target-user",
    default=None,
    help=(
        "Target user_id for the channel (recipient identifier). "
        "Required when not using -f/--file."
    ),
)
@click.option(
    "--target-session",
    default=None,
    help=(
        "Target session_id for the channel. "
        "Required when not using -f/--file."
    ),
)
@click.option(
    "--text",
    default=None,
    help=(
        "Content: for 'text' tasks this is the message sent to the channel; "
        "for 'agent' tasks this is the prompt/question sent to the agent. "
        "Required for both task types."
    ),
)
@click.option(
    "--timezone",
    default=None,
    help=(
        "Timezone for the cron schedule (e.g. UTC, America/New_York). "
        "Defaults to the user timezone from config."
    ),
)
@click.option(
    "--enabled/--no-enabled",
    default=True,
    help="Create the job as enabled (--enabled) or disabled (--no-enabled).",
)
@click.option(
    "--mode",
    type=click.Choice(["stream", "final"], case_sensitive=False),
    default="final",
    help=(
        "Delivery mode: 'stream' sends incremental updates; "
        "'final' sends only the final result."
    ),
)
@click.option(
    "--save-result-to-inbox/--no-save-result-to-inbox",
    default=None,
    help=(
        "Whether to save execution results to Inbox. "
        "If omitted, server-side defaults are applied."
    ),
)
@click.option(
    "--share-session/--no-share-session",
    default=True,
    help=(
        "Share session with target user. "
        "When disabled, creates isolated context for each run."
    ),
)
@click.option(
    "--timeout",
    "timeout_seconds",
    type=click.IntRange(min=1),
    default=120,
    show_default=True,
    help=(
        "Maximum execution time in seconds for agent tasks. "
        "If the task takes longer, it will be cancelled. "
        "Increase for complex tasks (e.g. --timeout 1800)."
    ),
)
@click.option(
    "--tool-safety/--no-tool-safety",
    default=False,
    show_default=True,
    help=(
        "Tool execution safety check. When enabled, risky tool calls "
        "require approval (may block unattended jobs). "
        "When disabled, all tools execute without approval."
    ),
)
@click.option(
    "--base-url",
    default=None,
    help="Override the API base URL. Defaults to global --host/--port.",
)
@click.option(
    "--agent-id",
    default="default",
    help="Agent ID (defaults to 'default')",
)
@click.pass_context
def create_job(
    ctx: click.Context,
    file_: Optional[Path],
    task_type: Optional[str],
    schedule_type: str,
    name: Optional[str],
    cron: Optional[str],
    run_at: Optional[str],
    repeat_every_days: Optional[int],
    repeat_end_type: Optional[str],
    repeat_until: Optional[str],
    repeat_count: Optional[int],
    channel: Optional[str],
    target_user: Optional[str],
    target_session: Optional[str],
    text: Optional[str],
    timezone: Optional[str],
    enabled: bool,
    mode: str,
    save_result_to_inbox: Optional[bool],
    share_session: bool,
    timeout_seconds: int,
    tool_safety: bool,
    base_url: Optional[str],
    agent_id: str,
) -> None:
    """Create a cron job.

    Either pass -f/--file with a JSON spec, or use --type, --name, --cron,
    --channel, --target-user, --target-session and --text to define the job
    inline.
    """
    if timezone is None:
        from ..config import load_config

        timezone = load_config().user_timezone or "UTC"
    base_url = _base_url(ctx, base_url)
    if file_ is not None:
        payload = json.loads(file_.read_text(encoding="utf-8"))
    else:
        for value, label in [
            (task_type, "--type"),
            (name, "--name"),
            (channel, "--channel"),
            (target_user, "--target-user"),
            (target_session, "--target-session"),
        ]:
            if not value or (isinstance(value, str) and not value.strip()):
                raise click.UsageError(
                    f"When creating without -f/--file, {label} is required",
                )
        if schedule_type == "cron":
            if not (cron and cron.strip()):
                raise click.UsageError(
                    "When --schedule-type is cron, --cron is required",
                )
        elif not (run_at and run_at.strip()):
            raise click.UsageError(
                "When --schedule-type is scheduled, --run-at is required",
            )
        payload = _build_spec_from_cli(
            task_type=task_type or "agent",
            schedule_type=schedule_type,
            name=name or "",
            cron=cron or "",
            run_at=run_at,
            repeat_every_days=repeat_every_days,
            repeat_end_type=repeat_end_type,
            repeat_until=repeat_until,
            repeat_count=repeat_count,
            channel=channel or DEFAULT_CHANNEL,
            target_user=target_user or "",
            target_session=target_session or "",
            text=text,
            timezone=timezone,
            enabled=enabled,
            mode=mode,
            save_result_to_inbox=save_result_to_inbox,
            share_session=share_session,
            timeout_seconds=timeout_seconds,
            tool_safety=tool_safety,
        )
    with client(base_url) as c:
        headers = {"X-Agent-Id": agent_id}
        r = c.post("/cron/jobs", json=payload, headers=headers)
        r.raise_for_status()
        print_json(r.json())


def _resolve_update_spec(
    spec: Dict[str, Any],
    task_type: Optional[str],
    schedule_type: Optional[str],
    name: Optional[str],
    cron: Optional[str],
    run_at: Optional[str],
    repeat_every_days: Optional[int],
    repeat_end_type: Optional[str],
    repeat_until: Optional[str],
    repeat_count: Optional[int],
    channel: Optional[str],
    target_user: Optional[str],
    target_session: Optional[str],
    text: Optional[str],
    timezone: Optional[str],
    enabled: Optional[bool],
    mode: Optional[str],
    save_result_to_inbox: Optional[bool],
    share_session: Optional[bool],
    timeout_seconds: Optional[int],
    tool_safety: Optional[bool] = None,
) -> Dict[str, Any]:
    """Merge CLI overrides with an existing cron-job spec.

    Only fields provided as non-None by the CLI are applied; everything
    else is retained from *spec*.  Returns a payload dict suitable for
    PUT /cron/jobs/{id}.
    """
    ext_schedule = spec.get("schedule", {})
    cli_schedule_type = schedule_type or ext_schedule.get("type", "cron")
    if cli_schedule_type in ("scheduled", "once"):
        cli_schedule_type_norm = "scheduled"
    else:
        cli_schedule_type_norm = cli_schedule_type

    tz = timezone or ext_schedule.get("timezone", "UTC")

    cli_cron = cron or ext_schedule.get("cron", "")
    cli_run_at = run_at or ext_schedule.get("run_at")
    cli_repeat_days = (
        repeat_every_days
        if repeat_every_days is not None
        else ext_schedule.get("repeat_every_days")
    )
    cli_repeat_end = (
        repeat_end_type
        if repeat_end_type is not None
        else ext_schedule.get("repeat_end_type")
    )
    cli_repeat_until = (  # fmt: skip
        repeat_until
        if repeat_until is not None
        else ext_schedule.get("repeat_until")
    )
    cli_repeat_count = (  # fmt: skip
        repeat_count
        if repeat_count is not None
        else ext_schedule.get("repeat_count")
    )

    # --- resolve other fields with CLI-override semantics ---
    t_type = task_type or spec.get("task_type", "text")
    t_name = name if name is not None else spec.get("name", "")
    t_enabled = enabled if enabled is not None else spec.get("enabled", True)
    t_mode = mode or spec.get("dispatch", {}).get("mode", "final")
    t_save = (
        save_result_to_inbox
        if save_result_to_inbox is not None
        else spec.get("save_result_to_inbox")
    )
    t_share = (
        share_session
        if share_session is not None
        else spec.get("runtime", {}).get("share_session", True)
    )
    t_timeout = (
        timeout_seconds
        if timeout_seconds is not None
        else spec.get("runtime", {}).get("timeout_seconds", 120)
    )
    t_tool_safety = (
        tool_safety
        if tool_safety is not None
        else spec.get("runtime", {}).get("tool_safety", False)
    )

    ext_dispatch = spec.get("dispatch", {})
    ext_target = ext_dispatch.get("target", {})
    t_channel = channel or ext_dispatch.get("channel", DEFAULT_CHANNEL)
    t_user = target_user or ext_target.get("user_id", "")
    t_session = target_session or ext_target.get("session_id", "")
    t_text = text
    if t_text is None and spec.get("task_type") == "agent":
        try:
            t_text = spec["request"]["input"][0]["content"][0]["text"]
        except (KeyError, IndexError, TypeError):
            t_text = None
    if t_text is None:
        t_text = spec.get("text")

    payload = _build_spec_from_cli(
        task_type=t_type,
        schedule_type=cli_schedule_type_norm,
        name=t_name,
        cron=cli_cron,
        run_at=cli_run_at,
        repeat_every_days=cli_repeat_days,
        repeat_end_type=cli_repeat_end,
        repeat_until=cli_repeat_until,
        repeat_count=cli_repeat_count,
        channel=t_channel,
        target_user=t_user,
        target_session=t_session,
        text=t_text,
        timezone=tz,
        enabled=t_enabled,
        mode=t_mode,
        save_result_to_inbox=t_save,
        share_session=t_share,
        timeout_seconds=t_timeout,
        tool_safety=t_tool_safety,
    )

    # Preserve existing meta
    existing_meta = spec.get("meta")
    if existing_meta:
        payload["meta"] = existing_meta
    existing_dispatch_meta = spec.get("dispatch", {}).get("meta")
    if existing_dispatch_meta:
        payload["dispatch"]["meta"] = existing_dispatch_meta

    return payload


@cron_group.command("update")
@click.argument("job_id", metavar="JOB_ID")
@click.option(
    "-f",
    "--file",
    "file_",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help=(
        "Path to a JSON file containing the full cron job spec. "
        "Mutually exclusive with inline options (--type, --name, etc.)."
    ),
)
@click.option(
    "--type",
    "task_type",
    type=click.Choice(["text", "agent"], case_sensitive=False),
    default=None,
    help="Task type: 'text' or 'agent'.",
)
@click.option(
    "--schedule-type",
    type=click.Choice(["cron", "scheduled"], case_sensitive=False),
    default=None,
    help="Schedule type: 'cron' or 'scheduled'.",
)
@click.option(
    "--name",
    default=None,
    help="Display name for the job.",
)
@click.option(
    "--cron",
    default=None,
    help="Cron expression (5 fields). Example: '0 9 * * *'.",
)
@click.option(
    "--run-at",
    default=None,
    help="Run time for scheduled jobs in ISO 8601 format.",
)
@click.option(
    "--repeat-every-days",
    type=click.IntRange(min=1),
    default=None,
    help="For scheduled: repeat every N days.",
)
@click.option(
    "--repeat-end-type",
    type=click.Choice(["never", "until", "count"], case_sensitive=False),
    default=None,
    help="For scheduled: end condition.",
)
@click.option(
    "--repeat-until",
    default=None,
    help="For scheduled: end date-time (ISO 8601).",
)
@click.option(
    "--repeat-count",
    type=click.IntRange(min=1),
    default=None,
    help="For scheduled: max run count.",
)
@click.option(
    "--channel",
    default=None,
    help="Delivery channel.",
)
@click.option(
    "--target-user",
    default=None,
    help="Target user_id.",
)
@click.option(
    "--target-session",
    default=None,
    help="Target session_id.",
)
@click.option(
    "--text",
    default=None,
    help="Text content or agent prompt.",
)
@click.option(
    "--timezone",
    default=None,
    help="Timezone for the schedule.",
)
@click.option(
    "--enabled/--no-enabled",
    default=None,
    help="Enable or disable the job.",
)
@click.option(
    "--mode",
    type=click.Choice(["stream", "final"], case_sensitive=False),
    default=None,
    help="Delivery mode: 'stream' or 'final'.",
)
@click.option(
    "--save-result-to-inbox/--no-save-result-to-inbox",
    default=None,
    help="Save execution results to Inbox.",
)
@click.option(
    "--share-session/--no-share-session",
    default=None,
    help="Share session with target user.",
)
@click.option(
    "--timeout",
    "timeout_seconds",
    type=click.IntRange(min=1),
    default=None,
    help="Maximum execution time in seconds.",
)
@click.option(
    "--tool-safety/--no-tool-safety",
    default=None,
    help=(
        "Tool execution safety check. When enabled, risky tool calls "
        "require approval. When disabled, all tools execute without approval."
    ),
)
@click.option(
    "--base-url",
    default=None,
    help="Override the API base URL.",
)
@click.option(
    "--agent-id",
    default="default",
    help="Agent ID (defaults to 'default')",
)
@click.pass_context
def update_job(
    ctx: click.Context,
    job_id: str,
    file_: Optional[Path],
    task_type: Optional[str],
    schedule_type: Optional[str],
    name: Optional[str],
    cron: Optional[str],
    run_at: Optional[str],
    repeat_every_days: Optional[int],
    repeat_end_type: Optional[str],
    repeat_until: Optional[str],
    repeat_count: Optional[int],
    channel: Optional[str],
    target_user: Optional[str],
    target_session: Optional[str],
    text: Optional[str],
    timezone: Optional[str],
    enabled: Optional[bool],
    mode: Optional[str],
    save_result_to_inbox: Optional[bool],
    share_session: Optional[bool],
    timeout_seconds: Optional[int],
    tool_safety: Optional[bool],
    base_url: Optional[str],
    agent_id: str,
) -> None:
    """Update an existing cron job.

    Either pass -f/--file with a complete JSON spec to replace the
    job entirely, or specify individual options to override specific
    fields.  Unspecified options keep their current values.
    """
    base_url = _base_url(ctx, base_url)

    # Fetch the existing job first so we can merge partial updates
    with client(base_url) as c:
        headers = {"X-Agent-Id": agent_id}
        r = c.get(f"/cron/jobs/{job_id}", headers=headers)
        if r.status_code == 404:
            raise click.ClickException("Job not found.")
        r.raise_for_status()
        existing = r.json()

    if file_ is not None:
        payload = json.loads(file_.read_text(encoding="utf-8"))
    else:
        payload = _resolve_update_spec(
            spec=existing.get("spec", existing),
            task_type=task_type,
            schedule_type=schedule_type,
            name=name,
            cron=cron,
            run_at=run_at,
            repeat_every_days=repeat_every_days,
            repeat_end_type=repeat_end_type,
            repeat_until=repeat_until,
            repeat_count=repeat_count,
            channel=channel,
            target_user=target_user,
            target_session=target_session,
            text=text,
            timezone=timezone,
            enabled=enabled,
            mode=mode,
            save_result_to_inbox=save_result_to_inbox,
            share_session=share_session,
            timeout_seconds=timeout_seconds,
            tool_safety=tool_safety,
        )

    payload["id"] = job_id

    with client(base_url) as c:
        headers = {"X-Agent-Id": agent_id}
        r = c.put(f"/cron/jobs/{job_id}", json=payload, headers=headers)
        r.raise_for_status()
        print_json(r.json())


@cron_group.command("delete")
@click.argument("job_id", metavar="JOB_ID")
@click.option(
    "--base-url",
    default=None,
    help="Override the API base URL. Defaults to global --host/--port.",
)
@click.option(
    "--agent-id",
    default="default",
    help="Agent ID (defaults to 'default')",
)
@click.pass_context
def delete_job(
    ctx: click.Context,
    job_id: str,
    base_url: Optional[str],
    agent_id: str,
) -> None:
    """Permanently delete a cron job. The job is removed from the server."""
    base_url = _base_url(ctx, base_url)
    with client(base_url) as c:
        headers = {"X-Agent-Id": agent_id}
        r = c.delete(f"/cron/jobs/{job_id}", headers=headers)
        if r.status_code == 404:
            raise click.ClickException("Job not found.")
        r.raise_for_status()
        print_json(r.json())


@cron_group.command("pause")
@click.argument("job_id", metavar="JOB_ID")
@click.option(
    "--base-url",
    default=None,
    help="Override the API base URL. Defaults to global --host/--port.",
)
@click.option(
    "--agent-id",
    default="default",
    help="Agent ID (defaults to 'default')",
)
@click.pass_context
def pause_job(
    ctx: click.Context,
    job_id: str,
    base_url: Optional[str],
    agent_id: str,
) -> None:
    """Pause a cron job so it no longer runs on schedule.
    Use 'resume' to re-enable.
    """
    base_url = _base_url(ctx, base_url)
    with client(base_url) as c:
        headers = {"X-Agent-Id": agent_id}
        r = c.post(f"/cron/jobs/{job_id}/pause", headers=headers)
        if r.status_code == 404:
            raise click.ClickException("Job not found.")
        r.raise_for_status()
        print_json(r.json())


@cron_group.command("resume")
@click.argument("job_id", metavar="JOB_ID")
@click.option(
    "--base-url",
    default=None,
    help="Override the API base URL. Defaults to global --host/--port.",
)
@click.option(
    "--agent-id",
    default="default",
    help="Agent ID (defaults to 'default')",
)
@click.pass_context
def resume_job(
    ctx: click.Context,
    job_id: str,
    base_url: Optional[str],
    agent_id: str,
) -> None:
    """Resume a paused cron job so it runs again on its schedule."""
    base_url = _base_url(ctx, base_url)
    with client(base_url) as c:
        headers = {"X-Agent-Id": agent_id}
        r = c.post(f"/cron/jobs/{job_id}/resume", headers=headers)
        if r.status_code == 404:
            raise click.ClickException("Job not found.")
        r.raise_for_status()
        print_json(r.json())


@cron_group.command("run")
@click.argument("job_id", metavar="JOB_ID")
@click.option(
    "--base-url",
    default=None,
    help="Override the API base URL. Defaults to global --host/--port.",
)
@click.option(
    "--agent-id",
    default="default",
    help="Agent ID (defaults to 'default')",
)
@click.pass_context
def run_job(
    ctx: click.Context,
    job_id: str,
    base_url: Optional[str],
    agent_id: str,
) -> None:
    """Trigger a one-off run of a cron job immediately (ignores schedule)."""
    base_url = _base_url(ctx, base_url)
    with client(base_url) as c:
        headers = {"X-Agent-Id": agent_id}
        r = c.post(f"/cron/jobs/{job_id}/run", headers=headers)
        if r.status_code == 404:
            raise click.ClickException("Job not found.")
        r.raise_for_status()
        print_json(r.json())
