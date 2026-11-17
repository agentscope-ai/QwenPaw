# -*- coding: utf-8 -*-
"""Reserve known WeChat credentials for live channels and QR sessions."""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
from typing import Any
from urllib.parse import urlsplit

from ...plugins.ownership import RuntimeKey, RuntimeLease, RuntimeStopReceipt
from .management import ManagementError


def _credential_scope(config: Mapping[str, Any]) -> str | None:
    credential = config.get(f"bot_token")
    if not credential:
        return None
    try:
        url = urlsplit(
            (
                config.get(f"base_url") or f"https://ilinkai.weixin.qq.com"
            ).strip(),
        )
        scheme, host = url.scheme.lower(), url.hostname
        if scheme not in {f"http", f"https"} or not host:
            raise ValueError
        if any(char.isspace() or ord(char) < 32 for char in host):
            raise ValueError
        port = url.port
        if port is None:
            port = 443 if scheme == f"https" else 80
        host = host.lower()
        if f":" in host:
            host = f"[{host}]"
        domain = f"{scheme}://{host}:{port}"
    except (AttributeError, TypeError, ValueError):
        raise ManagementError(f"MANAGEMENT_INVALID_REQUEST") from None
    return sha256(f"credential\0{domain}\0{credential}".encode()).hexdigest()


def reserve_wechat_auth(
    registry,
    *,
    owner: RuntimeLease,
    config: Mapping[str, Any],
) -> tuple[RuntimeLease, ...]:
    """Check and claim a credential in one event-loop turn."""
    owners = registry.runtime_owners
    leases = owners.leases()
    if owner not in leases:
        raise ManagementError(f"IDENTITY_MISMATCH")
    scope = _credential_scope(config)
    if scope is None:
        return ()
    key = RuntimeKey(f"wechat_auth", scope, f"host")
    for lease in leases:
        if lease.key == key:
            if owners.resource(lease) == owner:
                return (lease,)
            raise ManagementError(f"ACCOUNT_IN_USE")

    async def stop_owner():
        return await owners.stop(owner)

    claim = owners.reserve(
        owner.plugin_id,
        key,
        owner.code_root,
        instance_id=owner.instance_id,
        dependency_owner=owner,
    )
    try:
        owners.attach(claim, stop_owner, resource=owner)
    except BaseException:
        owners.release(claim, RuntimeStopReceipt(True, f"CLAIMS_NOT_STARTED"))
        raise
    return (claim,)


def release_wechat_auth(
    registry,
    claims: tuple[RuntimeLease, ...],
    receipt: RuntimeStopReceipt,
) -> None:
    """Only an owning resource's confirmed stop proof releases claims."""
    for claim in claims:
        registry.runtime_owners.release(claim, receipt)
