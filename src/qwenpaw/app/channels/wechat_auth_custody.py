# -*- coding: utf-8 -*-
"""Known WeChat authentication collisions, without opening auth files."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from ...config.config import load_agent_config
from ...config.utils import load_config
from ...constant import WORKING_DIR
from ...plugins.ownership import RuntimeKey, RuntimeLease, RuntimeStopReceipt
from .management import ManagementError


def wechat_auth_scopes(
    config: Mapping[str, Any],
    *,
    working_dir: Path,
) -> tuple[str, ...]:
    """Hash physical paths and an explicit credential/domain pair only."""
    token = Path(
        config.get("bot_token_file") or working_dir / "wechat_bot_token",
    ).expanduser()
    values = [
        "path\0" + str(token.resolve()),
        "path\0"
        + str((token.parent / "wechat_context_tokens.json").resolve()),
    ]
    credential = config.get("bot_token")
    if credential:
        try:
            url = urlsplit(
                (
                    config.get("base_url") or "https://ilinkai.weixin.qq.com"
                ).strip(),
            )
            scheme, host = url.scheme.lower(), url.hostname
            if scheme not in {"http", "https"} or not host:
                raise ValueError
            if any(char.isspace() or ord(char) < 32 for char in host):
                raise ValueError
            port = url.port
            if port is None:
                port = 443 if scheme == "https" else 80
            host = host.lower()
            domain = f"{scheme}://{'[' + host + ']' if ':' in host else host}:{port}"
        except (AttributeError, TypeError, ValueError):
            raise ManagementError("MANAGEMENT_INVALID_REQUEST") from None
        values.append("credential\0" + domain + "\0" + credential)
    return tuple(sha256(value.encode()).hexdigest() for value in values)


@dataclass(frozen=True)
class _AuthOwner:
    owner: RuntimeLease
    workspace_id: str
    workspace_dir: Path


def reserve_wechat_auth(
    registry,
    *,
    owner: RuntimeLease,
    workspace_id: str,
    workspace_dir: Path,
    config: Mapping[str, Any],
) -> tuple[RuntimeLease, ...]:
    """Atomically reserve known claims; never stop a conflicting owner."""
    owners = registry.runtime_owners
    if owner not in owners.leases():
        raise ManagementError("IDENTITY_MISMATCH")
    if not any(
        config.get(key) for key in ("enabled", "bot_token", "bot_token_file")
    ):
        return ()
    scopes = set(wechat_auth_scopes(config, working_dir=WORKING_DIR))
    root = load_config()
    for agent_id, profile in root.agents.profiles.items():
        if agent_id == workspace_id:
            continue
        channels = load_agent_config(agent_id).channels
        other = channels.model_dump().get("wechat", {}) if channels else {}
        # A default disabled model is not evidence of account ownership.
        runtime_key = RuntimeKey(
            "channel",
            "wechat",
            str(Path(profile.workspace_dir).expanduser().resolve()),
        )
        if not any(
            other.get(key)
            for key in ("enabled", "bot_token", "bot_token_file")
        ) and not any(lease.key == runtime_key for lease in owners.leases()):
            continue
        if scopes.intersection(
            wechat_auth_scopes(other, working_dir=WORKING_DIR),
        ):
            raise ManagementError("ACCOUNT_IN_USE")
    keys = tuple(
        RuntimeKey("wechat_auth", scope, "host") for scope in sorted(scopes)
    )
    existing = []
    for lease in owners.leases():
        if lease.key not in keys:
            continue
        resource = owners.resource(lease)
        if not isinstance(resource, _AuthOwner) or resource.owner != owner:
            raise ManagementError("ACCOUNT_IN_USE")
        existing.append(lease)
    claims = []

    async def stop_owner():
        return await owners.stop(owner)

    try:
        for key in keys:
            if any(claim.key == key for claim in existing):
                continue
            claim = owners.reserve(
                owner.plugin_id,
                key,
                owner.code_root,
                instance_id=owner.instance_id,
                dependency_owner=owner,
            )
            claims.append(claim)
            owners.attach(
                claim,
                stop_owner,
                resource=_AuthOwner(
                    owner,
                    workspace_id,
                    Path(workspace_dir).expanduser().resolve(),
                ),
            )
    except BaseException:
        release_wechat_auth(
            registry,
            tuple(claims),
            RuntimeStopReceipt(True, "CLAIMS_NOT_STARTED"),
        )
        raise
    return tuple((*existing, *claims))


def release_wechat_auth(
    registry,
    claims: tuple[RuntimeLease, ...],
    receipt: RuntimeStopReceipt,
) -> None:
    """Only an owning resource's confirmed stop proof releases claims."""
    for claim in claims:
        registry.runtime_owners.release(claim, receipt)
