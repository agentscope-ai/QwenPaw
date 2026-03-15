# -*- coding: utf-8 -*-
import json
import logging
import re
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import frontmatter
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from ...agents.skills_manager import (
    SkillService,
    SkillInfo,
    list_available_skills,
)
from ...agents.skills_hub import (
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


logger = logging.getLogger(__name__)


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


_OWNER_REPO_PATTERN = re.compile(r"^[\w.-]+/[\w.-]+$")
_MARKETPLACE_CACHE_LOCK = threading.Lock()
_MARKETPLACE_CACHE: dict[str, Any] = {
    "expires_at": 0.0,
    "items": [],
    "errors": [],
    "meta": {},
}


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


def _normalize_market_url(url: str) -> str:
    raw = (url or "").strip()
    if _OWNER_REPO_PATTERN.fullmatch(raw):
        return f"https://github.com/{raw}.git"
    return raw


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
        check=False,
        timeout=timeout_sec,
    )


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

    ttl = int(payload.cache.get("ttl_sec", 600))
    overwrite_default = bool(payload.install.get("overwrite_default", False))
    return SkillsMarketConfig(
        version=max(1, int(payload.version or 1)),
        markets=normalized_markets,
        cache=SkillsMarketCacheConfig(
            ttl_sec=max(0, min(ttl, 24 * 3600)),
        ),
        install=SkillsMarketInstallConfig(
            overwrite_default=overwrite_default,
        ),
    )


def _coerce_tags(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _generate_market_index_from_directory(
    market: SkillMarketSpec,
    repo_dir: Path,
    skills_dir: Path,
    effective_branch: str,
) -> dict[str, Any]:
    repo_web_url = _market_repo_web_url(market.url)
    branch = effective_branch or market.branch or "main"
    skill_dirs: list[Path] = []

    if (skills_dir / "SKILL.md").exists():
        skill_dirs.append(skills_dir)
    else:
        for skill_md in sorted(skills_dir.rglob("SKILL.md")):
            skill_dirs.append(skill_md.parent)

    skills: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for skill_dir in skill_dirs:
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue
        relative_dir = skill_dir.relative_to(repo_dir).as_posix()
        skill_id = skill_dir.name.strip()
        if not skill_id or skill_id in seen_ids:
            continue
        seen_ids.add(skill_id)

        content = skill_md.read_text(encoding="utf-8")
        try:
            post = frontmatter.loads(content)
        except Exception:
            post = None

        description_value = ""
        version_value = ""
        tags_value: list[str] = []
        display_name = skill_id
        if post is not None:
            display_name = str(post.get("name") or skill_id)
            description_value = _coerce_description(post.get("description"))
            version_value = str(post.get("version") or "")
            tags_value = _coerce_tags(post.get("tags"))

        skills.append(
            {
                "skill_id": skill_id,
                "name": display_name,
                "description": description_value,
                "version": version_value,
                "tags": tags_value,
                "source": {
                    "type": "git",
                    "url": market.url,
                    "branch": branch,
                    "path": relative_dir,
                },
                "homepage": f"{repo_web_url}/tree/{branch}/{relative_dir}",
            },
        )

    return {"skills": skills}


def _load_market_index(
    market: SkillMarketSpec,
) -> tuple[dict[str, Any], list[str]]:
    market_url = _normalize_market_url(market.url)
    with tempfile.TemporaryDirectory(prefix="copaw-market-") as tmp:
        repo_dir = Path(tmp) / "repo"
        clone_args = ["clone", "--depth", "1"]
        if market.branch:
            clone_args += ["--branch", market.branch]
        clone_args += [market_url, str(repo_dir)]
        clone_result = _run_git_command(clone_args, timeout_sec=45)
        if clone_result.returncode != 0:
            raise RuntimeError(
                "MARKET_UNREACHABLE: "
                + (clone_result.stderr.strip() or "clone failed")
            )

        effective_branch = (market.branch or "").strip()
        if not effective_branch:
            head_result = _run_git_command(
                ["branch", "--show-current"],
                cwd=str(repo_dir),
                timeout_sec=10,
            )
            if head_result.returncode == 0:
                effective_branch = head_result.stdout.strip()

        target_path = repo_dir / (market.path or "index.json")
        if target_path.exists() and target_path.is_file():
            with open(target_path, "r", encoding="utf-8") as f:
                return json.load(f), []

        if target_path.exists() and target_path.is_dir():
            return (
                _generate_market_index_from_directory(
                    market,
                    repo_dir,
                    target_path,
                    effective_branch,
                ),
                [
                    "MARKET_INDEX_GENERATED_FROM_DIRECTORY: "
                    f"{target_path.relative_to(repo_dir).as_posix()}"
                ],
            )

        if target_path.name == "index.json" and target_path.parent.is_dir():
            return (
                _generate_market_index_from_directory(
                    market,
                    repo_dir,
                    target_path.parent,
                    effective_branch,
                ),
                [
                    "MARKET_INDEX_GENERATED_FROM_DIRECTORY: "
                    f"{target_path.parent.relative_to(repo_dir).as_posix()}"
                ],
            )

        raise ValueError(
            f"MARKET_INDEX_INVALID: index or skills directory not found at {market.path}"
        )


def _coerce_description(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return str(value.get("zh") or value.get("en") or "")
    return ""


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
                message="skills must be a list",
                retryable=False,
            ),
        ]

    items: list[MarketplaceItem] = []
    errors: list[MarketError] = []
    seen_ids: set[str] = set()
    for raw in skills:
        if not isinstance(raw, dict):
            errors.append(
                MarketError(
                    market_id=market.id,
                    code="MARKET_INDEX_INVALID",
                    message="invalid skill entry type",
                    retryable=False,
                ),
            )
            continue

        skill_id = str(raw.get("skill_id") or "").strip()
        if not skill_id:
            errors.append(
                MarketError(
                    market_id=market.id,
                    code="MARKET_INDEX_INVALID",
                    message="missing skill_id",
                    retryable=False,
                ),
            )
            continue
        if skill_id in seen_ids:
            errors.append(
                MarketError(
                    market_id=market.id,
                    code="MARKET_INDEX_INVALID",
                    message=f"duplicated skill_id: {skill_id}",
                    retryable=False,
                ),
            )
            continue
        seen_ids.add(skill_id)

        source = raw.get("source")
        if not isinstance(source, dict):
            errors.append(
                MarketError(
                    market_id=market.id,
                    code="MARKET_INDEX_INVALID",
                    message=f"invalid source for {skill_id}",
                    retryable=False,
                ),
            )
            continue

        source_type = str(source.get("type") or "").strip().lower()
        source_url = str(source.get("url") or "").strip()
        if source_type != "git" or not source_url:
            errors.append(
                MarketError(
                    market_id=market.id,
                    code="MARKET_INDEX_INVALID",
                    message=f"unsupported source for {skill_id}",
                    retryable=False,
                ),
            )
            continue

        source_branch = str(source.get("branch") or "").strip()
        source_path = str(source.get("path") or "").strip()
        install_url = source_url
        if source_path:
            branch = source_branch or "main"
            source_url = source_url.replace(".git", "")
            if "github.com/" in source_url:
                install_url = (
                    f"{source_url}/tree/{branch}/{source_path.lstrip('/')}"
                )

        tags = raw.get("tags")
        items.append(
            MarketplaceItem(
                market_id=market.id,
                skill_id=skill_id,
                name=str(raw.get("name") or skill_id),
                description=_coerce_description(raw.get("description")),
                version=str(raw.get("version") or ""),
                source_url=source_url,
                install_url=install_url,
                tags=tags if isinstance(tags, list) else [],
            ),
        )

    return items, errors


def _aggregate_marketplace(
    market_cfg: SkillsMarketConfig,
    *,
    refresh: bool,
) -> tuple[list[MarketplaceItem], list[MarketError], dict[str, Any]]:
    now = time.time()
    with _MARKETPLACE_CACHE_LOCK:
        cache_expired = now >= float(_MARKETPLACE_CACHE.get("expires_at", 0.0))
        if not refresh and not cache_expired:
            return (
                list(_MARKETPLACE_CACHE.get("items", [])),
                list(_MARKETPLACE_CACHE.get("errors", [])),
                dict(_MARKETPLACE_CACHE.get("meta", {})),
            )

    enabled_markets = sorted(
        [m for m in market_cfg.markets if m.enabled],
        key=lambda x: (x.order, x.id),
    )
    all_items: list[MarketplaceItem] = []
    all_errors: list[MarketError] = []
    success_count = 0
    for market in enabled_markets:
        try:
            index_doc, _ = _load_market_index(market)
            items, errors = _extract_market_items(market, index_doc)
            all_items.extend(items)
            all_errors.extend(errors)
            success_count += 1
        except ValueError as e:
            all_errors.append(
                MarketError(
                    market_id=market.id,
                    code="MARKET_INDEX_INVALID",
                    message=str(e),
                    retryable=False,
                ),
            )
        except RuntimeError as e:
            all_errors.append(
                MarketError(
                    market_id=market.id,
                    code="MARKET_UNREACHABLE",
                    message=str(e),
                    retryable=True,
                ),
            )
        except (subprocess.SubprocessError, OSError, json.JSONDecodeError) as e:
            all_errors.append(
                MarketError(
                    market_id=market.id,
                    code="MARKET_INDEX_INVALID",
                    message=str(e),
                    retryable=True,
                ),
            )

    meta = {
        "refreshed_at": int(now),
        "cache_hit": False,
        "enabled_market_count": len(enabled_markets),
        "success_market_count": success_count,
    }
    with _MARKETPLACE_CACHE_LOCK:
        _MARKETPLACE_CACHE["expires_at"] = now + market_cfg.cache.ttl_sec
        _MARKETPLACE_CACHE["items"] = list(all_items)
        _MARKETPLACE_CACHE["errors"] = list(all_errors)
        _MARKETPLACE_CACHE["meta"] = dict(meta)

    return all_items, all_errors, meta


router = APIRouter(prefix="/skills", tags=["skills"])


@router.get("")
async def list_skills() -> list[SkillSpec]:
    all_skills = SkillService.list_all_skills()

    available_skills = list_available_skills()
    skills_spec = []
    for skill in all_skills:
        skills_spec.append(
            SkillSpec(
                **skill.model_dump(),
                enabled=skill.name in available_skills,
            ),
        )
    return skills_spec


@router.get("/available")
async def get_available_skills() -> list[SkillSpec]:
    available_skills = SkillService.list_available_skills()
    skills_spec = []
    for skill in available_skills:
        skills_spec.append(
            SkillSpec(
                **skill.model_dump(),
                enabled=True,
            ),
        )
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
async def validate_market(payload: ValidateMarketRequest):
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
async def get_marketplace(refresh: bool = False):
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


@router.post("/marketplace/install")
async def install_from_marketplace(request: InstallMarketplaceRequest):
    config = load_config()
    overwrite = request.overwrite or bool(
        config.skills_market.install.overwrite_default,
    )
    items, _, _ = _aggregate_marketplace(config.skills_market, refresh=False)
    selected = None
    for item in items:
        if (
            item.market_id == request.market_id
            and item.skill_id == request.skill_id
        ):
            selected = item
            break

    if selected is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"MARKET_ITEM_NOT_FOUND: "
                f"{request.market_id}/{request.skill_id}"
            ),
        )

    try:
        result = install_skill_from_hub(
            bundle_url=selected.install_url,
            version="",
            enable=request.enable,
            overwrite=overwrite,
        )
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
    except Exception as e:
        detail = f"Skill market install failed: {e}"
        raise HTTPException(status_code=502, detail=detail) from e

    return {
        "installed": True,
        "name": result.name,
        "enabled": result.enabled,
        "source_url": result.source_url,
    }


@router.post("/hub/install")
async def install_from_hub(request: HubInstallRequest):
    try:
        result = install_skill_from_hub(
            bundle_url=request.bundle_url,
            version=request.version,
            enable=request.enable,
            overwrite=request.overwrite,
        )
    except ValueError as e:
        detail = str(e)
        logger.warning(
            "Skill hub install 400: bundle_url=%s detail=%s",
            (request.bundle_url or "")[:80],
            detail,
        )
        raise HTTPException(status_code=400, detail=detail) from e
    except RuntimeError as e:
        # Upstream hub is flaky/rate-limited sometimes; surface as bad gateway.
        detail = str(e) + _github_token_hint(request.bundle_url)
        logger.exception(
            "Skill hub install failed (upstream/rate limit): %s",
            e,
        )
        raise HTTPException(status_code=502, detail=detail) from e
    except Exception as e:
        detail = f"Skill hub import failed: {e}" + _github_token_hint(
            request.bundle_url,
        )
        logger.exception("Skill hub import failed: %s", e)
        raise HTTPException(status_code=502, detail=detail) from e
    return {
        "installed": True,
        "name": result.name,
        "enabled": result.enabled,
        "source_url": result.source_url,
    }


@router.post("/batch-disable")
async def batch_disable_skills(skill_name: list[str]) -> None:
    for skill in skill_name:
        SkillService.disable_skill(skill)


@router.post("/batch-enable")
async def batch_enable_skills(skill_name: list[str]) -> None:
    for skill in skill_name:
        SkillService.enable_skill(skill)


@router.post("")
async def create_skill(request: CreateSkillRequest):
    result = SkillService.create_skill(
        name=request.name,
        content=request.content,
        references=request.references,
        scripts=request.scripts,
    )
    return {"created": result}


@router.post("/{skill_name}/disable")
async def disable_skill(skill_name: str):
    result = SkillService.disable_skill(skill_name)
    return {"disabled": result}


@router.post("/{skill_name}/enable")
async def enable_skill(skill_name: str):
    result = SkillService.enable_skill(skill_name)
    return {"enabled": result}


@router.delete("/{skill_name}")
async def delete_skill(skill_name: str):
    """Delete a skill from customized_skills directory permanently.

    This only deletes skills from customized_skills directory.
    Built-in skills cannot be deleted.
    """
    result = SkillService.delete_skill(skill_name)
    return {"deleted": result}


@router.get("/{skill_name}/files/{source}/{file_path:path}")
async def load_skill_file(
    skill_name: str,
    source: str,
    file_path: str,
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
    content = SkillService.load_skill_file(
        skill_name=skill_name,
        file_path=file_path,
        source=source,
    )
    return {"content": content}
