# -*- coding: utf-8 -*-
"""Integrity Protection delivery routes (settings, health, rule check)."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter

from .schemas_integrity_delivery import (
    HealthCheckFixRequest,
    HealthCheckFixResponse,
    HealthCheckScanRequest,
    HealthCheckScanResponse,
    IntegrityProtectionSettingsResponse,
)

router = APIRouter(tags=["config"])


@router.get(
    "/security/integrity-protection/settings",
    response_model=IntegrityProtectionSettingsResponse,
    summary="Get default-off Integrity Protection settings",
)
async def get_integrity_protection_settings() -> IntegrityProtectionSettingsResponse:
    from ...security.integrity_protection import get_default_integrity_settings

    settings = get_default_integrity_settings()
    return IntegrityProtectionSettingsResponse(**settings.to_dict())


@router.post(
    "/security/integrity-protection/health-check/scan",
    response_model=HealthCheckScanResponse,
    summary="Run read-only Integrity Protection health check scan",
)
async def run_integrity_health_check_scan(
    body: HealthCheckScanRequest | None = None,
) -> HealthCheckScanResponse:
    from ...security.integrity_protection import run_health_check_scan

    result = await asyncio.to_thread(
        run_health_check_scan,
        deep=bool(body.deep) if body is not None else False,
    )
    return HealthCheckScanResponse(**result.to_dict())


@router.post(
    "/security/integrity-protection/health-check/fix",
    response_model=HealthCheckFixResponse,
    summary="Run one explicitly confirmed doctor fix",
)
async def run_integrity_health_check_fix(
    body: HealthCheckFixRequest,
) -> HealthCheckFixResponse:
    from ...security.integrity_protection import run_confirmed_health_fix

    result = await asyncio.to_thread(
        run_confirmed_health_fix,
        fix_id=body.fix_id,
        selected_repair=body.selected_repair or f"repair_{body.fix_id}",
    )
    return HealthCheckFixResponse(**result.to_dict())

