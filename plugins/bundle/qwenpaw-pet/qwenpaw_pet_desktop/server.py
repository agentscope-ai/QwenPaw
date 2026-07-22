# -*- coding: utf-8 -*-
"""Local HTTP bridge for QwenPaw lifecycle events."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, model_validator

from . import runtime
from .pet_package import resolve_switch_pet_path
from .sprites import VALID_STATES, state_for_event

logger = logging.getLogger(__name__)


class PetEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    event: str | None = None
    state: str | None = None
    text: str | None = None
    source: str | None = "qwenpaw"
    duration_ms: int | None = None
    delay_ms: int | None = None
    agent_id: str | None = None
    agent_name: str | None = None
    session_id: str | None = None
    channel: str | None = None


class BubblePayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    text: str
    source: str | None = "qwenpaw"


class SwitchPetPayload(BaseModel):
    """Hot-switch the running pet to another Codex-compatible package."""

    model_config = ConfigDict(extra="forbid")

    pet_dir: str | None = None
    pet_id: str | None = None

    @model_validator(mode="after")
    def _one_target(self) -> SwitchPetPayload:
        d = (self.pet_dir or "").strip()
        i = (self.pet_id or "").strip()
        if bool(d) == bool(i):
            raise ValueError("provide exactly one of pet_dir or pet_id")
        return self


def _token_required() -> bool:
    """Whether the local bridge enforces ``X-QwenPaw-Pet-Token``.

    Defaults to **on**: any other process running as the same user on
    the local machine could otherwise drive the pet or inject arbitrary
    bubble text without authentication. Operators that explicitly want
    to disable the check (e.g. for local development) can opt out by
    setting ``QWENPAW_PET_REQUIRE_TOKEN=0``.
    """
    return os.environ.get("QWENPAW_PET_REQUIRE_TOKEN", "1") != "0"


def _check_token(header_value: str | None) -> None:
    if not _token_required():
        return
    expected = runtime.read_token()
    if not expected:
        raise HTTPException(status_code=503, detail="token not initialized")
    if header_value != expected:
        raise HTTPException(status_code=401, detail="unauthorized")


def build_app(
    on_event: Callable[[dict[str, Any]], None],
    on_switch_pet: Callable[[Path], None],
) -> FastAPI:
    app = FastAPI(title="QwenPaw Pet Desktop")
    runtime.ensure_runtime()
    runtime.ensure_token()

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "ok": True,
            "service": "qwenpaw-pet-desktop",
            "tokenRequired": _token_required(),
            **runtime.current_process_status(),
        }

    @app.get("/event")
    def event_info() -> dict[str, Any]:
        return {
            "ok": True,
            "method": "POST",
            "validStates": sorted(VALID_STATES),
        }

    @app.get("/state")
    def state() -> dict[str, Any]:
        return runtime.read_json(
            runtime.state_path(),
            {"state": "idle", "counter": 0},
        )

    @app.post("/event")
    async def event(
        payload: PetEvent,
        request: Request,
        x_qwenpaw_pet_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _check_token(x_qwenpaw_pet_token)
        state = state_for_event(payload.event, payload.state)
        body = (
            payload.model_dump()
            if hasattr(payload, "model_dump")
            else payload.dict()
        )
        body["state"] = state
        body["receivedAt"] = int(time.time() * 1000)
        body["client"] = request.client.host if request.client else None
        on_event(body)
        logger.debug("event=%s state=%s", payload.event, state)
        return {"ok": True, "state": state}

    @app.get("/bubble")
    def bubble() -> dict[str, Any]:
        return runtime.read_json(
            runtime.bubble_path(),
            {"text": "", "counter": 0},
        )

    @app.post("/bubble")
    async def post_bubble(
        payload: BubblePayload,
        x_qwenpaw_pet_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _check_token(x_qwenpaw_pet_token)
        text = payload.text[:200]
        current = runtime.read_json(runtime.bubble_path(), {"counter": 0})
        data = {
            "text": text,
            "source": payload.source,
            "updatedAt": int(time.time() * 1000),
            "counter": int(current.get("counter", 0)) + 1,
        }
        runtime.write_json(runtime.bubble_path(), data)
        return {"ok": True, "counter": data["counter"]}

    @app.post("/pet")
    def switch_pet(
        payload: SwitchPetPayload,
        request: Request,
        x_qwenpaw_pet_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _check_token(x_qwenpaw_pet_token)
        try:
            path = resolve_switch_pet_path(
                pet_dir=payload.pet_dir,
                pet_id=payload.pet_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        on_switch_pet(path)
        return {
            "ok": True,
            "petDir": str(path),
            "receivedAt": int(time.time() * 1000),
            "client": request.client.host if request.client else None,
        }

    return app
