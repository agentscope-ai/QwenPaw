# -*- coding: utf-8 -*-
"""Workspace and skill-pool APIs."""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ...agents.skills_hub import (
    SkillImportCancelled,
    search_hub_skills,
    import_pool_skill_from_hub,
    install_skill_from_hub,
)
from ...agents.skills_manager import (
    SkillConflictError,
    SkillPoolService,
    SkillInfo,
    SkillService,
    _default_pool_manifest,
    _default_workspace_manifest,
    _mutate_json,
    get_pool_builtin_sync_status,
    get_pool_skill_manifest_path,
    get_workspace_skill_manifest_path,
    import_builtin_skills,
    list_builtin_import_candidates,
    list_workspaces,
    read_skill_pool_manifest,
    read_skill_manifest,
    reconcile_workspace_manifest,
    suggest_conflict_name,
    update_single_builtin,
)
from ...config import load_config, save_config
from ...config.config import (
    SkillMarketSpec,
    SkillsMarketCacheConfig,
    SkillsMarketConfig,
    SkillsMarketInstallConfig,
)
from ...security.skill_scanner import SkillScanError
from ..utils import schedule_agent_reload

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/skills", tags=["skills"])


def _scan_error_payload(exc: SkillScanError) -> dict[str, Any]:
    """Normalize scanner exceptions into a stable API payload.

    Example response body:
        {
            "type": "security_scan_failed",
            "skill_name": "blocked_skill",
            "max_severity": "high",
            "findings": [...]
        }
    """
    result = exc.result
    return {
        "type": "security_scan_failed",
        "detail": str(exc),
        "skill_name": result.skill_name,
        "max_severity": result.max_severity.value,
        "findings": [
            {
                "severity": f.severity.value,
                "title": f.title,
                "description": f.description,
                "file_path": f.file_path,
                "line_number": f.line_number,
                "rule_id": f.rule_id,
            }
            for f in result.findings
        ],
    }


def _scan_error_response(exc: SkillScanError) -> JSONResponse:
    """Build the historical 422 response shape used by skill endpoints.

    We intentionally return a real HTTP 422 response object here so callers
    and tests observe the same behavior as before the skill-pool refactor.
    """
    return JSONResponse(
        status_code=422,
        content=_scan_error_payload(exc),
    )


class SkillSpec(SkillInfo):
    enabled: bool = False
    channels: list[str] = Field(default_factory=lambda: ["all"])
    sync_to_pool: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)


class PoolSkillSpec(SkillInfo):
    protected: bool = False
    commit_text: str = ""
    sync_status: str = ""
    latest_version_text: str = ""
    config: dict[str, Any] = Field(default_factory=dict)


class WorkspaceSkillSummary(BaseModel):
    agent_id: str
    agent_name: str = ""
    workspace_dir: str
    skills: list[SkillSpec] = Field(default_factory=list)


class HubSkillSpec(BaseModel):
    slug: str
    name: str
    description: str = ""
    version: str = ""
    source_url: str = ""


class BuiltinImportSpec(BaseModel):
    name: str
    description: str = ""
    version_text: str = ""
    current_version_text: str = ""
    current_source: str = ""
    status: str = ""


class ImportBuiltinRequest(BaseModel):
    skill_names: list[str] = Field(default_factory=list)
    overwrite_conflicts: bool = False


class CreateSkillRequest(BaseModel):
    name: str
    content: str
    overwrite: bool = False
    references: dict[str, Any] | None = None
    scripts: dict[str, Any] | None = None
    config: dict[str, Any] | None = None
    enable: bool = True


class UploadToPoolRequest(BaseModel):
    workspace_id: str
    skill_name: str
    new_name: str | None = None
    overwrite: bool = False


class PoolDownloadTarget(BaseModel):
    workspace_id: str
    target_name: str | None = None


class DownloadFromPoolRequest(BaseModel):
    skill_name: str
    targets: list[PoolDownloadTarget] = Field(default_factory=list)
    all_workspaces: bool = False
    overwrite: bool = False


class SkillConfigRequest(BaseModel):
    config: dict[str, Any] = Field(default_factory=dict)


class SavePoolSkillRequest(CreateSkillRequest):
    source_name: str | None = None


class SaveSkillRequest(CreateSkillRequest):
    source_name: str | None = None


class HubInstallRequest(BaseModel):
    bundle_url: str = Field(..., description="Skill URL")
    version: str = Field(default="", description="Optional version tag")
    enable: bool = Field(default=True, description="Enable after import")
    target_name: str = Field(default="", description="Optional renamed skill")
    overwrite: bool = Field(
        default=False,
        description="Overwrite existing workspace skill",
    )


class HubInstallTaskStatus(str, Enum):
    PENDING = "pending"
    IMPORTING = "importing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class HubInstallTask(BaseModel):
    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    bundle_url: str
    version: str = ""
    enable: bool = True
    overwrite: bool = False
    status: HubInstallTaskStatus = HubInstallTaskStatus.PENDING
    error: str | None = None
    result: dict[str, Any] | None = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


_hub_install_tasks: dict[str, HubInstallTask] = {}
_hub_install_runtime_tasks: dict[str, asyncio.Task] = {}
_hub_install_cancel_events: dict[str, threading.Event] = {}
_hub_install_lock = asyncio.Lock()


class SkillsMarketPayload(BaseModel):
    version: int = Field(default=1)
    cache: dict[str, int] = Field(default_factory=lambda: {"ttl_sec": 600})
    install: dict[str, bool] = Field(
        default_factory=lambda: {"overwrite_default": False},
    )
    markets: list[SkillMarketSpec] = Field(default_factory=list)


class ValidateMarketRequest(SkillMarketSpec):
    pass


class MarketError(BaseModel):
    market_id: str
    code: str
    message: str
    retryable: bool = False


class MarketplaceItem(BaseModel):
    market_id: str
    skill_id: str
    name: str
    description: str = ""
    version: str = ""
    source_url: str
    install_url: str
    tags: list[str] = Field(default_factory=list)


class InstallMarketplaceRequest(BaseModel):
    market_id: str
    skill_id: str
    enable: bool = True
    overwrite: bool = False


_OWNER_REPO_PATTERN = re.compile(r"^[\w.-]+/[\w.-]+$")
_MARKETPLACE_CACHE_LOCK = threading.Lock()
_MARKETPLACE_CACHE: dict[str, Any] = {
    "expires_at": 0.0,
    "items": [],
    "errors": [],
    "meta": {},
}
_SKILLS_MARKET_DEFAULT_DIR = Path(__file__).resolve().parents[2] / "skills_market"
_SKILLS_MARKET_CONFIG_PATH = _SKILLS_MARKET_DEFAULT_DIR / "config.json"
_SKILLS_MARKET_DEFAULT_PATH = _SKILLS_MARKET_DEFAULT_DIR / "default.json"

_ALLOWED_ZIP_TYPES = {
    "application/zip",
    "application/x-zip-compressed",
    "application/octet-stream",
}
_MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 MB


def _load_market_payload_from_path(path: Path) -> SkillsMarketPayload:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return SkillsMarketPayload.model_validate(raw)


def _write_market_payload_to_path(payload: SkillsMarketPayload, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _load_current_market_config() -> SkillsMarketConfig:
    if _SKILLS_MARKET_CONFIG_PATH.exists():
        return _payload_to_market_config(
            _load_market_payload_from_path(_SKILLS_MARKET_CONFIG_PATH),
        )
    return load_config().skills_market


def _extract_github_market_spec(url: str) -> tuple[str, str, str] | None:
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


def _normalize_market_url(url: str) -> str:
    raw = (url or "").strip()
    if _OWNER_REPO_PATTERN.fullmatch(raw):
        return f"https://github.com/{raw}.git"
    return raw


def _normalize_market_spec(market: SkillMarketSpec) -> SkillMarketSpec:
    normalized = market.model_copy(deep=True)
    github_spec = _extract_github_market_spec(normalized.url)
    if github_spec is not None:
        repo_url, branch, path = github_spec
        normalized.url = repo_url
        if branch and not normalized.branch:
            normalized.branch = branch
        if path and (
            not normalized.path
            or normalized.path == "index.json"
            or normalized.path == "/"
        ):
            normalized.path = path
        return normalized
    normalized.url = _normalize_market_url(normalized.url)
    return normalized


def _validate_market_url(url: str) -> bool:
    raw = (url or "").strip()
    if not raw:
        return False
    if _OWNER_REPO_PATTERN.fullmatch(raw):
        return True
    if _extract_github_market_spec(raw) is not None:
        return True
    if raw.startswith(("https://", "http://", "git@")):
        return True
    if raw.endswith(".git"):
        return True
    return False


def _validate_market_path(path: str) -> bool:
    raw = (path or "").strip() or "index.json"
    candidate = Path(raw)
    if candidate.is_absolute():
        return False
    return ".." not in candidate.parts


def _validate_market_ids(markets: list[SkillMarketSpec]) -> None:
    seen: set[str] = set()
    for market in markets:
        if market.id in seen:
            raise HTTPException(
                status_code=400,
                detail=f"MARKET_ID_DUPLICATED: {market.id}",
            )
        seen.add(market.id)


def _market_config_to_payload(cfg: SkillsMarketConfig) -> SkillsMarketPayload:
    return SkillsMarketPayload(
        version=cfg.version,
        cache={"ttl_sec": cfg.cache.ttl_sec},
        install={"overwrite_default": cfg.install.overwrite_default},
        markets=cfg.markets,
    )


def _payload_to_market_config(payload: SkillsMarketPayload) -> SkillsMarketConfig:
    _validate_market_ids(payload.markets)
    normalized_markets: list[SkillMarketSpec] = []
    for market in payload.markets:
        normalized_market = _normalize_market_spec(market)
        if not _validate_market_url(normalized_market.url):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"MARKET_URL_INVALID: {market.url}. "
                    "Use owner/repo, http(s), ssh, or .git URL"
                ),
            )
        if not _validate_market_path(normalized_market.path):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"MARKET_INDEX_INVALID: invalid path '{normalized_market.path}'"
                ),
            )
        normalized_markets.append(normalized_market)

    ttl_sec = int(payload.cache.get("ttl_sec", 600))
    overwrite_default = bool(payload.install.get("overwrite_default", False))
    return SkillsMarketConfig(
        version=max(1, int(payload.version)),
        markets=normalized_markets,
        cache=SkillsMarketCacheConfig(ttl_sec=ttl_sec),
        install=SkillsMarketInstallConfig(
            overwrite_default=overwrite_default,
        ),
    )


def _run_git_command(
    args: list[str],
    *,
    cwd: str | None = None,
    timeout_sec: int = 30,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout_sec,
        check=False,
    )


def _market_repo_web_url(url: str) -> str:
    raw = (url or "").strip()
    if raw.startswith("git@github.com:"):
        repo = raw[len("git@github.com:") :]
        if repo.endswith(".git"):
            repo = repo[: -len(".git")]
        return f"https://github.com/{repo}"
    if raw.endswith(".git"):
        return raw[: -len(".git")]
    return raw


def _generate_market_index_from_directory(
    market: SkillMarketSpec,
    skills_dir: Path,
    *,
    effective_branch: str,
) -> tuple[dict[str, Any], list[str]]:
    branch = effective_branch or market.branch or "main"
    warnings: list[str] = []
    skills: list[dict[str, Any]] = []
    for sub in sorted(skills_dir.iterdir()):
        if not sub.is_dir():
            continue
        if not (sub / "SKILL.md").exists():
            continue
        rel_path = sub.relative_to(skills_dir.parent).as_posix()
        skills.append(
            {
                "skill_id": sub.name,
                "name": sub.name,
                "description": "",
                "version": "",
                "source": {
                    "type": "git",
                    "url": market.url,
                    "branch": branch,
                    "path": rel_path,
                },
                "tags": [],
            },
        )
    if not skills:
        warnings.append("No SKILL.md folders found in market directory")
    return {"skills": skills}, warnings


def _load_market_index(market: SkillMarketSpec) -> tuple[dict[str, Any], list[str]]:
    normalized_market = _normalize_market_spec(market)
    market_url = _normalize_market_url(normalized_market.url)
    with tempfile.TemporaryDirectory(prefix="copaw-market-") as tmp:
        repo_dir = Path(tmp) / "repo"
        clone_args = ["clone", "--depth", "1"]
        if normalized_market.branch:
            clone_args += ["--branch", normalized_market.branch]
        clone_args += [market_url, str(repo_dir)]
        clone_result = _run_git_command(clone_args, timeout_sec=40)
        if clone_result.returncode != 0:
            raise RuntimeError(
                "MARKET_UNREACHABLE: "
                + (clone_result.stderr.strip() or "clone failed"),
            )

        effective_branch = (normalized_market.branch or "").strip()
        if not effective_branch:
            branch_result = _run_git_command(
                ["rev-parse", "--abbrev-ref", "HEAD"],
                cwd=str(repo_dir),
                timeout_sec=10,
            )
            if branch_result.returncode == 0:
                effective_branch = branch_result.stdout.strip()

        target_path = repo_dir / (normalized_market.path or "index.json")
        warnings: list[str] = []
        if target_path.is_file():
            return json.loads(target_path.read_text(encoding="utf-8")), warnings
        if target_path.is_dir():
            return _generate_market_index_from_directory(
                normalized_market,
                target_path,
                effective_branch=effective_branch,
            )
        raise ValueError(
            f"MARKET_INDEX_INVALID: path '{normalized_market.path}' not found",
        )


def _extract_market_items(
    market: SkillMarketSpec,
    index_doc: dict[str, Any],
) -> tuple[list[MarketplaceItem], list[MarketError]]:
    skills = index_doc.get("skills")
    if not isinstance(skills, list):
        return [], [
            MarketError(
                market_id=market.id,
                code="MARKET_INDEX_INVALID",
                message="skills field must be a list",
            ),
        ]

    items: list[MarketplaceItem] = []
    errors: list[MarketError] = []
    for raw in skills:
        if not isinstance(raw, dict):
            errors.append(
                MarketError(
                    market_id=market.id,
                    code="MARKET_INDEX_INVALID",
                    message="skill entry must be an object",
                ),
            )
            continue
        try:
            source = raw.get("source") or {}
            if not isinstance(source, dict):
                raise ValueError("source must be an object")
            source_url = str(source.get("url") or market.url).strip()
            source_branch = str(source.get("branch") or market.branch or "main").strip()
            source_path = str(source.get("path") or "").strip()
            repo_web_url = _market_repo_web_url(source_url)
            install_url = (
                f"{repo_web_url}/tree/{source_branch}/{source_path}"
                if source_path
                else repo_web_url
            )

            description = raw.get("description") or ""
            if isinstance(description, dict):
                description = (
                    description.get("zh")
                    or description.get("en")
                    or next(iter(description.values()), "")
                )

            items.append(
                MarketplaceItem(
                    market_id=market.id,
                    skill_id=str(raw.get("skill_id") or raw.get("name") or "").strip(),
                    name=str(raw.get("name") or raw.get("skill_id") or "").strip(),
                    description=str(description or ""),
                    version=str(raw.get("version") or ""),
                    source_url=source_url,
                    install_url=install_url,
                    tags=[str(tag) for tag in raw.get("tags") or []],
                ),
            )
        except Exception as exc:
            errors.append(
                MarketError(
                    market_id=market.id,
                    code="MARKET_INDEX_INVALID",
                    message=str(exc),
                ),
            )
    return items, errors


def _aggregate_marketplace(
    cfg: SkillsMarketConfig | None = None,
    *,
    refresh: bool = False,
) -> tuple[list[MarketplaceItem], list[MarketError], dict[str, Any]]:
    cfg = cfg or _load_current_market_config()
    now = time.time()
    ttl = max(0, int(cfg.cache.ttl_sec))
    with _MARKETPLACE_CACHE_LOCK:
        if not refresh and _MARKETPLACE_CACHE["expires_at"] > now:
            return (
                list(_MARKETPLACE_CACHE["items"]),
                list(_MARKETPLACE_CACHE["errors"]),
                dict(_MARKETPLACE_CACHE["meta"]),
            )

    items: list[MarketplaceItem] = []
    errors: list[MarketError] = []
    enabled_markets = [market for market in cfg.markets if market.enabled]
    success_market_count = 0
    for market in enabled_markets:
        try:
            index_doc, warnings = _load_market_index(market)
            market_items, market_errors = _extract_market_items(market, index_doc)
            items.extend(market_items)
            errors.extend(market_errors)
            for warning in warnings:
                errors.append(
                    MarketError(
                        market_id=market.id,
                        code="MARKET_WARNING",
                        message=warning,
                    ),
                )
            success_market_count += 1
        except Exception as exc:
            errors.append(
                MarketError(
                    market_id=market.id,
                    code="MARKET_UNREACHABLE",
                    message=str(exc),
                    retryable=True,
                ),
            )
    meta = {
        "refreshed_at": int(now),
        "cache_hit": False,
        "enabled_market_count": len(enabled_markets),
        "success_market_count": success_market_count,
        "item_count": len(items),
    }
    with _MARKETPLACE_CACHE_LOCK:
        _MARKETPLACE_CACHE.update(
            {
                "expires_at": now + ttl,
                "items": list(items),
                "errors": list(errors),
                "meta": dict(meta),
            },
        )
    return items, errors, meta


def _workspace_dir_for_agent(agent_id: str) -> Path:
    for workspace in list_workspaces():
        if workspace["agent_id"] == agent_id:
            return Path(workspace["workspace_dir"])
    raise HTTPException(
        status_code=404,
        detail=f"Workspace '{agent_id}' not found",
    )


def _snapshot_workspace_skill(
    workspace_dir: Path,
    skill_name: str,
) -> dict[str, Any]:
    manifest = read_skill_manifest(workspace_dir)
    entry = manifest.get("skills", {}).get(skill_name)
    skill_dir = workspace_dir / "skills" / skill_name
    backup_dir: Path | None = None
    if skill_dir.exists():
        backup_root = Path(
            tempfile.mkdtemp(prefix=f"copaw_skill_rollback_{skill_name}_"),
        )
        backup_dir = backup_root / skill_name
        shutil.copytree(skill_dir, backup_dir)
    return {
        "workspace_dir": workspace_dir,
        "skill_name": skill_name,
        "entry": copy.deepcopy(entry) if entry is not None else None,
        "backup_dir": backup_dir,
    }


def _restore_workspace_skill(snapshot: dict[str, Any]) -> None:
    workspace_dir = Path(snapshot["workspace_dir"])
    skill_name = str(snapshot["skill_name"])
    skill_dir = workspace_dir / "skills" / skill_name
    backup_dir = snapshot.get("backup_dir")
    entry = snapshot.get("entry")

    if skill_dir.exists():
        shutil.rmtree(skill_dir)
    if backup_dir is not None and Path(backup_dir).exists():
        shutil.copytree(Path(backup_dir), skill_dir)

    def _restore(payload: dict[str, Any]) -> None:
        payload.setdefault("skills", {})
        if entry is None:
            payload["skills"].pop(skill_name, None)
            return
        payload["skills"][skill_name] = copy.deepcopy(entry)

    _mutate_json(
        get_workspace_skill_manifest_path(workspace_dir),
        _default_workspace_manifest(),
        _restore,
    )
    reconcile_workspace_manifest(workspace_dir)
    if backup_dir is not None:
        shutil.rmtree(Path(backup_dir).parent, ignore_errors=True)


async def _request_workspace_dir(request: Request) -> Path:
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    return Path(workspace.workspace_dir)


async def _hub_task_set_status(
    task_id: str,
    status: HubInstallTaskStatus,
    *,
    error: str | None = None,
    result: dict[str, Any] | None = None,
) -> None:
    async with _hub_install_lock:
        task = _hub_install_tasks.get(task_id)
        if task is None:
            return
        task.status = status
        task.updated_at = time.time()
        if error is not None:
            task.error = error
        if result is not None:
            task.result = result


async def _hub_task_get(task_id: str) -> HubInstallTask | None:
    async with _hub_install_lock:
        return _hub_install_tasks.get(task_id)


async def validate_market(payload: ValidateMarketRequest) -> dict[str, Any]:
    normalized = _normalize_market_spec(payload)
    if not _validate_market_url(normalized.url):
        raise HTTPException(
            status_code=400,
            detail=(
                f"MARKET_URL_INVALID: {payload.url}. "
                "Use owner/repo, http(s), ssh, or .git URL"
            ),
        )
    if not _validate_market_path(normalized.path):
        raise HTTPException(
            status_code=400,
            detail=f"MARKET_INDEX_INVALID: invalid path '{normalized.path}'",
        )

    ls_remote = _run_git_command(["ls-remote", normalized.url], timeout_sec=20)
    if ls_remote.returncode != 0:
        raise HTTPException(
            status_code=502,
            detail="MARKET_UNREACHABLE: "
            + (ls_remote.stderr.strip() or "ls-remote failed"),
        )

    try:
        _index_doc, warnings = _load_market_index(normalized)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        "ok": True,
        "normalized": normalized.model_dump(mode="json"),
        "warnings": warnings,
    }


@router.get("/markets", response_model=SkillsMarketPayload)
async def get_markets() -> SkillsMarketPayload:
    return _market_config_to_payload(_load_current_market_config())


@router.put("/markets", response_model=SkillsMarketPayload)
async def save_markets(payload: SkillsMarketPayload) -> SkillsMarketPayload:
    cfg = _payload_to_market_config(payload)
    current = load_config()
    current.skills_market = cfg
    save_config(current)

    normalized_payload = _market_config_to_payload(cfg)
    _write_market_payload_to_path(normalized_payload, _SKILLS_MARKET_CONFIG_PATH)
    with _MARKETPLACE_CACHE_LOCK:
        _MARKETPLACE_CACHE["expires_at"] = 0.0
    return normalized_payload


@router.get("/markets/defaults", response_model=SkillsMarketPayload)
async def get_market_defaults() -> SkillsMarketPayload:
    return _load_market_payload_from_path(_SKILLS_MARKET_DEFAULT_PATH)


@router.post("/markets/reset", response_model=SkillsMarketPayload)
async def reset_markets() -> SkillsMarketPayload:
    payload = _load_market_payload_from_path(_SKILLS_MARKET_DEFAULT_PATH)
    _write_market_payload_to_path(payload, _SKILLS_MARKET_CONFIG_PATH)
    return payload


@router.post("/markets/validate")
async def validate_market_endpoint(payload: ValidateMarketRequest) -> dict[str, Any]:
    return await validate_market(payload)


@router.get("/marketplace")
async def get_marketplace(refresh: bool = False) -> dict[str, Any]:
    items, errors, meta = _aggregate_marketplace(refresh=refresh)
    return {
        "items": [item.model_dump(mode="json") for item in items],
        "market_errors": [error.model_dump(mode="json") for error in errors],
        "meta": meta,
    }


@router.post("/marketplace/install")
async def install_marketplace_skill(
    payload: InstallMarketplaceRequest,
    request: Request,
) -> dict[str, Any]:
    cfg = _load_current_market_config()
    items, _errors, _meta = _aggregate_marketplace(cfg, refresh=True)
    selected = next(
        (
            item
            for item in items
            if item.market_id == payload.market_id and item.skill_id == payload.skill_id
        ),
        None,
    )
    if selected is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"MARKET_ITEM_NOT_FOUND: market={payload.market_id} skill={payload.skill_id}"
            ),
        )

    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)

    overwrite = payload.overwrite or bool(cfg.install.overwrite_default)
    try:
        result = install_skill_from_hub(
            workspace_dir=workspace_dir,
            bundle_url=selected.install_url,
            enable=payload.enable,
            overwrite=overwrite,
        )
    except SkillScanError as exc:
        return _scan_error_response(exc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SkillConflictError as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    reconcile_workspace_manifest(workspace_dir)
    if payload.enable and result.enabled:
        schedule_agent_reload(request, workspace.agent_id)

    return {
        "installed": True,
        "workspace_dir": str(workspace.workspace_dir),
        "market_id": payload.market_id,
        "skill_id": payload.skill_id,
        "name": result.name,
        "enabled": result.enabled,
        "source_url": result.source_url,
    }


async def _hub_task_register_runtime(task_id: str, task: asyncio.Task) -> None:
    async with _hub_install_lock:
        _hub_install_runtime_tasks[task_id] = task


async def _hub_task_pop_runtime(task_id: str) -> asyncio.Task | None:
    async with _hub_install_lock:
        return _hub_install_runtime_tasks.pop(task_id, None)


async def _read_validated_zip_upload(file: UploadFile) -> bytes:
    if file.content_type and file.content_type not in _ALLOWED_ZIP_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                "Expected a zip file, "
                f"got content-type: {file.content_type}"
            ),
        )

    data = await file.read()
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"File too large ({len(data) // (1024 * 1024)} MB). "
                f"Maximum is {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
            ),
        )
    return data


def _cleanup_imported_skill(workspace_dir: Path, skill_name: str) -> None:
    if not skill_name:
        return
    try:
        skill_service = SkillService(workspace_dir)
        skill_service.disable_skill(skill_name)
        skill_service.delete_skill(skill_name)
    except Exception as exc:  # pragma: no cover
        logger.warning(
            "Cleanup after cancelled import failed for '%s': %s",
            skill_name,
            exc,
        )


async def _run_hub_install_task(
    *,
    task_id: str,
    workspace_dir: Path,
    body: HubInstallRequest,
    cancel_event: threading.Event,
) -> None:
    await _hub_task_set_status(task_id, HubInstallTaskStatus.IMPORTING)
    imported_skill_name: str | None = None
    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: install_skill_from_hub(
                workspace_dir=workspace_dir,
                bundle_url=body.bundle_url,
                version=body.version,
                enable=body.enable,
                target_name=body.target_name,
                overwrite=body.overwrite,
                cancel_checker=cancel_event.is_set,
            ),
        )
        imported_skill_name = result.name
        if cancel_event.is_set():
            _cleanup_imported_skill(workspace_dir, result.name)
            await _hub_task_set_status(
                task_id,
                HubInstallTaskStatus.CANCELLED,
                result={
                    "installed": False,
                    "name": result.name,
                    "enabled": False,
                    "source_url": result.source_url,
                },
            )
            return
        await _hub_task_set_status(
            task_id,
            HubInstallTaskStatus.COMPLETED,
            result={
                "installed": True,
                "name": result.name,
                "enabled": result.enabled,
                "source_url": result.source_url,
            },
        )
    except SkillImportCancelled:
        if imported_skill_name:
            _cleanup_imported_skill(workspace_dir, imported_skill_name)
        await _hub_task_set_status(task_id, HubInstallTaskStatus.CANCELLED)
    except SkillScanError as exc:
        await _hub_task_set_status(
            task_id,
            HubInstallTaskStatus.FAILED,
            error=str(exc),
            result=_scan_error_payload(exc),
        )
    except ValueError as exc:
        await _hub_task_set_status(
            task_id,
            HubInstallTaskStatus.FAILED,
            error=str(exc),
        )
    except SkillConflictError as exc:
        await _hub_task_set_status(
            task_id,
            HubInstallTaskStatus.FAILED,
            error=str(exc),
            result=exc.detail,
        )
    except RuntimeError as exc:
        await _hub_task_set_status(
            task_id,
            HubInstallTaskStatus.FAILED,
            error=str(exc),
        )
    except Exception as exc:  # pragma: no cover
        await _hub_task_set_status(
            task_id,
            HubInstallTaskStatus.FAILED,
            error=f"Skill hub import failed: {exc}",
        )
    finally:
        await _hub_task_pop_runtime(task_id)


def _build_workspace_skill_specs(workspace_dir: Path) -> list[SkillSpec]:
    manifest = read_skill_manifest(workspace_dir)
    service = SkillService(workspace_dir)
    entries = manifest.get("skills", {})
    specs: list[SkillSpec] = []
    for skill in service.list_all_skills():
        entry = entries.get(skill.name, {})
        specs.append(
            SkillSpec(
                **skill.model_dump(),
                enabled=entry.get("enabled", False),
                channels=entry.get("channels") or ["all"],
                sync_to_pool=entry.get("sync_to_pool") or {},
                config=entry.get("config") or {},
            ),
        )
    return specs


def _build_pool_skill_specs() -> list[PoolSkillSpec]:
    manifest = read_skill_pool_manifest()
    service = SkillPoolService()
    entries = manifest.get("skills", {})
    sync_info = get_pool_builtin_sync_status()
    specs: list[PoolSkillSpec] = []
    for skill in service.list_all_skills():
        entry = entries.get(skill.name, {})
        info = sync_info.get(skill.name, {})
        specs.append(
            PoolSkillSpec(
                **skill.model_dump(exclude={"version_text"}),
                protected=bool(entry.get("protected", False)),
                version_text=str(entry.get("version_text", "") or ""),
                commit_text=str(entry.get("commit_text", "") or ""),
                sync_status=str(info.get("sync_status", "") or ""),
                latest_version_text=str(
                    info.get("latest_version_text", "") or "",
                ),
                config=entry.get("config") or {},
            ),
        )
    return specs


@router.get("")
async def list_skills(request: Request) -> list[SkillSpec]:
    workspace_dir = await _request_workspace_dir(request)
    return _build_workspace_skill_specs(workspace_dir)


@router.get("/hub/search")
async def search_hub(
    q: str = "",
    limit: int = 20,
) -> list[HubSkillSpec]:
    results = search_hub_skills(q, limit=limit)
    return [
        HubSkillSpec(
            slug=item.slug,
            name=item.name,
            description=item.description,
            version=item.version,
            source_url=item.source_url,
        )
        for item in results
    ]


@router.get("/workspaces")
async def list_workspace_skill_sources() -> list[WorkspaceSkillSummary]:
    summaries: list[WorkspaceSkillSummary] = []
    workspaces = list_workspaces()
    for workspace in workspaces:
        workspace_dir = Path(workspace["workspace_dir"])
        summaries.append(
            WorkspaceSkillSummary(
                agent_id=workspace["agent_id"],
                agent_name=workspace.get("agent_name", ""),
                workspace_dir=str(workspace_dir),
                skills=_build_workspace_skill_specs(workspace_dir),
            ),
        )
    return summaries


@router.post("/hub/install/start", response_model=HubInstallTask)
async def start_install_from_hub(
    request_body: HubInstallRequest,
    request: Request,
) -> HubInstallTask:
    workspace_dir = await _request_workspace_dir(request)
    task = HubInstallTask(
        bundle_url=request_body.bundle_url,
        version=request_body.version,
        enable=request_body.enable,
        overwrite=request_body.overwrite,
    )
    cancel_event = threading.Event()
    async with _hub_install_lock:
        _hub_install_tasks[task.task_id] = task
        _hub_install_cancel_events[task.task_id] = cancel_event

    runtime_task = asyncio.create_task(
        _run_hub_install_task(
            task_id=task.task_id,
            workspace_dir=workspace_dir,
            body=request_body,
            cancel_event=cancel_event,
        ),
        name=f"skill-hub-install-{task.task_id}",
    )
    await _hub_task_register_runtime(task.task_id, runtime_task)
    return task


@router.get("/hub/install/status/{task_id}", response_model=HubInstallTask)
async def get_hub_install_status(task_id: str) -> HubInstallTask:
    task = await _hub_task_get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="install task not found")
    return task


@router.post("/hub/install/cancel/{task_id}")
async def cancel_hub_install(task_id: str) -> dict[str, Any]:
    async with _hub_install_lock:
        task = _hub_install_tasks.get(task_id)
        if task is None:
            raise HTTPException(
                status_code=404,
                detail="install task not found",
            )
        if task.status in (
            HubInstallTaskStatus.COMPLETED,
            HubInstallTaskStatus.FAILED,
            HubInstallTaskStatus.CANCELLED,
        ):
            return {"task_id": task_id, "status": task.status.value}
        cancel_event = _hub_install_cancel_events.get(task_id)
        if cancel_event is not None:
            cancel_event.set()
        task.status = HubInstallTaskStatus.CANCELLED
        task.updated_at = time.time()
    return {"task_id": task_id, "status": "cancelled"}


@router.get("/pool")
async def list_pool_skills() -> list[PoolSkillSpec]:
    return _build_pool_skill_specs()


@router.get("/pool/builtin-sources")
async def list_pool_builtin_sources() -> list[BuiltinImportSpec]:
    return [
        BuiltinImportSpec(**item) for item in list_builtin_import_candidates()
    ]


@router.post("")
async def create_skill(
    request: Request,
    body: CreateSkillRequest,
) -> dict[str, Any]:
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    try:
        created = SkillService(workspace_dir).create_skill(
            name=body.name,
            content=body.content,
            overwrite=body.overwrite,
            references=body.references,
            scripts=body.scripts,
            config=body.config,
            enable=body.enable,
        )
    except SkillScanError as exc:
        return _scan_error_response(exc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not created:
        raise HTTPException(
            status_code=409,
            detail={
                "reason": "conflict",
                "suggested_name": suggest_conflict_name(body.name),
            },
        )
    reconcile_workspace_manifest(workspace_dir)
    if body.enable:
        schedule_agent_reload(request, workspace.agent_id)
    return {"created": True, "name": created}


@router.post("/upload")
async def upload_skill_zip(
    request: Request,
    file: UploadFile = File(...),
    enable: bool = True,
    overwrite: bool = False,
    target_name: str = "",
    rename_map: str = "",
) -> dict[str, Any]:
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    data = await _read_validated_zip_upload(file)
    parsed_rename: dict[str, str] | None = None
    if rename_map.strip():
        try:
            parsed_rename = json.loads(rename_map)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail="rename_map must be valid JSON",
            ) from exc
        if not isinstance(parsed_rename, dict):
            raise HTTPException(
                status_code=400,
                detail="rename_map must be a JSON object",
            )
    try:
        result = await asyncio.to_thread(
            SkillService(workspace_dir).import_from_zip,
            data=data,
            overwrite=overwrite,
            enable=enable,
            target_name=target_name,
            rename_map=parsed_rename,
        )
    except SkillScanError as exc:
        return _scan_error_response(exc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result.get("conflicts"):
        raise HTTPException(status_code=409, detail=result)
    if enable and result.get("count", 0) > 0:
        schedule_agent_reload(request, workspace.agent_id)
    return result


@router.post("/pool/create")
async def create_pool_skill(body: CreateSkillRequest) -> dict[str, Any]:
    try:
        created = SkillPoolService().create_skill(
            name=body.name,
            content=body.content,
            references=body.references,
            scripts=body.scripts,
            config=body.config,
        )
    except SkillScanError as exc:
        return _scan_error_response(exc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not created:
        raise HTTPException(
            status_code=409,
            detail={
                "reason": "conflict",
                "suggested_name": suggest_conflict_name(body.name),
            },
        )
    return {"created": True, "name": created}


@router.put("/pool/save")
async def save_pool_skill(body: SavePoolSkillRequest) -> dict[str, Any]:
    """Edit or save-as a pool skill depending on the target name.

    Example:
    - editing a normal shared skill in place -> ``mode="edit"``
    - saving any skill under a new name -> ``mode="rename"``
    - editing a builtin in place -> conflict with suggestion
    - customizing a builtin -> save under a new name
    """
    service = SkillPoolService()
    try:
        result = service.save_pool_skill(
            skill_name=body.source_name or body.name,
            target_name=body.name,
            content=body.content,
            references=body.references,
            scripts=body.scripts,
            config=body.config,
        )
    except SkillScanError as exc:
        return _scan_error_response(exc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result.get("success"):
        reason = result.get("reason")
        status = 404 if reason == "not_found" else 409
        raise HTTPException(status_code=status, detail=result)
    return result


@router.post("/pool/upload-zip")
async def upload_skill_pool_zip(
    file: UploadFile = File(...),
    overwrite: bool = False,
    target_name: str = "",
    rename_map: str = "",
) -> dict[str, Any]:
    data = await _read_validated_zip_upload(file)
    parsed_rename: dict[str, str] | None = None
    if rename_map.strip():
        try:
            parsed_rename = json.loads(rename_map)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail="rename_map must be valid JSON",
            ) from exc
        if not isinstance(parsed_rename, dict):
            raise HTTPException(
                status_code=400,
                detail="rename_map must be a JSON object",
            )
    try:
        result = await asyncio.to_thread(
            SkillPoolService().import_from_zip,
            data=data,
            overwrite=overwrite,
            target_name=target_name,
            rename_map=parsed_rename,
        )
    except SkillScanError as exc:
        return _scan_error_response(exc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result.get("conflicts"):
        raise HTTPException(status_code=409, detail=result)
    return result


@router.post("/pool/import")
async def import_skill_pool_from_hub(
    body: HubInstallRequest,
) -> dict[str, Any]:
    try:
        result = import_pool_skill_from_hub(
            bundle_url=body.bundle_url,
            version=body.version,
            target_name=body.target_name,
        )
    except SkillScanError as exc:
        return _scan_error_response(exc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SkillConflictError as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "installed": True,
        "name": result.name,
        "enabled": False,
        "source_url": result.source_url,
    }


@router.post("/pool/upload")
async def upload_workspace_skill_to_pool(
    body: UploadToPoolRequest,
) -> dict[str, Any]:
    workspace_dir = _workspace_dir_for_agent(body.workspace_id)
    try:
        result = SkillPoolService().upload_from_workspace(
            workspace_dir=workspace_dir,
            skill_name=body.skill_name,
            target_name=body.new_name,
            overwrite=body.overwrite,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result.get("success"):
        status = 404 if result.get("reason") == "not_found" else 409
        raise HTTPException(status_code=status, detail=result)
    return result


def _preflight_download_conflicts(
    hub_service: SkillPoolService,
    targets: list[PoolDownloadTarget],
    skill_name: str,
    overwrite: bool,
) -> list[dict[str, Any]]:
    """Check all targets for conflicts before downloading."""
    conflicts: list[dict[str, Any]] = []
    for target in targets:
        workspace_dir = _workspace_dir_for_agent(target.workspace_id)
        result = hub_service.preflight_download_to_workspace(
            skill_name=skill_name,
            workspace_dir=workspace_dir,
            target_name=target.target_name,
            overwrite=overwrite,
        )
        if not result.get("success"):
            conflicts.append(result)
    return conflicts


def _resolve_and_preflight(
    body: DownloadFromPoolRequest,
) -> tuple[list[PoolDownloadTarget], SkillPoolService]:
    """Resolve targets and reject if any conflicts exist."""
    targets = list(body.targets)
    if body.all_workspaces:
        targets = [
            PoolDownloadTarget(workspace_id=workspace["agent_id"])
            for workspace in list_workspaces()
        ]
    if not targets:
        raise HTTPException(
            status_code=400,
            detail="No workspace targets provided",
        )
    hub_service = SkillPoolService()
    try:
        conflicts = _preflight_download_conflicts(
            hub_service,
            targets,
            body.skill_name,
            body.overwrite,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc
    if conflicts:
        raise HTTPException(
            status_code=409,
            detail={
                "downloaded": [],
                "conflicts": conflicts,
            },
        )
    return targets, hub_service


def _build_download_plan(
    targets: list[PoolDownloadTarget],
    skill_name: str,
) -> list[dict[str, Any]]:
    """Build execution plan with rollback snapshots."""
    plan: list[dict[str, Any]] = []
    for target in targets:
        workspace_dir = _workspace_dir_for_agent(target.workspace_id)
        snapshot = _snapshot_workspace_skill(
            workspace_dir,
            str(target.target_name or skill_name),
        )
        plan.append(
            {
                "workspace_id": target.workspace_id,
                "workspace_dir": workspace_dir,
                "target_name": target.target_name,
                "snapshot": snapshot,
            },
        )
    return plan


@router.post("/pool/download")
async def download_pool_skill_to_workspaces(
    body: DownloadFromPoolRequest,
) -> dict[str, Any]:
    """Download one pool skill into one or more workspaces.

    All-or-nothing: if any target conflicts, reject everything.
    """
    targets, hub_service = _resolve_and_preflight(body)

    execution_plan = _build_download_plan(targets, body.skill_name)

    downloaded: list[dict[str, str]] = []
    try:
        for plan in execution_plan:
            result = hub_service.download_to_workspace(
                skill_name=body.skill_name,
                workspace_dir=plan["workspace_dir"],
                target_name=plan["target_name"],
                overwrite=body.overwrite,
            )
            if not result.get("success"):
                for rollback in reversed(execution_plan):
                    _restore_workspace_skill(rollback["snapshot"])
                raise HTTPException(
                    status_code=409,
                    detail={
                        "downloaded": [],
                        "conflicts": [result],
                    },
                )
            downloaded.append(
                {
                    "workspace_id": str(plan["workspace_id"]),
                    "workspace_name": str(
                        result.get("workspace_name", "") or "",
                    ),
                    "name": str(result.get("name", "")),
                },
            )
    except HTTPException:
        raise
    except Exception:
        for rollback in reversed(execution_plan):
            _restore_workspace_skill(rollback["snapshot"])
        raise
    finally:
        for plan in execution_plan:
            backup_dir = plan["snapshot"].get("backup_dir")
            if backup_dir is not None:
                shutil.rmtree(Path(backup_dir).parent, ignore_errors=True)

    return {"downloaded": downloaded}


@router.post("/pool/import-builtin")
async def import_pool_builtins(
    body: ImportBuiltinRequest,
) -> dict[str, Any]:
    result = import_builtin_skills(
        body.skill_names,
        overwrite_conflicts=body.overwrite_conflicts,
    )
    if result.get("conflicts") and not body.overwrite_conflicts:
        raise HTTPException(status_code=409, detail=result)
    return result


@router.post("/pool/{skill_name}/update-builtin")
async def update_pool_builtin(skill_name: str) -> dict[str, Any]:
    try:
        return update_single_builtin(skill_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/pool/{skill_name}")
async def delete_pool_skill(skill_name: str) -> dict[str, Any]:
    deleted = SkillPoolService().delete_skill(skill_name)
    if not deleted:
        raise HTTPException(
            status_code=409,
            detail="Skill pool entry cannot be deleted",
        )
    return {"deleted": True}


@router.get("/pool/{skill_name}/config")
async def get_pool_skill_config(skill_name: str) -> dict[str, Any]:
    manifest = read_skill_pool_manifest()
    entry = manifest.get("skills", {}).get(skill_name)
    if entry is None:
        raise HTTPException(status_code=404, detail="Pool skill not found")
    return {"config": entry.get("config", {})}


@router.put("/pool/{skill_name}/config")
async def update_pool_skill_config(
    skill_name: str,
    body: SkillConfigRequest,
) -> dict[str, Any]:
    manifest_path = get_pool_skill_manifest_path()

    def _update(payload: dict[str, Any]) -> bool:
        entry = payload.get("skills", {}).get(skill_name)
        if entry is None:
            return False
        entry["config"] = dict(body.config)
        return True

    updated = _mutate_json(manifest_path, _default_pool_manifest(), _update)
    if not updated:
        raise HTTPException(status_code=404, detail="Pool skill not found")
    return {"updated": True}


@router.delete("/pool/{skill_name}/config")
async def delete_pool_skill_config(skill_name: str) -> dict[str, Any]:
    manifest_path = get_pool_skill_manifest_path()

    def _update(payload: dict[str, Any]) -> bool:
        entry = payload.get("skills", {}).get(skill_name)
        if entry is None:
            return False
        entry.pop("config", None)
        return True

    updated = _mutate_json(manifest_path, _default_pool_manifest(), _update)
    if not updated:
        raise HTTPException(status_code=404, detail="Pool skill not found")
    return {"cleared": True}


@router.post("/batch-disable")
async def batch_disable_skills(
    request: Request,
    skills: list[str],
) -> dict[str, Any]:
    workspace_dir = await _request_workspace_dir(request)
    service = SkillService(workspace_dir)
    results = {skill: service.disable_skill(skill) for skill in skills}
    return {"results": results}


@router.post("/batch-enable")
async def batch_enable_skills(
    request: Request,
    skills: list[str],
) -> dict[str, Any]:
    """Enable each requested skill independently and collect per-skill results.

    Example:
        enabling ``["ok_skill", "blocked_skill"]`` returns success for the
        first item and ``reason="security_scan_failed"`` for the second,
        rather than aborting the entire batch.
    """
    workspace_dir = await _request_workspace_dir(request)
    service = SkillService(workspace_dir)
    results: dict[str, Any] = {}
    for skill in skills:
        try:
            results[skill] = service.enable_skill(skill)
        except SkillScanError as exc:
            results[skill] = {
                "success": False,
                "reason": "security_scan_failed",
                "detail": _scan_error_payload(exc),
            }
    return {"results": results}


@router.post("/{skill_name}/disable")
async def disable_skill(
    request: Request,
    skill_name: str,
) -> dict[str, Any]:
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    result = SkillService(workspace_dir).disable_skill(skill_name)
    if not result.get("success"):
        raise HTTPException(status_code=404, detail="Skill not found")
    schedule_agent_reload(request, workspace.agent_id)
    return {"disabled": True, **result}


@router.post("/{skill_name}/enable")
async def enable_skill(
    request: Request,
    skill_name: str,
) -> dict[str, Any]:
    """Enable one workspace skill after a fresh scan."""
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    try:
        result = SkillService(workspace_dir).enable_skill(skill_name)
    except SkillScanError as exc:
        return _scan_error_response(exc)
    if not result.get("success"):
        raise HTTPException(
            status_code=404,
            detail=result.get("reason", "Skill not found"),
        )
    schedule_agent_reload(request, workspace.agent_id)
    return {"enabled": True, **result}


@router.delete("/{skill_name}")
async def delete_skill(
    request: Request,
    skill_name: str,
) -> dict[str, Any]:
    workspace_dir = await _request_workspace_dir(request)
    deleted = SkillService(workspace_dir).delete_skill(skill_name)
    if not deleted:
        raise HTTPException(
            status_code=409,
            detail="Only disabled workspace skills can be deleted",
        )
    return {"deleted": True}


@router.get("/{skill_name}/files/{source}/{file_path:path}")
async def load_skill_file(
    request: Request,
    skill_name: str,
    source: str,
    file_path: str,
) -> dict[str, Any]:
    workspace_dir = await _request_workspace_dir(request)
    content = SkillService(workspace_dir).load_skill_file(
        skill_name=skill_name,
        file_path=file_path,
        source=source,
    )
    if content is None:
        raise HTTPException(status_code=404, detail="File not found")
    return {"content": content}


@router.put("/save")
async def save_workspace_skill(
    request: Request,
    body: SaveSkillRequest,
) -> dict[str, Any]:
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    try:
        result = SkillService(workspace_dir).save_skill(
            skill_name=body.source_name or body.name,
            content=body.content,
            target_name=body.name if body.source_name else None,
            config=body.config,
            references=body.references,
            scripts=body.scripts,
        )
    except SkillScanError as exc:
        return _scan_error_response(exc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result.get("success"):
        if result.get("reason") == "conflict":
            raise HTTPException(status_code=409, detail=result)
        raise HTTPException(status_code=404, detail="Skill not found")
    if result.get("mode") != "noop":
        reconcile_workspace_manifest(workspace_dir)
        schedule_agent_reload(request, workspace.agent_id)
    return result


@router.put("/{skill_name}/channels")
async def update_skill_channels_endpoint(
    request: Request,
    skill_name: str,
    channels: list[str],
) -> dict[str, Any]:
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    updated = SkillService(workspace_dir).set_skill_channels(
        skill_name,
        channels,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Skill not found")
    schedule_agent_reload(request, workspace.agent_id)
    return {"updated": True, "channels": channels}


@router.get("/{skill_name}/config")
async def get_skill_config_endpoint(
    request: Request,
    skill_name: str,
) -> dict[str, Any]:
    workspace_dir = await _request_workspace_dir(request)
    manifest = read_skill_manifest(workspace_dir)
    entry = manifest.get("skills", {}).get(skill_name)
    if entry is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"config": entry.get("config", {})}


@router.put("/{skill_name}/config")
async def update_skill_config_endpoint(
    request: Request,
    skill_name: str,
    body: SkillConfigRequest,
) -> dict[str, Any]:
    workspace_dir = await _request_workspace_dir(request)
    manifest_path = get_workspace_skill_manifest_path(workspace_dir)

    def _update(payload: dict[str, Any]) -> bool:
        entry = payload.get("skills", {}).get(skill_name)
        if entry is None:
            return False
        entry["config"] = dict(body.config)
        return True

    updated = _mutate_json(
        manifest_path,
        _default_workspace_manifest(),
        _update,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"updated": True}


@router.delete("/{skill_name}/config")
async def delete_skill_config_endpoint(
    request: Request,
    skill_name: str,
) -> dict[str, Any]:
    workspace_dir = await _request_workspace_dir(request)
    manifest_path = get_workspace_skill_manifest_path(workspace_dir)

    def _update(payload: dict[str, Any]) -> bool:
        entry = payload.get("skills", {}).get(skill_name)
        if entry is None:
            return False
        entry.pop("config", None)
        return True

    updated = _mutate_json(
        manifest_path,
        _default_workspace_manifest(),
        _update,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"cleared": True}
