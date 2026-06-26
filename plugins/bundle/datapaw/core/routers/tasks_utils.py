# -*- coding: utf-8 -*-
"""Shared helpers for the DataPaw tasks REST router."""
from __future__ import annotations

import logging
import mimetypes
import posixpath
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, List, Literal, NamedTuple, Optional
from urllib.parse import quote, urlsplit

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, Response

from ..path_context import PathContext, shared_artifacts_root
from ..orchestration.artifact import ArtifactItem
from ..orchestration.dag_store import DAGStore
from ..orchestration.task_graph import TaskGraph

logger = logging.getLogger(__name__)

_HTML_RESOURCE_ATTRS = {"href", "src", "poster"}
_SKIPPED_URL_SCHEMES = {
    "http",
    "https",
    "data",
    "blob",
    "mailto",
    "tel",
    "javascript",
    "cid",
}
_CSS_URL_RE = re.compile(r"url\(\s*(['\"]?)([^)'\"\s]+)\1\s*\)")
SESSION_ARTIFACT_GRAPH_ID = "__session__"
SESSION_ARTIFACT_ROOT_NODE_ID = "__root__"


class PnContext(NamedTuple):
    """Bundle returned by :func:`acquire_pn` for PUT-style handlers."""

    session: Any  # SafeJSONSession-like
    session_id: str
    user_id: str
    dag_store: DAGStore
    pn: dict


# Backward-compatible alias for tests and internal callers.
_PnContext = PnContext


def get_multi_agent_manager(request: Request):
    manager = getattr(request.app.state, "multi_agent_manager", None)
    if manager is None:
        raise HTTPException(
            status_code=500,
            detail="MultiAgentManager not initialized",
        )
    return manager


def resolve_request_api_origin(request: Request) -> str:
    """Return the public API origin (scheme + host) for the current request."""
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get(
        "x-forwarded-host",
        request.headers.get("host", request.url.netloc),
    )
    return f"{proto}://{host}".rstrip("/")


async def get_session_for_agent(request: Request, agent_id: Optional[str]):
    """Return the ``SafeJSONSession`` for a specific agent."""
    manager = get_multi_agent_manager(request)

    if not agent_id:
        agent_id = (
            getattr(request.state, "agent_id", None)
            or request.headers.get("X-Agent-Id")
            or request.query_params.get("agent_id")
            or "datapaw"
        )

    workspace = await manager.get_agent(agent_id)
    runner = getattr(workspace, "runner", None)
    if runner is None or getattr(runner, "session", None) is None:
        raise HTTPException(
            status_code=503,
            detail=(f"Agent '{agent_id}' runner/session not ready"),
        )
    return runner.session, agent_id


async def get_workspace_for_agent(request: Request, agent_id: Optional[str]):
    """Return the workspace for an agent (used for running-state check)."""
    manager = get_multi_agent_manager(request)
    if not agent_id:
        agent_id = (
            getattr(request.state, "agent_id", None)
            or request.headers.get("X-Agent-Id")
            or request.query_params.get("agent_id")
            or "datapaw"
        )
    return await manager.get_agent(agent_id)


async def check_not_running(
    workspace: Any,
    session_id: str,
) -> None:
    """Raise 409 if an agent is actively running for this session."""
    chat_manager = getattr(workspace, "chat_manager", None)
    task_tracker = getattr(workspace, "task_tracker", None)
    if chat_manager is None or task_tracker is None:
        return

    chat_id = await chat_manager.get_chat_id_by_session(
        session_id,
        channel="console",
    )
    if chat_id is not None:
        status = await task_tracker.get_status(chat_id)
        if status == "running":
            raise HTTPException(
                status_code=409,
                detail=(
                    "Agent is running for this session. "
                    "Stop it via POST /console/chat/stop before editing tasks."
                ),
            )


def archive_current_plan_to_pn(pn: dict, reason: str) -> Optional[str]:
    """Archive ``pn["current_plan"]`` into ``pn["storage"]["plans"]``."""
    existing = pn.get("current_plan")
    if not isinstance(existing, dict):
        return None
    try:
        old = TaskGraph.model_validate(existing)
    except Exception:  # pylint: disable=broad-except
        return None
    if old.state not in ("done", "abandoned"):
        old.finish(
            "abandoned",
            reason,
        )
    pn.setdefault("storage", {}).setdefault("plans", {})[
        old.id
    ] = old.model_dump(mode="json")
    return old.id


def ensure_plan_notebook_keys(pn: dict) -> None:
    """Make sure the DAG runtime block has the expected top-level keys."""
    pn.setdefault("storage", {"plans": {}})
    pn.setdefault("artifacts", [])
    pn.setdefault("_pending_edits", [])
    pn.setdefault("current_plan", None)


async def persist_pn(ctx: PnContext) -> None:
    """Write the possibly mutated runtime-state dict to the DAG store."""
    await ctx.dag_store.write(ctx.session_id, ctx.pn)


async def load_pn_for_request(
    session: Any,
    session_id: str,
    *,
    user_id: str,
) -> dict:
    """Load DataPaw DAG runtime state through ``DAGStore``."""
    dag_store = DAGStore.from_session(session, user_id=user_id)
    pn = await dag_store.read(session_id)
    return pn if isinstance(pn, dict) else {}


def safe_filename(name: str) -> str:
    """Convert ``graph.name`` to an HTTP-header-safe filename (ASCII)."""
    safe = re.sub(r"[^A-Za-z0-9\-_.]", "_", name)[:120]
    safe = re.sub(r"_+", "_", safe).strip("_")
    return safe or "sop"


def build_file_urls(
    session_id: str,
    path: str,
    *,
    user_id: str = "",
) -> tuple[str, str]:
    """Build preview / download URLs scoped to session + artifact path."""
    encoded_session = quote(session_id, safe="")
    encoded_path = quote(path, safe="")
    user_part = f"&user_id={quote(user_id, safe='')}" if user_id else ""
    base = f"/api/tasks/{encoded_session}/files"
    return (
        f"{base}/preview?path={encoded_path}{user_part}",
        f"{base}/download?path={encoded_path}{user_part}",
    )


def build_resource_url(
    session_id: str,
    path: str,
    *,
    user_id: str = "",
    agent_id: str = "",
    fragment: str = "",
    api_origin: str = "",
) -> str:
    """Build a resource-proxy URL scoped to session + artifact path."""
    encoded_session = quote(session_id, safe="")
    encoded_path = quote(path, safe="")
    user_part = f"&user_id={quote(user_id, safe='')}" if user_id else ""
    agent_part = f"&agent_id={quote(agent_id, safe='')}" if agent_id else ""
    fragment_part = (
        f"#{quote(fragment, safe='/?:@!$&()*+,;=')}" if fragment else ""
    )
    relative = (
        f"/api/tasks/{encoded_session}/files/resource"
        f"?path={encoded_path}{user_part}{agent_part}{fragment_part}"
    )
    origin = api_origin.rstrip("/") if api_origin else ""
    return f"{origin}{relative}" if origin else relative


def extract_artifacts(pn: dict) -> List[ArtifactItem]:
    """Parse the artifacts list from a DAG runtime dict; skip malformed."""
    raw = pn.get("artifacts") if isinstance(pn, dict) else None
    if not isinstance(raw, list):
        return []
    items: List[ArtifactItem] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        try:
            items.append(ArtifactItem.model_validate(entry))
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "tasks router: skip malformed artifact entry %r",
                entry,
                exc_info=True,
            )
    return items


def get_workspace_dir(
    workspace: Any,
    agent_config: Any | None = None,
) -> Path:
    """Infer the agent workspace dir from workspace / runner / config."""
    runner = getattr(workspace, "runner", None)
    raw = (
        getattr(runner, "workspace_dir", None)
        or getattr(workspace, "workspace_dir", None)
        or getattr(agent_config, "workspace_dir", None)
    )
    return Path(raw).expanduser().resolve() if raw else Path.cwd().resolve()


def build_artifact_path_context(
    workspace: Any,
    session_id: str,
    agent_id: str,
) -> PathContext:
    """Build an artifact path context for the current workspace / agent."""
    del session_id
    agent_config: Any | None = None

    try:
        from qwenpaw.config.config import load_agent_config

        agent_config = load_agent_config(agent_id)
    except Exception:  # pylint: disable=broad-except
        logger.warning(
            "tasks router: failed to load agent config for %r; "
            "falling back to workspace_dir lookup on workspace object",
            agent_id,
            exc_info=True,
        )

    workspace_dir = get_workspace_dir(workspace, agent_config)
    base_dir = shared_artifacts_root(
        agent_id=agent_id,
        workspace_dir=workspace_dir,
        mount_override=None,
    )
    return PathContext(mount_dir=base_dir)


def build_session_artifact_root(
    workspace: Any,
    session_id: str,
    agent_id: str,
) -> tuple[PathContext, Path]:
    """Return artifacts-root context plus ``artifacts/{session_id}`` root."""
    context = build_artifact_path_context(workspace, session_id, agent_id)
    session_root = (context.mount_dir / session_id).resolve()
    if not context.contains(session_root):
        raise HTTPException(
            status_code=400,
            detail="Resolved session artifact path escapes artifacts root.",
        )
    return context, session_root


def resolve_artifact_host_path(
    workspace: Any,
    session_id: str,
    agent_id: str,
    path: str,
) -> Path:
    """Resolve a sandbox-relative path to a host absolute path."""
    context = build_artifact_path_context(workspace, session_id, agent_id)
    host_path = context.resolve_artifact_path(path)
    resolved = host_path.resolve()
    if not context.contains(resolved):
        raise HTTPException(
            status_code=400,
            detail="Resolved artifact path escapes the agent workspace.",
        )
    return resolved


def resolve_session_artifact_host_path(
    workspace: Any,
    session_id: str,
    agent_id: str,
    path: str,
) -> tuple[PathContext, Path, Path]:
    """Resolve ``path`` and require it to stay inside this session root."""
    context, session_root = build_session_artifact_root(
        workspace,
        session_id,
        agent_id,
    )
    host_path = context.resolve_artifact_path(path).resolve()
    if not context.contains(host_path):
        raise HTTPException(
            status_code=400,
            detail="Resolved artifact path escapes the agent workspace.",
        )
    if not host_path.is_relative_to(session_root):
        raise HTTPException(
            status_code=400,
            detail="Resolved artifact path escapes this session.",
        )
    return context, session_root, host_path


def artifact_relative_path(context: PathContext, host_path: Path) -> str:
    """Return a POSIX path relative to the artifacts root."""
    return host_path.resolve().relative_to(context.mount_dir).as_posix()


def infer_artifact_owner(
    session_root: Path,
    host_path: Path,
) -> tuple[str, str]:
    """Infer graph / node ids from ``artifacts/{session_id}`` layout."""
    parts = host_path.resolve().relative_to(session_root).parts
    if len(parts) >= 3:
        return parts[0], parts[1]
    if len(parts) == 2:
        return parts[0], SESSION_ARTIFACT_ROOT_NODE_ID
    return SESSION_ARTIFACT_GRAPH_ID, SESSION_ARTIFACT_ROOT_NODE_ID


def infer_artifact_mime_type(path: str) -> str:
    """Infer MIME type from a file path, falling back to octet-stream."""
    mime_type, _ = mimetypes.guess_type(path)
    return mime_type or "application/octet-stream"


def format_artifact_mtime(host_path: Path) -> str:
    """Format file mtime as a JSON/Date.parse-friendly timestamp."""
    return (
        datetime.fromtimestamp(
            host_path.stat().st_mtime,
            tz=timezone.utc,
        )
        .isoformat()
        .replace("+00:00", "Z")
    )


def build_filesystem_artifact_item(
    context: PathContext,
    session_root: Path,
    host_path: Path,
    *,
    registered: ArtifactItem | None = None,
) -> ArtifactItem:
    """Build a file-list entry from disk, optionally overlaying metadata."""
    rel_path = artifact_relative_path(context, host_path)
    graph_id, node_id = infer_artifact_owner(session_root, host_path)

    if registered is not None:
        return ArtifactItem(
            graph_id=registered.graph_id or graph_id,
            node_id=registered.node_id or node_id,
            name=registered.name or host_path.name,
            path=rel_path,
            mime_type=registered.mime_type or infer_artifact_mime_type(rel_path),
            size_bytes=registered.size_bytes,
            created_at=registered.created_at,
        )

    stat = host_path.stat()
    return ArtifactItem(
        graph_id=graph_id,
        node_id=node_id,
        name=host_path.name,
        path=rel_path,
        mime_type=infer_artifact_mime_type(rel_path),
        size_bytes=stat.st_size,
        created_at=format_artifact_mtime(host_path),
    )


def build_registered_artifact_index(
    context: PathContext,
    session_root: Path,
    artifacts: List[ArtifactItem],
) -> dict[str, ArtifactItem]:
    """Map registered artifact paths to session-relative disk entries."""
    indexed: dict[str, ArtifactItem] = {}
    for item in artifacts:
        host_path = context.resolve_artifact_path(item.path).resolve()
        if not context.contains(host_path):
            continue
        if not host_path.is_relative_to(session_root):
            continue
        indexed[artifact_relative_path(context, host_path)] = item
    return indexed


def list_session_artifact_files(
    workspace: Any,
    session_id: str,
    agent_id: str,
    artifacts: List[ArtifactItem],
) -> List[ArtifactItem]:
    """Scan ``artifacts/{session_id}`` and return every regular file."""
    context, session_root = build_session_artifact_root(
        workspace,
        session_id,
        agent_id,
    )
    if not session_root.exists() or not session_root.is_dir():
        return []

    registered_by_path = build_registered_artifact_index(
        context,
        session_root,
        artifacts,
    )
    items: list[ArtifactItem] = []

    for candidate in sorted(session_root.rglob("*")):
        try:
            resolved = candidate.resolve()
            if not resolved.is_relative_to(session_root):
                continue
            if not resolved.is_file():
                continue
            rel_path = artifact_relative_path(context, resolved)
            items.append(
                build_filesystem_artifact_item(
                    context,
                    session_root,
                    resolved,
                    registered=registered_by_path.get(rel_path),
                ),
            )
        except OSError:
            logger.warning(
                "tasks router: failed to scan artifact file %s",
                candidate,
                exc_info=True,
            )
    return items


def find_registered_artifact(
    context: PathContext,
    session_root: Path,
    artifacts: List[ArtifactItem],
    rel_path: str,
) -> ArtifactItem | None:
    """Return registered metadata for ``rel_path`` if present."""
    return build_registered_artifact_index(
        context,
        session_root,
        artifacts,
    ).get(rel_path)


def normalize_html_resource_path(
    html_path: str,
    raw_url: str,
) -> tuple[str, str] | None:
    """Normalize a relative URL inside HTML to an artifacts-root path."""
    raw = (raw_url or "").strip()
    if not raw or raw.startswith(("#", "?")) or raw.startswith("//"):
        return None
    parsed = urlsplit(raw)
    if parsed.scheme.lower() in _SKIPPED_URL_SCHEMES or parsed.netloc:
        return None
    if not parsed.path:
        return None

    if parsed.path.startswith(("./", "../")):
        resource_path = posixpath.normpath(
            posixpath.join(posixpath.dirname(html_path), parsed.path),
        )
    else:
        resource_path = parsed.path.lstrip("/")
    if resource_path in ("", ".") or resource_path.startswith("../"):
        return None
    return resource_path, parsed.fragment


def rewrite_css_urls(
    css_text: str,
    *,
    html_path: str,
    session_id: str,
    user_id: str,
    agent_id: str = "",
    api_origin: str = "",
) -> str:
    def replace(match: re.Match[str]) -> str:
        quote_char = match.group(1)
        raw_url = match.group(2)
        normalized = normalize_html_resource_path(html_path, raw_url)
        if normalized is None:
            return match.group(0)
        resource_path, fragment = normalized
        rewritten = build_resource_url(
            session_id,
            resource_path,
            user_id=user_id,
            agent_id=agent_id,
            fragment=fragment,
            api_origin=api_origin,
        )
        return f"url({quote_char}{rewritten}{quote_char})"

    return _CSS_URL_RE.sub(replace, css_text)


def rewrite_srcset(
    srcset: str,
    *,
    html_path: str,
    session_id: str,
    user_id: str,
    agent_id: str = "",
    api_origin: str = "",
) -> str:
    rewritten_parts: list[str] = []
    for candidate in srcset.split(","):
        stripped = candidate.strip()
        if not stripped:
            continue
        parts = stripped.split(None, 1)
        normalized = normalize_html_resource_path(html_path, parts[0])
        if normalized is None:
            rewritten_parts.append(stripped)
            continue
        resource_path, fragment = normalized
        rewritten = build_resource_url(
            session_id,
            resource_path,
            user_id=user_id,
            agent_id=agent_id,
            fragment=fragment,
            api_origin=api_origin,
        )
        if len(parts) == 2:
            rewritten = f"{rewritten} {parts[1]}"
        rewritten_parts.append(rewritten)
    return ", ".join(rewritten_parts)


class HTMLResourceRewriter(HTMLParser):
    """Rewrite relative resource URLs in HTML to session resource API URLs."""

    def __init__(
        self,
        *,
        html_path: str,
        session_id: str,
        user_id: str,
        agent_id: str = "",
        api_origin: str = "",
    ) -> None:
        super().__init__(convert_charrefs=False)
        self.html_path = html_path
        self.session_id = session_id
        self.user_id = user_id
        self.agent_id = agent_id
        self.api_origin = api_origin
        self.parts: list[str] = []
        self._style_depth = 0

    def _rewrite_url(self, raw_url: str) -> str:
        normalized = normalize_html_resource_path(self.html_path, raw_url)
        if normalized is None:
            return raw_url
        resource_path, fragment = normalized
        return build_resource_url(
            self.session_id,
            resource_path,
            user_id=self.user_id,
            agent_id=self.agent_id,
            fragment=fragment,
            api_origin=self.api_origin,
        )

    def _rewrite_attrs(
        self,
        attrs: list[tuple[str, str | None]],
    ) -> list[tuple[str, str | None]]:
        rewritten: list[tuple[str, str | None]] = []
        for name, value in attrs:
            if value is None:
                rewritten.append((name, value))
                continue
            lower_name = name.lower()
            if lower_name in _HTML_RESOURCE_ATTRS:
                value = self._rewrite_url(value)
            elif lower_name == "srcset":
                value = rewrite_srcset(
                    value,
                    html_path=self.html_path,
                    session_id=self.session_id,
                    user_id=self.user_id,
                    agent_id=self.agent_id,
                    api_origin=self.api_origin,
                )
            elif lower_name == "style":
                value = rewrite_css_urls(
                    value,
                    html_path=self.html_path,
                    session_id=self.session_id,
                    user_id=self.user_id,
                    agent_id=self.agent_id,
                    api_origin=self.api_origin,
                )
            rewritten.append((name, value))
        return rewritten

    @staticmethod
    def _format_attrs(attrs: list[tuple[str, str | None]]) -> str:
        parts: list[str] = []
        for name, value in attrs:
            if value is None:
                parts.append(name)
            else:
                escaped = (
                    value.replace("&", "&amp;")
                    .replace('"', "&quot;")
                    .replace("<", "&lt;")
                )
                parts.append(f'{name}="{escaped}"')
        return (" " + " ".join(parts)) if parts else ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "style":
            self._style_depth += 1
        self.parts.append(
            f"<{tag}{self._format_attrs(self._rewrite_attrs(attrs))}>",
        )

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self.parts.append(
            f"<{tag}{self._format_attrs(self._rewrite_attrs(attrs))} />",
        )

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "style" and self._style_depth:
            self._style_depth -= 1
        self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if self._style_depth:
            data = rewrite_css_urls(
                data,
                html_path=self.html_path,
                session_id=self.session_id,
                user_id=self.user_id,
                agent_id=self.agent_id,
                api_origin=self.api_origin,
            )
        self.parts.append(data)

    def handle_entityref(self, name: str) -> None:
        self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.parts.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        self.parts.append(f"<!--{data}-->")

    def handle_decl(self, decl: str) -> None:
        self.parts.append(f"<!{decl}>")

    def handle_pi(self, data: str) -> None:
        self.parts.append(f"<?{data}>")

    def html(self) -> str:
        return "".join(self.parts)


def rewrite_html_resource_links(
    html: str,
    *,
    html_path: str,
    session_id: str,
    user_id: str,
    agent_id: str = "",
    api_origin: str = "",
) -> str:
    parser = HTMLResourceRewriter(
        html_path=html_path,
        session_id=session_id,
        user_id=user_id,
        agent_id=agent_id,
        api_origin=api_origin,
    )
    parser.feed(html)
    parser.close()
    return parser.html()


def is_html_artifact(item: ArtifactItem) -> bool:
    """Return True iff the artifact looks like HTML (mime_type / ext)."""
    mt = (item.mime_type or "").split(";", 1)[0].strip().lower()
    if mt == "text/html":
        return True
    return Path(item.path).suffix.lower() in {".html", ".htm"}


def serve_artifact_file(
    workspace: Any,
    session_id: str,
    agent_id: str,
    artifacts: List[ArtifactItem],
    path: str,
    *,
    disposition: Literal["inline", "attachment"],
    rewrite_html: bool = False,
    user_id: str = "",
    api_origin: str = "",
) -> Response:
    """Validate against session boundary, then serve a disk artifact."""
    context, session_root, host_path = resolve_session_artifact_host_path(
        workspace,
        session_id,
        agent_id,
        path,
    )
    if not host_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=(f"Artifact file is missing on disk: {path}"),
        )

    rel_path = artifact_relative_path(context, host_path)
    matched = find_registered_artifact(
        context,
        session_root,
        artifacts,
        rel_path,
    )
    matched = build_filesystem_artifact_item(
        context,
        session_root,
        host_path,
        registered=matched,
    )

    media_type = matched.mime_type or "application/octet-stream"
    if rewrite_html and is_html_artifact(matched):
        original_html = host_path.read_bytes().decode("utf-8", errors="replace")
        safe_name = safe_filename(matched.name)
        encoded_name = quote(matched.name)
        content_disposition = (
            f'{disposition}; filename="{safe_name}"; '
            f"filename*=UTF-8''{encoded_name}"
        )
        return Response(
            content=rewrite_html_resource_links(
                original_html,
                html_path=matched.path,
                session_id=session_id,
                user_id=user_id,
                agent_id=agent_id,
                api_origin=api_origin,
            ),
            media_type="text/html; charset=utf-8",
            headers={"Content-Disposition": content_disposition},
        )

    return FileResponse(
        path=host_path,
        media_type=media_type,
        filename=matched.name,
        content_disposition_type=disposition,
    )


def serve_resource_file(
    workspace: Any,
    session_id: str,
    agent_id: str,
    path: str,
) -> FileResponse:
    """Serve any file under this session's artifacts root."""
    _, _, host_path = resolve_session_artifact_host_path(
        workspace,
        session_id,
        agent_id,
        path,
    )
    if not host_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"Resource file is missing: {path}",
        )
    return FileResponse(path=host_path)


# Private aliases kept for existing tests.
_rewrite_html_resource_links = rewrite_html_resource_links
_serve_artifact_file = serve_artifact_file
_serve_resource_file = serve_resource_file
