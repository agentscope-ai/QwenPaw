# -*- coding: utf-8 -*-
"""Multi-agent management API.

Provides RESTful API for managing multiple agent instances.
"""
import asyncio
import copy
import json
import logging
import re
import tempfile
import subprocess
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any, cast
from urllib.parse import unquote, urlparse
from fastapi import APIRouter, Body, HTTPException, Request
from fastapi import Path as PathParam
from pydantic import BaseModel, Field

from ...config.config import (
    AgentProfileConfig,
    AgentProfileRef,
    AgentsSquareSourceSpec,
    AgentsSquareConfig,
    AgentsSquareCacheConfig,
    AgentsSquareInstallConfig,
    load_agent_config,
    save_agent_config,
    generate_short_agent_id,
)
from ...config.utils import load_config, save_config
from ...agents.memory.agent_md_manager import AgentMdManager
from ..multi_agent_manager import MultiAgentManager
from ...constant import WORKING_DIR

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents", tags=["agents"])


class AgentSummary(BaseModel):
    """Agent summary information."""

    id: str
    name: str
    description: str
    workspace_dir: str


class AgentListResponse(BaseModel):
    """Response for listing agents."""

    agents: list[AgentSummary]


class CreateAgentRequest(BaseModel):
    """Request model for creating a new agent (id is auto-generated)."""

    name: str
    description: str = ""
    workspace_dir: str | None = None
    language: str = "en"


class MdFileInfo(BaseModel):
    """Markdown file metadata."""

    filename: str
    path: str
    size: int
    created_time: str
    modified_time: str


class MdFileContent(BaseModel):
    """Markdown file content."""

    content: str


class AgentsSquareSourcesPayload(BaseModel):
    """Payload for Agents Square source management."""

    version: int = 1
    cache: dict[str, int] = Field(default_factory=lambda: {"ttl_sec": 600})
    install: dict[str, bool] = Field(
        default_factory=lambda: {
            "overwrite_default": False,
            "preserve_workspace_files": True,
        },
    )
    sources: list[AgentsSquareSourceSpec] = Field(default_factory=list)


class ValidateSquareSourceRequest(AgentsSquareSourceSpec):
    """Request body for validating a single Agents Square source."""


class SourceError(BaseModel):
    """Source-level marketplace errors."""

    source_id: str
    code: str
    message: str
    retryable: bool = False


class AgentSquareItem(BaseModel):
    """Single Agent Square item."""

    source_id: str
    agent_id: str
    name: str
    description: str = ""
    version: str = ""
    license: str = ""
    source_url: str
    install_url: str
    tags: list[str] = Field(default_factory=list)
    extra: dict[str, str] = Field(default_factory=dict)


class ImportAgentRequest(BaseModel):
    """Import request for a source agent into local agents."""

    source_id: str
    agent_id: str
    overwrite: bool = False
    enable: bool = True
    preferred_name: str | None = None


class ImportAgentResponse(BaseModel):
    """Import response for Agents Square import API."""

    imported: bool
    id: str
    name: str
    workspace_dir: str
    source: dict[str, str]


_OWNER_REPO_PATTERN = re.compile(r"^[\w.-]+/[\w.-]+$")
_AGENT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,127}$")
_SQUARE_CACHE_LOCK = threading.Lock()
_SQUARE_CACHE: dict[str, Any] = {
    "expires_at": 0.0,
    "items": [],
    "errors": [],
    "meta": {},
    "import_index": {},
}
_SQUARE_SKIP_DIRS = {
    ".git",
    ".github",
    "integrations",
    "scripts",
    "examples",
    "docs",
    "assets",
}
_SQUARE_SKIP_FILES = {
    "README.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "CHANGELOG.md",
}


def _slugify(value: str) -> str:
    text = unicodedata.normalize("NFKD", (value or "").strip().lower())
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-z0-9_-]+", "-", text)
    text = text.strip("-")
    return text or "agent"


def _github_owner_repo_from_url(url: str) -> tuple[str, str] | None:
    parsed = urlparse((url or "").strip())
    host = (parsed.netloc or "").lower()
    if host not in {"github.com", "www.github.com"}:
        return None
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        return None
    owner = parts[0]
    repo = parts[1]
    if repo.endswith(".git"):
        repo = repo[: -len(".git")]
    return owner, repo


def _build_github_blob_url(
    source: AgentsSquareSourceSpec,
    rel_path: str,
) -> str:
    owner_repo = _github_owner_repo_from_url(source.url)
    if owner_repo is None:
        return source.url
    owner, repo = owner_repo
    branch = source.branch or "main"
    rel = rel_path.strip("/")
    return f"https://github.com/{owner}/{repo}/blob/{branch}/{rel}"


def _run_git_command(
    args: list[str],
    *,
    cwd: str | None = None,
    timeout_sec: int = 60,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout_sec,
        check=False,
    )


def _clone_square_source(source: AgentsSquareSourceSpec) -> Path:
    tmp_dir = Path(tempfile.mkdtemp(prefix="copaw-square-"))
    clone_args = ["clone", "--depth", "1"]
    if source.branch:
        clone_args.extend(["--branch", source.branch])
    clone_args.extend([source.url, str(tmp_dir)])
    cp = _run_git_command(clone_args, timeout_sec=120)
    if cp.returncode != 0:
        raise RuntimeError(
            "SOURCE_UNREACHABLE: " + (cp.stderr.strip() or "clone failed"),
        )
    return tmp_dir


def _parse_markdown_frontmatter(path: Path) -> tuple[dict, str] | None:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    if not raw.startswith("---\n"):
        return None
    lines = raw.splitlines()
    end = -1
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end = idx
            break
    if end == -1:
        return None

    header = "\n".join(lines[1:end])
    body = "\n".join(lines[end + 1 :]).strip()
    try:
        import yaml

        data = yaml.safe_load(header) or {}
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return data, body


def _is_square_candidate_markdown(path: Path) -> bool:
    if path.suffix.lower() != ".md":
        return False
    if path.name in _SQUARE_SKIP_FILES:
        return False
    for p in path.parts:
        if p in _SQUARE_SKIP_DIRS:
            return False
    return True


def _collect_agency_markdown_items(
    source: AgentsSquareSourceSpec,
    source_root: Path,
    repo_dir: Path,
) -> tuple[list[AgentSquareItem], dict[str, dict[str, str]]]:
    items: list[AgentSquareItem] = []
    import_index: dict[str, dict[str, str]] = {}
    seen: set[str] = set()

    for md_file in sorted(source_root.rglob("*.md")):
        if not md_file.is_file() or not _is_square_candidate_markdown(md_file):
            continue
        parsed = _parse_markdown_frontmatter(md_file)
        if parsed is None:
            continue
        meta, body = parsed
        name = str(meta.get("name") or "").strip()
        description = str(meta.get("description") or "").strip()
        if not name:
            continue

        # Normalize both paths to avoid macOS /var vs /private/var alias mismatch.
        rel_path = md_file.resolve().relative_to(repo_dir.resolve()).as_posix()
        agent_id = _slugify(str(meta.get("slug") or "") or md_file.stem)
        key = f"{source.id}:{agent_id}"
        if key in seen:
            agent_id = _slugify(f"{agent_id}-{md_file.stem}")
            key = f"{source.id}:{agent_id}"
        seen.add(key)

        category = rel_path.split("/")[0] if "/" in rel_path else ""
        item = AgentSquareItem(
            source_id=source.id,
            agent_id=agent_id,
            name=name,
            description=description,
            version=str(meta.get("version") or ""),
            license=source.license_hint or "",
            source_url=_build_github_blob_url(source, rel_path),
            install_url=_build_github_blob_url(source, rel_path),
            tags=[str(t) for t in (meta.get("tags") or []) if str(t).strip()],
            extra={
                "emoji": str(meta.get("emoji") or ""),
                "vibe": str(meta.get("vibe") or ""),
                "color": str(meta.get("color") or ""),
                "category": category,
                "original_path": rel_path,
            },
        )
        items.append(item)
        import_index[f"{source.id}/{agent_id}"] = {
            "name": name,
            "description": description,
            "content": body,
            "source_url": item.source_url,
            "license": item.license,
            "original_agent_id": agent_id,
        }

    return items, import_index


def _collect_index_json_items(
    source: AgentsSquareSourceSpec,
    source_root: Path,
    repo_dir: Path,
) -> tuple[list[AgentSquareItem], dict[str, dict[str, str]]]:
    index_path = source_root
    if index_path.is_dir():
        index_path = index_path / "index.json"
    if not index_path.exists():
        raise ValueError("SOURCE_INDEX_INVALID: index.json not found")

    doc = json.loads(index_path.read_text(encoding="utf-8"))
    agents = doc.get("agents")
    if not isinstance(agents, list):
        raise ValueError("SOURCE_INDEX_INVALID: agents must be list")

    items: list[AgentSquareItem] = []
    import_index: dict[str, dict[str, str]] = {}
    for node in agents:
        if not isinstance(node, dict):
            continue
        agent_id = _slugify(str(node.get("agent_id") or node.get("id") or ""))
        name = str(node.get("name") or "").strip()
        if not agent_id or not name:
            continue
        rel = str(node.get("path") or "").strip()
        source_url = str(node.get("source_url") or "").strip()
        install_url = str(node.get("install_url") or source_url).strip()
        if rel and not source_url:
            source_url = _build_github_blob_url(source, rel)
            install_url = source_url

        item = AgentSquareItem(
            source_id=source.id,
            agent_id=agent_id,
            name=name,
            description=str(node.get("description") or ""),
            version=str(node.get("version") or ""),
            license=str(node.get("license") or source.license_hint or ""),
            source_url=source_url or source.url,
            install_url=install_url or source.url,
            tags=[str(t) for t in (node.get("tags") or []) if str(t).strip()],
            extra={
                "category": str(node.get("category") or ""),
                "original_path": rel,
            },
        )
        items.append(item)
        import_index[f"{source.id}/{agent_id}"] = {
            "name": name,
            "description": str(node.get("description") or ""),
            "content": str(node.get("content") or ""),
            "source_url": item.source_url,
            "license": item.license,
            "original_agent_id": agent_id,
        }

    return items, import_index


def _aggregate_square_items(
    cfg: AgentsSquareConfig,
    *,
    refresh: bool = False,
) -> tuple[list[AgentSquareItem], list[SourceError], dict[str, object], dict[str, dict[str, str]]]:
    now = time.time()
    with _SQUARE_CACHE_LOCK:
        expires_at = float(_SQUARE_CACHE.get("expires_at", 0.0) or 0.0)
        if not refresh and now < expires_at:
            meta = cast(
                dict[str, object],
                copy.deepcopy(_SQUARE_CACHE.get("meta") or {}),
            )
            if isinstance(meta, dict):
                meta["cache_hit"] = True
            return (
                cast(
                    list[AgentSquareItem],
                    copy.deepcopy(_SQUARE_CACHE.get("items") or []),
                ),
                cast(
                    list[SourceError],
                    copy.deepcopy(_SQUARE_CACHE.get("errors") or []),
                ),
                meta,
                cast(
                    dict[str, dict[str, str]],
                    copy.deepcopy(_SQUARE_CACHE.get("import_index") or {}),
                ),
            )

    started = time.time()
    items: list[AgentSquareItem] = []
    errors: list[SourceError] = []
    import_index: dict[str, dict[str, str]] = {}
    enabled_sources = sorted(
        [s for s in cfg.sources if s.enabled],
        key=lambda s: (s.order, s.id),
    )

    for source in enabled_sources:
        tmp_dir: Path | None = None
        try:
            tmp_dir = _clone_square_source(source)
            source_root = (tmp_dir / (source.path or ".")).resolve()
            if not str(source_root).startswith(str(tmp_dir.resolve())):
                raise ValueError("SOURCE_INDEX_INVALID: path escapes repository")
            if not source_root.exists():
                raise ValueError(
                    f"SOURCE_INDEX_INVALID: path not found '{source.path}'",
                )

            if source.provider == "agency_markdown_repo":
                source_items, source_import_index = _collect_agency_markdown_items(
                    source,
                    source_root,
                    tmp_dir,
                )
            else:
                source_items, source_import_index = _collect_index_json_items(
                    source,
                    source_root,
                    tmp_dir,
                )

            items.extend(source_items)
            import_index.update(source_import_index)
        except ValueError as e:
            errors.append(
                SourceError(
                    source_id=source.id,
                    code="SOURCE_INDEX_INVALID",
                    message=str(e),
                    retryable=False,
                ),
            )
        except RuntimeError as e:
            errors.append(
                SourceError(
                    source_id=source.id,
                    code="SOURCE_UNREACHABLE",
                    message=str(e),
                    retryable=True,
                ),
            )
        except Exception as e:  # pylint: disable=broad-except
            errors.append(
                SourceError(
                    source_id=source.id,
                    code="SOURCE_LOAD_FAILED",
                    message=str(e),
                    retryable=True,
                ),
            )
        finally:
            if tmp_dir and tmp_dir.exists():
                import shutil

                shutil.rmtree(tmp_dir, ignore_errors=True)

    items.sort(key=lambda item: (item.source_id, item.name.lower(), item.agent_id))
    duration_ms = int((time.time() - started) * 1000)
    meta: dict[str, object] = {
        "generated_at": time.time(),
        "cache_ttl_sec": cfg.cache.ttl_sec,
        "source_count": len(enabled_sources),
        "item_count": len(items),
        "cache_hit": False,
        "duration_ms": duration_ms,
    }

    with _SQUARE_CACHE_LOCK:
        _SQUARE_CACHE["expires_at"] = time.time() + cfg.cache.ttl_sec
        _SQUARE_CACHE["items"] = copy.deepcopy(items)
        _SQUARE_CACHE["errors"] = copy.deepcopy(errors)
        _SQUARE_CACHE["meta"] = copy.deepcopy(meta)
        _SQUARE_CACHE["import_index"] = copy.deepcopy(import_index)

    return items, errors, meta, import_index


def _find_imported_agent(
    config,
    source_id: str,
    original_agent_id: str,
) -> tuple[str, Path] | None:
    for local_agent_id, agent_ref in config.agents.profiles.items():
        metadata_file = Path(agent_ref.workspace_dir) / "imported_from.json"
        if not metadata_file.exists():
            continue
        try:
            payload = json.loads(metadata_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        if (
            payload.get("source_id") == source_id
            and payload.get("original_agent_id") == original_agent_id
        ):
            return local_agent_id, Path(agent_ref.workspace_dir)
    return None


def _persist_import_metadata(workspace_dir: Path, payload: dict[str, str]) -> None:
    metadata_file = workspace_dir / "imported_from.json"
    metadata_file.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _extract_github_source_spec(url: str) -> tuple[str, str, str] | None:
    parsed = urlparse((url or "").strip())
    host = (parsed.netloc or "").lower()
    if host not in {"github.com", "www.github.com"}:
        return None
    parts = [unquote(p) for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        return None

    owner, repo = parts[0], parts[1]
    if repo.endswith(".git"):
        repo = repo[: -len(".git")]
    repo_url = f"https://github.com/{owner}/{repo}.git"
    branch = ""
    path = ""
    if len(parts) >= 4 and parts[2] in {"tree", "blob"}:
        branch = parts[3].strip()
        if len(parts) > 4:
            path = "/".join(parts[4:]).strip()
    return repo_url, branch, path


def _normalize_source_url(url: str) -> str:
    raw = (url or "").strip()
    if _OWNER_REPO_PATTERN.fullmatch(raw):
        return f"https://github.com/{raw}.git"
    return raw


def _normalize_square_source(source: AgentsSquareSourceSpec) -> AgentsSquareSourceSpec:
    normalized = source.model_copy(deep=True)
    github_spec = _extract_github_source_spec(normalized.url)
    if github_spec is not None:
        repo_url, branch, path = github_spec
        normalized.url = repo_url
        if branch and not normalized.branch:
            normalized.branch = branch
        if path and (not normalized.path or normalized.path == "."):
            normalized.path = path
        return normalized

    normalized.url = _normalize_source_url(normalized.url)
    return normalized


def _validate_square_source_url(url: str) -> bool:
    raw = (url or "").strip()
    if not raw:
        return False
    if _OWNER_REPO_PATTERN.fullmatch(raw):
        return True
    if _extract_github_source_spec(raw) is not None:
        return True
    if raw.startswith(("https://", "http://", "git@")):
        return True
    if raw.endswith(".git"):
        return True
    return False


def _validate_square_source_path(path: str) -> bool:
    raw = (path or "").strip() or "."
    p = Path(raw)
    if p.is_absolute():
        return False
    return ".." not in p.parts


def _validate_square_source_ids(sources: list[AgentsSquareSourceSpec]) -> None:
    seen: set[str] = set()
    for source in sources:
        if not _AGENT_ID_RE.fullmatch(source.id):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"SOURCE_ID_INVALID: {source.id}. "
                    "Use lowercase letters, digits, underscore, or hyphen"
                ),
            )
        if source.id in seen:
            raise HTTPException(
                status_code=400,
                detail=f"SOURCE_ID_DUPLICATED: {source.id}",
            )
        seen.add(source.id)


def _square_config_to_payload(cfg: AgentsSquareConfig) -> AgentsSquareSourcesPayload:
    return AgentsSquareSourcesPayload(
        version=cfg.version,
        cache={"ttl_sec": cfg.cache.ttl_sec},
        install={
            "overwrite_default": cfg.install.overwrite_default,
            "preserve_workspace_files": cfg.install.preserve_workspace_files,
        },
        sources=cfg.sources,
    )


def _payload_to_square_config(payload: AgentsSquareSourcesPayload) -> AgentsSquareConfig:
    _validate_square_source_ids(payload.sources)
    normalized_sources: list[AgentsSquareSourceSpec] = []

    for source in payload.sources:
        normalized = _normalize_square_source(source)
        if not _validate_square_source_url(normalized.url):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"SOURCE_URL_INVALID: {source.url}. "
                    "Use owner/repo, http(s), ssh, or .git URL"
                ),
            )
        if not _validate_square_source_path(normalized.path):
            raise HTTPException(
                status_code=400,
                detail=f"SOURCE_INDEX_INVALID: invalid path '{normalized.path}'",
            )
        normalized_sources.append(normalized)

    ttl_sec = int(payload.cache.get("ttl_sec", 600))
    overwrite_default = bool(payload.install.get("overwrite_default", False))
    preserve_workspace_files = bool(
        payload.install.get("preserve_workspace_files", True),
    )

    return AgentsSquareConfig(
        version=max(1, int(payload.version)),
        sources=normalized_sources,
        cache=AgentsSquareCacheConfig(ttl_sec=ttl_sec),
        install=AgentsSquareInstallConfig(
            overwrite_default=overwrite_default,
            preserve_workspace_files=preserve_workspace_files,
        ),
    )


def _get_multi_agent_manager(request: Request | None) -> MultiAgentManager:
    """Get MultiAgentManager from app state."""
    if request is None:
        raise HTTPException(
            status_code=500,
            detail="Request context is required for agent runtime operations",
        )
    if not hasattr(request.app.state, "multi_agent_manager"):
        raise HTTPException(
            status_code=500,
            detail="MultiAgentManager not initialized",
        )
    return request.app.state.multi_agent_manager


@router.get(
    "",
    response_model=AgentListResponse,
    summary="List all agents",
    description="Get list of all configured agents",
)
async def list_agents() -> AgentListResponse:
    """List all configured agents."""
    config = load_config()

    agents = []
    for agent_id, agent_ref in config.agents.profiles.items():
        # Load agent config to get name and description
        try:
            agent_config = load_agent_config(agent_id)
            agents.append(
                AgentSummary(
                    id=agent_id,
                    name=agent_config.name,
                    description=agent_config.description,
                    workspace_dir=agent_ref.workspace_dir,
                ),
            )
        except Exception:  # noqa: E722
            # If agent config load fails, use basic info
            agents.append(
                AgentSummary(
                    id=agent_id,
                    name=agent_id.title(),
                    description="",
                    workspace_dir=agent_ref.workspace_dir,
                ),
            )

    return AgentListResponse(
        agents=agents,
    )


@router.get("/square/sources", response_model=AgentsSquareSourcesPayload)
async def get_square_sources() -> AgentsSquareSourcesPayload:
    """Get Agents Square source configuration."""
    config = load_config()
    return _square_config_to_payload(config.agents_square)


@router.put("/square/sources", response_model=AgentsSquareSourcesPayload)
async def put_square_sources(
    payload: AgentsSquareSourcesPayload,
) -> AgentsSquareSourcesPayload:
    """Update Agents Square source configuration."""
    config = load_config()
    square_cfg = _payload_to_square_config(payload)

    # Pinned sources can be disabled but not removed.
    pinned_ids = {
        source.id
        for source in config.agents_square.sources
        if source.pinned
    }
    next_ids = {source.id for source in square_cfg.sources}
    removed_pinned = pinned_ids - next_ids
    if removed_pinned:
        source_id = sorted(removed_pinned)[0]
        raise HTTPException(
            status_code=400,
            detail=f"SOURCE_PINNED_CANNOT_DELETE: {source_id}",
        )

    config.agents_square = square_cfg
    save_config(config)
    return _square_config_to_payload(square_cfg)


@router.post("/square/sources/validate")
async def validate_square_source(
    payload: ValidateSquareSourceRequest,
) -> dict:
    """Validate a source specification and return normalized contract."""
    normalized = _normalize_square_source(payload)
    if not _validate_square_source_url(normalized.url):
        raise HTTPException(
            status_code=400,
            detail=(
                f"SOURCE_URL_INVALID: {payload.url}. "
                "Use owner/repo, http(s), ssh, or .git URL"
            ),
        )
    if not _validate_square_source_path(normalized.path):
        raise HTTPException(
            status_code=400,
            detail=f"SOURCE_INDEX_INVALID: invalid path '{normalized.path}'",
        )

    probe = subprocess.run(
        ["git", "ls-remote", "--heads", normalized.url],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if probe.returncode != 0:
        raise HTTPException(
            status_code=502,
            detail=(
                "SOURCE_UNREACHABLE: "
                + (probe.stderr.strip() or "ls-remote failed")
            ),
        )

    return {
        "ok": True,
        "normalized": normalized.model_dump(mode="json"),
        "warnings": [],
    }


@router.get("/square/items")
async def get_square_items(refresh: bool = False) -> dict:
    """Get aggregated Agents Square items."""
    config = load_config()
    items, source_errors, meta, _ = _aggregate_square_items(
        config.agents_square,
        refresh=refresh,
    )

    if refresh:
        meta["cache_hit"] = False

    return {
        "items": [item.model_dump(mode="json") for item in items],
        "source_errors": [e.model_dump(mode="json") for e in source_errors],
        "meta": meta,
    }


@router.post("/square/import", response_model=ImportAgentResponse)
async def import_square_agent(
    req: ImportAgentRequest,
) -> ImportAgentResponse:
    """Import a source agent into local agents."""
    config = load_config()
    source = next(
        (s for s in config.agents_square.sources if s.id == req.source_id and s.enabled),
        None,
    )
    if source is None:
        raise HTTPException(
            status_code=404,
            detail=f"AGENT_ITEM_NOT_FOUND: {req.source_id}/{req.agent_id}",
        )

    items, _, _, import_index = _aggregate_square_items(
        config.agents_square,
        refresh=False,
    )
    selected_item = next(
        (
            item
            for item in items
            if item.source_id == req.source_id and item.agent_id == req.agent_id
        ),
        None,
    )
    selected_payload = import_index.get(f"{req.source_id}/{req.agent_id}")
    if selected_item is None or selected_payload is None:
        raise HTTPException(
            status_code=404,
            detail=f"AGENT_ITEM_NOT_FOUND: {req.source_id}/{req.agent_id}",
        )

    content = (selected_payload.get("content") or "").strip()
    if not content:
        raise HTTPException(
            status_code=422,
            detail=(
                "AGENT_TEMPLATE_INVALID: source item has no importable content"
            ),
        )

    overwrite = bool(req.overwrite or config.agents_square.install.overwrite_default)
    preferred_name = (req.preferred_name or "").strip()
    target_name = preferred_name or selected_item.name
    target_description = selected_item.description

    existing_import = _find_imported_agent(
        config,
        req.source_id,
        req.agent_id,
    )

    if existing_import is not None and not overwrite:
        raise HTTPException(
            status_code=409,
            detail=(
                f"AGENT_NAME_CONFLICT: {req.source_id}/{req.agent_id} "
                "already imported"
            ),
        )

    if existing_import is None:
        for local_id in config.agents.profiles:
            try:
                cfg = load_agent_config(local_id)
            except Exception:
                continue
            if cfg.name.strip().lower() == target_name.strip().lower():
                if not overwrite:
                    raise HTTPException(
                        status_code=409,
                        detail=f"AGENT_NAME_CONFLICT: {target_name}",
                    )
                existing_import = (local_id, Path(config.agents.profiles[local_id].workspace_dir))
                break

    if existing_import is not None:
        local_agent_id, workspace_dir = existing_import
        workspace_dir.mkdir(parents=True, exist_ok=True)
        agent_cfg = load_agent_config(local_agent_id)
        agent_cfg.name = target_name
        agent_cfg.description = target_description
        save_agent_config(local_agent_id, agent_cfg)
    else:
        max_attempts = 10
        local_agent_id = None
        for _ in range(max_attempts):
            candidate_id = generate_short_agent_id()
            if candidate_id not in config.agents.profiles:
                local_agent_id = candidate_id
                break
        if local_agent_id is None:
            raise HTTPException(
                status_code=500,
                detail="Failed to generate unique agent ID after 10 attempts",
            )

        workspace_dir = Path(f"{WORKING_DIR}/workspaces/{local_agent_id}").expanduser()
        workspace_dir.mkdir(parents=True, exist_ok=True)

        from ...config.config import (
            ChannelConfig,
            MCPConfig,
            HeartbeatConfig,
            ToolsConfig,
        )

        agent_cfg = AgentProfileConfig(
            id=local_agent_id,
            name=target_name,
            description=target_description,
            workspace_dir=str(workspace_dir),
            language=config.agents.language,
            channels=ChannelConfig(),
            mcp=MCPConfig(),
            heartbeat=HeartbeatConfig(),
            tools=ToolsConfig(),
        )
        _initialize_agent_workspace(workspace_dir, agent_cfg)
        config.agents.profiles[local_agent_id] = AgentProfileRef(
            id=local_agent_id,
            workspace_dir=str(workspace_dir),
        )
        save_config(config)
        save_agent_config(local_agent_id, agent_cfg)

    (workspace_dir / "AGENTS.md").write_text(content + "\n", encoding="utf-8")

    imported_from_payload = {
        "source_id": req.source_id,
        "source_url": selected_payload.get("source_url") or selected_item.source_url,
        "license": selected_payload.get("license") or selected_item.license,
        "original_agent_id": req.agent_id,
        "imported_at": str(int(time.time())),
    }
    _persist_import_metadata(workspace_dir, imported_from_payload)

    return ImportAgentResponse(
        imported=True,
        id=local_agent_id,
        name=target_name,
        workspace_dir=str(workspace_dir),
        source={
            "source_id": req.source_id,
            "source_url": imported_from_payload["source_url"],
            "license": imported_from_payload["license"],
            "original_agent_id": req.agent_id,
        },
    )


@router.get(
    "/{agentId}",
    response_model=AgentProfileConfig,
    summary="Get agent details",
    description="Get complete configuration for a specific agent",
)
async def get_agent(agentId: str = PathParam(...)) -> AgentProfileConfig:
    """Get agent configuration."""
    try:
        agent_config = load_agent_config(agentId)
        return agent_config
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post(
    "",
    response_model=AgentProfileRef,
    status_code=201,
    summary="Create new agent",
    description="Create a new agent (ID is auto-generated by server)",
)
async def create_agent(
    request: CreateAgentRequest = Body(...),
) -> AgentProfileRef:
    """Create a new agent with auto-generated ID."""
    config = load_config()

    # Always generate a unique short UUID (6 characters)
    max_attempts = 10
    new_id = None
    for _ in range(max_attempts):
        candidate_id = generate_short_agent_id()
        if candidate_id not in config.agents.profiles:
            new_id = candidate_id
            break

    if new_id is None:
        raise HTTPException(
            status_code=500,
            detail="Failed to generate unique agent ID after 10 attempts",
        )

    # Create workspace directory
    workspace_dir = Path(
        request.workspace_dir or f"{WORKING_DIR}/workspaces/{new_id}",
    ).expanduser()
    workspace_dir.mkdir(parents=True, exist_ok=True)

    # Build complete agent config with generated ID
    from ...config.config import (
        ChannelConfig,
        MCPConfig,
        HeartbeatConfig,
        ToolsConfig,
    )

    agent_config = AgentProfileConfig(
        id=new_id,
        name=request.name,
        description=request.description,
        workspace_dir=str(workspace_dir),
        language=request.language,
        channels=ChannelConfig(),
        mcp=MCPConfig(),
        heartbeat=HeartbeatConfig(),
        tools=ToolsConfig(),
    )

    # Initialize workspace with default files
    _initialize_agent_workspace(workspace_dir, agent_config)

    # Save agent configuration to workspace/agent.json
    agent_ref = AgentProfileRef(
        id=new_id,
        workspace_dir=str(workspace_dir),
    )

    # Add to root config
    config.agents.profiles[new_id] = agent_ref
    save_config(config)

    # Save agent config to workspace
    save_agent_config(new_id, agent_config)

    logger.info(f"Created new agent: {new_id} (name={request.name})")

    return agent_ref


@router.put(
    "/{agentId}",
    response_model=AgentProfileConfig,
    summary="Update agent",
    description="Update agent configuration and trigger reload",
)
async def update_agent(
    request: Request,
    agentId: str = PathParam(...),
    agent_config: AgentProfileConfig = Body(...),
) -> AgentProfileConfig:
    """Update agent configuration."""
    config = load_config()

    if agentId not in config.agents.profiles:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{agentId}' not found",
        )

    # Load existing complete configuration
    existing_config = load_agent_config(agentId)

    # Merge updates: only update fields that are explicitly set
    update_data = agent_config.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if key != "id":
            setattr(existing_config, key, value)

    # Ensure ID doesn't change
    existing_config.id = agentId

    # Save merged configuration
    save_agent_config(agentId, existing_config)

    # Trigger hot reload if agent is running (async, non-blocking)
    # IMPORTANT: Get manager before creating background task to avoid
    # accessing request object after its lifecycle ends
    manager = _get_multi_agent_manager(request)

    async def reload_in_background():
        try:
            await manager.reload_agent(agentId)
        except Exception as e:
            logger.warning(f"Background reload failed for {agentId}: {e}")

    asyncio.create_task(reload_in_background())

    return agent_config


@router.delete(
    "/{agentId}",
    summary="Delete agent",
    description="Delete agent and workspace (cannot delete default agent)",
)
async def delete_agent(
    request: Request,
    agentId: str = PathParam(...),
) -> dict:
    """Delete an agent."""
    config = load_config()

    if agentId not in config.agents.profiles:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{agentId}' not found",
        )

    if agentId == "default":
        raise HTTPException(
            status_code=400,
            detail="Cannot delete the default agent",
        )

    # Stop agent instance if running
    manager = _get_multi_agent_manager(request)
    await manager.stop_agent(agentId)

    # Remove from config
    del config.agents.profiles[agentId]
    save_config(config)

    # Note: We don't delete the workspace directory for safety
    # Users can manually delete it if needed

    return {"success": True, "agent_id": agentId}


@router.get(
    "/{agentId}/files",
    response_model=list[MdFileInfo],
    summary="List agent workspace files",
    description="List all markdown files in agent's workspace",
)
async def list_agent_files(
    request: Request,
    agentId: str = PathParam(...),
) -> list[MdFileInfo]:
    """List agent workspace files."""
    manager = _get_multi_agent_manager(request)

    try:
        workspace = await manager.get_agent(agentId)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    workspace_manager = AgentMdManager(str(workspace.workspace_dir))

    try:
        files = [
            MdFileInfo.model_validate(file)
            for file in workspace_manager.list_working_mds()
        ]
        return files
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get(
    "/{agentId}/files/{filename}",
    response_model=MdFileContent,
    summary="Read agent workspace file",
    description="Read a markdown file from agent's workspace",
)
async def read_agent_file(
    request: Request,
    agentId: str = PathParam(...),
    filename: str = PathParam(...),
) -> MdFileContent:
    """Read agent workspace file."""
    manager = _get_multi_agent_manager(request)

    try:
        workspace = await manager.get_agent(agentId)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    workspace_manager = AgentMdManager(str(workspace.workspace_dir))

    try:
        content = workspace_manager.read_working_md(filename)
        return MdFileContent(content=content)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"File '{filename}' not found",
        ) from exc
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.put(
    "/{agentId}/files/{filename}",
    response_model=dict,
    summary="Write agent workspace file",
    description="Create or update a markdown file in agent's workspace",
)
async def write_agent_file(
    request: Request,
    agentId: str = PathParam(...),
    filename: str = PathParam(...),
    file_content: MdFileContent = Body(...),
) -> dict:
    """Write agent workspace file."""
    manager = _get_multi_agent_manager(request)

    try:
        workspace = await manager.get_agent(agentId)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    workspace_manager = AgentMdManager(str(workspace.workspace_dir))

    try:
        workspace_manager.write_working_md(filename, file_content.content)
        return {"written": True, "filename": filename}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get(
    "/{agentId}/memory",
    response_model=list[MdFileInfo],
    summary="List agent memory files",
    description="List all memory files for an agent",
)
async def list_agent_memory(
    request: Request,
    agentId: str = PathParam(...),
) -> list[MdFileInfo]:
    """List agent memory files."""
    manager = _get_multi_agent_manager(request)

    try:
        workspace = await manager.get_agent(agentId)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    workspace_manager = AgentMdManager(str(workspace.workspace_dir))

    try:
        files = [
            MdFileInfo.model_validate(file)
            for file in workspace_manager.list_memory_mds()
        ]
        return files
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


def _initialize_agent_workspace(  # pylint: disable=too-many-branches
    workspace_dir: Path,
    agent_config: AgentProfileConfig,  # pylint: disable=unused-argument
) -> None:
    """Initialize agent workspace (similar to copaw init --defaults).

    Args:
        workspace_dir: Path to agent workspace
        agent_config: Agent configuration (reserved for future use)
    """
    import shutil
    from ...config import load_config as load_global_config

    # Create essential subdirectories
    (workspace_dir / "sessions").mkdir(exist_ok=True)
    (workspace_dir / "memory").mkdir(exist_ok=True)
    (workspace_dir / "active_skills").mkdir(exist_ok=True)
    (workspace_dir / "customized_skills").mkdir(exist_ok=True)

    # Get language from global config
    config = load_global_config()
    language = config.agents.language or "zh"

    # Copy MD files from agents/md_files/{language}/ to workspace
    md_files_dir = (
        Path(__file__).parent.parent.parent / "agents" / "md_files" / language
    )
    if md_files_dir.exists():
        for md_file in md_files_dir.glob("*.md"):
            target_file = workspace_dir / md_file.name
            if not target_file.exists():
                try:
                    shutil.copy2(md_file, target_file)
                except Exception as e:
                    logger.warning(
                        f"Failed to copy {md_file.name}: {e}",
                    )

    # Create HEARTBEAT.md if not exists
    heartbeat_file = workspace_dir / "HEARTBEAT.md"
    if not heartbeat_file.exists():
        DEFAULT_HEARTBEAT_MDS = {
            "zh": """# Heartbeat checklist
- 扫描收件箱紧急邮件
- 查看未来 2h 的日历
- 检查待办是否卡住
- 若安静超过 8h，轻量 check-in
""",
            "en": """# Heartbeat checklist
- Scan inbox for urgent email
- Check calendar for next 2h
- Check tasks for blockers
- Light check-in if quiet for 8h
""",
            "ru": """# Heartbeat checklist
- Проверить входящие на срочные письма
- Просмотреть календарь на ближайшие 2 часа
- Проверить задачи на наличие блокировок
- Лёгкая проверка при отсутствии активности более 8 часов
""",
        }
        heartbeat_content = DEFAULT_HEARTBEAT_MDS.get(
            language,
            DEFAULT_HEARTBEAT_MDS["en"],
        )
        with open(heartbeat_file, "w", encoding="utf-8") as f:
            f.write(heartbeat_content.strip())

    # Copy builtin skills to agent's active_skills directory
    builtin_skills_dir = (
        Path(__file__).parent.parent.parent / "agents" / "skills"
    )
    if builtin_skills_dir.exists():
        for skill_dir in builtin_skills_dir.iterdir():
            if skill_dir.is_dir() and (skill_dir / "SKILL.md").exists():
                target_skill_dir = (
                    workspace_dir / "active_skills" / skill_dir.name
                )
                if not target_skill_dir.exists():
                    try:
                        shutil.copytree(skill_dir, target_skill_dir)
                    except Exception as e:
                        logger.warning(
                            f"Failed to copy skill {skill_dir.name}: {e}",
                        )

    # Create empty jobs.json for cron jobs
    jobs_file = workspace_dir / "jobs.json"
    if not jobs_file.exists():
        with open(jobs_file, "w", encoding="utf-8") as f:
            json.dump(
                {"version": 1, "jobs": []},
                f,
                ensure_ascii=False,
                indent=2,
            )

    # Create empty chats.json for chat history
    chats_file = workspace_dir / "chats.json"
    if not chats_file.exists():
        with open(chats_file, "w", encoding="utf-8") as f:
            json.dump(
                {"version": 1, "chats": []},
                f,
                ensure_ascii=False,
                indent=2,
            )

    # Create empty token_usage.json
    token_usage_file = workspace_dir / "token_usage.json"
    if not token_usage_file.exists():
        with open(token_usage_file, "w", encoding="utf-8") as f:
            f.write("[]")
