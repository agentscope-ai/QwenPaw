# -*- coding: utf-8 -*-
"""API endpoints for local model management."""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...local_models.model_manager import LocalModelInfo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/local-models", tags=["local-models"])


@router.get(
    "/list",
    response_model=List[LocalModelInfo],
    summary="List local models",
)
async def list_local() -> List[LocalModelInfo]:
    """List all recommended local models."""
    # TODO


@router.get(
    "",
    response_model=bool,
    summary="Check if local server is available",
)
async def available() -> bool:
    """Check if the local model server is properly installed and ready."""
    # TODO


# TODO
