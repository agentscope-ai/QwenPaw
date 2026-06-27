# -*- coding: utf-8 -*-
"""OSS sync: reload sessions on startup, upload current session after each turn."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

from qwenpaw.constant import WORKING_DIR, EnvVarLoader

from ..constants import BUILTIN_DATAPAW_AGENT_ID

logger = logging.getLogger(__name__)

CHATS_FILE_NAME = "chats.json"

OSS_PREFIX = (
    os.environ.get("DATAPAW_OSS_PREFIX") or f"workspaces/{BUILTIN_DATAPAW_AGENT_ID}"
).strip("/")
OSS_ENDPOINT = (
    os.environ.get("DATAPAW_OSS_ENDPOINT") or "https://oss-cn-hangzhou.aliyuncs.com"
).rstrip("/")
OSS_BUCKET = os.environ.get("DATAPAW_OSS_BUCKET") or "datapaw"
OSS_AK = (os.environ.get("DATAPAW_OSS_ACCESS_KEY_ID") or "").strip()
OSS_SK = (os.environ.get("DATAPAW_OSS_ACCESS_KEY_SECRET") or "").strip()

_bucket = None


def _get_oss_bucket():
    global _bucket  # pylint: disable=global-statement
    if _bucket is not None:
        return _bucket
    if not OSS_AK or not OSS_SK:
        return None
    try:
        import oss2  # pylint: disable=import-outside-toplevel
    except ImportError as exc:
        raise RuntimeError("oss2 is required for DataPaw OSS sync.") from exc
    _bucket = oss2.Bucket(
        oss2.Auth(OSS_AK, OSS_SK),
        OSS_ENDPOINT,
        OSS_BUCKET,
    )
    return _bucket


def _oss_list(prefix: str) -> list[str]:
    bucket = _get_oss_bucket()
    if bucket is None:
        return []
    import oss2  # pylint: disable=import-outside-toplevel

    normalized = prefix.rstrip("/") + "/"
    return [
        obj.key
        for obj in oss2.ObjectIterator(bucket, prefix=normalized)
        if obj.key and not obj.key.endswith("/")
    ]


def _oss_upload(local_path: Path, key: str) -> None:
    bucket = _get_oss_bucket()
    if bucket is None:
        raise RuntimeError("OSS credentials are missing")
    bucket.put_object_from_file(key, str(local_path))


def _oss_download(key: str, local_path: Path) -> None:
    bucket = _get_oss_bucket()
    if bucket is None:
        raise RuntimeError("OSS credentials are missing")
    local_path.parent.mkdir(parents=True, exist_ok=True)
    bucket.get_object_to_file(key, str(local_path))


def _parse_chats_file(path: Path) -> dict | None:
    """Return parsed chats.json when it is non-empty valid JSON."""
    if not path.is_file():
        return None
    try:
        if path.stat().st_size == 0:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if not isinstance(data.get("chats"), list):
        return None
    return data


def _reload_chats_from_oss(local_chats: Path) -> None:
    parsed = _parse_chats_file(local_chats)
    if parsed is not None and parsed["chats"]:
        return
    try:
        _oss_download(f"{OSS_PREFIX}/{CHATS_FILE_NAME}", local_chats)
    except Exception:  # pylint: disable=broad-except
        logger.debug(
            "datapaw oss reload: chats.json missing or failed",
            exc_info=True,
        )
    if _parse_chats_file(local_chats) is None and local_chats.is_file():
        local_chats.unlink(missing_ok=True)
        logger.warning(
            "datapaw oss reload: discarded invalid chats.json at %s",
            local_chats,
        )


def upload_session(
    *,
    session_id: str,
    user_id: str = "default",
    channel: str = "console",
    workspace_dir: Path | str | None = None,
) -> None:
    """Upload one session plus workspace chats.json to OSS."""
    if not session_id or _get_oss_bucket() is None:
        if session_id:
            logger.warning(
                "datapaw oss upload skipped: missing credentials (session=%s)",
                session_id,
            )
        return

    ws = (
        Path(workspace_dir).expanduser().resolve()
        if workspace_dir is not None
        else (WORKING_DIR / "workspaces" / BUILTIN_DATAPAW_AGENT_ID).resolve()
    )
    name = f"{user_id or 'default'}_{session_id}.json"

    console = ws / "sessions" / channel / name
    if console.is_file():
        _oss_upload(console, f"{OSS_PREFIX}/sessions/{channel}/{name}")

    dag = ws / "sessions" / "dag" / name
    if dag.is_file():
        _oss_upload(dag, f"{OSS_PREFIX}/sessions/dag/{name}")

    artifacts = ws / "artifacts" / session_id
    if artifacts.is_dir():
        for path in artifacts.rglob("*"):
            if path.is_file():
                rel = path.relative_to(artifacts).as_posix()
                _oss_upload(path, f"{OSS_PREFIX}/artifacts/{session_id}/{rel}")

    chats = ws / CHATS_FILE_NAME
    if _parse_chats_file(chats) is not None:
        _oss_upload(chats, f"{OSS_PREFIX}/{CHATS_FILE_NAME}")
    elif chats.is_file():
        logger.warning(
            "datapaw oss upload skipped: invalid chats.json at %s",
            chats,
        )

    logger.info(
        "datapaw oss upload done: session_id=%s user_id=%s",
        session_id,
        user_id,
    )


def reload_from_oss(*, workspace_dir: Path | str | None = None) -> None:
    """Download sessions from OSS when local copies are missing."""
    if _get_oss_bucket() is None:
        logger.warning("datapaw oss reload skipped: missing credentials")
        return
    logger.info("datapaw oss reload started")

    ws = (
        Path(workspace_dir).expanduser().resolve()
        if workspace_dir is not None
        else (WORKING_DIR / "workspaces" / BUILTIN_DATAPAW_AGENT_ID).resolve()
    )

    local_chats = ws / CHATS_FILE_NAME
    _reload_chats_from_oss(local_chats)

    console_prefix = f"{OSS_PREFIX}/sessions/console"
    seen: set[tuple[str, str]] = set()

    for key in _oss_list(console_prefix):
        name = key.rsplit("/", 1)[-1]
        stem = name[:-5] if name.endswith(".json") else name
        if "_" not in stem:
            continue
        uid, sid = stem.rsplit("_", 1)
        if not uid or not sid or (uid, sid) in seen:
            continue
        seen.add((uid, sid))

        local_console = ws / "sessions" / "console" / name
        if not local_console.is_file():
            try:
                _oss_download(key, local_console)
            except Exception:  # pylint: disable=broad-except
                logger.warning(
                    "datapaw oss reload: console failed session=%s",
                    sid,
                    exc_info=True,
                )

        local_dag = ws / "sessions" / "dag" / name
        if not local_dag.is_file():
            try:
                _oss_download(f"{OSS_PREFIX}/sessions/dag/{name}", local_dag)
            except Exception:  # pylint: disable=broad-except
                logger.debug(
                    "datapaw oss reload: dag missing session=%s",
                    sid,
                    exc_info=True,
                )

        local_artifacts = ws / "artifacts" / sid
        if not local_artifacts.is_dir():
            artifact_prefix = f"{OSS_PREFIX}/artifacts/{sid}/"
            for artifact_key in _oss_list(artifact_prefix.rstrip("/")):
                if not artifact_key.startswith(artifact_prefix):
                    continue
                rel = artifact_key[len(artifact_prefix) :]
                if not rel:
                    continue
                try:
                    _oss_download(artifact_key, local_artifacts / rel)
                except Exception:  # pylint: disable=broad-except
                    logger.warning(
                        "datapaw oss reload: artifact failed session=%s key=%s",
                        sid,
                        artifact_key,
                        exc_info=True,
                    )

    logger.info("datapaw oss reload done: sessions=%s", len(seen))


def upload_session_to_oss(
    *,
    runner: Any,
    session_id: str,
    user_id: str,
    channel: str,
) -> None:
    """Upload the current session to OSS after a turn, without blocking chat."""
    if not EnvVarLoader.get_bool("DATAPAW_OSS_UPLOAD", False) or not session_id:
        return

    workspace_dir = getattr(runner, "workspace_dir", None)

    async def _run() -> None:
        try:
            await asyncio.to_thread(
                upload_session,
                session_id=session_id,
                user_id=user_id or "default",
                channel=channel or "console",
                workspace_dir=workspace_dir,
            )
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "datapaw oss upload failed: session_id=%s",
                session_id,
                exc_info=True,
            )

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug("datapaw oss upload skipped: no event loop")
        return
    loop.create_task(_run())
