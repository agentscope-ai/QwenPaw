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
from ...config.utils import config_publication_revision, load_config
from ...constant import WORKING_DIR
from ...utils.io_utils import run_sync_io
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


def _read_wechat_auth_evidence(config, workspace_id, working_dir):
    """Read detached path/config evidence without touching runtime owners."""
    if not any(
        config.get(key) for key in ("enabled", "bot_token", "bot_token_file")
    ):
        return frozenset(), ()
    scopes = frozenset(wechat_auth_scopes(config, working_dir=working_dir))
    others = []
    root = load_config()
    for agent_id, profile in root.agents.profiles.items():
        if agent_id == workspace_id:
            continue
        channels = load_agent_config(agent_id).channels
        other = channels.model_dump().get("wechat", {}) if channels else {}
        runtime_key = RuntimeKey(
            "channel",
            "wechat",
            str(Path(profile.workspace_dir).expanduser().resolve()),
        )
        configured = any(
            other.get(key)
            for key in ("enabled", "bot_token", "bot_token_file")
        )
        others.append(
            (
                runtime_key,
                configured,
                frozenset(wechat_auth_scopes(other, working_dir=WORKING_DIR)),
            ),
        )
    return scopes, tuple(others)


def _reserve_wechat_auth_evidence(
    registry,
    *,
    owner,
    workspace_id,
    workspace_dir,
    evidence,
):
    """Check fresh loop-owned custody and reserve the complete claim set."""
    owners = registry.runtime_owners
    leases = owners.leases()
    if owner not in leases:
        raise ManagementError("IDENTITY_MISMATCH")
    scopes, others = evidence
    for runtime_key, configured, other_scopes in others:
        if (
            configured or any(lease.key == runtime_key for lease in leases)
        ) and (scopes.intersection(other_scopes)):
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
                    workspace_dir,
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


def reserve_wechat_auth(
    registry,
    *,
    owner,
    workspace_id,
    workspace_dir,
    config,
):
    """Synchronous compatibility for runtime and CLI callers."""
    if owner not in registry.runtime_owners.leases():
        raise ManagementError("IDENTITY_MISMATCH")
    evidence = _read_wechat_auth_evidence(config, workspace_id, WORKING_DIR)
    return _reserve_wechat_auth_evidence(
        registry,
        owner=owner,
        workspace_id=workspace_id,
        workspace_dir=Path(workspace_dir).expanduser().resolve(),
        evidence=evidence,
    )


async def reserve_wechat_auth_async(
    registry,
    *,
    owner,
    workspace_id,
    workspace_dir,
    config,
    working_dir,
    authorize=None,
):
    """Scan files off-loop, retrying if relevant custody changed meanwhile."""
    owners = registry.runtime_owners

    def ownership():
        return tuple(
            (lease, id(owners.resource(lease)))
            for lease in owners.leases()
            if lease == owner
            or lease.key.kind == "wechat_auth"
            or (lease.key.kind == "channel" and lease.key.name == "wechat")
        )

    while True:
        if owner not in owners.leases():
            raise ManagementError("IDENTITY_MISMATCH")
        snapshot = ownership()
        publication = config_publication_revision()
        evidence = await run_sync_io(
            _read_wechat_auth_evidence,
            dict(config),
            workspace_id,
            working_dir,
        )
        if (
            snapshot != ownership()
            or publication != config_publication_revision()
        ):
            continue
        if authorize is not None:
            authorize()
        return _reserve_wechat_auth_evidence(
            registry,
            owner=owner,
            workspace_id=workspace_id,
            workspace_dir=workspace_dir,
            evidence=evidence,
        )


def release_wechat_auth(
    registry,
    claims: tuple[RuntimeLease, ...],
    receipt: RuntimeStopReceipt,
) -> None:
    """Only an owning resource's confirmed stop proof releases claims."""
    for claim in claims:
        registry.runtime_owners.release(claim, receipt)
