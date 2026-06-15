# -*- coding: utf-8 -*-
"""Secure skill pool import orchestration (verify then import)."""
from __future__ import annotations

import json
from typing import Any

from qwenpaw.agents.skill_system import SkillPoolService

from .errors import SkillSignatureRejectedError
from .verifier import verify_skill_package_signature


def parse_rename_map(rename_map: str) -> dict[str, str] | None:
    if not rename_map.strip():
        return None
    parsed = json.loads(rename_map)
    if not isinstance(parsed, dict):
        raise ValueError("rename_map must be a JSON object")
    return parsed


def secure_import_pool_zip(
    *,
    zip_data: bytes,
    signature_data: bytes,
    target_name: str = "",
    rename_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Verify signature, then import into the shared skill pool."""
    if not signature_data.strip():
        raise ValueError("signature_required")

    verification = verify_skill_package_signature(
        zip_data,
        signature_data,
    ).to_dict()
    if not verification.get("valid"):
        raise SkillSignatureRejectedError(verification)

    result = SkillPoolService().import_from_zip(
        data=zip_data,
        target_name=target_name,
        rename_map=rename_map,
    )
    result["verification"] = verification
    return result
