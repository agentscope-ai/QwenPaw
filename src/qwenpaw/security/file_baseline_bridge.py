# -*- coding: utf-8

"""Thin bridge from qwenpaw core into extension/file_baseline."""

from __future__ import annotations



import sys

from pathlib import Path



_REPO_ROOT = Path(__file__).resolve().parents[3]

_EXTENSION_DIR = _REPO_ROOT / "extension"

if str(_EXTENSION_DIR) not in sys.path:

    sys.path.insert(0, str(_EXTENSION_DIR))



from file_baseline.host_bridge import (  # noqa: E402

    CONFIRM_ACCEPT_PHRASE,

    CONFIRM_REESTABLISH_PHRASE,

    CONFIRM_RESTORE_PHRASE,

    GuardedCommandOutcome,

    GuardedWriteOutcome,

    FileBaselineGuardian,

    get_integrity_settings_projection,

    get_file_baseline_service,

    notify_file_saved,

    run_startup_scan_if_enabled,

    stream_file_baseline_events,

    try_guarded_agent_file_write,

    try_guarded_operator_file_write,

    try_guarded_python_code,

    try_guarded_shell_command,

    browse_workspace_protectable_files,

)



__all__ = [

    "CONFIRM_ACCEPT_PHRASE",

    "CONFIRM_REESTABLISH_PHRASE",

    "CONFIRM_RESTORE_PHRASE",

    "FileBaselineGuardian",

    "get_integrity_settings_projection",

    "get_file_baseline_service",

    "notify_file_saved",

    "run_startup_scan_if_enabled",

    "stream_file_baseline_events",

    "try_guarded_agent_file_write",

    "try_guarded_operator_file_write",

    "try_guarded_python_code",

    "try_guarded_shell_command",

    "GuardedWriteOutcome",

    "GuardedCommandOutcome",

    "browse_workspace_protectable_files",

]


