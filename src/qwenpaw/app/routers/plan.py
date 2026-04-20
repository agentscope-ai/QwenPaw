# -*- coding: utf-8 -*-
"""Plan API endpoints for real-time plan visualization and management."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from starlette.responses import StreamingResponse

from ...constant import EnvVarLoader
from ..agent_context import get_agent_for_request
from ..auth import _get_jwt_secret, has_registered_users, is_auth_enabled
from ...plan import set_plan_gate
from ...plan.session_sync import (
    clear_plan_notebook_if_session_has_no_snapshot,
    persist_plan_notebook_to_session,
)
from ...plan.schemas import (
    FinishPlanRequest,
    PlanConfigUpdateRequest,
    PlanStateResponse,
    RevisePlanRequest,
    plan_to_response,
)
from ...plan.broadcast import (
    plan_sse_scope,
    plan_sse_scope_key,
    register_sse_client,
    unregister_sse_client,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plan", tags=["plan"])

# Short-lived HMAC-signed tickets for plan SSE (EventSource cannot send
# Authorization headers; avoids putting long-lived JWTs in query strings).
# Stateless tickets work across multiple workers; set
# ``QWENPAW_PLAN_SSE_SIGNING_KEY`` when workers do not share the same
# ``jwt_secret`` on disk.
_SSE_TICKET_TTL_SECONDS = 60


def _sse_ticket_signing_key() -> bytes:
    custom = EnvVarLoader.get_str("QWENPAW_PLAN_SSE_SIGNING_KEY", "").strip()
    if custom:
        return custom.encode("utf-8")
    return _get_jwt_secret().encode("utf-8")


def _issue_sse_ticket(agent_id: str) -> str:
    payload = {"a": agent_id, "iat": time.time()}
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    encoded = base64.urlsafe_b64encode(body.encode("utf-8")).decode("ascii")
    body_b64 = encoded.rstrip("=")
    sig = hmac.new(
        _sse_ticket_signing_key(),
        body_b64.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    return f"{body_b64}.{sig}"


def _decode_sse_ticket_payload(raw: str) -> dict | None:
    """Decode and verify SSE ticket payload."""
    try:
        parts = raw.split(".", 1)
        if len(parts) != 2:
            return None
        body_b64, sig = parts
        expected = hmac.new(
            _sse_ticket_signing_key(),
            body_b64.encode("ascii"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, sig):
            return None
        pad = "=" * (-len(body_b64) % 4)
        decoded = base64.urlsafe_b64decode(body_b64 + pad)
        payload = json.loads(decoded.decode("utf-8"))
        iat = float(payload.get("iat", 0))
        if time.time() - iat > _SSE_TICKET_TTL_SECONDS:
            return None
        return payload if isinstance(payload, dict) else None
    except Exception:  # pylint: disable=broad-except
        return None


def _consume_sse_ticket(raw: str) -> tuple[Optional[str], Optional[str]]:
    """Return (agent_id, scope_key) for a valid ticket, else (None, None)."""
    payload = _decode_sse_ticket_payload(raw)
    if payload is None:
        return None, None

    aid = payload.get("a")
    if not isinstance(aid, str) or not aid.strip():
        return None, None

    sk_raw = payload.get("s")
    if sk_raw is not None and not isinstance(sk_raw, str):
        return None, None

    scope_key = (
        sk_raw.strip() if isinstance(sk_raw, str) and sk_raw.strip() else None
    )
    return aid, scope_key


async def _get_plan_notebook(request: Request):
    """Resolve the PlanNotebook for the current request's agent."""
    workspace = await get_agent_for_request(request)
    nb = workspace.plan_notebook
    if nb is None:
        raise HTTPException(
            status_code=404,
            detail="Plan mode is not enabled for this agent",
        )
    return nb, workspace


def _session_scope_from_request(request: Request) -> tuple[str, str]:
    """Return session_id and user_id from headers or query (console chat)."""
    session_id = (
        request.headers.get("X-Session-Id")
        or request.query_params.get("session_id")
        or ""
    ).strip()
    user_id = (
        request.headers.get("X-User-Id")
        or request.query_params.get("user_id")
        or ""
    ).strip()
    return session_id, user_id


def _channel_from_request(request: Request) -> str:
    """Channel id for plan SSE scope (defaults to ``console``)."""
    return (
        request.headers.get("X-Channel")
        or request.query_params.get("channel")
        or "console"
    ).strip() or "console"


async def _hydrate_plan_notebook_from_session(
    request: Request,
    workspace,
    plan_notebook,
) -> None:
    """Load ``plan_notebook`` from the session file before HTTP mutations."""
    session_id, user_id = _session_scope_from_request(request)
    runner = getattr(workspace, "runner", None)
    sess = getattr(runner, "session", None) if runner is not None else None
    if not session_id or sess is None or plan_notebook is None:
        return
    try:
        await sess.load_session_state(
            session_id=session_id,
            user_id=user_id,
            plan_notebook=plan_notebook,
        )
    except KeyError as e:
        logger.warning(
            "plan hydrate skipped (schema mismatch or missing key): %s",
            e,
        )


async def _persist_plan_notebook_to_session(
    request: Request,
    workspace,
    plan_notebook,
) -> None:
    """Write the in-memory notebook to the chat session JSON immediately."""
    session_id, user_id = _session_scope_from_request(request)
    runner = getattr(workspace, "runner", None)
    session = getattr(runner, "session", None) if runner is not None else None
    try:
        await persist_plan_notebook_to_session(
            session=session,
            plan_notebook=plan_notebook,
            session_id=session_id,
            user_id=user_id,
        )
    except Exception as e:
        logger.exception("Failed to persist plan_notebook via HTTP")
        raise HTTPException(
            status_code=500,
            detail="Failed to persist plan notebook to session",
        ) from e


@router.get(
    "/current",
    response_model=Optional[PlanStateResponse],
    summary="Get current plan state",
)
async def get_current_plan(
    request: Request,
    strict: bool = Query(
        False,
        description=(
            "When true, respond with 404 if no plan is active; "
            "default is 200 with null body for backward compatibility."
        ),
    ),
):
    """Return the current plan state, or null if no plan is active.

    Use ``strict=true`` for API clients that prefer 404 over nullable 200.

    When ``X-Session-Id`` (or query ``session_id``) is set, sync the shared
    notebook from that session file first so callers never read another
    session's in-memory plan.
    """
    workspace = await get_agent_for_request(request)
    nb = workspace.plan_notebook
    if nb is None:
        if strict:
            raise HTTPException(status_code=404, detail="No active plan")
        return None

    session_id, user_id = _session_scope_from_request(request)
    channel = _channel_from_request(request)
    if session_id:
        runner = getattr(workspace, "runner", None)
        sess = getattr(runner, "session", None) if runner is not None else None
        if sess is not None:
            with plan_sse_scope(channel, session_id):
                await clear_plan_notebook_if_session_has_no_snapshot(
                    session=sess,
                    plan_notebook=nb,
                    session_id=session_id,
                    user_id=user_id,
                    agent_id=workspace.agent_id,
                )
                await _hydrate_plan_notebook_from_session(
                    request,
                    workspace,
                    nb,
                )

    if nb.current_plan is None:
        if strict:
            raise HTTPException(status_code=404, detail="No active plan")
        return None
    return plan_to_response(nb.current_plan)


@router.post(
    "/revise",
    response_model=PlanStateResponse,
    summary="Revise the current plan",
)
async def revise_plan(body: RevisePlanRequest, request: Request):
    """Revise the current plan by adding, revising, or deleting a subtask."""
    nb, workspace = await _get_plan_notebook(request)
    if nb.current_plan is None:
        raise HTTPException(
            status_code=400,
            detail="No active plan to revise",
        )

    from agentscope.plan import SubTask

    subtask = None
    if body.subtask is not None:
        subtask = SubTask(
            name=body.subtask.name,
            description=body.subtask.description,
            expected_outcome=body.subtask.expected_outcome,
        )
    channel = _channel_from_request(request)
    session_id, _ = _session_scope_from_request(request)
    with plan_sse_scope(channel, session_id):
        await _hydrate_plan_notebook_from_session(request, workspace, nb)
        await nb.revise_current_plan(
            subtask_idx=body.subtask_idx,
            action=body.action,
            subtask=subtask,
        )
    await _persist_plan_notebook_to_session(request, workspace, nb)
    return plan_to_response(nb.current_plan)


@router.post(
    "/finish",
    summary="Finish or abandon the current plan",
)
async def finish_plan(body: FinishPlanRequest, request: Request):
    """Finish or abandon the current plan."""
    nb, workspace = await _get_plan_notebook(request)
    if nb.current_plan is None:
        raise HTTPException(
            status_code=400,
            detail="No active plan to finish",
        )
    channel = _channel_from_request(request)
    session_id, _ = _session_scope_from_request(request)
    with plan_sse_scope(channel, session_id):
        await _hydrate_plan_notebook_from_session(request, workspace, nb)
        await nb.finish_plan(state=body.state, outcome=body.outcome)
    set_plan_gate(nb, False)
    await _persist_plan_notebook_to_session(request, workspace, nb)
    return {"success": True}


@router.post(
    "/stream/ticket",
    summary="Issue a short-lived SSE ticket for plan stream",
)
async def issue_plan_stream_ticket(request: Request):
    """Return a short-lived signed ticket for ``GET /plan/stream``.

    Call this with a normal ``Authorization: Bearer`` header; the ticket
    is bound to the resolved agent and must be used within
    ``_SSE_TICKET_TTL_SECONDS``. Signing is stateless so multiple workers
    can validate the same ticket.
    """
    workspace = await get_agent_for_request(request)
    ticket = _issue_sse_ticket(workspace.agent_id)
    return {"ticket": ticket}


@router.get(
    "/stream",
    summary="SSE stream for real-time plan updates",
)
async def stream_plan_updates(request: Request):
    """Open an SSE connection that emits plan_update events."""
    auth_required = is_auth_enabled() and has_registered_users()
    ticket_raw = request.query_params.get("ticket")
    if auth_required:
        if not ticket_raw:
            raise HTTPException(
                status_code=401,
                detail="Missing SSE ticket; POST /plan/stream/ticket first",
            )
        bound_agent_id, ticket_scope = _consume_sse_ticket(ticket_raw)
        if bound_agent_id is None:
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired SSE ticket",
            )
        workspace = await get_agent_for_request(
            request,
            agent_id=bound_agent_id,
        )
    else:
        workspace = await get_agent_for_request(request)
        ticket_scope = None
    agent_id = workspace.agent_id

    if auth_required:
        sse_scope = ticket_scope
    else:
        channel = _channel_from_request(request)
        session_id, _ = _session_scope_from_request(request)
        sse_scope = plan_sse_scope_key(channel, session_id)

    q = register_sse_client(agent_id, scope_key=sse_scope)

    async def _event_generator():
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=60)
                    data = json.dumps(
                        payload,
                        ensure_ascii=False,
                    )
                    yield f"event: plan_update\ndata: {data}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"

                if await request.is_disconnected():
                    break
        except asyncio.CancelledError:
            pass
        finally:
            unregister_sse_client(agent_id, q, scope_key=sse_scope)

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/config",
    summary="Get plan configuration",
)
async def get_plan_config(request: Request):
    """Get the plan configuration for the current agent."""
    workspace = await get_agent_for_request(request)
    config = workspace.config
    return config.plan.model_dump()


@router.put(
    "/config",
    summary="Update plan configuration",
)
async def update_plan_config(
    body: PlanConfigUpdateRequest,
    request: Request,
):
    """Update the plan configuration and activate/deactivate
    the PlanNotebook dynamically (no restart required)."""
    from ...config.config import (
        PlanConfig,
        load_agent_config,
        save_agent_config,
    )

    workspace = await get_agent_for_request(request)
    agent_id = workspace.agent_id

    agent_config = load_agent_config(agent_id)
    was_enabled = agent_config.plan.enabled
    agent_config.plan = PlanConfig(**body.model_dump())
    save_agent_config(agent_id, agent_config)

    if body.enabled and not was_enabled:
        await workspace.activate_plan_notebook()
    elif not body.enabled and was_enabled:
        await workspace.deactivate_plan_notebook()
        # Drop saved plan snapshot for the current chat session so re-enable
        # does not resurrect a stale plan from disk.
        session_id, user_id = _session_scope_from_request(request)
        runner = getattr(workspace, "runner", None)
        sess = getattr(runner, "session", None) if runner is not None else None
        if sess is not None and session_id:
            try:
                await sess.update_session_state(
                    session_id=session_id,
                    key="plan_notebook",
                    value=None,
                    user_id=user_id,
                )
            except Exception:
                logger.warning(
                    "Could not clear plan_notebook in session file on disable",
                    exc_info=True,
                )

    return agent_config.plan.model_dump()


@router.post(
    "/confirm",
    summary="Confirm and start executing the current plan",
)
async def confirm_plan(request: Request):
    """Mark the first todo subtask as in_progress so the agent
    begins execution on the next user message."""
    nb, workspace = await _get_plan_notebook(request)
    if nb.current_plan is None:
        raise HTTPException(
            status_code=400,
            detail="No active plan to confirm",
        )

    channel = _channel_from_request(request)
    session_id, _ = _session_scope_from_request(request)
    with plan_sse_scope(channel, session_id):
        await _hydrate_plan_notebook_from_session(request, workspace, nb)

        plan = nb.current_plan
        for idx, st in enumerate(plan.subtasks):
            if st.state == "todo":
                await nb.update_subtask_state(idx, "in_progress")
                if hasattr(nb, "_plan_needs_reconfirmation"):
                    # pylint: disable-next=protected-access
                    nb._plan_needs_reconfirmation = False
                await _persist_plan_notebook_to_session(
                    request,
                    workspace,
                    nb,
                )
                return {
                    "confirmed": True,
                    "started_subtask_idx": idx,
                }

        if hasattr(nb, "_plan_needs_reconfirmation"):
            # pylint: disable-next=protected-access
            nb._plan_needs_reconfirmation = False
    await _persist_plan_notebook_to_session(request, workspace, nb)
    return {"confirmed": True, "started_subtask_idx": None}
