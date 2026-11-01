# -*- coding: utf-8 -*-
"""Scoped native-console admission on the stable PawApp SDK."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Literal

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field


class DataScope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    app_id: Literal["qwenpaw-data"] = "qwenpaw-data"
    principal_id: str = Field(min_length=1, max_length=256)
    workspace_id: str = Field(min_length=1, max_length=128)


async def console_scope(request: Request) -> DataScope:
    principal = str(getattr(request.state, "user", None) or "default")
    workspace = request.headers.get("X-Agent-Id") or request.query_params.get(
        "agent_id",
        "default",
    )
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", workspace):
        raise HTTPException(422, "Invalid workspace")
    for query, header, expected in (
        ("user_id", "X-User-Id", principal),
        ("channel", "X-Channel", "console"),
        ("agent_id", "X-Agent-Id", workspace),
        ("app_id", "X-PawApp-Id", "qwenpaw-data"),
    ):
        claims = request.query_params.getlist(query) + request.headers.getlist(
            header,
        )
        if any(claim != expected for claim in claims):
            raise HTTPException(403, "Request scope does not match")
    return DataScope(principal_id=principal, workspace_id=workspace)


def identity_namespace(scope: DataScope) -> str:
    encoded = json.dumps(
        scope.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()
    return "pawapp_" + hashlib.sha256(encoded).hexdigest()


async def dispatch_console_chat(request: Request, gateway, model_resolver):
    scope = await console_scope(request)
    try:
        inputs = await request.json()
    except ValueError:
        raise HTTPException(422, "Invalid analysis inputs") from None
    allowed = {
        "session_id",
        "text",
        "datasource_id",
        "dataset_names",
        "attachment_ids",
        "artifact_comments",
        "enable_clarification",
    }
    if not isinstance(inputs, dict) or set(inputs) - allowed:
        raise HTTPException(422, "Invalid analysis inputs")
    if inputs.get("enable_clarification", True) is not True:
        raise HTTPException(422, "Clarification must be enabled")
    identity = identity_namespace(scope)
    try:
        capabilities = await gateway.json(
            "GET",
            "/api/v1/console/capabilities",
            user_id=identity,
        )
    except HTTPException as exc:
        if exc.status_code == 404:
            raise HTTPException(
                503,
                "Update the Data Engine runtime to 0.3.3 or later",
            ) from None
        raise
    if (
        not isinstance(capabilities, dict)
        or not all(
            capabilities.get(name) is True
            for name in (
                "scoped_sessions",
                "runtime_model_bindings",
                "dataset_context",
            )
        )
        or capabilities.get("console_protocol") != 1
    ):
        raise HTTPException(
            503,
            "Update the Data Engine runtime to 0.3.3 or later",
        )
    inputs["runtime_models"] = await model_resolver(scope)
    return await gateway.json(
        "POST",
        "/api/v1/console/chat",
        body=inputs,
        user_id=identity,
    )
