# -*- coding: utf-8 -*-
"""Markdown rendering for checkpoint command results."""

from __future__ import annotations

from datetime import datetime

from .policy import ref_display_name, ref_kind, ref_session_key
from .models import CheckpointEntry, GcResult, RestoreResult


def render_timeline(
    entries: list[CheckpointEntry],
    *,
    query_preview_chars: int,
    include_all: bool = False,
) -> str:
    if not entries:
        scope = "this workspace" if include_all else "this session"
        return (
            "**Checkpoint timeline**\n\n"
            f"No checkpoints found for {scope}.\n\n"
            "- Create one: `/checkpoint snapshot [name]`\n"
            "- Enable automatic checkpoints: `/checkpoint auto on`"
        )
    show_sessions = len({entry.session_key for entry in entries}) > 1
    lines = ["**Checkpoint timeline**"]
    if show_sessions:
        by_session: dict[str, list[CheckpointEntry]] = {}
        for entry in entries:
            by_session.setdefault(entry.session_key, []).append(entry)
        for session, session_entries in by_session.items():
            lines.extend(["", f"Session `{session}`"])
            lines.extend(_render_timeline_graph(session_entries))
    else:
        lines.extend(_render_timeline_graph(entries))

    header = "| # | HEAD | Type | Name | SHA | Time | Query |"
    separator = "|--:|:----:|------|------|-----|------|-------|"
    if show_sessions:
        header = "| # | Session | HEAD | Type | Name | SHA | Time | Query |"
        separator = "|--:|---------|:----:|------|------|-----|------|-------|"
    lines.extend(
        [
            "",
            header,
            separator,
        ],
    )
    for entry in entries:
        idx = (
            str(entry.restore_index)
            if entry.restore_index is not None
            else "-"
        )
        kind_label = {
            "auto": "auto",
            "snap": "snapshot",
            "pre-restore": "pre-restore",
        }.get(entry.kind, entry.kind)

        name = entry.name if entry.kind == "snap" and entry.name else ""
        timestamp = datetime.fromtimestamp(
            entry.timestamp_ms / 1000,
        ).astimezone()
        date_text = timestamp.strftime("%Y-%m-%d %H:%M %z")
        query = " ".join(entry.query.split()) if entry.query else ""
        if len(query) > query_preview_chars:
            query = query[: query_preview_chars - 3] + "..."
        query = _escape_table(query)
        name = _escape_table(name)
        values = [
            idx,
            "*" if entry.is_head else "",
            kind_label,
            f"`{name}`" if name else "",
            f"`{entry.commit[:8]}`",
            date_text,
            query,
        ]
        if show_sessions:
            values.insert(1, f"`{_escape_table(entry.session_key)}`")
        lines.append("| " + " | ".join(values) + " |")

    lines.extend(
        [
            "",
            f"Showing {len(entries)} checkpoint(s).",
            "Restore by number: `/checkpoint restore #N --dry-run`",
        ],
    )
    return "\n".join(lines)


def _escape_table(value: str) -> str:
    return (value or "").replace("|", "\\|").replace("`", "\\`")


def _restore_confirm_command(result: RestoreResult) -> str:
    """Build a copyable command pinned to the resolved checkpoint commit."""
    command = f"/checkpoint restore {result.commit}"
    if result.include_memory:
        command += " --include-memory"
    if result.include_files and result.file_paths:
        command += " --include-files"
        for path in result.file_paths:
            escaped = path.replace('"', '\\"')
            command += f' --files "{escaped}"'
    return command + " --confirm"


def _render_timeline_graph(entries: list[CheckpointEntry]) -> list[str]:
    by_commit = {entry.commit: entry for entry in entries}
    head = next((entry for entry in entries if entry.is_head), None)
    active: set[str] = set()
    current = head
    while current is not None and current.commit not in active:
        active.add(current.commit)
        current = by_commit.get(current.parent_commit or "")

    children: dict[str | None, list[CheckpointEntry]] = {}
    for entry in entries:
        parent = (
            entry.parent_commit if entry.parent_commit in by_commit else None
        )
        children.setdefault(parent, []).append(entry)
    for siblings in children.values():
        siblings.sort(
            key=lambda item: (item.commit not in active, item.timestamp_ms),
        )

    graph_lines = ["ROOT"]
    visited: set[str] = set()

    def _walk(parent: str | None, prefix: str) -> None:
        siblings = children.get(parent, [])
        for i, entry in enumerate(siblings):
            if entry.commit in visited:
                continue
            visited.add(entry.commit)
            is_last = i == len(siblings) - 1
            connector = "\\-- " if is_last else "+-- "
            if entry.is_head:
                marker = "*"
            elif entry.commit in active:
                marker = "o"
            else:
                marker = "x"
            idx = (
                str(entry.restore_index)
                if entry.restore_index is not None
                else "-"
            )
            index_label = f" #{idx}" if idx != "-" else ""
            name = (
                f" {entry.name}" if entry.kind == "snap" and entry.name else ""
            )
            kind_label = {
                "snap": "snapshot",
                "pre-restore": "safety",
            }.get(entry.kind, entry.kind)
            graph_lines.append(
                f"{prefix}{connector}{marker}{index_label} "
                f"{kind_label}{name} {entry.commit[:8]}",
            )
            _walk(
                entry.commit,
                prefix + ("    " if is_last else "|   "),
            )

    _walk(None, "")

    return [
        "",
        "```text",
        "  * = HEAD    o = active path    x = branch    "
        f"({len(entries)} entries)",
        "",
        *graph_lines,
        "```",
    ]


def render_restore(result: RestoreResult) -> str:
    # Rendering mirrors RestoreResult sections directly; splitting the branches
    # would make the markdown flow harder to audit.
    # pylint: disable=too-many-branches
    if result.dry_run:
        title = "Restore preview"
        action = "Would restore"
        delete_action = "Would delete"
    else:
        title = "Restore complete"
        action = "Restored"
        delete_action = "Deleted"

    scope_parts = ["conversation"]
    if result.include_memory:
        scope_parts.append("memory")
    if result.include_files:
        scope_parts.append("files")

    conversation_paths = [
        path for path in result.restored_paths if path.startswith("sessions/")
    ]
    changed_paths = [
        path
        for path in result.restored_paths
        if not path.startswith("sessions/")
    ]
    # File previews are the user's selection list for --files, so truncating
    # them would make valid restore candidates undiscoverable.
    show_all_paths = result.dry_run and result.include_files

    lines = [
        f"**{title}**",
        "",
        f"- Target: `{result.target}`",
        f"- Commit: `{result.commit[:12]}`",
        f"- Scope: {' + '.join(scope_parts)}",
        "- Conversation: "
        f"{'would be restored' if result.dry_run else 'restored'}",
    ]

    if changed_paths:
        lines.extend(["", f"**{action} ({len(changed_paths)})**"])
        shown_paths = changed_paths if show_all_paths else changed_paths[:20]
        for path in shown_paths:
            lines.append(f"- `{path}`")
        if not show_all_paths and len(changed_paths) > 20:
            lines.append(
                f"- ... and {len(changed_paths) - 20} more",
            )
    if result.deleted_paths:
        lines.extend(
            ["", f"**{delete_action} ({len(result.deleted_paths)})**"],
        )
        shown_deleted = (
            result.deleted_paths
            if show_all_paths
            else result.deleted_paths[:20]
        )
        for path in shown_deleted:
            lines.append(f"- `{path}`")
        if not show_all_paths and len(result.deleted_paths) > 20:
            lines.append(
                f"- ... and {len(result.deleted_paths) - 20} more",
            )
    if (
        (result.include_memory or result.include_files)
        and not changed_paths
        and not result.deleted_paths
    ):
        lines.extend(["", "No memory or workspace file changes are needed."])
    if result.pre_restore_ref:
        lines.extend(
            ["", f"Safety checkpoint: `{result.pre_restore_ref}`"],
        )

    if result.dry_run:
        lines.extend(
            [
                "",
                "No changes were made with '--dry-run'.",
                "",
                "Apply this exact checkpoint:",
                "```text",
                _restore_confirm_command(result),
                "```",
            ],
        )
    elif conversation_paths:
        lines.extend(
            ["", "Reopen the conversation to load restored messages."],
        )
    return "\n".join(lines)


def render_gc(result: GcResult) -> str:
    if result.dry_run:
        title = "Checkpoint cleanup preview"
    else:
        title = "Checkpoint cleanup complete"

    lines = [
        f"**{title}**",
        "",
        f"- {'Would remove' if result.dry_run else 'Removed'}: "
        f"{len(result.deleted_refs)} eligible checkpoint(s)",
        f"- Kept by retention policy: {len(result.kept_refs)}",
    ]

    if result.deleted_refs:
        lines.extend(["", "**Checkpoints**"])
        shown = result.deleted_refs[:15]
        for ref in shown:
            kind = ref_kind(ref)
            name = ref_display_name(ref) or ref_session_key(ref) or ref
            lines.append(f"- `{name}` ({kind})")
        if len(result.deleted_refs) > 15:
            lines.append(
                f"- ... and {len(result.deleted_refs) - 15} more",
            )
    else:
        lines.extend(["", "Nothing is eligible for cleanup."])

    if result.dry_run:
        lines.extend(["", "No changes were made. Add `--confirm` to apply."])
    return "\n".join(lines)
