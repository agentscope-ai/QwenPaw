# -*- coding: utf-8 -*-
import logging
from typing import Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from ...config import load_config, save_config
from ...config.config import SkillEntryConfig
from ...agents.skills_manager import (
    SkillService,
    SkillInfo,
    list_available_skills,
)
from ...agents.skills_hub import (
    search_hub_skills,
    install_skill_from_hub,
)


logger = logging.getLogger(__name__)


class SkillSpec(SkillInfo):
    enabled: bool = False


class SkillConfigView(BaseModel):
    key: str
    enabled: bool | None = None
    has_api_key: bool = False
    env: dict[str, str] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)
    env_keys: list[str] = Field(default_factory=list)
    config_keys: list[str] = Field(default_factory=list)


class SkillConfigUpdateRequest(BaseModel):
    enabled: bool | None = None
    api_key: str | None = Field(default=None, alias="apiKey")
    clear_api_key: bool | None = Field(default=None, alias="clearApiKey")
    env: dict[str, str] | None = None
    config: dict[str, Any] | None = None


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


router = APIRouter(prefix="/skills", tags=["skills"])


def _build_skill_spec(skill: SkillInfo, enabled_skills: set[str]) -> SkillSpec:
    return SkillSpec(
        name=skill.name,
        content=skill.content,
        source=skill.source,
        path=skill.path,
        references=skill.references,
        scripts=skill.scripts,
        metadata=skill.metadata,
        resolved_skill_key=skill.resolved_skill_key,
        eligibility=skill.eligibility,
        config_status=skill.config_status,
        enabled=skill.name in enabled_skills,
    )


def _build_skill_config_view(
    skill_key: str,
    entry: SkillEntryConfig | None,
) -> SkillConfigView:
    entry = entry or SkillEntryConfig()
    return SkillConfigView(
        key=skill_key,
        enabled=entry.enabled,
        has_api_key=bool(entry.api_key),
        env=dict(entry.env or {}),
        config=dict(entry.config or {}),
        env_keys=sorted((entry.env or {}).keys()),
        config_keys=sorted((entry.config or {}).keys()),
    )


def _allowed_skill_env_keys(skill: SkillInfo) -> set[str]:
    allowed: set[str] = set()
    metadata = skill.metadata
    if not metadata:
        return allowed

    if metadata.primary_env:
        allowed.add(metadata.primary_env)
    if metadata.requires:
        allowed.update(item for item in metadata.requires.env if item)
    return allowed


def _validate_skill_env_payload(
    skill: SkillInfo,
    env_payload: dict[str, str] | None,
) -> None:
    env_payload = env_payload or {}
    invalid_keys = sorted(set(env_payload) - _allowed_skill_env_keys(skill))
    if not invalid_keys:
        return
    raise HTTPException(
        status_code=400,
        detail=(
            f"Skill '{skill.name}' does not declare env key(s): "
            f"{', '.join(invalid_keys)}"
        ),
    )


@router.get("")
async def list_skills() -> list[SkillSpec]:
    all_skills = SkillService.list_all_skills()

    available_skills = set(list_available_skills())
    return [_build_skill_spec(skill, available_skills) for skill in all_skills]


@router.get("/available")
async def get_available_skills() -> list[SkillSpec]:
    available_skills = SkillService.list_available_skills()
    return [
        _build_skill_spec(skill, {skill.name}) for skill in available_skills
    ]


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


def _github_token_hint(bundle_url: str) -> str:
    """Hint to set GITHUB_TOKEN when URL is from GitHub/skills.sh."""
    if not bundle_url:
        return ""
    lower = bundle_url.lower()
    if "skills.sh" in lower or "github.com" in lower:
        return " Tip: set GITHUB_TOKEN (or GH_TOKEN) to avoid rate limits."
    return ""


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


@router.get("/{skill_name}/config")
async def get_skill_config(skill_name: str) -> SkillConfigView:
    skill = SkillService.get_skill(skill_name)
    if skill is None:
        raise HTTPException(
            status_code=404,
            detail=f"Skill '{skill_name}' not found",
        )
    config = load_config()
    skill_key = skill.resolved_skill_key or skill.name
    entry = config.skills.entries.get(skill_key)
    return _build_skill_config_view(skill_key, entry)


@router.put("/{skill_name}/config")
async def put_skill_config(
    skill_name: str,
    request: SkillConfigUpdateRequest,
) -> SkillConfigView:
    skill = SkillService.get_skill(skill_name)
    if skill is None:
        raise HTTPException(
            status_code=404,
            detail=f"Skill '{skill_name}' not found",
        )

    config = load_config()
    skill_key = skill.resolved_skill_key or skill.name
    existing = config.skills.entries.get(skill_key, SkillEntryConfig())
    update_data = request.model_dump(exclude_unset=True, by_alias=False)

    if "env" in update_data:
        _validate_skill_env_payload(skill, update_data["env"])

    if "enabled" in update_data:
        existing.enabled = update_data["enabled"]
    if update_data.get("clear_api_key"):
        existing.api_key = ""
    elif update_data.get("api_key"):
        existing.api_key = update_data["api_key"] or ""
    if "env" in update_data:
        existing.env = update_data["env"] or {}
    if "config" in update_data:
        existing.config = update_data["config"] or {}

    if (
        existing.enabled is None
        and not existing.api_key
        and not existing.env
        and not existing.config
    ):
        config.skills.entries.pop(skill_key, None)
    else:
        config.skills.entries[skill_key] = existing
    save_config(config)

    refreshed = SkillService.get_skill(skill_name)
    refreshed_key = refreshed.resolved_skill_key if refreshed else skill_key
    return _build_skill_config_view(
        refreshed_key or skill_key,
        config.skills.entries.get(refreshed_key or skill_key),
    )


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
