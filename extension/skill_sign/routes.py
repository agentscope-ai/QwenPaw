# -*- coding: utf-8 -*-
"""FastAPI routes for skill pool secure import."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from agentscope_runtime.engine.schemas.exception import AppBaseException
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from qwenpaw.security.skill_scanner import SkillScanError

from .errors import SkillSignatureRejectedError
from .pool_import import parse_rename_map, secure_import_pool_zip
from .upload import read_validated_zip_upload

router = APIRouter(tags=["skills"])


def _scan_error_payload(exc: SkillScanError) -> dict[str, Any]:
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
    return JSONResponse(
        status_code=422,
        content=_scan_error_payload(exc),
    )


@router.post("/pool/secure-import")
async def upload_skill_pool_secure_zip(
    file: UploadFile = File(...),
    signature: UploadFile = File(...),
    target_name: str = "",
    rename_map: str = "",
) -> dict[str, Any]:
    data = await read_validated_zip_upload(file)
    signature_data = await signature.read()
    if not signature_data.strip():
        raise HTTPException(
            status_code=400,
            detail={
                "reason": "signature_required",
                "message": "A detached .sig file is required for secure import",
            },
        )

    try:
        parsed_rename = parse_rename_map(rename_map)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail="rename_map must be valid JSON",
        ) from exc

    try:
        result = await asyncio.to_thread(
            secure_import_pool_zip,
            zip_data=data,
            signature_data=signature_data,
            target_name=target_name,
            rename_map=parsed_rename,
        )
    except SkillSignatureRejectedError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "reason": "signature_verification_failed",
                "verification": exc.verification,
            },
        ) from exc
    except SkillScanError as exc:
        return _scan_error_response(exc)
    except ValueError as exc:
        if str(exc) == "signature_required":
            raise HTTPException(
                status_code=400,
                detail={
                    "reason": "signature_required",
                    "message": "A detached .sig file is required for secure import",
                },
            ) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AppBaseException as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if result.get("conflicts"):
        raise HTTPException(status_code=409, detail=result)
    return result
