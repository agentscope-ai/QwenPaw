# -*- coding: utf-8 -*-
import re
from typing import Any
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


router = APIRouter(prefix="/skills", tags=["skills"])


@router.get("")
async def list_skills() -> list[SkillSpec]:
    all_skills = SkillService.list_all_skills()

    available_skills = list_available_skills()
    skills_spec = []
    for skill in all_skills:
        skills_spec.append(
            SkillSpec(
                name=skill.name,
                content=skill.content,
                source=skill.source,
                path=skill.path,
                references=skill.references,
                scripts=skill.scripts,
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
                name=skill.name,
                content=skill.content,
                source=skill.source,
                path=skill.path,
                references=skill.references,
                scripts=skill.scripts,
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
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        # Upstream hub is flaky/rate-limited sometimes; surface as bad gateway.
        raise HTTPException(status_code=502, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Skill hub import failed: {e}",
        ) from e
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


_SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def _validate_skill_name(name: str) -> None:
    """Reject skill names that could escape the skills directory."""
    if not name or not _SAFE_NAME_RE.match(name):
        raise HTTPException(
            status_code=400,
            detail="Skill name must contain only alphanumeric characters, "
            "hyphens, and underscores.",
        )


def _validate_tree_keys(tree: dict | None, field_name: str) -> None:
    """Validate that keys in references/scripts trees have no path traversal."""
    if not tree:
        return
    for key, value in tree.items():
        if ".." in key or key.startswith("/"):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid path in '{field_name}': '{key}'. "
                f"Path traversal sequences are not allowed.",
            )
        if isinstance(value, dict):
            _validate_tree_keys(value, field_name)


@router.post("")
async def create_skill(request: CreateSkillRequest):
    # Validate inputs to prevent path traversal
    _validate_skill_name(request.name)
    _validate_tree_keys(request.references, "references")
    _validate_tree_keys(request.scripts, "scripts")

    result = SkillService.create_skill(
        name=request.name,
        content=request.content,
        references=request.references,
        scripts=request.scripts,
    )
    if not result:
        raise HTTPException(
            status_code=400,
            detail=(
                "Failed to create skill. Possible reasons include: invalid "
                "SKILL.md front matter (e.g. missing 'name' or 'description'), "
                "a duplicate skill name, or a server error."
            ),
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
