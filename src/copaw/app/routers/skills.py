# -*- coding: utf-8 -*-
import asyncio
import json
import logging
import re
import subprocess
import tempfile
import threading
import time
import uuid
from enum import Enum
from typing import Any
from urllib.parse import unquote, urlparse
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from ...agents.skills_manager import (
    SkillService,
    SkillInfo,
)
from ...agents.skills_hub import (
    SkillImportCancelled,
    search_hub_skills,
    install_skill_from_hub,
)
from ...config import load_config, save_config
from ...config.config import (
    SkillMarketSpec,
    SkillsMarketCacheConfig,
    SkillsMarketConfig,
    SkillsMarketInstallConfig,
)
from ...security.skill_scanner import SkillScanError


logger = logging.getLogger(__name__)


def _scan_error_response(exc: SkillScanError) -> JSONResponse:
    """Build a 422 response with structured scan findings."""
    result = exc.result
    return JSONResponse(
        status_code=422,
        content={
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
        },
    )


class SkillSpec(SkillInfo):
    enabled: bool = False


class CreateSkillRequest(BaseModel):
    name: str = Field(..., description="Skill name")
    content: str = Field(..., description="Skill content (SKILL.md)")
    references: dict[str, Any] | None = Field(
        None,
        description="Optional tree structure for references/. "
        "Can be flat {filename: content} or nested "
        "{dirname: {filename: content}}",
    )
    scripts: dict[str, Any] | None = Field(
        None,
        description="Optional tree structure for scripts/. "
        "Can be flat {filename: content} or nested "
        "{dirname: {filename: content}}",
    )


class HubSkillSpec(BaseModel):
    slug: str
    name: str
    description: str = ""
    version: str = ""
    source_url: str = ""


class HubInstallRequest(BaseModel):
    bundle_url: str = Field(..., description="Skill URL")
    version: str = Field(default="", description="Optional version tag")
    enable: bool = Field(default=True, description="Enable after import")
    overwrite: bool = Field(
        default=False,
        description="Overwrite existing customized skill",
    )


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

_OWNER_REPO_PATTERN = re.compile(r"^[\w.-]+/[\w.-]+$")
_MARKETPLACE_CACHE_LOCK = threading.Lock()
_MARKETPLACE_CACHE: dict[str, Any] = {
    "expires_at": 0.0,
    "items": [],
    "errors": [],
    "meta": {},
}


router = APIRouter(prefix="/skills", tags=["skills"])


def _extract_github_market_spec(
    url: str,
) -> tuple[str, str, str] | None:
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
    p = Path(raw)
    if p.is_absolute():
        return False
    return ".." not in p.parts


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
    repo_web_url = _market_repo_web_url(market.url)
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


def _load_market_index(
    market: SkillMarketSpec,
) -> tuple[dict[str, Any], list[str]]:
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
                + (clone_result.stderr.strip() or "clone failed")
            )

        # Resolve branch from local clone when user did not specify one.
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
        if target_path.suffix.lower() == ".json":
            parent_dir = target_path.parent
            if parent_dir.is_dir():
                return _generate_market_index_from_directory(
                    normalized_market,
                    parent_dir,
                    effective_branch=effective_branch,
                )
        raise ValueError(
            "MARKET_INDEX_INVALID: index or skills directory not found at "
            f"{normalized_market.path}"
        )


def _extract_market_items(
    market: SkillMarketSpec,
    index_doc: dict[str, Any],
) -> tuple[list[MarketplaceItem], list[MarketError]]:
    errors: list[MarketError] = []
    raw_skills = index_doc.get("skills", [])
    if not isinstance(raw_skills, list):
        return [], [
            MarketError(
                market_id=market.id,
                code="MARKET_INDEX_INVALID",
                message="'skills' must be a list",
                retryable=False,
            ),
        ]

    items: list[MarketplaceItem] = []
    for raw in raw_skills:
        if not isinstance(raw, dict):
            errors.append(
                MarketError(
                    market_id=market.id,
                    code="MARKET_INDEX_INVALID",
                    message="Each skill entry must be an object",
                    retryable=False,
                ),
            )
            continue

        skill_id = str(raw.get("skill_id") or "").strip()
        name = str(raw.get("name") or "").strip() or skill_id
        source_raw = raw.get("source")
        source: dict[str, Any] = source_raw if isinstance(source_raw, dict) else {}
        source_url = str(source.get("url") or market.url).strip()
        source_branch = str(source.get("branch") or market.branch or "main").strip()
        source_path = str(source.get("path") or "").strip()
        if not skill_id or not source_url:
            errors.append(
                MarketError(
                    market_id=market.id,
                    code="MARKET_ITEM_INVALID",
                    message="skill_id/source.url is required",
                    retryable=False,
                ),
            )
            continue

        repo_web_url = _market_repo_web_url(source_url)
        install_url = (
            f"{repo_web_url}/tree/{source_branch}/{source_path}"
            if source_path
            else repo_web_url
        )

        description = raw.get("description", "")
        if isinstance(description, dict):
            description = (
                description.get("zh")
                or description.get("en")
                or next(iter(description.values()), "")
            )

        tags_raw = raw.get("tags")
        tags: list[Any] = tags_raw if isinstance(tags_raw, list) else []
        items.append(
            MarketplaceItem(
                market_id=market.id,
                skill_id=skill_id,
                name=name,
                description=str(description or ""),
                version=str(raw.get("version") or ""),
                source_url=source_url,
                install_url=install_url,
                tags=[str(tag) for tag in tags],
            ),
        )
    return items, errors


def _aggregate_marketplace(
    market_cfg: SkillsMarketConfig,
    *,
    refresh: bool = False,
) -> tuple[list[MarketplaceItem], list[MarketError], dict[str, Any]]:
    now = time.time()
    with _MARKETPLACE_CACHE_LOCK:
        if (
            not refresh
            and _MARKETPLACE_CACHE["expires_at"] > now
            and _MARKETPLACE_CACHE["items"]
        ):
            return (
                _MARKETPLACE_CACHE["items"],
                _MARKETPLACE_CACHE["errors"],
                _MARKETPLACE_CACHE["meta"],
            )

    items: list[MarketplaceItem] = []
    errors: list[MarketError] = []
    success_count = 0
    enabled_markets = sorted(
        [m for m in market_cfg.markets if m.enabled],
        key=lambda m: m.order,
    )
    for market in enabled_markets:
        normalized_market = _normalize_market_spec(market)
        try:
            index_doc, warnings = _load_market_index(normalized_market)
            extracted_items, extracted_errors = _extract_market_items(
                normalized_market,
                index_doc,
            )
            items.extend(extracted_items)
            errors.extend(extracted_errors)
            for warning in warnings:
                errors.append(
                    MarketError(
                        market_id=market.id,
                        code="MARKET_INDEX_WARNING",
                        message=warning,
                        retryable=False,
                    ),
                )
            success_count += 1
        except ValueError as e:
            errors.append(
                MarketError(
                    market_id=market.id,
                    code="MARKET_INDEX_INVALID",
                    message=str(e),
                    retryable=False,
                ),
            )
        except RuntimeError as e:
            errors.append(
                MarketError(
                    market_id=market.id,
                    code="MARKET_UNREACHABLE",
                    message=str(e),
                    retryable=True,
                ),
            )
        except (subprocess.SubprocessError, OSError) as e:
            errors.append(
                MarketError(
                    market_id=market.id,
                    code="MARKET_UNREACHABLE",
                    message=str(e),
                    retryable=True,
                ),
            )

    meta = {
        "enabled_market_count": len(enabled_markets),
        "success_market_count": success_count,
        "item_count": len(items),
    }
    with _MARKETPLACE_CACHE_LOCK:
        _MARKETPLACE_CACHE["items"] = items
        _MARKETPLACE_CACHE["errors"] = errors
        _MARKETPLACE_CACHE["meta"] = meta
        _MARKETPLACE_CACHE["expires_at"] = now + market_cfg.cache.ttl_sec
    return items, errors, meta


@router.get("")
async def list_skills(
    request: Request,
) -> list[SkillSpec]:
    """List all skills for active agent."""
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    skill_service = SkillService(workspace_dir)

    # Get all skills (builtin + customized)
    all_skills = skill_service.list_all_skills()

    # Get active skills to determine enabled status
    active_skills_dir = workspace_dir / "active_skills"
    active_skill_names = set()
    if active_skills_dir.exists():
        active_skill_names = {
            d.name
            for d in active_skills_dir.iterdir()
            if d.is_dir() and (d / "SKILL.md").exists()
        }

    # Convert to SkillSpec with enabled status
    skills_spec = [
        SkillSpec(
            name=skill.name,
            description=skill.description,
            content=skill.content,
            source=skill.source,
            path=skill.path,
            references=skill.references,
            scripts=skill.scripts,
            enabled=skill.name in active_skill_names,
        )
        for skill in all_skills
    ]

    return skills_spec


@router.get("/available")
async def get_available_skills(
    request: Request,
) -> list[SkillSpec]:
    """List available (enabled) skills for active agent."""
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    skill_service = SkillService(workspace_dir)

    # Get available (active) skills
    available_skills = skill_service.list_available_skills()

    # Convert to SkillSpec
    skills_spec = [
        SkillSpec(
            name=skill.name,
            description=skill.description,
            content=skill.content,
            source=skill.source,
            path=skill.path,
            references=skill.references,
            scripts=skill.scripts,
            enabled=True,
        )
        for skill in available_skills
    ]

    return skills_spec


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


@router.get("/markets", response_model=SkillsMarketPayload)
async def get_markets() -> SkillsMarketPayload:
    config = load_config()
    return _market_config_to_payload(config.skills_market)


@router.put("/markets", response_model=SkillsMarketPayload)
async def put_markets(payload: SkillsMarketPayload) -> SkillsMarketPayload:
    config = load_config()
    market_cfg = _payload_to_market_config(payload)
    config.skills_market = market_cfg
    save_config(config)
    with _MARKETPLACE_CACHE_LOCK:
        _MARKETPLACE_CACHE["expires_at"] = 0.0
    return _market_config_to_payload(market_cfg)


@router.post("/markets/validate")
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

    ls_remote = _run_git_command(
        ["ls-remote", "--heads", normalized.url],
        timeout_sec=20,
    )
    if ls_remote.returncode != 0:
        raise HTTPException(
            status_code=502,
            detail=(
                "MARKET_UNREACHABLE: "
                + (ls_remote.stderr.strip() or "ls-remote failed")
            ),
        )
    try:
        _, warnings = _load_market_index(normalized)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=400,
            detail=f"MARKET_INDEX_INVALID: {e}",
        ) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    except (subprocess.SubprocessError, OSError) as e:
        raise HTTPException(
            status_code=502,
            detail=f"MARKET_UNREACHABLE: {e}",
        ) from e

    return {
        "ok": True,
        "normalized": normalized.model_dump(mode="json"),
        "warnings": warnings,
    }


@router.get("/marketplace")
async def get_marketplace(refresh: bool = False) -> dict[str, Any]:
    config = load_config()
    items, errors, meta = _aggregate_marketplace(
        config.skills_market,
        refresh=refresh,
    )
    return {
        "items": [item.model_dump(mode="json") for item in items],
        "market_errors": [err.model_dump(mode="json") for err in errors],
        "meta": meta,
    }


def _github_token_hint(bundle_url: str) -> str:
    """Hint to set GITHUB_TOKEN when URL is from GitHub/skills.sh."""
    if not bundle_url:
        return ""
    lower = bundle_url.lower()
    if "skills.sh" in lower or "github.com" in lower:
        return " Tip: set GITHUB_TOKEN (or GH_TOKEN) to avoid rate limits."
    return ""


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


async def _hub_task_register_runtime(task_id: str, task: asyncio.Task) -> None:
    async with _hub_install_lock:
        _hub_install_runtime_tasks[task_id] = task


async def _hub_task_pop_runtime(task_id: str) -> asyncio.Task | None:
    async with _hub_install_lock:
        return _hub_install_runtime_tasks.pop(task_id, None)


def _cleanup_imported_skill(workspace_dir: Path, skill_name: str) -> None:
    """Best-effort cleanup for cancelled skill imports."""
    if not skill_name:
        return
    try:
        skill_service = SkillService(workspace_dir)
        skill_service.disable_skill(skill_name)
        skill_service.delete_skill(skill_name)
    except Exception as e:  # pylint: disable=broad-except
        logger.warning(
            "Cleanup after cancelled import failed for '%s': %s",
            skill_name,
            e,
        )


async def _run_hub_install_task(
    *,
    task_id: str,
    workspace_dir: Path,
    body: HubInstallRequest,
    cancel_event: threading.Event,
) -> None:
    await _hub_task_set_status(task_id, HubInstallTaskStatus.IMPORTING)
    result_payload: dict[str, Any] | None = None
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
                overwrite=body.overwrite,
                cancel_checker=cancel_event.is_set,
            ),
        )
        result_payload = {
            "installed": True,
            "name": result.name,
            "enabled": result.enabled,
            "source_url": result.source_url,
        }
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
            result=result_payload,
        )
    except SkillImportCancelled:
        if imported_skill_name:
            _cleanup_imported_skill(workspace_dir, imported_skill_name)
        await _hub_task_set_status(task_id, HubInstallTaskStatus.CANCELLED)
    except SkillScanError as e:
        await _hub_task_set_status(
            task_id,
            HubInstallTaskStatus.FAILED,
            error=str(e),
        )
    except ValueError as e:
        await _hub_task_set_status(
            task_id,
            HubInstallTaskStatus.FAILED,
            error=str(e),
        )
    except RuntimeError as e:
        await _hub_task_set_status(
            task_id,
            HubInstallTaskStatus.FAILED,
            error=str(e) + _github_token_hint(body.bundle_url),
        )
    except Exception as e:  # pylint: disable=broad-except
        await _hub_task_set_status(
            task_id,
            HubInstallTaskStatus.FAILED,
            error=f"Skill hub import failed: {e}"
            + _github_token_hint(body.bundle_url),
        )
    finally:
        await _hub_task_pop_runtime(task_id)


@router.post("/hub/install")
async def install_from_hub(
    request_body: HubInstallRequest,
    request: Request,
):
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)

    try:
        result = install_skill_from_hub(
            workspace_dir=workspace_dir,
            bundle_url=request_body.bundle_url,
            version=request_body.version,
            enable=request_body.enable,
            overwrite=request_body.overwrite,
        )
    except SkillScanError as e:
        return _scan_error_response(e)
    except ValueError as e:
        detail = str(e)
        logger.warning(
            "Skill hub install 400: bundle_url=%s detail=%s",
            (request_body.bundle_url or "")[:80],
            detail,
        )
        raise HTTPException(status_code=400, detail=detail) from e
    except RuntimeError as e:
        detail = str(e) + _github_token_hint(request_body.bundle_url)
        logger.exception(
            "Skill hub install failed (upstream/rate limit): %s",
            e,
        )
        raise HTTPException(status_code=502, detail=detail) from e
    except Exception as e:
        detail = f"Skill hub import failed: {e}" + _github_token_hint(
            request_body.bundle_url,
        )
        logger.exception("Skill hub import failed: %s", e)
        raise HTTPException(status_code=502, detail=detail) from e
    return {
        "installed": True,
        "name": result.name,
        "enabled": result.enabled,
        "source_url": result.source_url,
    }


@router.post("/marketplace/install")
async def install_from_marketplace(
    request_body: InstallMarketplaceRequest,
    request: Request,
):
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    config = load_config()
    overwrite = request_body.overwrite or bool(
        config.skills_market.install.overwrite_default,
    )
    items, _, _ = _aggregate_marketplace(config.skills_market, refresh=False)
    selected = None
    for item in items:
        if (
            item.market_id == request_body.market_id
            and item.skill_id == request_body.skill_id
        ):
            selected = item
            break

    if selected is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"MARKET_ITEM_NOT_FOUND: "
                f"{request_body.market_id}/{request_body.skill_id}"
            ),
        )

    try:
        result = install_skill_from_hub(
            workspace_dir=workspace_dir,
            bundle_url=selected.install_url,
            version="",
            enable=request_body.enable,
            overwrite=overwrite,
        )
    except SkillScanError as e:
        return _scan_error_response(e)
    except ValueError as e:
        detail = str(e)
        if "already exists" in detail.lower() and not overwrite:
            raise HTTPException(
                status_code=409,
                detail=f"SKILL_NAME_CONFLICT: {detail}",
            ) from e
        raise HTTPException(status_code=400, detail=detail) from e
    except RuntimeError as e:
        detail = str(e) + _github_token_hint(selected.install_url)
        raise HTTPException(status_code=502, detail=detail) from e
    except Exception as e:  # pylint: disable=broad-except
        detail = f"Skill market install failed: {e}"
        raise HTTPException(status_code=502, detail=detail) from e

    return {
        "installed": True,
        "name": result.name,
        "enabled": result.enabled,
        "source_url": result.source_url,
    }


@router.post("/hub/install/start", response_model=HubInstallTask)
async def start_install_from_hub(
    request_body: HubInstallRequest,
    request: Request,
) -> HubInstallTask:
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
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


@router.post("/batch-disable")
async def batch_disable_skills(
    skill_name: list[str],
    request: Request,
) -> None:
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    skill_service = SkillService(workspace_dir)

    for skill in skill_name:
        skill_service.disable_skill(skill)


@router.post("/batch-enable")
async def batch_enable_skills(
    skill_name: list[str],
    request: Request,
):
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    skill_service = SkillService(workspace_dir)

    blocked: list[dict] = []
    for skill in skill_name:
        try:
            skill_service.enable_skill(skill)
        except SkillScanError as e:
            blocked.append(
                {
                    "skill_name": skill,
                    "max_severity": e.result.max_severity.value,
                    "detail": str(e),
                },
            )
    if blocked:
        return JSONResponse(
            status_code=422,
            content={
                "type": "security_scan_failed",
                "detail": (
                    f"{len(blocked)} skill(s) blocked by security scan"
                ),
                "blocked_skills": blocked,
            },
        )


@router.post("")
async def create_skill(
    request_body: CreateSkillRequest,
    request: Request,
):
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    skill_service = SkillService(workspace_dir)

    try:
        result = skill_service.create_skill(
            name=request_body.name,
            content=request_body.content,
            references=request_body.references,
            scripts=request_body.scripts,
        )
    except SkillScanError as e:
        return _scan_error_response(e)
    return {"created": result}


@router.post("/{skill_name}/disable")
async def disable_skill(
    skill_name: str,
    request: Request,
):
    """Disable skill for active agent."""
    from ..agent_context import get_agent_for_request
    import shutil

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    active_skill_dir = workspace_dir / "active_skills" / skill_name

    if active_skill_dir.exists():
        shutil.rmtree(active_skill_dir)

        # Hot reload config (async, non-blocking)
        # IMPORTANT: Get manager and agent_id before creating background task
        # to avoid accessing request/workspace after their lifecycle ends
        manager = request.app.state.multi_agent_manager
        agent_id = workspace.agent_id

        async def reload_in_background():
            try:
                await manager.reload_agent(agent_id)
            except Exception as e:
                logger.warning(f"Background reload failed: {e}")

        asyncio.create_task(reload_in_background())

        return {"disabled": True}

    return {"disabled": False}


@router.post("/{skill_name}/enable")
async def enable_skill(
    skill_name: str,
    request: Request,
):
    """Enable skill for active agent."""
    from ..agent_context import get_agent_for_request
    import shutil

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    active_skill_dir = workspace_dir / "active_skills" / skill_name

    # If already enabled, skip
    if active_skill_dir.exists():
        return {"enabled": True}

    # Find skill from builtin or customized
    builtin_skill_dir = (
        Path(__file__).parent.parent.parent / "agents" / "skills" / skill_name
    )
    customized_skill_dir = workspace_dir / "customized_skills" / skill_name

    source_dir = None
    if customized_skill_dir.exists():
        source_dir = customized_skill_dir
    elif builtin_skill_dir.exists():
        source_dir = builtin_skill_dir

    if not source_dir or not (source_dir / "SKILL.md").exists():
        raise HTTPException(
            status_code=404,
            detail=f"Skill '{skill_name}' not found",
        )

    # --- Security scan (pre-activation) --------------------------------
    try:
        from ...security.skill_scanner import scan_skill_directory

        scan_skill_directory(source_dir, skill_name=skill_name)
    except SkillScanError as e:
        return _scan_error_response(e)
    except Exception as scan_exc:
        logger.warning(
            "Security scan error for skill '%s' (non-fatal): %s",
            skill_name,
            scan_exc,
        )
    # -------------------------------------------------------------------

    # Copy to active_skills
    shutil.copytree(source_dir, active_skill_dir)

    # Hot reload config (async, non-blocking)
    # IMPORTANT: Get manager and agent_id before creating background task
    # to avoid accessing request/workspace after their lifecycle ends
    manager = request.app.state.multi_agent_manager
    agent_id = workspace.agent_id

    async def reload_in_background():
        try:
            await manager.reload_agent(agent_id)
        except Exception as e:
            logger.warning(f"Background reload failed: {e}")

    asyncio.create_task(reload_in_background())

    return {"enabled": True}


@router.delete("/{skill_name}")
async def delete_skill(
    skill_name: str,
    request: Request,
):
    """Delete a skill from customized_skills directory permanently.

    This only deletes skills from customized_skills directory.
    Built-in skills cannot be deleted.
    """
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    skill_service = SkillService(workspace_dir)

    result = skill_service.delete_skill(skill_name)
    return {"deleted": result}


@router.get("/{skill_name}/files/{source}/{file_path:path}")
async def load_skill_file(
    skill_name: str,
    source: str,
    file_path: str,
    request: Request,
):
    """Load a specific file from a skill's references or scripts directory.

    Args:
        skill_name: Name of the skill
        source: Source directory ("builtin" or "customized")
        file_path: Path relative to skill directory, must start with
                   "references/" or "scripts/"

    Returns:
        File content as string, or None if not found

        Example:

            GET /skills/my_skill/files/customized/references/doc.md

            GET /skills/builtin_skill/files/builtin/scripts/utils/helper.py

    """
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    skill_service = SkillService(workspace_dir)

    content = skill_service.load_skill_file(
        skill_name=skill_name,
        file_path=file_path,
        source=source,
    )
    return {"content": content}
