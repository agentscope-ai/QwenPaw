# -*- coding: utf-8 -*-
"""Built-in ``/checkpoint`` control command handler."""

from __future__ import annotations

import shlex

from ....checkpoints.policy import context_channel
from ....checkpoints.models import CheckpointError
from ....checkpoints.render import render_gc, render_restore, render_timeline
from ....checkpoints.runtime import RUNTIME
from .base import BaseControlCommandHandler, ControlContext

CHECKPOINT_HELP = """\
**Checkpoint**

Save and restore conversation state, memory, and workspace files.

**Commands**
- `/checkpoint auto [on|off]` - show or change automatic checkpoints
- `/checkpoint timeline [--limit=N] [--all]` - view checkpoint history
- `/checkpoint snapshot [name]` - create a named checkpoint now
- `/checkpoint restore <target> [options]` - preview or restore a checkpoint
- `/checkpoint gc [options]` - preview or clean old automatic checkpoints
- `/checkpoint reset --confirm` - delete all checkpoint data in this workspace

**Restore targets**
- `#N` or `N` - number shown by `timeline`
- `<name>` - named snapshot
- `<sha>` - commit prefix shown by `timeline` (at least 7 characters)

**Restore options**
- `--dry-run` - show exactly what would change
- `--confirm` - apply the restore
- `--include-memory` - also restore `MEMORY.md` and `memory/`
- `--include-files` - preview workspace-file candidates
- `--files <path...>` - restore selected candidates
  (requires `--include-files`)

`--include-memory` and `--include-files` can be used together. File restore is
two-step: preview candidates with `--include-files --dry-run`, then apply the
chosen workspace-relative paths with `--include-files --files ... --confirm`.
Quote paths containing spaces. `--files` may be repeated, and comma-separated
paths are also accepted.

**GC options**
- `--dry-run` - show refs eligible for deletion
- `--confirm` - delete eligible refs
- `--compact` - remove all non-HEAD automatic checkpoints
- `--all-sessions` - include every session in this workspace\
"""


def _parse_limit(raw: str, *, default: int, maximum: int) -> int:
    for part in (raw or "").split():
        if part.startswith("--limit="):
            try:
                value = int(part.split("=", 1)[1])
            except ValueError as exc:
                raise CheckpointError(
                    "`--limit` must be a positive integer, for example "
                    "`--limit=50`.",
                ) from exc
            if value < 1:
                raise CheckpointError("`--limit` must be at least 1.")
            return min(maximum, value)
    return default


def _split_subcommand(raw: str) -> tuple[str, str]:
    parts = (raw or "").strip().split(maxsplit=1)
    if not parts:
        return "", ""
    return parts[0].lower(), parts[1] if len(parts) > 1 else ""


def _parse_flags(raw: str) -> set[str]:
    """Return ``--flag`` tokens from raw command args."""
    return {part for part in (raw or "").split() if part.startswith("--")}


def _command_tokens(raw: str) -> list[str]:
    """Split command input while preserving backslashes in file paths."""
    try:
        return shlex.split(raw or "", posix=False)
    except ValueError as exc:
        raise CheckpointError(f"Invalid command quoting: {exc}") from exc


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _parse_selected_files(raw: str) -> tuple[str, ...] | None:
    """Parse repeated ``--files`` / ``--files=`` selections."""
    tokens = _command_tokens(raw)
    selected: list[str] = []
    saw_files = False
    index = 0
    while index < len(tokens):
        token = tokens[index]
        values: list[str] = []
        if token == "--files":
            saw_files = True
            index += 1
            while index < len(tokens) and not tokens[index].startswith("--"):
                values.append(tokens[index])
                index += 1
            if not values:
                raise CheckpointError(
                    "`--files` requires at least one workspace-relative path.",
                )
            index -= 1
        elif token.startswith("--files="):
            saw_files = True
            values.append(token.split("=", 1)[1])

        for value in values:
            for part in _strip_quotes(value).split(","):
                path = part.strip()
                if path and path not in selected:
                    selected.append(path)
        index += 1

    if saw_files and not selected:
        raise CheckpointError(
            "`--files` requires at least one workspace-relative path.",
        )
    return tuple(selected) if saw_files else None


def _format_selected_files(paths: tuple[str, ...] | None) -> str:
    """Render selections into a copyable confirmation command."""
    if not paths:
        return ""
    rendered = []
    for path in paths:
        escaped = path.replace('"', '\\"')
        rendered.append(f' --files "{escaped}"')
    return "".join(rendered)


def _first_positional(raw: str) -> str | None:
    """Return the first non-flag token from raw command args."""
    for part in (raw or "").split():
        if not part.startswith("--"):
            return part
    return None


def _validate_flags(
    raw: str,
    *,
    allowed: set[str],
    allowed_prefixes: tuple[str, ...] = (),
) -> None:
    unknown = sorted(
        flag
        for flag in _parse_flags(raw)
        if flag not in allowed
        and not any(flag.startswith(prefix) for prefix in allowed_prefixes)
    )
    if unknown:
        raise CheckpointError(
            "Unknown option(s): " + ", ".join(f"`{flag}`" for flag in unknown),
        )


class CheckpointCommandHandler(BaseControlCommandHandler):
    """Dispatch checkpoint operations through ``/checkpoint``."""

    command_name = "/checkpoint"
    description = (
        "Inspect and manage conversation checkpoints "
        "(auto / timeline / snapshot / restore / gc / reset)."
    )

    async def handle(self, context: ControlContext) -> str:
        raw = context.args.get("_raw_args", "")
        subcommand, subargs = _split_subcommand(raw)
        handlers = {
            "auto": self._auto,
            "timeline": self._timeline,
            "snapshot": self._snapshot,
            "restore": self._restore,
            "gc": self._gc,
            "reset": self._reset,
        }
        if subcommand in {"", "help", "--help", "-h"}:
            return CHECKPOINT_HELP
        if subcommand in handlers:
            return await handlers[subcommand](context, subargs)
        return f"Unknown subcommand `{subcommand}`.\n\n{CHECKPOINT_HELP}"

    @staticmethod
    async def _auto(context: ControlContext, raw: str) -> str:
        engine = await RUNTIME.get_for_workspace_async(context.workspace)
        arg = raw.strip().lower()
        if arg in ("on", "true", "enable", "1"):
            _enabled, debounce_seconds = await engine.set_auto_enabled(True)
            return (
                "**Auto checkpoint enabled**\n\n"
                "A checkpoint will be created after each completed, "
                "non-command "
                f"response (debounce: {debounce_seconds}s).\n\n"
                "Disable: `/checkpoint auto off`"
            )
        if arg in ("off", "false", "disable", "0"):
            await engine.set_auto_enabled(False)
            return (
                "**Auto checkpoint disabled**\n\n"
                "Use `/checkpoint snapshot [name]` to save checkpoints "
                "manually."
            )
        if arg:
            raise CheckpointError(
                "Usage: `/checkpoint auto [on|off]`",
            )
        auto_enabled, _debounce_seconds = await engine.auto_settings()
        status = "enabled" if auto_enabled else "disabled"
        return (
            f"**Auto checkpoint: {status}**\n\n"
            f"- Enable: `/checkpoint auto on`\n"
            f"- Disable: `/checkpoint auto off`"
        )

    @staticmethod
    async def _timeline(context: ControlContext, raw: str) -> str:
        _validate_flags(
            raw,
            allowed={"--all"},
            allowed_prefixes=("--limit=",),
        )
        engine = await RUNTIME.get_for_workspace_async(context.workspace)
        (
            timeline_default_limit,
            timeline_max_limit,
            query_preview_chars,
        ) = await engine.timeline_settings()
        include_all = "--all" in _parse_flags(raw)
        entries = await engine.timeline(
            session_id=context.session_id,
            user_id=context.user_id,
            channel=context_channel(context),
            limit=_parse_limit(
                raw,
                default=timeline_default_limit,
                maximum=timeline_max_limit,
            ),
            include_all=include_all,
        )
        return render_timeline(
            entries,
            query_preview_chars=query_preview_chars,
            include_all=include_all,
        )

    @staticmethod
    async def _snapshot(context: ControlContext, raw: str) -> str:
        engine = await RUNTIME.get_for_workspace_async(context.workspace)
        name = await engine.snapshot(
            session_id=context.session_id,
            user_id=context.user_id,
            channel=context_channel(context),
            message=raw,
        )
        return (
            "**Snapshot created**\n\n"
            f"- Name: `{name}`\n"
            f"- Restore: `/checkpoint restore {name} --dry-run`"
        )

    @staticmethod
    # Restore command validation intentionally branches by safety mode:
    # preview, confirmation prompt, memory restore, file restore.
    # pylint: disable=too-many-branches
    async def _restore(context: ControlContext, raw: str) -> str:
        flags = _parse_flags(raw)
        _validate_flags(
            raw,
            allowed={
                "--include-memory",
                "--include-files",
                "--files",
                "--dry-run",
                "--confirm",
            },
            allowed_prefixes=("--files=",),
        )
        include_memory = "--include-memory" in flags
        include_files = "--include-files" in flags
        selected_files = _parse_selected_files(raw)
        if selected_files is not None and not include_files:
            raise CheckpointError(
                "`--files` can only be used together with `--include-files`.",
            )
        dry_run = "--dry-run" in flags
        confirm = "--confirm" in flags
        if dry_run and confirm:
            raise CheckpointError(
                "`--dry-run` and `--confirm` cannot be used together.",
            )

        target = _first_positional(raw)
        if not target:
            raise CheckpointError(
                "Usage: /checkpoint restore <N | snap_name | sha> "
                "[--dry-run | --confirm]",
            )

        if include_files and selected_files is None and not dry_run:
            memory_flag = " --include-memory" if include_memory else ""
            if confirm:
                raise CheckpointError(
                    "Applying workspace-file restore requires `--files`. "
                    "Preview candidates with `--include-files --dry-run`, "
                    "then select one or more paths.",
                )
            return (
                "**File selection required**\n\n"
                "Preview the changed workspace files, then explicitly select "
                "the paths to restore.\n\n"
                f"- Preview: `/checkpoint restore {target}{memory_flag} "
                "--include-files --dry-run`\n"
                f"- Apply: `/checkpoint restore {target}{memory_flag} "
                "--include-files --files <path...> --confirm`"
            )

        if not dry_run and not confirm:
            extra_flags = ""
            if include_memory:
                extra_flags += " --include-memory"
            if include_files:
                extra_flags += " --include-files"
                extra_flags += _format_selected_files(selected_files)
            scope = ["conversation"]
            if include_memory:
                scope.append("memory")
            if include_files:
                scope.append("workspace files")
            return (
                "**Confirmation required**\n\n"
                f"- Target: `{target}`\n"
                f"- Scope: {' + '.join(scope)}\n\n"
                f"- Preview: `/checkpoint restore {target}{extra_flags} "
                "--dry-run`\n"
                f"- Apply: `/checkpoint restore {target}{extra_flags} "
                "--confirm`\n\n"
                "A safety checkpoint is created before applying changes."
            )

        engine = await RUNTIME.get_for_workspace_async(context.workspace)
        chan = context_channel(context)
        if include_files:
            result = await engine.restore_with_files(
                target=target,
                session_id=context.session_id,
                user_id=context.user_id,
                channel=chan,
                dry_run=dry_run,
                include_memory=include_memory,
                selected_files=selected_files,
            )
        elif include_memory:
            result = await engine.restore_with_memory(
                target=target,
                session_id=context.session_id,
                user_id=context.user_id,
                channel=chan,
                dry_run=dry_run,
            )
        else:
            result = await engine.restore(
                target=target,
                session_id=context.session_id,
                user_id=context.user_id,
                channel=chan,
                dry_run=dry_run,
            )
        return render_restore(result)

    @staticmethod
    async def _gc(context: ControlContext, raw: str) -> str:
        flags = _parse_flags(raw)
        _validate_flags(
            raw,
            allowed={"--dry-run", "--confirm", "--compact", "--all-sessions"},
        )
        dry_run = "--dry-run" in flags
        confirm = "--confirm" in flags
        if dry_run and confirm:
            raise CheckpointError(
                "`--dry-run` and `--confirm` cannot be used together.",
            )
        if not dry_run and not confirm:
            selected = ""
            if "--compact" in flags:
                selected += " --compact"
            if "--all-sessions" in flags:
                selected += " --all-sessions"
            return (
                "**Confirmation required**\n\n"
                "GC removes eligible automatic and pre-restore checkpoints. "
                "Named snapshots are kept.\n\n"
                f"- Preview: `/checkpoint gc{selected} --dry-run`\n"
                f"- Apply: `/checkpoint gc{selected} --confirm`\n"
                "- Aggressive: `/checkpoint gc --compact --confirm`\n"
                "- All sessions: `/checkpoint gc --all-sessions --confirm`"
            )
        engine = await RUNTIME.get_for_workspace_async(context.workspace)
        result = await engine.gc(
            session_id=context.session_id,
            user_id=context.user_id,
            channel=context_channel(context),
            compact="--compact" in flags,
            all_sessions="--all-sessions" in flags,
            dry_run=dry_run,
        )
        return render_gc(result)

    @staticmethod
    async def _reset(context: ControlContext, raw: str) -> str:
        _validate_flags(raw, allowed={"--confirm"})
        if "--confirm" not in _parse_flags(raw):
            return (
                "**Reset checkpoint data?**\n\n"
                "This permanently deletes automatic checkpoints, named "
                "snapshots, safety checkpoints, and checkpoint settings for "
                "this workspace.\n\n"
                "Conversation files, memory, and user workspace files are not "
                "deleted.\n\n"
                "Run `/checkpoint reset --confirm` to continue."
            )
        engine = await RUNTIME.get_for_workspace_async(context.workspace)
        await engine.reset()
        return (
            "**Checkpoint data reset**\n\n"
            "The checkpoint store was deleted and reinitialized. "
            "Automatic checkpoints are off by default."
        )
