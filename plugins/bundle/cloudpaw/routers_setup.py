# -*- coding: utf-8 -*-
"""API router builders for CloudPaw plugin.

Returns FastAPI APIRouter instances that the plugin registers via
``api.register_http_router()`` — no manual app mounting needed.
"""

import logging

logger = logging.getLogger("qwenpaw").getChild(
    __name__.replace("plugin_cloudpaw.", ""),
)


def build_plugin_routers():
    """Build and return all plugin API routers.

    The caller should register each router via
    ``api.register_http_router(router, prefix=...)``.
    """
    from .routers.a2a import router as a2a_router
    from .routers.interaction import router as interaction_router
    from .routers.prd import router as prd_router

    return [
        (interaction_router, "/interaction"),
        (prd_router, "/prd"),
        (a2a_router, "/a2a"),
    ]
