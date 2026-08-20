# -*- coding: utf-8 -*-
"""API router for mail access control (whitelist / blacklist / pending).

Read endpoints aggregate ACL data across all agents that have mail access
control enabled; write endpoints route each entry to the owning agent's
workspace store.  An empty ``agent_id`` on whitelist/blacklist "add" entries
means "broadcast to all mail-enabled agents".
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ...utils.io_utils import run_sync_io

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mail-access-control", tags=["mail-access-control"])


# ── Store helpers ───────────────────────────────────────────────────────────


def _agent_mail_acl_enabled(agent_id: str) -> bool:
    """Return True if the agent has mailbox management
    with access control enabled."""
    from ...config.config import load_agent_config

    try:
        agent_config = load_agent_config(agent_id)
    except Exception:
        return False
    mail = getattr(agent_config, "mail", None)
    if mail is None or mail.push is None:
        return False
    return mail.push.mode != "off" and bool(mail.push.access_control_enabled)


def _iter_mail_agent_stores() -> Iterator[Tuple[str, Any]]:
    """Yield (agent_id, store) for all enabled agents with mail ACL enabled."""
    from ...config.utils import load_config
    from ..mail.mail_access_control import get_mail_access_control_store

    config = load_config()
    for agent_id, agent_ref in config.agents.profiles.items():
        if not getattr(agent_ref, "enabled", True):
            continue
        if not _agent_mail_acl_enabled(agent_id):
            continue
        yield agent_id, get_mail_access_control_store(
            Path(agent_ref.workspace_dir),
        )


def _get_store_for_agent(agent_id: str):
    """Get the MailAccessControlStore for a specific agent,
    or None if unknown."""
    from ...config.utils import load_config
    from ..mail.mail_access_control import get_mail_access_control_store

    config = load_config()
    agent_ref = config.agents.profiles.get(agent_id)
    if agent_ref is None:
        return None
    return get_mail_access_control_store(Path(agent_ref.workspace_dir))


def _require_valid_addresses(entries: List["MailACLEntry"]) -> None:
    """Reject malformed addresses up front (400) before any store write."""
    from ..mail.mail_access_control import validate_acl_address

    for entry in entries:
        try:
            validate_acl_address(entry.address)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


# ── Request / Response schemas ──────────────────────────────────────────────


class MailACLEntry(BaseModel):
    agent_id: str
    address: str
    remark: Optional[str] = None
    display_name: Optional[str] = None


class MailACLActionBody(BaseModel):
    entries: List[MailACLEntry]


class MailACLRemarkBody(BaseModel):
    agent_id: str
    address: str
    remark: str


def _group_action_entries(
    entries: List[MailACLEntry],
    *,
    broadcast: bool = False,
) -> List[Tuple[str, Any, List[MailACLEntry]]]:
    """Resolve stores once and group a request into workspace transactions."""
    grouped: Dict[Tuple[str, int], Tuple[str, Any, List[MailACLEntry]]] = {}
    direct_stores: Dict[str, Any] = {}
    broadcast_targets: Optional[List[Tuple[str, Any]]] = None

    for entry in entries:
        if broadcast and entry.agent_id == "":
            if broadcast_targets is None:
                broadcast_targets = list(_iter_mail_agent_stores())
            targets = broadcast_targets
        else:
            if entry.agent_id not in direct_stores:
                direct_stores[entry.agent_id] = _get_store_for_agent(
                    entry.agent_id,
                )
            store = direct_stores[entry.agent_id]
            targets = [] if store is None else [(entry.agent_id, store)]

        for agent_id, store in targets:
            key = (agent_id, id(store))
            if key not in grouped:
                grouped[key] = (agent_id, store, [])
            grouped[key][2].append(entry)
    return list(grouped.values())


def _list_mail_agents_sync() -> Dict[str, List[str]]:
    return {"agents": [agent_id for agent_id, _ in _iter_mail_agent_stores()]}


def _get_all_acls_sync() -> Dict[str, Dict[str, Any]]:
    return {
        agent_id: store.get_acl(agent_id)
        for agent_id, store in _iter_mail_agent_stores()
    }


def _get_all_pending_sync() -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for agent_id, store in _iter_mail_agent_stores():
        result.extend(store.get_acl(agent_id).get("pending", []))
    result.sort(key=lambda item: item.get("timestamp", 0), reverse=True)
    return result


def _get_pending_count_sync() -> Dict[str, int]:
    return {
        "count": sum(
            len(store.get_acl(agent_id).get("pending", []))
            for agent_id, store in _iter_mail_agent_stores()
        ),
    }


def _approve_pending_sync(
    entries: List[MailACLEntry],
) -> List[Tuple[MailACLEntry, Optional[Dict[str, Any]]]]:
    results: List[Tuple[MailACLEntry, Optional[Dict[str, Any]]]] = []
    for agent_id, store, grouped_entries in _group_action_entries(entries):
        snapshots = store.approve_many(
            agent_id,
            [(entry.address, entry.remark or "") for entry in grouped_entries],
        )
        results.extend(zip(grouped_entries, snapshots))
    return results


def _deny_pending_sync(entries: List[MailACLEntry]) -> List[MailACLEntry]:
    results: List[MailACLEntry] = []
    for agent_id, store, grouped_entries in _group_action_entries(entries):
        store.deny_many(
            agent_id,
            [(entry.address, entry.remark or "") for entry in grouped_entries],
        )
        results.extend(grouped_entries)
    return results


def _dismiss_pending_sync(entries: List[MailACLEntry]) -> List[MailACLEntry]:
    results: List[MailACLEntry] = []
    for agent_id, store, grouped_entries in _group_action_entries(entries):
        store.dismiss_many(
            agent_id,
            [entry.address for entry in grouped_entries],
        )
        results.extend(grouped_entries)
    return results


def _mutate_list_sync(
    entries: List[MailACLEntry],
    action: str,
    *,
    broadcast: bool = False,
) -> int:
    count = 0
    for agent_id, store, grouped_entries in _group_action_entries(
        entries,
        broadcast=broadcast,
    ):
        if action == "whitelist_add":
            count += store.add_many_to_whitelist(
                agent_id,
                [
                    (
                        entry.address,
                        entry.remark or "",
                        entry.display_name or "",
                    )
                    for entry in grouped_entries
                ],
            )
        elif action == "whitelist_remove":
            count += store.remove_many_from_whitelist(
                agent_id,
                [entry.address for entry in grouped_entries],
            )
        elif action == "blacklist_add":
            count += store.add_many_to_blacklist(
                agent_id,
                [
                    (
                        entry.address,
                        entry.remark or "",
                        entry.display_name or "",
                    )
                    for entry in grouped_entries
                ],
            )
        elif action == "blacklist_remove":
            count += store.remove_many_from_blacklist(
                agent_id,
                [entry.address for entry in grouped_entries],
            )
    return count


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.get(
    "/agents",
    summary="List all agents with mail access control enabled",
)
async def list_mail_agents():
    """Return agent ids that have mailbox access control enabled."""
    return await run_sync_io(_list_mail_agents_sync)


@router.get(
    "",
    summary="Get all mail access control lists",
)
async def get_all_acls():
    """Return mail ACLs aggregated across all mail-enabled agents."""
    return await run_sync_io(_get_all_acls_sync)


@router.get(
    "/pending/all",
    summary="Get all pending approval entries",
)
async def get_all_pending():
    """Return pending entries aggregated across all mail-enabled agents."""
    return await run_sync_io(_get_all_pending_sync)


@router.get(
    "/pending/count",
    summary="Get pending approval count",
)
async def get_pending_count():
    """Return the total pending count across all mail-enabled agents."""
    return await run_sync_io(_get_pending_count_sync)


@router.post(
    "/pending/approve",
    summary="Approve one or more pending senders (add to whitelist)",
)
async def approve_pending(body: MailACLActionBody, request: Request):
    from ..inbox_store import mark_read_by_acl_sender

    _require_valid_addresses(body.entries)
    # The store atomically removes the user-visible pending row and moves all
    # of its message UIDs into a separate durable replay outbox.
    approved = await run_sync_io(_approve_pending_sync, body.entries)
    for entry, pending_info in approved:
        # Mark the corresponding inbox "pending" notification as read so
        # the unread badge decreases after approval.
        await mark_read_by_acl_sender(entry.agent_id, entry.address)
        try:
            await _trigger_wake_after_approve(request, entry, pending_info)
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "failed to trigger mail auto-handling after approving "
                "sender %s for agent %s",
                entry.address,
                entry.agent_id,
                exc_info=True,
            )
    return {"status": "ok", "count": len(approved)}


async def _trigger_wake_after_approve(
    request: Request,
    entry: MailACLEntry,
    pending_info: Optional[Dict[str, Any]],
) -> None:
    """Ask the agent's monitor to drain its durable approval outbox."""

    if not pending_info:
        return None
    if request is None:
        return None
    manager = getattr(request.app.state, "multi_agent_manager", None)
    if manager is None:
        return None
    workspace = await manager.get_agent(entry.agent_id)
    if workspace is None:
        return None
    monitor = getattr(workspace, "mail_monitor", None)
    if monitor is None:
        return None
    monitor.schedule_approved_replay()
    return None


@router.post(
    "/pending/deny",
    summary="Deny one or more pending senders (add to blacklist)",
)
async def deny_pending(body: MailACLActionBody):
    from ..inbox_store import mark_read_by_acl_sender

    _require_valid_addresses(body.entries)
    denied = await run_sync_io(_deny_pending_sync, body.entries)
    for entry in denied:
        await mark_read_by_acl_sender(entry.agent_id, entry.address)
    return {"status": "ok", "count": len(denied)}


@router.post(
    "/pending/dismiss",
    summary="Dismiss one or more pending senders (remove w/o action)",
)
async def dismiss_pending(body: MailACLActionBody):
    from ..inbox_store import mark_read_by_acl_sender

    dismissed = await run_sync_io(_dismiss_pending_sync, body.entries)
    for entry in dismissed:
        await mark_read_by_acl_sender(entry.agent_id, entry.address)
    return {"status": "ok", "count": len(dismissed)}


@router.post(
    "/pending/remark",
    summary="Update remark on a pending entry",
)
async def update_pending_remark(body: MailACLRemarkBody):
    def _update() -> bool:
        store = _get_store_for_agent(body.agent_id)
        return store is not None and store.update_pending_remark(
            body.agent_id,
            body.address,
            body.remark,
        )

    found = await run_sync_io(
        _update,
    )
    if not found:
        raise HTTPException(
            status_code=404,
            detail="Pending entry not found",
        )
    return {"status": "ok"}


# ── Whitelist / Blacklist endpoints ─────────────────────────────────────────


@router.post(
    "/whitelist/add",
    summary="Add one or more addresses to whitelist",
)
async def add_to_whitelist(body: MailACLActionBody):
    _require_valid_addresses(body.entries)
    count = await run_sync_io(
        _mutate_list_sync,
        body.entries,
        "whitelist_add",
        broadcast=True,
    )
    return {"status": "ok", "count": count}


@router.post(
    "/whitelist/remove",
    summary="Remove one or more addresses from whitelist",
)
async def remove_from_whitelist(body: MailACLActionBody):
    count = await run_sync_io(
        _mutate_list_sync,
        body.entries,
        "whitelist_remove",
    )
    return {"status": "ok", "count": count}


@router.post(
    "/blacklist/add",
    summary="Add one or more addresses to blacklist",
)
async def add_to_blacklist(body: MailACLActionBody):
    _require_valid_addresses(body.entries)
    count = await run_sync_io(
        _mutate_list_sync,
        body.entries,
        "blacklist_add",
        broadcast=True,
    )
    return {"status": "ok", "count": count}


@router.post(
    "/blacklist/remove",
    summary="Remove one or more addresses from blacklist",
)
async def remove_from_blacklist(body: MailACLActionBody):
    count = await run_sync_io(
        _mutate_list_sync,
        body.entries,
        "blacklist_remove",
    )
    return {"status": "ok", "count": count}


@router.post(
    "/remark",
    summary="Update remark for an address in whitelist or blacklist",
)
async def update_remark(body: MailACLRemarkBody):
    def _update() -> bool:
        store = _get_store_for_agent(body.agent_id)
        return store is not None and store.update_remark(
            body.agent_id,
            body.address,
            body.remark,
        )

    found = await run_sync_io(
        _update,
    )
    if not found:
        raise HTTPException(
            status_code=404,
            detail="Address not found in any list",
        )
    return {"status": "ok"}
