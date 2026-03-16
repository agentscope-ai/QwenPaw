# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import io
import json
import re
import subprocess
import sys
from typing import Optional


_PORT_ARG_PATTERN = re.compile(r"(?:^|\s)--port(?:=|\s+)(\d+)(?=\s|$)")


def _coerce_optional_int(value: object) -> Optional[int]:
    """Best-effort conversion of JSON-decoded values to integers."""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _parse_windows_process_snapshot_json(
    payload: str,
) -> dict[int, tuple[Optional[int], str, str]]:
    """Parse PowerShell JSON process snapshot output."""
    if not payload.strip():
        return {}

    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return {}

    rows = data if isinstance(data, list) else [data]
    snapshot: dict[int, tuple[Optional[int], str, str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue

        pid_value = row.get("ProcessId")
        parent_value = row.get("ParentProcessId")
        pid = _coerce_optional_int(pid_value)
        if pid is None:
            continue

        parent_pid = _coerce_optional_int(parent_value)

        name = str(row.get("Name") or "")
        command = str(row.get("CommandLine") or "")
        snapshot[pid] = (parent_pid, name, command)
    return snapshot


def _parse_windows_process_snapshot_csv(
    payload: str,
) -> dict[int, tuple[Optional[int], str, str]]:
    """Parse WMIC CSV process snapshot output."""
    if not payload.strip():
        return {}

    snapshot: dict[int, tuple[Optional[int], str, str]] = {}
    reader = csv.DictReader(io.StringIO(payload))
    for row in reader:
        pid_value = (row.get("ProcessId") or "").strip()
        if not pid_value.isdigit():
            continue

        parent_value = (row.get("ParentProcessId") or "").strip()
        parent_pid = int(parent_value) if parent_value.isdigit() else None
        pid = int(pid_value)
        name = (row.get("Name") or "").strip()
        command = (row.get("CommandLine") or "").strip()
        snapshot[pid] = (parent_pid, name, command)
    return snapshot


def _windows_process_snapshot() -> dict[int, tuple[Optional[int], str, str]]:
    """Return Windows process info as pid -> (parent_pid, name, cmdline)."""
    commands = (
        (
            [
                "powershell",
                "-NoProfile",
                "-Command",
                (
                    "Get-CimInstance Win32_Process | "
                    "Select-Object ProcessId,ParentProcessId,Name,"
                    "CommandLine | ConvertTo-Json -Compress"
                ),
            ],
            _parse_windows_process_snapshot_json,
        ),
        (
            [
                "wmic",
                "process",
                "get",
                "ProcessId,ParentProcessId,Name,CommandLine",
                "/FORMAT:CSV",
            ],
            _parse_windows_process_snapshot_csv,
        ),
    )

    for command, parser in commands:
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue

        snapshot = parser(result.stdout or "")
        if snapshot:
            return snapshot
    return {}


def _process_table() -> list[tuple[int, str]]:
    """Return a best-effort process table as (pid, command line)."""
    if sys.platform == "win32":
        return [
            (pid, command or name or "<unknown command line>")
            for pid, (
                _parent_pid,
                name,
                command,
            ) in _windows_process_snapshot().items()
        ]

    try:
        result = subprocess.run(
            ["ps", "-ax", "-o", "pid=", "-o", "command="],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []

    rows: list[tuple[int, str]] = []
    for line in (result.stdout or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split(None, 1)
        if not parts or not parts[0].isdigit():
            continue
        command = parts[1] if len(parts) > 1 else ""
        rows.append((int(parts[0]), command))
    return rows


def _matches_copaw_cli_command(command: str, *subcommands: str) -> bool:
    """Return whether command line looks like a CoPaw CLI invocation."""
    lowered = f" {command.lower()}"
    return any(
        pattern in lowered
        for subcommand in subcommands
        for pattern in (
            f" -m copaw {subcommand}",
            f" copaw {subcommand}",
            f"__main__.py {subcommand}",
            f'copaw.exe" {subcommand}',
            f"copaw.exe {subcommand}",
        )
    )


def _is_copaw_service_command(command: str) -> bool:
    """Return whether the command line looks like a local CoPaw app."""
    return _matches_copaw_cli_command(command, "app")


def _is_copaw_wrapper_process(name: str, command: str) -> bool:
    """Return whether the process looks like a CoPaw CLI wrapper."""
    lowered_name = name.lower().removesuffix(".exe")
    return lowered_name == "copaw" or _matches_copaw_cli_command(
        command,
        "app",
        "desktop",
    )


def _extract_port_from_command(command: str, default: int = 8088) -> int:
    """Extract `--port` from a command line when present."""
    match = _PORT_ARG_PATTERN.search(command)
    return int(match.group(1)) if match else default


def _base_url(host: str, port: int) -> str:
    """Build a base URL from host and port."""
    normalized_host = host.strip()
    if ":" in normalized_host and not normalized_host.startswith("["):
        normalized_host = f"[{normalized_host}]"
    return f"http://{normalized_host}:{port}"


def _candidate_hosts(host: str | None) -> list[str]:
    """Return host variants that can reach a local CoPaw service."""
    if not host:
        return []

    normalized = host.strip()
    lowered = normalized.lower().strip("[]")
    candidates: list[str] = []

    def _add(value: str) -> None:
        if value and value not in candidates:
            candidates.append(value)

    if lowered in {"0.0.0.0", "::"}:
        _add("127.0.0.1")
        _add("localhost")
        if lowered == "::":
            _add("::1")
    elif lowered == "localhost":
        _add("localhost")
        _add("127.0.0.1")
        _add("::1")

    _add(normalized)
    return candidates
