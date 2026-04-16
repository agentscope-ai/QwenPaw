# -*- coding: utf-8 -*-
"""Shared media URL utilities for channels."""

import asyncio
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


async def resolve_media_url(local_path: str) -> str:
    """Convert a local media path to the best available URL.

    If media server is enabled + tunnel configured, returns signed HTTPS URL.
    Otherwise returns the local path as-is (formatter will base64 encode).
    """
    try:
        from ...agents.tools.view_media import _get_media_config, _get_signed_url

        cfg = _get_media_config()
        if cfg["enabled"] and cfg["tunnel_domain"]:
            signed = await _get_signed_url(Path(local_path))
            if signed:
                return signed
    except Exception as e:
        logger.debug("resolve_media_url: fallback to local path: %s", e)
    return str(local_path)
