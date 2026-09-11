# -*- coding: utf-8 -*-
"""Explicit text proposal/accept workflow; never dispatches media."""

import asyncio

from fastapi import APIRouter, Depends
from pydantic import Field

from services.project_files.models import StrictModel
from services.prompt_sync_service import PromptSyncService, PromptSyncSource
from .dependencies import CreatorErrorRoute, project_file_services

router = APIRouter(
    prefix=(
        "/projects/{project_id}/timelines/{timeline_id}"
        "/elements/{element_id}"
    ),
    tags=["prompt-sync"],
    route_class=CreatorErrorRoute,
)


class PromptProposalRequest(StrictModel):
    guidance: str = Field(default="", max_length=6000)
    source: PromptSyncSource = "currentPlan"


@router.get("/prompt-sync")
async def prompt_status(
    project_id: str,
    timeline_id: str,
    element_id: str,
    services=Depends(project_file_services),
):
    return await asyncio.to_thread(
        PromptSyncService(services).status,
        project_id,
        timeline_id,
        element_id,
    )


@router.post("/prompt-proposals")
async def propose_prompts(
    project_id: str,
    timeline_id: str,
    element_id: str,
    request: PromptProposalRequest,
    services=Depends(project_file_services),
):
    return await PromptSyncService(services).propose(
        project_id,
        timeline_id,
        element_id,
        request.guidance,
        source=request.source,
    )


@router.post("/prompt-proposals/{proposal_id}/accept")
async def accept_prompts(
    project_id: str,
    timeline_id: str,
    element_id: str,
    proposal_id: str,
    services=Depends(project_file_services),
):
    return await PromptSyncService(services).accept(
        project_id,
        timeline_id,
        element_id,
        proposal_id,
    )
