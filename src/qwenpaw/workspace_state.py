# -*- coding: utf-8 -*-
"""Shared path rules for QwenPaw-owned workspace state."""

CHECKPOINT_STATE_FILES = frozenset({"MEMORY.md"})
CHECKPOINT_STATE_DIRS = (
    "memory/",
    "sessions/",
)

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

QWENPAW_STATE_FILES = frozenset(
    {*CHECKPOINT_STATE_FILES, *QWENPAW_RUNTIME_STATE_FILES},
)
QWENPAW_STATE_DIRS = (
    *CHECKPOINT_STATE_DIRS,
    *QWENPAW_RUNTIME_STATE_DIRS,
)


def is_qwenpaw_state_path(relative_path: str) -> bool:
    """Return whether a relative path is QwenPaw-owned workspace state."""
    normalized = (relative_path or "").replace("\\", "/").lstrip("/")
    if not normalized:
        return False
    if "/" not in normalized and normalized in QWENPAW_STATE_FILES:
        return True
    if "/" not in normalized and normalized.endswith(
        QWENPAW_STATE_SUFFIXES,
    ):
        return True
    return any(normalized.startswith(prefix) for prefix in QWENPAW_STATE_DIRS)


__all__ = [
    "CHECKPOINT_STATE_DIRS",
    "CHECKPOINT_STATE_FILES",
    "QWENPAW_RUNTIME_STATE_DIRS",
    "QWENPAW_RUNTIME_STATE_FILES",
    "QWENPAW_STATE_DIRS",
    "QWENPAW_STATE_FILES",
    "QWENPAW_STATE_SUFFIXES",
    "is_qwenpaw_state_path",
]
