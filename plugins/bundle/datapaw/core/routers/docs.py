# -*- coding: utf-8 -*-
"""Transparent proxy for KG document APIs served by CM."""
from __future__ import annotations

import logging
import os
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from qwenpaw.utils.http import trust_env_for_url

from ..data_sources.cm_notifier import CM_BASE_URL_ENV

logger = logging.getLogger(__name__)

router = APIRouter(tags=["datapaw-docs"])

_DOCS_API_PATH = "/api/v1/docs"
_SERVER_ERROR_BODY = {"code": 50001, "message": "server_error", "data": None}
_TIMEOUT = httpx.Timeout(60.0, connect=10.0)


def _server_error() -> JSONResponse:
    return JSONResponse(status_code=500, content=_SERVER_ERROR_BODY)


def _cm_docs_url(path: str = "") -> str | None:
    base_url = (os.environ.get(CM_BASE_URL_ENV) or "").strip().rstrip("/")
    if not base_url:
        return None
    return f"{base_url}{_DOCS_API_PATH}{path}"


async def _proxy_json_request(
    method: str,
    path: str = "",
    *,
    query: str = "",
    content: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    url = _cm_docs_url(path)
    if not url:
        logger.warning("%s not set; docs proxy unavailable", CM_BASE_URL_ENV)
        return _server_error()
    if query:
        url = f"{url}?{query}"

    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT,
            trust_env=trust_env_for_url(url),
        ) as client:
            response = await client.request(
                method,
                url,
                content=content,
                headers=headers,
            )
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning(
            "CM docs proxy request failed: method=%s url=%s err=%s",
            method,
            url,
            exc,
        )
        return _server_error()

    try:
        body = response.json()
    except ValueError:
        logger.warning(
            "CM docs proxy returned non-json response: method=%s url=%s status=%s",
            method,
            url,
            response.status_code,
        )
        return _server_error()

    return JSONResponse(status_code=response.status_code, content=body)


@router.post("/upload", summary="Proxy document upload to CM")
async def upload_doc(request: Request) -> JSONResponse:
    headers: dict[str, str] = {}
    content_type = request.headers.get("content-type")
    if content_type:
        headers["Content-Type"] = content_type
    return await _proxy_json_request(
        "POST",
        "/upload",
        content=await request.body(),
        headers=headers,
    )


@router.get("", summary="Proxy document list to CM")
async def list_docs(request: Request) -> JSONResponse:
    return await _proxy_json_request("GET", query=request.url.query)


@router.delete("/{doc_id:path}", summary="Proxy document delete to CM")
async def delete_doc(doc_id: str) -> JSONResponse:
    return await _proxy_json_request("DELETE", f"/{quote(doc_id, safe='')}")
