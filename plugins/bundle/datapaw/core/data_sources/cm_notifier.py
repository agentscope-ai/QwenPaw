# -*- coding: utf-8 -*-
"""Notify the remote cm service about data-source changes.

Best-effort: failures are logged and never affect the local CRUD operation.
The cm endpoint is configured via the ``DATAPAW_CM_BASE_URL`` environment
variable, falling back to the DataPaw default when unset.
"""
from __future__ import annotations

import logging
import uuid
from typing import Dict, Literal

import httpx

from qwenpaw.utils.http import trust_env_for_url

from ...constants import get_datapaw_cm_base_url
from .models import DataSourceRecord, _utc_now_iso

logger = logging.getLogger(__name__)

_SYNC_PATH = "/api/datasources/sync"
_TIMEOUT_SECONDS = 5.0

Action = Literal["created", "updated", "deleted"]


def _cm_sync_url() -> str:
    return f"{get_datapaw_cm_base_url()}{_SYNC_PATH}"


def _data_source_payload(action: Action, record: DataSourceRecord) -> Dict[str, object]:
    """Full, unmasked record for created/updated; id+type only for deleted."""
    if action == "deleted":
        data_source: Dict[str, object] = {"id": record.id, "type": record.type}
    else:
        data_source = record.model_dump(by_alias=True, mode="json")
    return {
        "action": action,
        "timestamp": _utc_now_iso(),
        "dataSource": data_source,
    }


async def notify_cm(action: Action, record: DataSourceRecord) -> None:
    """Send a change notification to cm. Never raises."""
    url = _cm_sync_url()

    payload = _data_source_payload(action, record)
    request_id = uuid.uuid4().hex
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT_SECONDS,
            trust_env=trust_env_for_url(url),
        ) as client:
            resp = await client.post(
                url,
                json=payload,
                headers={"X-Request-Id": request_id},
            )
        if resp.status_code >= 400:
            logger.warning(
                "cm notify failed: action=%s id=%s status=%s request_id=%s",
                action,
                record.id,
                resp.status_code,
                request_id,
            )
        else:
            logger.info(
                "cm notify ok: action=%s id=%s status=%s request_id=%s",
                action,
                record.id,
                resp.status_code,
                request_id,
            )
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning(
            "cm notify error: action=%s id=%s err=%s request_id=%s",
            action,
            record.id,
            exc,
            request_id,
        )
