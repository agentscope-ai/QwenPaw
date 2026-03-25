# -*- coding: utf-8 -*-
"""Multi-agent management API.

Provides RESTful API for managing multiple agent instances.
"""
import asyncio
import copy
import json
import logging
import re
import shutil
import tempfile
import subprocess
import threading
import time
import unicodedata
from pathlib import Path
from datetime import datetime
from typing import Any, cast
from urllib.parse import unquote, urlparse
from fastapi import APIRouter, Body, HTTPException, Request
from fastapi import Path as PathParam
from pydantic import BaseModel, Field

from ..utils import schedule_agent_reload
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
from ...agents.skills_manager import (
    prune_active_skills,
    sync_skills_to_working_dir,
)
from ...agents.utils import copy_builtin_qa_md_files
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
    enabled: bool = True
    project_count: int = 0
    projects: list["ProjectSummary"] = Field(default_factory=list)


class ProjectSummary(BaseModel):
    """Project summary information under an agent workspace."""

    id: str
    name: str
    description: str = ""
    status: str = "active"
    workspace_dir: str
    data_dir: str
    metadata_file: str
    tags: list[str] = Field(default_factory=list)
    updated_time: str


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


class ProjectFileInfo(BaseModel):
    """Project file metadata."""

    filename: str
    path: str
    size: int
    modified_time: str


class ProjectFileContent(BaseModel):
    """Project file content."""

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
_AGENTS_SQUARE_DEFAULT_DIR = Path(__file__).resolve().parents[2] / "agents_square"
_AGENTS_SQUARE_CONFIG_PATH = WORKING_DIR / "agents_square" / "config.json"
_AGENTS_SQUARE_DEFAULT_PATH = _AGENTS_SQUARE_DEFAULT_DIR / "default.json"
_PROJECTS_DIRNAME = "projects"
_PROJECT_METADATA_FILENAMES = ("PROJECT.md", "project.md")


def _ensure_square_config_initialized() -> None:
    """Ensure agents_square/config.json exists, bootstrap from default.json."""
    if _AGENTS_SQUARE_CONFIG_PATH.exists():
        return

    _AGENTS_SQUARE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

    if _AGENTS_SQUARE_DEFAULT_PATH.exists():
        shutil.copyfile(_AGENTS_SQUARE_DEFAULT_PATH, _AGENTS_SQUARE_CONFIG_PATH)
        return

    # Last resort fallback when default.json is missing.
    fallback_payload = {
        "version": 1,
        "sources": [],
        "cache": {"ttl_sec": 600},
        "install": {
            "overwrite_default": False,
            "preserve_workspace_files": True,
        },
    }
    _AGENTS_SQUARE_CONFIG_PATH.write_text(
        json.dumps(fallback_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _load_square_payload_from_file(path: Path) -> AgentsSquareSourcesPayload:
    """Load Agents Square payload from file."""
    try:
        raw_text = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"SQUARE_CONFIG_READ_FAILED: {path.name}: {exc}",
        ) from exc

    if not raw_text:
        raise HTTPException(
            status_code=500,
            detail=f"SQUARE_CONFIG_INVALID: {path.name} is empty",
        )

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"SQUARE_CONFIG_INVALID_JSON: {path.name}: {exc}",
        ) from exc

    return AgentsSquareSourcesPayload.model_validate(parsed)


def _load_current_square_config() -> AgentsSquareConfig:
    """Load current square config from agents_square/config.json."""
    _ensure_square_config_initialized()
    payload = _load_square_payload_from_file(_AGENTS_SQUARE_CONFIG_PATH)
    return _payload_to_square_config(payload)


def _load_default_square_config() -> AgentsSquareConfig:
    """Load bundled square defaults from agents_square/default.json."""
    if not _AGENTS_SQUARE_DEFAULT_PATH.exists():
        _ensure_square_config_initialized()
        return _load_current_square_config()

    payload = _load_square_payload_from_file(_AGENTS_SQUARE_DEFAULT_PATH)
    return _payload_to_square_config(payload)


def _save_current_square_config(cfg: AgentsSquareConfig) -> None:
    """Persist current square config to agents_square/config.json."""
    _AGENTS_SQUARE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = _square_config_to_payload(cfg).model_dump(mode="json")
    _AGENTS_SQUARE_CONFIG_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _reset_current_square_config_to_default() -> AgentsSquareConfig:
    """Reset current square config by copying default.json to config.json."""
    _AGENTS_SQUARE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

    if _AGENTS_SQUARE_DEFAULT_PATH.exists():
        shutil.copyfile(_AGENTS_SQUARE_DEFAULT_PATH, _AGENTS_SQUARE_CONFIG_PATH)
        return _load_current_square_config()

    # Fallback when default.json is missing.
    fallback_cfg = _load_default_square_config()
    _save_current_square_config(fallback_cfg)
    return fallback_cfg


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


def _format_iso_time(ts: float) -> str:
    return datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def _safe_project_data_subdir(raw_value: str) -> str:
    candidate = (raw_value or "").strip() or "data"
    path = Path(candidate)
    if path.is_absolute() or ".." in path.parts:
        return "data"
    normalized = path.as_posix().strip("/")
    return normalized or "data"


def _parse_project_tags(raw_tags: Any) -> list[str]:
    if isinstance(raw_tags, list):
        return [str(item).strip() for item in raw_tags if str(item).strip()]
    if isinstance(raw_tags, str):
        return [item.strip() for item in raw_tags.split(",") if item.strip()]
    return []


def _first_nonempty_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped
    return ""


def _load_project_summary(project_dir: Path) -> ProjectSummary | None:
    metadata_file = next(
        (project_dir / name for name in _PROJECT_METADATA_FILENAMES if (project_dir / name).is_file()),
        None,
    )
    if metadata_file is None:
        return None

    parsed = _parse_markdown_frontmatter(metadata_file)
    metadata: dict[str, Any] = {}
    body = ""
    if parsed is not None:
        metadata, body = parsed
    else:
        body = metadata_file.read_text(encoding="utf-8", errors="ignore")

    data_subdir = _safe_project_data_subdir(
        str(metadata.get("data_dir") or metadata.get("dataDir") or "data"),
    )
    project_id = str(metadata.get("id") or project_dir.name).strip() or project_dir.name
    project_name = str(metadata.get("name") or project_dir.name).strip() or project_dir.name
    description = str(metadata.get("description") or _first_nonempty_line(body)).strip()
    status = str(metadata.get("status") or "active").strip() or "active"
    tags = _parse_project_tags(metadata.get("tags"))
    updated_time = _format_iso_time(metadata_file.stat().st_mtime)

    return ProjectSummary(
        id=project_id,
        name=project_name,
        description=description,
        status=status,
        workspace_dir=str(project_dir),
        data_dir=str(project_dir / data_subdir),
        metadata_file=str(metadata_file),
        tags=tags,
        updated_time=updated_time,
    )


def _list_agent_projects(workspace_dir: Path) -> list[ProjectSummary]:
    projects_dir = workspace_dir / _PROJECTS_DIRNAME
    if not projects_dir.exists() or not projects_dir.is_dir():
        return []

    projects: list[ProjectSummary] = []
    for project_dir in sorted(projects_dir.iterdir(), key=lambda item: item.name.lower()):
        if not project_dir.is_dir():
            continue
        summary = _load_project_summary(project_dir)
        if summary is not None:
            projects.append(summary)
    return projects


def _ensure_projects_layout(workspace_dir: Path) -> None:
    projects_dir = workspace_dir / _PROJECTS_DIRNAME
    projects_dir.mkdir(exist_ok=True)
    readme_path = projects_dir / "README.md"
    if readme_path.exists():
        return

    readme_path.write_text(
        """# Projects

Store one project per subdirectory, for example:

- project-abcde123/
  - PROJECT.md
  - data/

The project metadata should be declared in PROJECT.md frontmatter:

---
id: project-abcde123
name: Example project
description: Short summary
status: active
data_dir: data
tags: [demo, draft]
---

Project details go below.
""",
        encoding="utf-8",
    )


def _resolve_project_dir(workspace_dir: Path, project_id: str) -> Path:
    projects_dir = workspace_dir / _PROJECTS_DIRNAME
    if not projects_dir.exists() or not projects_dir.is_dir():
        raise HTTPException(status_code=404, detail="Projects directory not found")

    for project_dir in sorted(projects_dir.iterdir(), key=lambda item: item.name.lower()):
        if not project_dir.is_dir():
            continue
        summary = _load_project_summary(project_dir)
        if summary is None:
            continue
        if summary.id == project_id or project_dir.name == project_id:
            return project_dir

    raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")


def _is_safe_relative_path(rel_path: str) -> bool:
    if not rel_path:
        return False
    candidate = Path(rel_path)
    if candidate.is_absolute() or ".." in candidate.parts:
        return False
    return True


def _list_project_files(project_dir: Path) -> list[ProjectFileInfo]:
    project_root = project_dir.resolve()
    files: list[ProjectFileInfo] = []

    for path in sorted(project_root.rglob("*"), key=lambda item: item.as_posix().lower()):
        if not path.is_file():
            continue

        rel = path.resolve().relative_to(project_root).as_posix()
        if rel.startswith(".git/") or "/.git/" in rel:
            continue

        stat = path.stat()
        files.append(
            ProjectFileInfo(
                filename=path.name,
                path=rel,
                size=stat.st_size,
                modified_time=_format_iso_time(stat.st_mtime),
            ),
        )

    return files


def _read_project_text_file(project_dir: Path, rel_path: str) -> str:
    if not _is_safe_relative_path(rel_path):
        raise HTTPException(status_code=400, detail="Invalid file path")

    target = (project_dir / rel_path).resolve()
    project_root = project_dir.resolve()
    if not str(target).startswith(str(project_root)):
        raise HTTPException(status_code=400, detail="Invalid file path")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail=f"File '{rel_path}' not found")

    raw = target.read_bytes()
    if b"\x00" in raw[:4096]:
        raise HTTPException(status_code=400, detail="Binary file preview is not supported")
    return raw.decode("utf-8", errors="replace")


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


def _read_profile_description(workspace_dir: str) -> str:
    """Read description from PROFILE.md if exists.

    Extracts identity section from PROFILE.md as fallback description.

    Args:
        workspace_dir: Path to agent workspace

    Returns:
        Description text from PROFILE.md, or empty string if not found
    """
    try:
        profile_path = Path(workspace_dir) / "PROFILE.md"
        if not profile_path.exists():
            return ""

        content = profile_path.read_text(encoding="utf-8")
        lines = []
        in_identity = False

        for line in content.split("\n"):
            if line.strip().startswith("## 身份") or line.strip().startswith(
                "## Identity",
            ):
                in_identity = True
                continue
            if in_identity:
                if line.strip().startswith("##"):
                    break
                if line.strip() and not line.strip().startswith("#"):
                    lines.append(line.strip())

        return " ".join(lines)[:200] if lines else ""
    except Exception:  # noqa: E722
        return ""


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
        workspace_dir = Path(agent_ref.workspace_dir)
        _ensure_projects_layout(workspace_dir)
        projects = _list_agent_projects(workspace_dir)

        # Load agent config to get name and description
        try:
            agent_config = load_agent_config(agent_id)
            description = agent_config.description or ""

            # Always read PROFILE.md and append/merge
            profile_desc = _read_profile_description(agent_ref.workspace_dir)
            if profile_desc:
                if description.strip():
                    # Both exist: merge with separator
                    description = f"{description.strip()} | {profile_desc}"
                else:
                    # Only PROFILE.md exists
                    description = profile_desc

            agents.append(
                AgentSummary(
                    id=agent_id,
                    name=agent_config.name,
                    description=description,
                    workspace_dir=agent_ref.workspace_dir,
                    enabled=getattr(agent_ref, "enabled", True),
                    project_count=len(projects),
                    projects=projects,
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
                    enabled=getattr(agent_ref, "enabled", True),
                    project_count=len(projects),
                    projects=projects,
                ),
            )

    return AgentListResponse(
        agents=agents,
    )


@router.get("/square/sources", response_model=AgentsSquareSourcesPayload)
async def get_square_sources() -> AgentsSquareSourcesPayload:
    """Get Agents Square source configuration."""
    square_cfg = _load_current_square_config()
    return _square_config_to_payload(square_cfg)


@router.get("/square/sources/defaults", response_model=AgentsSquareSourcesPayload)
async def get_square_source_defaults() -> AgentsSquareSourcesPayload:
    """Get bundled Agents Square default source configuration from package."""
    square_cfg = _load_default_square_config()
    return _square_config_to_payload(square_cfg)


@router.put("/square/sources", response_model=AgentsSquareSourcesPayload)
async def put_square_sources(
    payload: AgentsSquareSourcesPayload,
) -> AgentsSquareSourcesPayload:
    """Update Agents Square source configuration."""
    current_square_cfg = _load_current_square_config()
    square_cfg = _payload_to_square_config(payload)

    # Pinned sources can be disabled but not removed.
    pinned_ids = {
        source.id
        for source in current_square_cfg.sources
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

    _save_current_square_config(square_cfg)

    # Keep root config in sync for backward compatibility.
    config = load_config()
    config.agents_square = square_cfg
    save_config(config)
    return _square_config_to_payload(square_cfg)


@router.post("/square/sources/reset", response_model=AgentsSquareSourcesPayload)
async def reset_square_sources() -> AgentsSquareSourcesPayload:
    """Reset current square sources by copying bundled default.json."""
    square_cfg = _reset_current_square_config_to_default()

    # Keep root config in sync for backward compatibility.
    config = load_config()
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
    square_cfg = _load_current_square_config()
    items, source_errors, meta, _ = _aggregate_square_items(
        square_cfg,
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
    square_cfg = _load_current_square_config()
    config = load_config()
    source = next(
        (s for s in square_cfg.sources if s.id == req.source_id and s.enabled),
        None,
    )
    if source is None:
        raise HTTPException(
            status_code=404,
            detail=f"AGENT_ITEM_NOT_FOUND: {req.source_id}/{req.agent_id}",
        )

    items, _, _, import_index = _aggregate_square_items(
        square_cfg,
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

    overwrite = bool(req.overwrite or square_cfg.install.overwrite_default)
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
        enabled=True,
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
    schedule_agent_reload(request, agentId)

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


@router.patch(
    "/{agentId}/toggle",
    summary="Toggle agent enabled state",
    description="Enable or disable an agent (cannot disable default agent)",
)
async def toggle_agent_enabled(
    agentId: str = PathParam(...),
    enabled: bool = Body(..., embed=True),
    request: Request = None,
) -> dict:
    """Toggle agent enabled state.

    When disabling an agent:
    1. Stop the agent instance if running
    2. Update enabled field in config.json

    When enabling an agent:
    1. Update enabled field in config.json
    2. Agent will be started immediately
    """
    config = load_config()

    if agentId not in config.agents.profiles:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{agentId}' not found",
        )

    if agentId == "default":
        raise HTTPException(
            status_code=400,
            detail="Cannot disable the default agent",
        )

    agent_ref = config.agents.profiles[agentId]
    manager = _get_multi_agent_manager(request)

    # If disabling, stop the agent instance
    if not enabled and getattr(agent_ref, "enabled", True):
        await manager.stop_agent(agentId)

    # Update enabled status
    agent_ref.enabled = enabled
    save_config(config)

    # If enabling, start the agent instance immediately
    if enabled:
        try:
            await manager.get_agent(agentId)
            logger.info(f"Agent {agentId} started successfully")
        except Exception as e:
            logger.error(f"Failed to start agent {agentId}: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Agent enabled but failed to start: {str(e)}",
            ) from e

    return {
        "success": True,
        "agent_id": agentId,
        "enabled": enabled,
    }


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


@router.get(
    "/{agentId}/projects/{projectId}/files",
    response_model=list[ProjectFileInfo],
    summary="List project files",
    description="List files under a project directory",
)
async def list_agent_project_files(
    request: Request,
    agentId: str = PathParam(...),
    projectId: str = PathParam(...),
) -> list[ProjectFileInfo]:
    """List files under a project."""
    manager = _get_multi_agent_manager(request)

    try:
        workspace = await manager.get_agent(agentId)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    try:
        project_dir = _resolve_project_dir(Path(workspace.workspace_dir), projectId)
        return _list_project_files(project_dir)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get(
    "/{agentId}/projects/{projectId}/files/{filePath:path}",
    response_model=ProjectFileContent,
    summary="Read project file",
    description="Read text content from a project file",
)
async def read_agent_project_file(
    request: Request,
    agentId: str = PathParam(...),
    projectId: str = PathParam(...),
    filePath: str = PathParam(...),
) -> ProjectFileContent:
    """Read text content from a project file."""
    manager = _get_multi_agent_manager(request)

    try:
        workspace = await manager.get_agent(agentId)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    try:
        project_dir = _resolve_project_dir(Path(workspace.workspace_dir), projectId)
        content = _read_project_text_file(project_dir, filePath)
        return ProjectFileContent(content=content)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


def _ensure_default_heartbeat_md(workspace_dir: Path, language: str) -> None:
    """Write a default HEARTBEAT.md when the workspace has none."""
    heartbeat_file = workspace_dir / "HEARTBEAT.md"
    if heartbeat_file.exists():
        return
    default_by_lang = {
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
    content = default_by_lang.get(language, default_by_lang["en"])
    with open(heartbeat_file, "w", encoding="utf-8") as f:
        f.write(content.strip())


def _initialize_agent_workspace(  # pylint: disable=too-many-branches
    workspace_dir: Path,
    agent_config: AgentProfileConfig,  # pylint: disable=unused-argument
    *,
    active_skill_names: list[str] | None = None,
    builtin_qa_md_seed: bool = False,
) -> None:
    """Initialize agent workspace (similar to copaw init --defaults).

    Args:
        workspace_dir: Path to agent workspace
        agent_config: Agent configuration (reserved for future use)
        active_skill_names: If set, only these skills are synced to
            ``active_skills``; others are removed. If ``None``, copy all
            builtin skills when missing (default for new agents).
        builtin_qa_md_seed: If True, seed the builtin QA persona from
            ``md_files/qa/<lang>/`` (AGENTS, PROFILE, SOUL), copy MEMORY and
            HEARTBEAT from the normal language pack, and **omit** BOOTSTRAP.md
            so bootstrap mode never triggers.
    """
    from ...config import load_config as load_global_config

    workspace_dir = Path(workspace_dir).expanduser()

    # Create essential subdirectories
    (workspace_dir / "sessions").mkdir(exist_ok=True)
    (workspace_dir / "memory").mkdir(exist_ok=True)
    (workspace_dir / "active_skills").mkdir(exist_ok=True)
    (workspace_dir / "customized_skills").mkdir(exist_ok=True)
    _ensure_projects_layout(workspace_dir)

    # Get language from global config
    config = load_global_config()
    language = config.agents.language or "zh"

    package_agents_root = Path(__file__).parent.parent.parent / "agents"
    md_files_dir = package_agents_root / "md_files" / language

    if builtin_qa_md_seed:
        copy_builtin_qa_md_files(
            language,
            workspace_dir,
            only_if_missing=True,
        )
    elif md_files_dir.exists():
        for md_file in md_files_dir.glob("*.md"):
            target_file = workspace_dir / md_file.name
            if not target_file.exists():
                try:
                    shutil.copy2(md_file, target_file)
                except Exception as e:
                    logger.warning(
                        f"Failed to copy {md_file.name}: {e}",
                    )

    _ensure_default_heartbeat_md(workspace_dir, language)

    builtin_skills_dir = package_agents_root / "skills"
    if active_skill_names is not None:
        synced, skipped = sync_skills_to_working_dir(
            workspace_dir,
            skill_names=active_skill_names,
            force=True,
        )
        logger.debug(
            "Synced skills for %s: synced=%s skipped=%s names=%s",
            workspace_dir,
            synced,
            skipped,
            active_skill_names,
        )
        prune_active_skills(workspace_dir, set(active_skill_names))
    elif builtin_skills_dir.exists():
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
