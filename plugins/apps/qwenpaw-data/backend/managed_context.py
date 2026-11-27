# -*- coding: utf-8 -*-
"""Start Context after its Auth and Host table dependencies are ready."""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace

from context_manager.api.app import create_service_app
from context_manager.settings import Settings
from qwenpaw_data.host.core.db.engine import init_db, reset_engine
from qwenpaw_data_auth import bootstrap_local
from qwenpaw_data_auth.auth_api import auth_temporary_access
from qwenpaw_data_auth.database import get_db, workspaces
from sqlalchemy import or_, update


def initialize_service_workspace(config):
    bootstrap_local(replace(config, mode="local"))
    # Existing server tools use the original graph configured by the operator.
    # Private PawApp workspaces get a separate registered graph route.
    with get_db(config.control_plane_dsn) as db:
        db.execute(
            update(workspaces)
            .where(
                workspaces.c.id == "default",
                workspaces.c.tenant_id == "default",
                or_(
                    workspaces.c.endpoint_ref.is_(None),
                    workspaces.c.endpoint_ref == "",
                ),
                or_(
                    workspaces.c.secret_ref.is_(None),
                    workspaces.c.secret_ref == "",
                ),
            )
            .values(
                endpoint_ref="env:NEO4J_URI",
                secret_ref="env:QWENPAW_DATA_LOCAL_GRAPH_CREDENTIALS",
            ),
        )
        db.commit()


def create_app():
    Settings.load()
    app = create_service_app()
    context_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def managed_lifespan(application):
        # Engine needs the allocated Context port. Prepare its shared tables
        # before Context validates them on first boot.
        await asyncio.to_thread(
            initialize_service_workspace,
            application.state.auth_config,
        )
        try:
            await init_db()
        finally:
            await reset_engine()
        async with context_lifespan(application) as state:
            yield state

    app.router.lifespan_context = managed_lifespan
    # Engine workers use this private service-authenticated endpoint.
    app.add_api_route(
        "/api/auth/temporary-access",
        auth_temporary_access,
        methods=["POST"],
    )
    return app
