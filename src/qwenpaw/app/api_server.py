# -*- coding: utf-8 -*-
"""Publish the HTTP endpoint from the process that actually serves it."""

import uvicorn

from ..config.utils import cache_last_api, write_last_api
from ..utils.http import probe_host_for_bind_host
from .base_path import get_runtime_base_path


class ApiServer(uvicorn.Server):
    async def startup(self, sockets=None) -> None:
        # Uvicorn has already imported the app, which fixes the mount after
        # loading persisted env vars. A lifespan hook alone runs before bind.
        base_path = get_runtime_base_path()
        host = probe_host_for_bind_host(self.config.host)
        port = sockets[0].getsockname()[1] if sockets else self.config.port
        if port:
            cache_last_api(host, port, base_path)

        await super().startup(sockets=sockets)
        if not self.started or self.should_exit:
            return

        if not port:
            # With port 0 and no pre-bound socket, use one actual listener;
            # separate address families may receive different ports.
            sock = self.servers[0].sockets[0]
            address = sock.getsockname()
            host, port = probe_host_for_bind_host(address[0]), address[1]
        write_last_api(host, port, base_path)
