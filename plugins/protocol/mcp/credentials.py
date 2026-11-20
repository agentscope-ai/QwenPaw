# -*- coding: utf-8 -*-
"""Resolve only declared source aliases through the SDK runtime provider."""

from qwenpaw.plugins.drivers import DriverCredential


class CredentialResolver:
    async def resolve(self, context):
        credentials = {}
        for alias in context.credentials.aliases:
            values = await context.credentials.resolve_runtime(alias)
            credentials[alias] = DriverCredential("runtime", 0, {}, values)
        if "default" not in credentials and len(credentials) == 1:
            credentials["default"] = next(iter(credentials.values()))
        return credentials
