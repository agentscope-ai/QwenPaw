# -*- coding: utf-8 -*-
"""Health check and system status endpoints."""
from __future__ import annotations

import os
import platform
import sys
from datetime import datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from ..auth import has_registered_users, is_auth_enabled
from ...__version__ import __version__

router = APIRouter(prefix="/health", tags=["health"])


class HealthResponse(BaseModel):
    """Health check response model."""

    status: str
    timestamp: str
    version: str
    python_version: str
    platform: str


class DetailedHealthResponse(BaseModel):
    """Detailed health check response with system information."""

    status: str
    timestamp: str
    version: str
    system: dict[str, Any]
    auth: dict[str, Any]
    environment: dict[str, Any]


@router.get("/", response_model=HealthResponse)
async def health_check():
    """Basic health check endpoint.

    Returns a simple status indicating the service is running.
    This endpoint is public and does not require authentication.
    """
    return HealthResponse(
        status="healthy",
        timestamp=datetime.utcnow().isoformat(),
        version=__version__,
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        platform=platform.system(),
    )


@router.get("/detailed", response_model=DetailedHealthResponse)
async def detailed_health_check():
    """Detailed health check with system information.

    Returns comprehensive system status including:
    - Authentication configuration
    - Environment settings
    - System resources

    This endpoint is public but may expose sensitive configuration
    in development environments. Consider restricting in production.
    """
    return DetailedHealthResponse(
        status="healthy",
        timestamp=datetime.utcnow().isoformat(),
        version=__version__,
        system={
            "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "platform": platform.system(),
            "platform_release": platform.release(),
            "architecture": platform.machine(),
            "processor": platform.processor() or "unknown",
        },
        auth={
            "enabled": is_auth_enabled(),
            "has_users": has_registered_users(),
            "status": "configured" if is_auth_enabled() and has_registered_users() else "not_configured",
        },
        environment={
            "working_dir": os.environ.get("COPAW_WORKING_DIR", "default"),
            "secret_dir": os.environ.get("COPAW_SECRET_DIR", "default"),
            "log_level": os.environ.get("COPAW_LOG_LEVEL", "info"),
            "debug": os.environ.get("DEBUG", "false").lower() in ("true", "1", "yes"),
        },
    )


@router.get("/ready")
async def readiness_check():
    """Readiness check for Kubernetes/container orchestration.

    Returns 200 if the service is ready to accept traffic.
    Returns 503 if the service is not ready (e.g., still initializing).
    """
    # Add any initialization checks here
    # For now, always return ready
    return {"status": "ready", "timestamp": datetime.utcnow().isoformat()}


@router.get("/live")
async def liveness_check():
    """Liveness check for Kubernetes/container orchestration.

    Returns 200 if the service is alive and responding.
    This is a simple ping endpoint that should always succeed
    unless the service is completely unresponsive.
    """
    return {"status": "alive", "timestamp": datetime.utcnow().isoformat()}
