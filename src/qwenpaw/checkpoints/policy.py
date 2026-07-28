# -*- coding: utf-8 -*-
"""Checkpoint configuration, identity rules, and snapshot boundaries."""

from __future__ import annotations

import shutil
import re
import hashlib
import json
import unicodedata
from pathlib import Path
from typing import Any, TypeVar, cast

from ..utils.io_utils import get_sync_path_lock, write_text_atomic
from .models import CheckpointError

ConfigValue = TypeVar("ConfigValue", int, float)

DEFAULT_GC_KEEP_COUNT = 20
DEFAULT_GC_KEEP_DAYS = 7
DEFAULT_PRE_RESTORE_RETENTION_DAYS = 7
DEFAULT_AUTO_DEBOUNCE_SECONDS = 1.5
DEFAULT_TIMELINE_LIMIT = 20
DEFAULT_TIMELINE_MAX_LIMIT = 200
DEFAULT_QUERY_PREVIEW_CHARS = 120
DEFAULT_MEMORY_QUIESCE_TIMEOUT = 30.0

GIT_REQUIRED_MESSAGE = (
    "QwenPaw checkpoints require Git, but the git executable was not found on "
    "PATH. Install Git from https://git-scm.com/downloads, ensure `git` is "
    "available in your terminal, and then restart QwenPaw."
)

DEFAULT_CONFIG = f"""\
[gc]
gc_keep_count = {DEFAULT_GC_KEEP_COUNT}
gc_keep_days = {DEFAULT_GC_KEEP_DAYS}
pre_restore_retention_days = {DEFAULT_PRE_RESTORE_RETENTION_DAYS}

[auto]
enabled = false
debounce_seconds = {DEFAULT_AUTO_DEBOUNCE_SECONDS}

[timeline]
default_limit = {DEFAULT_TIMELINE_LIMIT}
max_limit = {DEFAULT_TIMELINE_MAX_LIMIT}

[display]
query_preview_chars = {DEFAULT_QUERY_PREVIEW_CHARS}

[safety]
include_memory_quiesce_timeout = {DEFAULT_MEMORY_QUIESCE_TIMEOUT}
"""

# Checkpoint-owned state stays in the shadow Git tree. These paths are
# restored by the conversation/memory flows, never by --include-files.
CHECKPOINT_STATE_FILES = frozenset({"MEMORY.md"})
CHECKPOINT_STATE_DIRS = (
    "memory/",
    "sessions/",
)

# Other QwenPaw-owned paths are runtime implementation details. Keep this
# list aligned with workspace defaults (including Coding Mode's .gitignore),
# while retaining checkpoint-specific paths that Coding Mode does not know.
QWENPAW_RUNTIME_STATE_FILES = frozenset(
    {
        ".bootstrap_completed",
        ".reme_store_v1",
        ".skill.json.lock",
        ".synced.json",
        "access_control.json",
        "agent.json",
        "AGENTS.md",
        "BOOTSTRAP.md",
        "chats.json",
        "copaw_file_metadata.json",
        "credentials.yaml",
        "dingtalk_session_webhooks.json",
        "feishu_receive_ids.json",
        "HEARTBEAT.md",
        "history.db",
        "jobs.json",
        "matrix_auth_state.json",
        "matrix_sync_token",
        "memory_file_metadata.json",
        "PROFILE.md",
        "skill.json",
        "SOUL.md",
        "yuanbao_sessions.json",
    },
)

QWENPAW_RUNTIME_STATE_DIRS = (
    ".qwenpaw/",
    ".scroll/",
    ".pawgit/",
    "active_skills/",
    "backup/",
    "browser/",
    "checkpoints/",
    "customized_skills/",
    "dialog/",
    "digest/",
    "drivers/",
    "embedding_cache/",
    "file_store/",
    "jobs_history/",
    "matrix_crypto_store/",
    "media/",
    "mem_agent/",
    "mem_metadata/",
    "mem_session/",
    "missions/",
    "ralph_loops/",
    "resource/",
    "skills/",
    "tool_result/",
    "tool_results/",
)

QWENPAW_STATE_SUFFIXES = (
    ".json.tmp",
    ".lock",
    ".weixin-migrate.bak",
)

# Public aggregate constants answer "is this QwenPaw-owned state?". They
# deliberately include checkpoint-owned session and memory paths.
QWENPAW_STATE_FILES = frozenset(
    {*CHECKPOINT_STATE_FILES, *QWENPAW_RUNTIME_STATE_FILES},
)
QWENPAW_STATE_DIRS = (
    *CHECKPOINT_STATE_DIRS,
    *QWENPAW_RUNTIME_STATE_DIRS,
)

# Generic generated content follows Coding Mode's broad .gitignore
# categories. These are not QwenPaw state, but checkpointing them would be
# noisy and potentially very large.
DEVELOPMENT_ARTIFACT_PATTERNS = (
    ".gitignore",
    "__pycache__/",
    "*.py[cod]",
    "*.egg-info/",
    ".venv/",
    "venv/",
    "env/",
    ".env",
    "node_modules/",
    "dist/",
    "build/",
    ".DS_Store",
    "*.log",
)

EXCLUDE_PATTERNS = (
    ".git/",
    *DEVELOPMENT_ARTIFACT_PATTERNS,
    *(f"/{name}" for name in sorted(QWENPAW_RUNTIME_STATE_FILES)),
    *(f"/{name}" for name in QWENPAW_RUNTIME_STATE_DIRS),
    *(f"/*{suffix}" for suffix in QWENPAW_STATE_SUFFIXES),
)


def exclude_pattern_to_pathspec(pattern: str) -> str:
    """Convert a gitignore-style exclude entry to a ``git add`` pathspec."""
    anchored = pattern.startswith("/")
    body = pattern.lstrip("/")
    is_dir = body.endswith("/")
    body = body.rstrip("/")
    scope = "top,glob" if anchored else "glob"
    if is_dir:
        prefix = "" if anchored else "**/"
        return f":(exclude,{scope}){prefix}{body}/**"
    if anchored:
        return f":(exclude,{scope}){body}"
    return f":(exclude,{scope})**/{body}"


SNAPSHOT_EXCLUDE_PATHSPECS = tuple(
    exclude_pattern_to_pathspec(pattern) for pattern in EXCLUDE_PATTERNS
)


def ensure_git_available() -> None:
    """Raise an actionable error when Git is unavailable."""
    if shutil.which("git") is None:
        raise CheckpointError(GIT_REQUIRED_MESSAGE)


def is_qwenpaw_state_path(rel: str) -> bool:
    """Return whether *rel* is QwenPaw runtime state, not user content."""
    normalized = (rel or "").replace("\\", "/").lstrip("/")
    if not normalized:
        return False
    if "/" not in normalized and normalized in QWENPAW_STATE_FILES:
        return True
    if "/" not in normalized and normalized.endswith(QWENPAW_STATE_SUFFIXES):
        return True
    return any(normalized.startswith(prefix) for prefix in QWENPAW_STATE_DIRS)


class CheckpointPolicy:
    """Load, validate, and update workspace checkpoint policy."""

    def __init__(self, config_file: Path) -> None:
        self.config_file = config_file
        self._config: dict[str, Any] = {}
        self._mtime_ns: int | None = None
        self.reload(force=True)

    def _load(self) -> dict[str, Any]:
        try:
            import tomllib
        except ImportError as exc:  # pragma: no cover
            raise CheckpointError("tomllib is not available") from exc
        try:
            with self.config_file.open("rb") as stream:
                data = tomllib.load(stream)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise CheckpointError(
                f"Failed to load checkpoints config {self.config_file}: {exc}",
            ) from exc
        if not isinstance(data, dict):
            raise CheckpointError("Checkpoints config root must be a table")
        return data

    def reload(self, *, force: bool = False) -> dict[str, Any]:
        try:
            mtime_ns = self.config_file.stat().st_mtime_ns
        except OSError as exc:
            raise CheckpointError(
                f"Failed to stat checkpoints config {self.config_file}: {exc}",
            ) from exc
        if force or mtime_ns != self._mtime_ns:
            self._config = self._load()
            self._mtime_ns = mtime_ns
        return self._config

    def number(
        self,
        section: str,
        key: str,
        default: ConfigValue,
        *,
        minimum: ConfigValue,
        maximum: ConfigValue,
    ) -> ConfigValue:
        table = self.reload().get(section, {})
        if not isinstance(table, dict):
            raise CheckpointError(
                f"Config section [{section}] must be a table",
            )
        value = table.get(key, default)
        expected_type = type(default)
        valid = isinstance(value, expected_type)
        if expected_type is float:
            valid = isinstance(value, (int, float))
        if isinstance(value, bool) or not valid:
            raise CheckpointError(
                f"Config {section}.{key} must be {expected_type.__name__}",
            )
        if expected_type is float:
            value = float(value)
        value = cast(ConfigValue, value)
        if value < minimum or value > maximum:
            raise CheckpointError(
                f"Config {section}.{key} must be between "
                f"{minimum} and {maximum}",
            )
        return value

    def boolean(self, section: str, key: str, default: bool) -> bool:
        table = self.reload().get(section, {})
        if not isinstance(table, dict):
            raise CheckpointError(
                f"Config section [{section}] must be a table",
            )
        value = table.get(key, default)
        if not isinstance(value, bool):
            raise CheckpointError(f"Config {section}.{key} must be bool")
        return value

    def set_auto_enabled(self, enabled: bool) -> None:
        self._set_config_values(
            "auto",
            {"enabled": "true" if enabled else "false"},
        )

    def set_gc_retention(
        self,
        *,
        gc_keep_count: int,
        gc_keep_days: int,
        pre_restore_retention_days: int,
    ) -> None:
        """Persist validated checkpoint retention settings."""
        values = {
            "gc_keep_count": (gc_keep_count, 1_000_000),
            "gc_keep_days": (gc_keep_days, 36_500),
            "pre_restore_retention_days": (
                pre_restore_retention_days,
                36_500,
            ),
        }
        for key, (value, maximum) in values.items():
            if isinstance(value, bool) or not isinstance(value, int):
                raise CheckpointError(f"Config gc.{key} must be int")
            if value < 0 or value > maximum:
                raise CheckpointError(
                    f"Config gc.{key} must be between 0 and {maximum}",
                )
        self._set_config_values(
            "gc",
            {key: str(value) for key, (value, _maximum) in values.items()},
        )

    def _set_config_values(
        self,
        section_name: str,
        values: dict[str, str],
    ) -> None:
        """Replace selected scalar values while preserving other sections."""
        with get_sync_path_lock(self.config_file):
            try:
                text = self.config_file.read_text(encoding="utf-8")
            except FileNotFoundError:
                text = DEFAULT_CONFIG
            match = re.search(
                rf"(?ms)^\[{re.escape(section_name)}\]\s*$.*?(?=^\[|\Z)",
                text,
            )
            if match:
                section = match.group(0)
                missing: list[tuple[str, str]] = []
                for key, value in values.items():
                    if re.search(rf"(?m)^{re.escape(key)}\s*=", section):
                        section = re.sub(
                            rf"(?m)^{re.escape(key)}\s*=.*$",
                            f"{key} = {value}",
                            section,
                            count=1,
                        )
                    else:
                        missing.append((key, value))
                if missing:
                    additions = "\n".join(
                        f"{key} = {value}" for key, value in missing
                    )
                    section = section.rstrip() + f"\n{additions}\n\n"
                text = text[: match.start()] + section + text[match.end() :]
            else:
                body = "\n".join(
                    f"{key} = {value}" for key, value in values.items()
                )
                text = text.rstrip() + f"\n\n[{section_name}]\n{body}\n"
            try:
                write_text_atomic(self.config_file, text)
            except OSError as exc:
                raise CheckpointError(
                    "Failed to write checkpoints config "
                    f"{self.config_file}: {exc}",
                ) from exc
            self.reload(force=True)


# Characters forbidden in Windows filenames, matching SafeJSONSession.
_UNSAFE_FILENAME_RE = re.compile(r'[\\/:*?"<>|]')
_REF_UNSAFE_RE = re.compile(r"[\x00-\x20\x7f~^:?*\[\]\\]+")
_REF_DOTLOCK_RE = re.compile(r"\.lock(?:/|$)")
_WINDOWS_RESERVED_REF_BASENAMES = frozenset(
    {
        "aux",
        "con",
        "nul",
        "prn",
        *(f"com{index}" for index in range(1, 10)),
        *(f"lpt{index}" for index in range(1, 10)),
    },
)

METADATA_PREFIX = "Checkpoint-Metadata: "


def context_channel(context: object) -> str:
    """Resolve a channel consistently from hook and control contexts."""
    candidates = [
        getattr(context, "payload", None),
        getattr(context, "request", None),
        context,
    ]
    for candidate in candidates:
        value = getattr(candidate, "channel", None)
        if isinstance(value, str) and value:
            return value
        if value is not None:
            nested = getattr(value, "channel", None) or getattr(
                value,
                "id",
                None,
            )
            if isinstance(nested, str) and nested:
                return nested
    return ""


def sanitize_filename(name: str) -> str:
    """Replace characters illegal in Windows filenames with ``--``."""
    normalized = unicodedata.normalize("NFC", name or "")
    return _UNSAFE_FILENAME_RE.sub("--", normalized)


def session_file_path(
    workspace_dir: Path,
    *,
    session_id: str,
    user_id: str,
    channel: str,
) -> Path:
    """Return the QwenPaw 2.0 JSON session path for one session."""
    if not session_id:
        raise ValueError("session_id must not be None or empty")

    save_dir = Path(workspace_dir) / "sessions"
    safe_sid = sanitize_filename(session_id)
    safe_uid = sanitize_filename(user_id) if user_id else ""
    if safe_uid and safe_uid == safe_sid:
        safe_uid = ""
    filename = (
        f"{safe_uid}_{safe_sid}.json" if safe_uid else f"{safe_sid}.json"
    )
    if channel:
        return save_dir / sanitize_filename(channel) / filename
    return save_dir / filename


def session_key(*, channel: str, user_id: str, session_id: str) -> str:
    """Return a bounded, collision-resistant key for a QwenPaw session."""
    identity = [channel, user_id, session_id]
    encoded = json.dumps(
        identity,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()

    readable = "-".join(part for part in identity if part)
    readable = (
        unicodedata.normalize("NFKD", readable)
        .encode("ascii", errors="ignore")
        .decode("ascii")
        .lower()
    )
    readable = re.sub(r"[^a-z0-9]+", "-", readable).strip("-")
    prefix = readable[:24].rstrip("-") or "session"
    return f"{prefix}-{digest}"


def sanitize_ref_component(value: str, *, fallback: str = "snapshot") -> str:
    """Sanitize user text for one Git ref component, preserving Unicode."""
    value = unicodedata.normalize("NFC", value or "").strip()
    if not value:
        return fallback
    value = value.replace("/", "-").replace("\\", "-")
    value = _REF_UNSAFE_RE.sub("-", value)
    value = re.sub(r"-{2,}", "-", value).strip("/.-")
    value = value.replace("..", ".")
    value = value.replace("@{", "-")
    value = _REF_DOTLOCK_RE.sub("-", value)
    basename = value.partition(".")[0].casefold()
    if basename in _WINDOWS_RESERVED_REF_BASENAMES:
        value = f"ref-{value}"
    if len(value) > 80:
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
        value = f"{value[:67].rstrip('.-')}-{digest}"
    return value or fallback


def ref_kind(ref: str) -> str:
    parts = ref.split("/")
    return parts[1] if len(parts) > 1 else "unknown"


def ref_session_key(ref: str) -> str:
    if ref.startswith(("refs/auto/", "refs/snap/")):
        parts = ref.split("/")
        return parts[2] if len(parts) > 2 else ""
    if ref.startswith("refs/pre-restore/"):
        tail = ref.removeprefix("refs/pre-restore/")
        return tail.split("-", 1)[1] if "-" in tail else ""
    return ""


def ref_display_name(ref: str) -> str:
    if ref_kind(ref) == "pre-restore":
        return ref.removeprefix("refs/pre-restore/").split("-", 1)[0]
    parts = ref.split("/")
    return "/".join(parts[3:]) if len(parts) > 3 else ""


def message_text(content: object) -> str | None:
    """Extract text blocks from one serialized AgentScope message."""
    if isinstance(content, str):
        return content.strip() or None
    if not isinstance(content, list):
        return None
    parts = [
        block.get("text", "")
        for block in content
        if isinstance(block, dict)
        and block.get("type") == "text"
        and isinstance(block.get("text"), str)
    ]
    text = "\n".join(part for part in parts if part).strip()
    return text or None


def _context_from_session_payload(state: dict) -> list:
    agent_state = state.get("agent")
    if not isinstance(agent_state, dict):
        return []
    runtime_state = agent_state.get("state")
    if isinstance(runtime_state, dict):
        context = runtime_state.get("context")
        if isinstance(context, list):
            return context
    return []


def latest_user_query(
    workspace_dir: Path,
    *,
    session_id: str,
    user_id: str,
    channel: str,
) -> str | None:
    """Return the latest persisted user text for one QwenPaw 2.0 session."""
    path = session_file_path(
        workspace_dir,
        session_id=session_id,
        user_id=user_id,
        channel=channel,
    )
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    for message in reversed(_context_from_session_payload(state)):
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        text = message_text(message.get("content"))
        if text:
            return text
    return None


def encode_metadata(
    query: str | None,
    *,
    channel: str | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
    parent_commit: str | None = None,
) -> str:
    """Encode metadata as a single UTF-8-safe commit-message line."""
    payload = json.dumps(
        {
            "query": query,
            "channel": channel,
            "user_id": user_id,
            "session_id": session_id,
            "parent": parent_commit,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"{METADATA_PREFIX}{payload}"


def metadata_from_commit_message(message: str) -> dict:
    """Read checkpoint metadata from a commit message."""
    for line in reversed(message.splitlines()):
        if not line.startswith(METADATA_PREFIX):
            continue
        try:
            metadata = json.loads(line[len(METADATA_PREFIX) :])
        except json.JSONDecodeError:
            return {}
        return metadata if isinstance(metadata, dict) else {}
    return {}


def query_from_commit_message(message: str) -> str | None:
    """Read the latest-query field from a checkpoint commit message."""
    query = metadata_from_commit_message(message).get("query")
    return query if isinstance(query, str) and query else None
