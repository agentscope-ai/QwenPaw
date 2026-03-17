# -*- coding: utf-8 -*-
import logging
from typing import Any
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from ...agents.skills_manager import (
    SkillService,
    SkillInfo,
)
from ...agents.skills_hub import (
    search_hub_skills,
    install_skill_from_hub,
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


router = APIRouter(prefix="/skills", tags=["skills"])


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


def _github_token_hint(bundle_url: str) -> str:
    """Hint to set GITHUB_TOKEN when URL is from GitHub/skills.sh."""
    if not bundle_url:
        return ""
    lower = bundle_url.lower()
    if "skills.sh" in lower or "github.com" in lower:
        return " Tip: set GITHUB_TOKEN (or GH_TOKEN) to avoid rate limits."
    return ""


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
    request: Request = None,
):
    """Disable skill for active agent."""
    from ..agent_context import get_agent_for_request
    import shutil
    import asyncio

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    active_skill_dir = workspace_dir / "active_skills" / skill_name

    if active_skill_dir.exists():
        shutil.rmtree(active_skill_dir)

        # Hot reload config (async, non-blocking)
        async def reload_in_background():
            try:
                manager = request.app.state.multi_agent_manager
                await manager.reload_agent(workspace.agent_id)
            except Exception as e:
                logger.warning(f"Background reload failed: {e}")

        asyncio.create_task(reload_in_background())

        return {"disabled": True}

    return {"disabled": False}


@router.post("/{skill_name}/enable")
async def enable_skill(
    skill_name: str,
    request: Request = None,
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
    import asyncio

    async def reload_in_background():
        try:
            manager = request.app.state.multi_agent_manager
            await manager.reload_agent(workspace.agent_id)
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
