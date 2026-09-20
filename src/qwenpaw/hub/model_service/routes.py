# -*- coding: utf-8 -*-
"""Composable governance routes with separate member and runtime identities."""

from __future__ import annotations

import asyncio
import json
from datetime import date

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool

from ..api_models import PasswordChangeBody
from .analytics import usage_details
from .provider_setup import discover_models, provider_presets
from .api_models import (
    BudgetBody,
    ConnectionBody,
    InviteBatchBody,
    ModelBody,
    PolicyBody,
)


def governance_router(
    store,
    catalog,
    budgets,
    gateway,
    invitations,
    auth,
    require_user,
    require_admin,
    audit,
):
    """Build routes without expanding the control application closure."""
    router = APIRouter(prefix="/api/hub", tags=["governance"])

    async def mutation(user, action, resource, operation, *args):
        try:
            result = await run_in_threadpool(operation, *args)
        except (ValueError, KeyError) as exc:
            raise HTTPException(409, str(exc)) from exc
        await audit(user, action, "governance", resource)
        return result

    @router.get("/admin/model-policy")
    def policy(_admin=Depends(require_admin)):
        return store.settings()

    @router.put("/admin/model-policy")
    async def save_policy(body: PolicyBody, user=Depends(require_admin)):
        return await mutation(
            user,
            "model.policy_update",
            "organization",
            catalog.save_policy,
            body,
        )

    @router.get("/admin/model-provider-presets")
    def presets(_admin=Depends(require_admin)):
        return provider_presets()

    @router.post("/admin/model-connections/{connection_id}/discover")
    async def discover(connection_id: str, _admin=Depends(require_admin)):
        try:
            async with asyncio.timeout(15):
                return await discover_models(catalog, connection_id)
        except KeyError as exc:
            raise HTTPException(404, "Connection not found") from exc
        except Exception as exc:
            # Provider errors may contain credentials or response data.
            raise HTTPException(502, "hub_model_discovery_failed") from exc

    @router.get("/admin/model-connections/{connection_id}/token-defaults")
    def token_defaults(
        connection_id: str,
        model_id: str = Query(min_length=1, max_length=256),
        _admin=Depends(require_admin),
    ):
        try:
            return catalog.token_defaults(connection_id, model_id)
        except KeyError as exc:
            raise HTTPException(404, "Connection not found") from exc

    @router.get("/admin/model-connections")
    def connections(_admin=Depends(require_admin)):
        return catalog.connections()

    @router.post("/admin/model-connections")
    async def create_connection(
        body: ConnectionBody,
        user=Depends(require_admin),
    ):
        return await mutation(
            user,
            "model.connection_create",
            "connection",
            catalog.save_connection,
            body,
        )

    @router.put("/admin/model-connections/{connection_id}")
    async def update_connection(
        connection_id: str,
        body: ConnectionBody,
        user=Depends(require_admin),
    ):
        return await mutation(
            user,
            "model.connection_update",
            connection_id,
            catalog.save_connection,
            body,
            connection_id,
        )

    @router.get("/admin/models")
    def models(_admin=Depends(require_admin)):
        return catalog.rows("hub_managed_models")

    @router.post("/admin/models")
    async def create_model(body: ModelBody, user=Depends(require_admin)):
        return await mutation(
            user,
            "model.publish",
            "model",
            catalog.save_model,
            body,
        )

    @router.put("/admin/models/{model_id}")
    async def update_model(
        model_id: str,
        body: ModelBody,
        user=Depends(require_admin),
    ):
        return await mutation(
            user,
            "model.publish",
            model_id,
            catalog.save_model,
            body,
            model_id,
        )

    @router.post("/admin/models/{model_id}/test")
    async def test_model(model_id: str, user=Depends(require_admin)):
        return await gateway.call(
            {"user_id": user.user_id, "runtime_id": "admin-test"},
            {
                "model": model_id,
                "messages": [
                    {"role": "user", "content": "Reply OK"},
                ],
                "max_tokens": 16,
            },
            admin_test=True,
        )

    @router.get("/admin/model-status")
    def status(_admin=Depends(require_admin)):
        with store.connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT r.runtime_id, r.owner_user_id, r.observed_state, "
                    "t.observed_revision, t.observed_at, "
                    "(SELECT MAX(q.revision) FROM hub_model_requests q "
                    "WHERE q.runtime_id = r.runtime_id "
                    "AND q.status = 'settled') "
                    "AS used_revision FROM runtimes r "
                    "LEFT JOIN hub_model_runtime_tokens t "
                    "ON t.runtime_id = r.runtime_id "
                    "WHERE r.deleted_at IS NULL",
                )
            ]

    @router.post("/admin/users/{user_id}/password", status_code=204)
    async def reset_password(
        user_id: str,
        body: PasswordChangeBody,
        user=Depends(require_admin),
    ):
        target = await run_in_threadpool(auth.get_user, user_id)
        if target is None:
            raise HTTPException(404, "User not found")
        if target.is_admin or user_id == user.user_id:
            raise HTTPException(
                403,
                "Only ordinary member passwords can reset",
            )
        await mutation(
            user,
            "user.password_reset",
            user_id,
            auth.change_password,
            user_id,
            body.new_password,
        )

    @router.get("/admin/invite-batches")
    def batches(_admin=Depends(require_admin)):
        return invitations.list_batches()

    @router.post("/admin/invite-batches")
    async def create_batch(body: InviteBatchBody, user=Depends(require_admin)):
        return await mutation(
            user,
            "invitation.create",
            body.request_id,
            invitations.create,
            user.user_id,
            body,
        )

    @router.post("/admin/invite-batches/{batch_id}/revoke", status_code=204)
    async def revoke(batch_id: str, user=Depends(require_admin)):
        await mutation(
            user,
            "invitation.revoke",
            batch_id,
            invitations.revoke,
            batch_id,
        )

    @router.put("/admin/budgets/{subject}", status_code=204)
    async def budget(
        subject: str,
        body: BudgetBody,
        user=Depends(require_admin),
    ):
        await mutation(
            user,
            "budget.update",
            subject,
            budgets.set_limit,
            subject,
            body,
        )

    @router.get("/admin/usage")
    def usage(_admin=Depends(require_admin)):
        return budgets.report()

    @router.get("/admin/usage/details")
    def detailed_usage(
        start_date: date,
        end_date: date,
        _admin=Depends(require_admin),
    ):
        try:
            return usage_details(store, start_date, end_date)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.get("/me/models")
    def member_models(user=Depends(require_user)):
        return catalog.member_catalog(user.user_id)

    @router.get("/me/usage")
    def member_usage(user=Depends(require_user)):
        result = budgets.summary(user.user_id)
        # Members see their own usage, not organization-wide consumption.
        organization = result.pop("organization")
        result["organization_blocked"] = organization["remaining"] == 0
        return result

    return router


def runtime_model_router(catalog, gateway):
    """Expose only capability-authenticated model traffic to runtimes."""
    router = APIRouter()

    def require_runtime(authorization: str = Header(default="")):
        prefix = "Bearer "
        try:
            return catalog.authenticate(
                authorization[len(prefix) :]
                if authorization.startswith(
                    prefix,
                )
                else "",
            )
        except PermissionError as exc:
            raise HTTPException(401, "Invalid model credential") from exc

    @router.get("/model-runtime/catalog")
    def runtime_catalog(identity=Depends(require_runtime)):
        result = catalog.member_catalog(identity["user_id"])
        catalog.observe(identity["runtime_id"], result["revision"])
        return result

    @router.post("/model-runtime/v1/chat/completions")
    async def completion(request: Request, identity=Depends(require_runtime)):
        data = bytearray()
        async with asyncio.timeout(30):
            async for chunk in request.stream():
                data.extend(chunk)
                if len(data) > 16 * 1024 * 1024:
                    raise HTTPException(413, "Model request too large")
        try:
            body = json.loads(data)
        except (ValueError, UnicodeError) as exc:
            raise HTTPException(422, "Invalid JSON") from exc
        return await gateway.call(identity, body)

    return router
