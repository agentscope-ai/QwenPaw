from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from .store import SecurityCenterStore

_TEST_FAILURE_INJECTION_ENV = "QWENPAW_SECURITY_CENTER_ENABLE_TEST_FAILURE_INJECTION"


def _test_failure_injection_enabled() -> bool:
    return os.environ.get(_TEST_FAILURE_INJECTION_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


class RecoveryHandshakeRequest(BaseModel):
    client_id: str = Field(..., min_length=1)
    session_id: str | None = None
    trace_id: str | None = None
    local_hash: str = Field(..., min_length=1)
    checkpoint_hash: str | None = None
    lease_ttl_seconds: int | None = Field(None, ge=1)
    local_sequence: int | None = Field(None, ge=0)
    checkpoint_sequence: int | None = Field(None, ge=0)
    anchored_event_id: str | None = None
    checkpoint_anchor_id: str | None = None
    gap_proof: dict[str, Any] | None = None
    requested_at_ns: int | None = None


class RejectionUplinkRequest(BaseModel):
    client_id: str | None = None
    trace_id: str | None = None
    run_id: str | None = None
    session_id: str | None = None
    user_id: str = Field(..., min_length=1)
    tool_name: str = Field(..., min_length=1)
    prompt_text: str | None = None
    current_hash: str | None = None
    edge_timestamp_ns: int = Field(..., ge=1)
    security_rejection_nonce: str | None = None
    Security_Rejection_Nonce: str | None = None
    security_rejection_nonce_binding_hash: str | None = None


class LockdownUplinkRequest(BaseModel):
    client_id: str | None = None
    trace_id: str | None = None
    run_id: str | None = None
    session_id: str | None = None
    user_id: str = Field(..., min_length=1)
    tool_name: str = Field(..., min_length=1)
    current_hash: str = Field(..., min_length=1)
    prior_hash: str | None = None
    current_sequence: int | None = Field(None, ge=0)
    prior_sequence: int | None = Field(None, ge=0)
    anchored_event_id: str | None = None
    prior_anchored_event_id: str | None = None
    edge_timestamp_ns: int = Field(..., ge=1)


class TrustedAnchorUplinkRequest(BaseModel):
    client_id: str = Field(..., min_length=1)
    trace_id: str | None = None
    run_id: str | None = None
    session_id: str | None = None
    event_type: str = Field(..., min_length=1)
    anchor: dict[str, Any] = Field(...)


def create_app(store: SecurityCenterStore | None = None) -> FastAPI:
    app = FastAPI(
        title="QwenPaw Security Center API",
        version="0.1.0",
        summary="Independent Security Center backend API for recovery handshakes, vouchers, and realtime alerts.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    service_store = store or SecurityCenterStore.from_default()

    @app.get("/")
    async def root() -> dict[str, Any]:
        return {
            "service": "security_center_backend_api",
            "health": "ok",
            "stream": "/security-center/v1/operator/stream",
            "overview": "/security-center/v1/operator/overview",
        }

    @app.get("/security-center/v1/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "service": "security_center_backend_api"}

    @app.post("/security-center/v1/recovery/handshake")
    async def recovery_handshake(body: RecoveryHandshakeRequest) -> dict[str, Any]:
        return await service_store.recovery_handshake(body.model_dump(mode="json"))

    @app.post("/security-center/v1/uplinks/rejections")
    async def uplink_rejection(body: RejectionUplinkRequest) -> dict[str, Any]:
        return await service_store.record_rejection(body.model_dump(mode="json"))

    @app.post("/security-center/v1/uplinks/lockdowns")
    async def uplink_lockdown(body: LockdownUplinkRequest) -> dict[str, Any]:
        return await service_store.record_lockdown(body.model_dump(mode="json"))

    @app.post("/security-center/v1/uplinks/trusted-anchors")
    async def uplink_trusted_anchor(body: TrustedAnchorUplinkRequest) -> dict[str, Any]:
        return await service_store.record_trusted_anchor(body.model_dump(mode="json"))

    @app.post("/security-center/v1/events")
    async def submit_security_event(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except json.JSONDecodeError:
            body = {}
        if not isinstance(body, dict):
            body = {"_invalidRequest": body}
        test_persistence_failure_requested = (
            _test_failure_injection_enabled()
            and request.headers.get("X-QwenPaw-Test-Persistence-Failure", "").lower() == "true"
        )
        result = await service_store.submit_security_event(
            body,
            force_persistence_failure=test_persistence_failure_requested,
        )
        status_code = int(result.pop("_status_code", 200))
        return JSONResponse(result, status_code=status_code)

    @app.get("/security-center/v1/operator/overview")
    async def operator_overview() -> dict[str, Any]:
        return await service_store.overview()

    @app.get("/security-center/v1/operator/events")
    async def operator_security_events(
        sourceSystem: str | None = None,  # noqa: N803 - external API field spelling is frozen.
        eventTypeId: str | None = None,  # noqa: N803
        severity: str | None = None,
        occurredFrom: str | None = None,  # noqa: N803
        occurredTo: str | None = None,  # noqa: N803
    ) -> dict[str, Any]:
        return await service_store.security_events(
            source_system=sourceSystem,
            event_type_id=eventTypeId,
            severity=severity,
            occurred_from=occurredFrom,
            occurred_to=occurredTo,
        )

    @app.get("/security-center/v1/operator/events/{source_system}/{event_id}")
    async def operator_security_event_detail(source_system: str, event_id: str) -> dict[str, Any]:
        event = await service_store.security_event_detail(source_system, event_id)
        if event is None:
            raise HTTPException(status_code=404, detail="security event not found")
        return event

    @app.get("/security-center/v1/operator/event-reception-failures")
    async def operator_security_event_failures() -> dict[str, Any]:
        return await service_store.security_event_failures()

    @app.get("/security-center/v1/operator/event-observation-panel")
    async def operator_security_event_observation_panel(
        range: str | None = None,  # noqa: A002 - external API query parameter is frozen.
        focusSourceSystem: str | None = None,  # noqa: N803
        focusEventId: str | None = None,  # noqa: N803
    ) -> dict[str, Any]:
        return await service_store.security_event_observation_panel(
            range_key=range,
            focus_source_system=focusSourceSystem,
            focus_event_id=focusEventId,
        )

    @app.get("/security-center/v1/operator/rejections/{nonce}")
    async def operator_rejection(nonce: str) -> dict[str, Any]:
        record = await service_store.rejection(nonce)
        if record is None:
            raise HTTPException(status_code=404, detail="rejection not found")
        return record

    @app.get("/security-center/v1/operator/vouchers/{nonce}")
    async def operator_voucher(nonce: str) -> dict[str, Any]:
        voucher = await service_store.voucher(nonce)
        if voucher is None:
            raise HTTPException(status_code=404, detail="voucher not found")
        return voucher

    @app.get("/security-center/v1/operator/timelines/{client_id}")
    async def operator_timeline(client_id: str) -> dict[str, Any]:
        timeline = await service_store.timeline(client_id)
        if timeline is None:
            raise HTTPException(status_code=404, detail="timeline not found")
        return timeline

    @app.get("/security-center/v1/operator/stream")
    async def operator_stream() -> StreamingResponse:
        queue = await service_store.subscribe()

        async def event_stream():
            try:
                yield "event: ready\ndata: {\"service\":\"security_center_backend_api\"}\n\n"
                while True:
                    try:
                        alert = await asyncio.wait_for(queue.get(), timeout=15.0)
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    yield f"event: security-alert\ndata: {json.dumps(alert, ensure_ascii=False)}\n\n"
            finally:
                await service_store.unsubscribe(queue)

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run(
        "deploy.api.app:app",
        host=os.environ.get("SECURITY_CENTER_API_HOST", "127.0.0.1"),
        port=int(os.environ.get("SECURITY_CENTER_API_PORT", "8091")),
        reload=False,
        timeout_graceful_shutdown=2,
    )
