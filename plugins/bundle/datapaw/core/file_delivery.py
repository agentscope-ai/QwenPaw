# -*- coding: utf-8 -*-
"""DataPaw file-delivery tool wrappers."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from agentscope.tool import ToolResponse
from qwenpaw.agents.tools.agent_management import resolve_agent_api_base_url
from qwenpaw.agents.tools.send_file import (
    send_file_to_user as _host_send_file_to_user,
)

from .path_context import default_artifacts_root
from .routers.tasks_utils import rewrite_html_resource_links

logger = logging.getLogger(__name__)

_HTML_SUFFIXES = {".html", ".htm"}


def _agent_id(agent: Any) -> str:
    agent_config = getattr(agent, "_agent_config", None)
    return str(getattr(agent_config, "id", "") or "datapaw")


def _workspace_dir(agent: Any) -> Path | None:
    raw = (
        getattr(agent, "_workspace_dir", None)
        or getattr(agent, "_datapaw_workspace_dir", None)
    )
    return Path(raw).expanduser().resolve() if raw is not None else None


def _request_context(agent: Any) -> dict[str, Any]:
    rc = getattr(agent, "_request_context", None)
    return rc if isinstance(rc, dict) else {}


def _normalize_api_origin(value: Any) -> str:
    origin = str(value or "").strip().rstrip("/")
    if origin.endswith("/api"):
        origin = origin[:-4]
    return origin


def _api_origin(agent: Any) -> str:
    rc = _request_context(agent)
    origin = _normalize_api_origin(rc.get("api_origin"))
    if origin:
        return origin
    try:
        return _normalize_api_origin(resolve_agent_api_base_url())
    except Exception:  # pylint: disable=broad-except
        logger.warning(
            "DataPaw send_file_to_user: failed to resolve API origin",
            exc_info=True,
        )
        return "http://127.0.0.1:8088"


def _contains(parent: Path, child: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _resolve_candidate_paths(
    file_path: str,
    *,
    workspace_dir: Path | None,
    artifacts_root: Path,
) -> list[Path]:
    raw = Path(file_path).expanduser()
    candidates: list[Path] = []
    if raw.is_absolute():
        candidates.append(raw.resolve())
    else:
        if workspace_dir is not None:
            candidates.append((workspace_dir / raw).resolve())
        candidates.append((artifacts_root / raw).resolve())
    return list(dict.fromkeys(candidates))


def _resolve_artifact_html_path(
    file_path: str,
    *,
    workspace_dir: Path | None,
    artifacts_root: Path,
) -> tuple[Path, str] | None:
    for candidate in _resolve_candidate_paths(
        file_path,
        workspace_dir=workspace_dir,
        artifacts_root=artifacts_root,
    ):
        if candidate.suffix.lower() not in _HTML_SUFFIXES:
            continue
        if not candidate.is_file():
            continue
        if not _contains(artifacts_root, candidate):
            continue
        rel_path = candidate.relative_to(artifacts_root).as_posix()
        return candidate, rel_path
    return None


def _send_copy_path(html_path: Path) -> Path:
    if html_path.stem.endswith(".datapaw-send"):
        return html_path
    suffix = html_path.suffix or ".html"
    return html_path.with_name(f"{html_path.stem}.datapaw-send{suffix}")


def _rewrite_html_delivery_copy(
    agent: Any,
    *,
    html_host_path: Path,
    html_artifact_path: str,
    artifacts_root: Path,
) -> Path | None:
    rc = _request_context(agent)
    session_id = str(rc.get("session_id") or "")
    if not session_id:
        return None

    user_id = str(rc.get("user_id") or "default")
    agent_id = str(rc.get("agent_id") or _agent_id(agent))
    original_html = html_host_path.read_text(encoding="utf-8", errors="replace")
    rewritten = rewrite_html_resource_links(
        original_html,
        html_path=html_artifact_path,
        session_id=session_id,
        user_id=user_id,
        agent_id=agent_id,
        api_origin=_api_origin(agent),
        artifacts_root=artifacts_root,
    )
    copy_path = _send_copy_path(html_host_path)
    copy_path.write_text(rewritten, encoding="utf-8")
    return copy_path


def build_send_file_to_user_fn(
    agent: Any,
) -> Callable[[str], Any]:
    """Build DataPaw's ``send_file_to_user`` wrapper for one agent."""

    async def send_file_to_user(file_path: str) -> ToolResponse:
        """Send a file to the user.

        For DataPaw HTML artifacts, sends a rewritten copy whose local
        resources point at the DataPaw resource API.
        """
        workspace_dir = _workspace_dir(agent)
        artifacts_root = default_artifacts_root(
            _agent_id(agent),
            workspace_dir,
        ).resolve()
        resolved = _resolve_artifact_html_path(
            file_path,
            workspace_dir=workspace_dir,
            artifacts_root=artifacts_root,
        )
        if resolved is None:
            return await _host_send_file_to_user(file_path)

        html_host_path, html_artifact_path = resolved
        try:
            copy_path = _rewrite_html_delivery_copy(
                agent,
                html_host_path=html_host_path,
                html_artifact_path=html_artifact_path,
                artifacts_root=artifacts_root,
            )
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "DataPaw send_file_to_user: failed to rewrite HTML %s",
                html_host_path,
                exc_info=True,
            )
            copy_path = None

        if copy_path is None:
            return await _host_send_file_to_user(file_path)
        return await _host_send_file_to_user(str(copy_path))

    send_file_to_user.__annotations__ = {
        "file_path": str,
        "return": ToolResponse,
    }
    return send_file_to_user
