# -*- coding: utf-8 -*-
"""Bounded, read-only readers for Codex automation source stores."""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import stat
import tempfile
import tomllib
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..skill_transfer import read_regular_file
from .schedule_fields import (
    contains_control as _contains_control,
    encoded as _encoded,
    metadata_text as _metadata_text,
    safe_field as _safe_field,
    safe_prompt as _shared_safe_prompt,
    safe_title as _shared_safe_title,
    text as _text,
    text_audit as _text_audit,
)

_MAX_TOML_BYTES = 2 * 1024 * 1024
_MAX_STATE_BYTES = 16 * 1024 * 1024
_MAX_SQLITE_DATABASE_BYTES = 1024 * 1024 * 1024
_MAX_SQLITE_WAL_BYTES = 512 * 1024 * 1024
_MAX_SQLITE_SHM_BYTES = 64 * 1024 * 1024
_MAX_SQLITE_TASKS = 10_000
_MAX_AUTOMATION_RUNS = 100_000
_MAX_SOURCE_ID_CHARS = 512
_MAX_SOURCE_ID_BYTES = 2_048
_MAX_TITLE_CHARS = 200
_MAX_TITLE_BYTES = 800
_MAX_PROMPT_CHARS = 20_000
_MAX_PROMPT_BYTES = 80_000
_MAX_CWD_CHARS = 4_000
_MAX_CWD_BYTES = 16_000
_MAX_TIMEZONE_CHARS = 100
_MAX_TIMEZONE_BYTES = 400
_MAX_RRULE_CHARS = 4_096
_MAX_RRULE_BYTES = 16_384
_MAX_METADATA_STRING_CHARS = 2_048
_MAX_SMALL_METADATA_STRING_CHARS = 256
_MAX_METADATA_LIST_ITEMS = 16
_MAX_CWDS_JSON_CHARS = 64_000
_WEEKDAYS = {
    "MO": "mon",
    "TU": "tue",
    "WE": "wed",
    "TH": "thu",
    "FR": "fri",
    "SA": "sat",
    "SU": "sun",
}
_SAFE_AUTOMATION_COLUMNS = {
    "id",
    "name",
    "prompt",
    "status",
    "enabled",
    "next_run_at",
    "last_run_at",
    "cwds",
    "cwd",
    "rrule",
    "run_at",
    "timezone",
    "model",
    "reasoning_effort",
    "created_at",
    "updated_at",
    "target_type",
    "project_id",
    "kind",
    "notification_policy",
    "destination",
    "execution_environment",
    "local_environment_config_path",
    "target_thread_id",
}


def _warning_detail(error: BaseException) -> str:
    detail = _metadata_text(str(error), _MAX_SMALL_METADATA_STRING_CHARS)
    return detail or type(error).__name__


def _metadata_scalar(value: Any) -> str | int | float | bool:
    """Normalize the small scalar types allowed in task metadata."""
    if isinstance(value, str):
        return _metadata_text(value, _MAX_SMALL_METADATA_STRING_CHARS)
    if isinstance(value, datetime):
        return _metadata_text(
            value.isoformat(),
            _MAX_SMALL_METADATA_STRING_CHARS,
        )
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and abs(value) <= 2**63 - 1:
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    return ""


def _safe_source_id(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    candidate = value.strip()
    if (
        not candidate
        or len(candidate) > _MAX_SOURCE_ID_CHARS
        or len(_encoded(candidate)) > _MAX_SOURCE_ID_BYTES
        or _contains_control(value)
    ):
        return ""
    return candidate


def _unsafe_identity_token(value: Any, *, fallback: str) -> str:
    """Create a bounded internal count key without retaining source text."""
    original = value if isinstance(value, str) else repr(type(value).__name__)
    digest = hashlib.sha256(_encoded(original)).hexdigest()
    return f"unsafe:{digest}:{fallback}"


def _safe_prompt(value: Any) -> tuple[str, dict[str, Any], str]:
    return _shared_safe_prompt(
        value,
        max_chars=_MAX_PROMPT_CHARS,
        max_bytes=_MAX_PROMPT_BYTES,
    )


def _safe_title(
    value: Any,
    *,
    fallback: str,
) -> tuple[str, dict[str, Any], str]:
    return _shared_safe_title(
        value,
        fallback=fallback or "Codex automation",
        max_chars=_MAX_TITLE_CHARS,
        max_bytes=_MAX_TITLE_BYTES,
    )


def _safe_cwd(value: Any) -> tuple[str, dict[str, Any], str]:
    return _safe_field(
        value,
        max_chars=_MAX_CWD_CHARS,
        max_bytes=_MAX_CWD_BYTES,
        reason="source_cwd_blocked",
    )


def _safe_timezone(value: Any) -> tuple[str, dict[str, Any], str]:
    return _safe_field(
        value,
        max_chars=_MAX_TIMEZONE_CHARS,
        max_bytes=_MAX_TIMEZONE_BYTES,
        reason="source_timezone_blocked",
    )


def _safe_rrule(value: Any) -> tuple[str, dict[str, Any], str]:
    original = value if isinstance(value, str) else ""
    encoded = _encoded(original)
    if len(original) > _MAX_RRULE_CHARS or len(encoded) > _MAX_RRULE_BYTES:
        return (
            "",
            _text_audit(
                original,
                disposition="omitted",
                encoded_value=encoded,
            ),
            "source_rrule_exceeds_limit",
        )
    if _contains_control(original, allow_whitespace=True):
        return (
            "",
            _text_audit(original, disposition="omitted"),
            "source_rrule_unsafe",
        )
    return original.strip(), {}, ""


def _first(mapping: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in mapping and mapping[name] is not None:
            return mapping[name]
    return None


def _valid_timezone(value: str) -> bool:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return False
    return True


def _local_timezone_name() -> tuple[str, str]:
    """Return a local IANA timezone and how it was determined."""
    env_timezone, _, _ = _safe_timezone(os.environ.get("TZ"))
    if env_timezone and _valid_timezone(env_timezone):
        return env_timezone, "environment"

    local_tz = datetime.now().astimezone().tzinfo
    key = _text(getattr(local_tz, "key", ""))
    if key and _valid_timezone(key):
        return key, "system"

    for candidate in (
        Path("/etc/localtime"),
        Path("/var/db/timezone/localtime"),
    ):
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        marker = "/zoneinfo/"
        resolved_text = resolved.as_posix()
        if marker not in resolved_text:
            continue
        name = resolved_text.split(marker, 1)[1]
        if _valid_timezone(name):
            return name, "system"
    return "UTC", "utc_fallback"


# pylint: disable-next=too-many-locals
def _read_project_roots(
    codex_home: Path,
    warnings: list[str],
) -> dict[str, list[str]]:
    path = codex_home / ".codex-global-state.json"
    try:
        encoded = read_regular_file(path, max_bytes=_MAX_STATE_BYTES)
        payload = json.loads(encoded.decode("utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        warnings.append(
            "Could not read Codex project-to-workspace mapping: "
            f"{type(exc).__name__}: {_warning_detail(exc)}",
        )
        return {}
    if not isinstance(payload, dict):
        return {}
    projects = payload.get("local-projects")
    if not isinstance(projects, dict):
        return {}
    result: dict[str, list[str]] = {}
    for key, raw_project in projects.items():
        if not isinstance(raw_project, dict):
            continue
        project_id = _safe_source_id(raw_project.get("id"))
        if not project_id:
            project_id = _safe_source_id(str(key))
        if not project_id:
            warnings.append(
                "Skipped one Codex project mapping with an unsafe id.",
            )
            continue
        roots = raw_project.get("rootPaths")
        if not isinstance(roots, list):
            continue
        clean_roots: list[str] = []
        for item in roots[:_MAX_METADATA_LIST_ITEMS]:
            cwd, _, reason = _safe_cwd(item)
            if cwd and not reason and cwd not in clean_roots:
                clean_roots.append(cwd)
        if project_id and clean_roots:
            result[project_id] = clean_roots
    return result


def _toml_record(document: dict[str, Any], fallback_id: str) -> dict[str, Any]:
    main = document.get("automation")
    if not isinstance(main, dict):
        main = document
    schedule = main.get("schedule")
    if not isinstance(schedule, dict):
        schedule = document.get("schedule")
    if not isinstance(schedule, dict):
        schedule = {}
    target = main.get("target")
    if not isinstance(target, dict):
        target = document.get("target")
    if not isinstance(target, dict):
        target = {}
    execution = main.get("execution")
    if not isinstance(execution, dict):
        execution = document.get("execution")
    if not isinstance(execution, dict):
        execution = {}

    def pick(*names: str, scopes: tuple[dict[str, Any], ...] = (main,)) -> Any:
        for scope in scopes:
            value = _first(scope, *names)
            if value is not None:
                return value
        return None

    return {
        "id": pick("id", "automation_id", "automationId") or fallback_id,
        "name": pick("name", "title"),
        "prompt": pick("prompt", "task", "instruction"),
        "status": pick("status"),
        "enabled": pick("enabled"),
        "rrule": pick(
            "rrule",
            "rule",
            scopes=(main, schedule, document),
        ),
        "run_at": pick(
            "run_at",
            "runAt",
            "scheduled_at",
            "scheduledAt",
            scopes=(main, schedule, document),
        ),
        "timezone": pick(
            "timezone",
            "time_zone",
            "timeZone",
            "tzid",
            scopes=(main, schedule, document),
        ),
        "schedule_type": pick("type", "schedule_type", scopes=(schedule,)),
        "cwd": pick(
            "cwd",
            "source_cwd",
            "working_directory",
            "workingDirectory",
            scopes=(main, target, document),
        ),
        "cwds": pick("cwds", scopes=(main, target, document)),
        "kind": pick("kind", "automation_kind", "automationKind"),
        "target_type": pick(
            "target_type",
            "targetType",
            scopes=(main, target),
        ),
        "project_id": pick("project_id", "projectId", scopes=(main, target)),
        "target_thread_id": pick(
            "target_thread_id",
            "targetThreadId",
            scopes=(main, target),
        ),
        "model": pick("model"),
        "reasoning_effort": pick("reasoning_effort", "reasoningEffort"),
        "notification_policy": pick(
            "notification_policy",
            "notificationPolicy",
        ),
        "destination": pick("destination", scopes=(main, execution)),
        "execution_environment": pick(
            "execution_environment",
            "executionEnvironment",
            scopes=(main, execution),
        ),
        "local_environment_config_path": pick(
            "local_environment_config_path",
            "localEnvironmentConfigPath",
            scopes=(main, execution),
        ),
        "created_at": pick("created_at", "createdAt"),
        "updated_at": pick("updated_at", "updatedAt"),
        "next_run_at": pick("next_run_at", "nextRunAt"),
        "last_run_at": pick("last_run_at", "lastRunAt"),
    }


# pylint: disable-next=too-many-locals
def _read_toml_candidates(
    codex_home: Path,
    warnings: list[str],
) -> tuple[dict[str, tuple[dict[str, Any], Path]], set[str]]:
    root = codex_home / "automations"
    records: dict[str, tuple[dict[str, Any], Path]] = {}
    discovered_ids: set[str] = set()
    if not root.exists():
        return records, discovered_ids
    if root.is_symlink() or not root.is_dir():
        warnings.append(
            "Skipped unsafe Codex automations path (expected a directory).",
        )
        return records, discovered_ids
    try:
        directories = sorted(root.iterdir(), key=lambda item: item.name)
    except OSError as exc:
        warnings.append(
            "Could not list Codex automation definitions: "
            f"{_warning_detail(exc)}",
        )
        return records, discovered_ids
    for directory in directories:
        if directory.is_symlink() or not directory.is_dir():
            continue
        path = directory / "automation.toml"
        raw_candidate_id = directory.name
        candidate_id = _safe_source_id(raw_candidate_id)
        count_key = candidate_id or _unsafe_identity_token(
            raw_candidate_id,
            fallback="toml-directory",
        )
        display_id = candidate_id or "<unsafe-id>"
        try:
            encoded = read_regular_file(path, max_bytes=_MAX_TOML_BYTES)
        except FileNotFoundError:
            continue
        except (OSError, ValueError) as exc:
            discovered_ids.add(count_key)
            warnings.append(
                f"Could not parse Codex automation {display_id!r}: "
                f"{type(exc).__name__}: {_warning_detail(exc)}",
            )
            continue
        discovered_ids.add(count_key)
        try:
            document = tomllib.loads(encoded.decode("utf-8"))
            if not isinstance(document, dict):
                raise ValueError("TOML root is not a table")
        except (OSError, tomllib.TOMLDecodeError, ValueError) as exc:
            warnings.append(
                f"Could not parse Codex automation {display_id!r}: "
                f"{type(exc).__name__}: {_warning_detail(exc)}",
            )
            continue
        record = _toml_record(document, candidate_id)
        automation_id = _safe_source_id(record.get("id"))
        if not automation_id:
            warnings.append(
                "Skipped Codex TOML automation with an unsafe or oversized "
                "source id.",
            )
            continue
        discovered_ids.discard(count_key)
        discovered_ids.add(automation_id)
        if automation_id in records:
            warnings.append(
                "Ignored duplicate Codex TOML automation id "
                f"{automation_id!r}.",
            )
            continue
        record["id"] = automation_id
        records[automation_id] = (record, path)
    return records, discovered_ids


def _table_columns(
    connection: sqlite3.Connection,
    table: str,
) -> list[str]:
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    if not exists:
        return []
    return [
        str(row[1])
        for row in connection.execute(f"PRAGMA table_info({table})")
    ]


def _quoted_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _regular_file_signature(path: Path, maximum_bytes: int) -> tuple[int, ...]:
    """Return a change-detection signature for a bounded regular file."""
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f"{path.name} is not a regular file")
    if info.st_size > maximum_bytes:
        detail = f"read safety limit ({maximum_bytes} bytes)"
        raise ValueError(f"{path.name} exceeds the {detail}")
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def _copy_bounded_regular_file(
    source: Path,
    target: Path,
    maximum_bytes: int,
) -> None:
    """Copy one source file without following a replaced symlink."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    source_fd = os.open(source, flags)
    try:
        info = os.fstat(source_fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f"{source.name} is not a regular file")
        if info.st_size > maximum_bytes:
            raise ValueError(
                f"{source.name} exceeds the read safety limit "
                f"({maximum_bytes} bytes)",
            )
        target_fd = os.open(
            target,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        try:
            total = 0
            while True:
                chunk = os.read(source_fd, 1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > maximum_bytes:
                    raise ValueError(
                        f"{source.name} grew beyond the read safety limit",
                    )
                view = memoryview(chunk)
                while view:
                    written = os.write(target_fd, view)
                    view = view[written:]
        finally:
            os.close(target_fd)
    finally:
        os.close(source_fd)


@contextmanager
def _safe_sqlite_read_target(  # pylint: disable=R0912,R0915
    database: Path,
) -> Iterator[tuple[Path, bool]]:
    """Yield a source DB or an owner-only snapshot that includes its WAL."""
    database_signature = _regular_file_signature(
        database,
        _MAX_SQLITE_DATABASE_BYTES,
    )
    wal = database.with_name(database.name + "-wal")
    try:
        wal_signature = _regular_file_signature(wal, _MAX_SQLITE_WAL_BYTES)
    except FileNotFoundError:
        # An immutable read cannot create source-side lock or sidecar files.
        yield database, True
        if database_signature != _regular_file_signature(
            database,
            _MAX_SQLITE_DATABASE_BYTES,
        ):
            raise ValueError(
                f"{database.name} changed while being read",
            ) from None
        try:
            _regular_file_signature(wal, _MAX_SQLITE_WAL_BYTES)
        except FileNotFoundError:
            pass
        else:
            raise ValueError(
                f"{wal.name} appeared while {database.name} was being read",
            ) from None
        return

    sidecars: list[tuple[Path, int]] = [(wal, _MAX_SQLITE_WAL_BYTES)]
    signatures: dict[Path, tuple[int, ...]] = {
        database: database_signature,
        wal: wal_signature,
    }
    shm = database.with_name(database.name + "-shm")
    try:
        signatures[shm] = _regular_file_signature(
            shm,
            _MAX_SQLITE_SHM_BYTES,
        )
    except FileNotFoundError:
        pass
    else:
        # SQLite can rebuild this WAL index, but a safe existing index is part
        # of the closest point-in-time copy of the live store.
        sidecars.append((shm, _MAX_SQLITE_SHM_BYTES))

    with tempfile.TemporaryDirectory(prefix="qwenpaw-codex-sqlite-") as root:
        os.chmod(root, 0o700)
        snapshot = Path(root) / "snapshot.db"
        try:
            _copy_bounded_regular_file(
                database,
                snapshot,
                _MAX_SQLITE_DATABASE_BYTES,
            )
        except FileNotFoundError:
            raise ValueError(
                f"{database.name} disappeared while being copied",
            ) from None
        for source, maximum_bytes in sidecars:
            suffix = source.name.removeprefix(database.name)
            try:
                _copy_bounded_regular_file(
                    source,
                    snapshot.with_name(snapshot.name + suffix),
                    maximum_bytes,
                )
            except FileNotFoundError:
                raise ValueError(
                    f"{source.name} disappeared while being copied",
                ) from None

        limits = dict(sidecars)
        limits[database] = _MAX_SQLITE_DATABASE_BYTES
        for path, signature in signatures.items():
            try:
                current_signature = _regular_file_signature(
                    path,
                    limits[path],
                )
            except FileNotFoundError:
                raise ValueError(
                    f"{path.name} disappeared while being copied",
                ) from None
            if signature != current_signature:
                raise ValueError(
                    f"{database.name} or a sidecar changed while being copied",
                )
        if shm not in signatures:
            try:
                _regular_file_signature(shm, _MAX_SQLITE_SHM_BYTES)
            except FileNotFoundError:
                pass
            else:
                raise ValueError(
                    f"{shm.name} appeared while {database.name} was copied",
                ) from None
        yield snapshot, False


# pylint: disable-next=too-many-locals
def _read_sqlite_target(
    database: Path,
    *,
    source_name: str,
    immutable: bool,
) -> tuple[list[dict[str, Any]], set[str], list[str]]:
    rows: list[dict[str, Any]] = []
    run_thread_ids: set[str] = set()
    warnings: list[str] = []
    # Some Codex builds have not created this optional projection yet.  Keep
    # the post-query loop safe when the table or its thread_id column is
    # absent, and when schema discovery returns no selectable query.
    fetched_runs: list[sqlite3.Row] = []
    try:
        query = "?mode=ro"
        if immutable:
            query += "&immutable=1"
        uri = f"{database.resolve(strict=True).as_uri()}{query}"
        with sqlite3.connect(uri, uri=True, timeout=2.0) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only = ON")
            columns = _table_columns(connection, "automations")
            selected = [
                column
                for column in columns
                if column.lower() in _SAFE_AUTOMATION_COLUMNS
            ]
            if columns and not any(item.lower() == "id" for item in selected):
                warnings.append(
                    "Ignored automation table without an id column in "
                    f"{source_name}.",
                )
            elif selected:
                selection = ", ".join(
                    _quoted_identifier(item) for item in selected
                )
                cursor = connection.execute(
                    f"SELECT {selection} FROM automations LIMIT ?",
                    (_MAX_SQLITE_TASKS + 1,),
                )
                fetched = cursor.fetchall()
                if len(fetched) > _MAX_SQLITE_TASKS:
                    warnings.append(
                        f"Codex automation safety limit ({_MAX_SQLITE_TASKS}) "
                        f"was reached in {source_name}.",
                    )
                    fetched = fetched[:_MAX_SQLITE_TASKS]
                rows.extend(
                    {str(key).lower(): row[key] for key in row.keys()}
                    for row in fetched
                )

            run_columns = _table_columns(connection, "automation_runs")
            thread_column = next(
                (item for item in run_columns if item.lower() == "thread_id"),
                "",
            )
            if thread_column:
                # Intentionally select only the identifier.  In particular,
                # archived_user_message and archived_assistant_message are
                # never loaded by portability discovery.
                cursor = connection.execute(
                    "SELECT "
                    f"{_quoted_identifier(thread_column)} "
                    "FROM automation_runs "
                    "LIMIT ?",
                    (_MAX_AUTOMATION_RUNS + 1,),
                )
                fetched_runs = cursor.fetchall()
                if len(fetched_runs) > _MAX_AUTOMATION_RUNS:
                    warnings.append(
                        "Codex automation-run safety limit "
                        f"({_MAX_AUTOMATION_RUNS}) was reached in "
                        f"{source_name}.",
                    )
                    fetched_runs = fetched_runs[:_MAX_AUTOMATION_RUNS]
        unsafe_run_ids = 0
        for row in fetched_runs:
            thread_id = _safe_source_id(row[0])
            if thread_id:
                run_thread_ids.add(thread_id)
            elif row[0] is not None:
                unsafe_run_ids += 1
        if unsafe_run_ids:
            warnings.append(
                "Skipped "
                f"{unsafe_run_ids} Codex automation-run thread id(s) "
                f"with unsafe values in {source_name}.",
            )
    except (OSError, sqlite3.Error) as exc:
        warnings.append(
            f"Could not read Codex automation database {source_name}: "
            f"{type(exc).__name__}: {_warning_detail(exc)}",
        )
    return rows, run_thread_ids, warnings


def _read_sqlite_database(
    database: Path,
) -> tuple[list[dict[str, Any]], set[str], list[str]]:
    source_name = (
        _metadata_text(
            database.name,
            _MAX_SMALL_METADATA_STRING_CHARS,
        )
        or "<unsafe-name>"
    )
    try:
        with _safe_sqlite_read_target(database) as (target, immutable):
            return _read_sqlite_target(
                target,
                source_name=source_name,
                immutable=immutable,
            )
    except (OSError, ValueError) as exc:
        return (
            [],
            set(),
            [
                "Could not read Codex automation database "
                f"{source_name}: {type(exc).__name__}: "
                f"{_warning_detail(exc)}",
            ],
        )


# pylint: disable-next=too-many-locals
def _read_sqlite_candidates(
    codex_home: Path,
    warnings: list[str],
) -> tuple[dict[str, tuple[dict[str, Any], Path]], set[str], set[str]]:
    root = codex_home / "sqlite"
    candidates: dict[str, tuple[dict[str, Any], Path]] = {}
    discovered_ids: set[str] = set()
    run_thread_ids: set[str] = set()
    if not root.is_dir() or root.is_symlink():
        return candidates, discovered_ids, run_thread_ids
    try:
        databases = sorted(root.glob("*.db"), key=lambda item: item.name)
    except OSError as exc:
        warnings.append(
            f"Could not list Codex SQLite stores: {_warning_detail(exc)}",
        )
        return candidates, discovered_ids, run_thread_ids
    for database in databases:
        database_name = (
            _metadata_text(
                database.name,
                _MAX_SMALL_METADATA_STRING_CHARS,
            )
            or "<unsafe-name>"
        )
        if database.is_symlink() or not database.is_file():
            warnings.append(
                f"Skipped unsafe Codex SQLite path {database_name!r}.",
            )
            continue
        rows, database_run_ids, database_warnings = _read_sqlite_database(
            database,
        )
        warnings.extend(database_warnings)
        run_thread_ids.update(database_run_ids)
        for row in rows:
            raw_automation_id = row.get("id")
            automation_id = _safe_source_id(raw_automation_id)
            if not automation_id:
                if raw_automation_id is None or raw_automation_id == "":
                    warnings.append(
                        "Skipped one Codex automation without an id in "
                        f"{database_name}.",
                    )
                else:
                    discovered_ids.add(
                        _unsafe_identity_token(
                            raw_automation_id,
                            fallback="sqlite-row",
                        ),
                    )
                    warnings.append(
                        "Skipped one Codex automation with an unsafe or "
                        f"oversized id in {database_name}.",
                    )
                continue
            discovered_ids.add(automation_id)
            existing = candidates.get(automation_id)
            if existing is not None and _updated_score(
                existing[0],
            ) >= _updated_score(row):
                continue
            candidates[automation_id] = (row, database)
    return candidates, discovered_ids, run_thread_ids


def _updated_score(record: dict[str, Any]) -> float:
    value = record.get("updated_at")
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return float("-inf")


__all__ = [
    "_contains_control",
    "_local_timezone_name",
    "_metadata_scalar",
    "_read_project_roots",
    "_read_sqlite_candidates",
    "_read_toml_candidates",
    "_safe_cwd",
    "_safe_prompt",
    "_safe_rrule",
    "_safe_source_id",
    "_safe_timezone",
    "_safe_title",
]
