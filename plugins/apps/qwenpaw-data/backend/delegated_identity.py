# -*- coding: utf-8 -*-
"""Provision managed-sidecar identities from the authenticated PawApp scope.

Executed in the Data runtime interpreter so the host need not import sidecar
packages. Only the backend invokes this program; no browser can choose grants.
Existing disabled users or removed memberships are never repaired implicitly.
"""
from __future__ import annotations

import json
import re
import secrets
import sys
from pathlib import Path


def provision(home: Path, identity: str) -> dict:
    from sqlalchemy import insert, select
    from qwenpaw_data_auth import AuthConfig, bootstrap_local
    from qwenpaw_data_auth.database import (
        get_db,
        new_id,
        query_one,
        role_bindings,
        tenants,
        users,
        workspaces,
    )
    from qwenpaw_data_auth.authentication import resolve_current_authorization
    from qwenpaw_data_auth.password import hash_password

    if not re.fullmatch(r"pawapp_[0-9a-f]{64}", identity):
        raise ValueError("Invalid PawApp identity")
    cfg = bootstrap_local(
        AuthConfig(
            home=home,
            control_plane_dsn=str(home / "control_plane.db"),
        ),
    )
    tenant_id = "pawapp"
    # One private workspace for each host principal/workspace pair. Keep the
    # old hashed user ID so existing console session ownership stays stable.
    workspace_id = identity
    with get_db(cfg.control_plane_dsn) as conn:
        conn.execute("BEGIN IMMEDIATE")
        if not query_one(
            conn,
            select(tenants).where(tenants.c.id == tenant_id),
        ):
            conn.execute(
                insert(tenants).values(
                    id=tenant_id,
                    name="QwenPaw App",
                    neo4j_database="neo4j",
                ),
            )
        user = query_one(conn, select(users).where(users.c.id == identity))
        if user is None:
            if query_one(
                conn,
                select(workspaces).where(workspaces.c.id == workspace_id),
            ):
                raise ValueError(
                    "PawApp workspace already exists without its owner",
                )
            conn.execute(
                insert(workspaces).values(
                    id=workspace_id,
                    tenant_id=tenant_id,
                    name="PawApp workspace",
                    instance_status="pending",
                ),
            )
            conn.execute(
                insert(users).values(
                    id=identity,
                    username=identity,
                    tenant_id=tenant_id,
                    password_hash=hash_password(secrets.token_urlsafe(48)),
                    active_workspace_id=workspace_id,
                ),
            )
            conn.execute(
                insert(role_bindings).values(
                    id=new_id(),
                    user_id=identity,
                    role="ws_admin",
                    scope_type="workspace",
                    scope_id=workspace_id,
                ),
            )
        elif user["tenant_id"] != tenant_id:
            raise ValueError("PawApp identity belongs to another tenant")
        conn.commit()
    workspace_ids, role, _ = resolve_current_authorization(
        cfg.control_plane_dsn,
        identity,
        tenant_id,
        workspace_id,
    )
    return {
        "user_id": identity,
        "tenant_id": tenant_id,
        "workspace_id": workspace_id,
        "workspace_ids": workspace_ids,
        "role": role,
    }


if __name__ == "__main__":
    data = json.load(sys.stdin)
    provision(Path(data["home"]), data["identity"])
