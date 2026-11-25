# -*- coding: utf-8 -*-
"""Trusted checkpoint scope and approval bridge; never exported to plugins."""

import asyncio
from dataclasses import asdict
import json
from pathlib import Path

from .apps import AppContext
from .checkpoints import (
    CheckpointEntry,
    CheckpointError,
    SnapshotResult,
    RestoreResult,
)
from .context import RequestContext
from ._identity import control_context
from .errors import SDKAccessError
from .tools import ToolContext
from ..checkpoints.models import CheckpointError as HostCheckpointError


async def bound(call):
    workspace_ops = call.workspace_ops
    root = await workspace_ops._directory_async()
    identity = call.identity
    if isinstance(call, AppContext) and call._services.selected_chat:
        workspace, chat = await call._services.selected_conversation()
        identity = RequestContext(
            call.workspace_id,
            chat.session_id,
            chat.channel,
            chat.user_id,
        )
    else:
        manager = call._plugin._loader.registry.get_workspace_manager()
        workspace = (
            await manager.get_agent(call.workspace_id) if manager else None
        )
    if not workspace or not all(
        (identity.session_id, identity.channel, identity.user_id),
    ):
        raise SDKAccessError(
            "Checkpoints require a bound conversation and authenticated identity",
        )
    live_root = await call.resources.run_sync(
        Path(workspace.workspace_dir).resolve,
    )
    if live_root != root:
        raise SDKAccessError("Workspace binding changed")
    from ..checkpoints.runtime import RUNTIME

    service = await RUNTIME.get_for_workspace_async(workspace)
    if (
        await workspace_ops._directory_async() != root
        or service.workspace_dir != root
    ):
        raise SDKAccessError("Workspace binding changed")
    return service, identity


def scope(identity):
    return dict(
        session_id=identity.session_id,
        user_id=identity.user_id,
        channel=identity.channel,
    )


async def timeline(
    call: ToolContext,
    limit: int,
) -> tuple[CheckpointEntry, ...]:
    if type(limit) is not int or not 1 <= limit <= 200:
        raise CheckpointError("Timeline limit must be between 1 and 200")
    try:
        service, identity = await bound(call)
        entries = await service.timeline(**scope(identity), limit=limit)
        return tuple(
            CheckpointEntry(
                item.commit,
                item.kind,
                item.name,
                item.timestamp_ms,
                item.subject,
                item.is_head,
            )
            for item in entries
        )
    except HostCheckpointError as exc:
        raise CheckpointError(str(exc)) from exc


async def snapshot(call: ToolContext, name: str) -> SnapshotResult:
    if not isinstance(name, str) or len(name) > 200:
        raise CheckpointError(
            "Snapshot name must be text of at most 200 characters",
        )
    try:
        service, identity = await bound(call)
        result = await service.make_snapshot_result(
            **scope(identity),
            kind="snap",
            name=name or None,
            message=name,
        )
        return SnapshotResult(result.commit, result.timestamp_ms)
    except (HostCheckpointError, ValueError) as exc:
        raise CheckpointError(str(exc)) from exc


async def approve_restore(call, identity, preview):
    from ..app.approvals import get_approval_service
    from ..app.approvals.models import ApprovalRequestSummary
    from ..app.approvals.service import ApprovalActor, ApprovalIdentityPolicy
    from ..security.tool_guard.approval import ApprovalDecision

    approvals = get_approval_service()
    extra = {"plugin_id": call.plugin_id}
    control = control_context.get()
    if control is not None and control[0] is call:
        # Only the host request may supply a channel instance and reply route.
        runtime = control[1]
        request = getattr(runtime, "request", None)
        channel = getattr(request, "channel_instance", None)
        if channel is None and identity.channel != "console":
            manager = getattr(runtime.workspace, "channel_manager", None)
            if manager is not None:
                channel = await manager.get_channel(identity.channel)
        extra.update(
            _channel_instance=channel,
            channel_meta=dict(getattr(request, "channel_meta", None) or {}),
        )
    pending = await approvals.create_pending_summary(
        session_id=identity.session_id,
        root_session_id=identity.session_id,
        owner_agent_id=identity.workspace_id,
        agent_id=identity.workspace_id,
        user_id=identity.user_id,
        channel=identity.channel,
        summary=ApprovalRequestSummary(
            "sdk_checkpoint_restore",
            "Restore checkpoint",
            result_summary=json.dumps(asdict(preview), ensure_ascii=False),
        ),
        extra=extra,
        timeout_seconds=120,
        identity_policy=ApprovalIdentityPolicy.EXACT_REQUESTER,
    )
    try:
        decision = await approvals.wait_for_approval(pending, 120)
    except asyncio.CancelledError:
        await approvals.cancel_request(
            pending.request_id,
            actor=ApprovalActor(
                identity.session_id,
                identity.session_id,
                identity.user_id,
                identity.channel,
                identity.workspace_id,
            ),
        )
        raise
    if decision != ApprovalDecision.APPROVED:
        raise CheckpointError("Restore was not confirmed: " + decision.value)


async def restore(
    call: ToolContext,
    target: str,
    *,
    dry_run: bool,
    include_memory: bool,
    include_files: bool,
    files: tuple[str, ...] | None,
) -> RestoreResult:
    if not isinstance(target, str) or not target.strip():
        raise CheckpointError("Restore target must be nonempty text")
    if any(
        type(flag) is not bool
        for flag in (dry_run, include_memory, include_files)
    ):
        raise CheckpointError("Restore flags must be boolean")
    if files is not None and (
        not isinstance(files, tuple)
        or not all(isinstance(path, str) and path for path in files)
    ):
        raise CheckpointError("files must be a tuple of nonempty paths")
    if files is not None and not include_files:
        raise CheckpointError("File selection requires include_files")
    if not dry_run and include_files and not files:
        raise CheckpointError("Select files before applying a file restore")
    control = control_context.get()
    if not dry_run and not (
        isinstance(call, AppContext)
        or (control is not None and control[0] is call)
    ):
        raise SDKAccessError(
            "Only app requests or control commands may request a confirmed restore",
        )
    try:
        service, identity = await bound(call)
        kwargs = {
            **scope(identity),
            "target": target,
            "include_memory": include_memory,
            "include_files": include_files,
            "selected_files": files,
        }
        preview = await service._restores._run_restore(**kwargs, dry_run=True)
        result = preview
        if not dry_run:
            await approve_restore(call, identity, preview)
            current_service, current_identity = await bound(call)
            if current_service is not service or current_identity != identity:
                raise SDKAccessError(
                    "Restore identity changed while awaiting confirmation",
                )
            result = await service._restores._run_restore(
                **{**kwargs, "target": preview.commit},
                expected_preview=preview,
            )
        return RestoreResult(
            result.commit,
            result.dry_run,
            result.restored_paths,
            result.deleted_paths,
            result.file_paths,
            result.include_memory,
            result.include_files,
        )
    except HostCheckpointError as exc:
        raise CheckpointError(str(exc)) from exc


def http_handler(action):
    from fastapi import HTTPException

    async def handle(call, request):
        try:
            if action == "timeline":
                return [
                    asdict(item)
                    for item in await call.checkpoints.timeline(
                        limit=int(request.query.get("limit", "20")),
                    )
                ]
            body = request.json()
            allowed = (
                {"name"}
                if action == "snapshot"
                else {"target", "include_memory", "include_files", "files"}
            )
            if not isinstance(body, dict) or set(body) - allowed:
                raise HTTPException(422, "Invalid checkpoint request fields")
            if action == "snapshot":
                return asdict(
                    await call.checkpoints.snapshot(name=body.get("name", "")),
                )
            files = body.get("files")
            if files is not None and not isinstance(files, list):
                raise HTTPException(422, "files must be an array")
            return asdict(
                await call.checkpoints.restore(
                    body.get("target", ""),
                    dry_run=action == "preview",
                    include_memory=body.get("include_memory", False),
                    include_files=body.get("include_files", False),
                    files=tuple(files) if files is not None else None,
                ),
            )
        except (CheckpointError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc

    return handle
