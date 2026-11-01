# -*- coding: utf-8 -*-
"""Structured logging with host-owned plugin and invocation identity."""

# Host adapters access private ownership state behind the public SDK.
# pylint: disable=protected-access

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Mapping

from .events import JSONValue
from .errors import SDKError


class PluginLogger:
    """
    Obtained from a plugin or callback context; identity is not caller input.
    """

    def __init__(self, context):
        self._context = context

    def _log(self, level, message, fields, *, exception=False):
        context = self._context
        plugin = getattr(context, "_plugin", None) or context
        plugin._storage_guard()
        if not isinstance(message, str):
            raise SDKError("Log message must be a string")
        from ._models import json_mapping

        values = json_mapping({} if fields is None else fields)
        identity = {
            "plugin_id": plugin.plugin_id,
            "generation": plugin.generation,
        }
        if context is not plugin:
            identity.update(
                workspace_id=context.workspace_id,
                session_id=context.session_id,
                invocation_id=context.resources.owner.instance_id,
            )
            for name in ("app_id", "user_id", "channel", "channel_name"):
                if hasattr(context, name):
                    identity[name] = getattr(context, name)
        logging.getLogger(f"qwenpaw.plugins.author.{plugin.plugin_id}").log(
            level,
            message,
            exc_info=exception,
            extra={"sdk_context": identity, "sdk_fields": deepcopy(values)},
        )

    def debug(
        self,
        message: str,
        *,
        fields: Mapping[str, JSONValue] | None = None,
    ) -> None:
        self._log(logging.DEBUG, message, fields)

    def info(
        self,
        message: str,
        *,
        fields: Mapping[str, JSONValue] | None = None,
    ) -> None:
        self._log(logging.INFO, message, fields)

    def warning(
        self,
        message: str,
        *,
        fields: Mapping[str, JSONValue] | None = None,
    ) -> None:
        self._log(logging.WARNING, message, fields)

    def error(
        self,
        message: str,
        *,
        fields: Mapping[str, JSONValue] | None = None,
    ) -> None:
        self._log(logging.ERROR, message, fields)

    def exception(
        self,
        message: str,
        *,
        fields: Mapping[str, JSONValue] | None = None,
    ) -> None:
        self._log(logging.ERROR, message, fields, exception=True)
