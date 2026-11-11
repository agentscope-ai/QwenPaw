# -*- coding: utf-8 -*-
"""Register the MCP protocol and its authenticated management app."""

from qwenpaw.plugins.drivers import DriverProtocolSpec

from .connection import MCPConnection, validate
from .oauth import OAuthManagement


class Plugin:
    def register(self, context):
        context.register_driver_protocol(
            DriverProtocolSpec(
                protocol="mcp",
                validate=validate,
                create=MCPConnection,
            ),
        )
        OAuthManagement().app().register(context)


plugin = Plugin()
