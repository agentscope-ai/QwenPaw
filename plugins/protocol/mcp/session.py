# -*- coding: utf-8 -*-
"""Keep native MCP result validation local to the received schema resources."""

import logging

from jsonschema import SchemaError, ValidationError, validate
from mcp import ClientSession as _ClientSession
from referencing import Registry
from referencing.exceptions import Unresolvable

logger = logging.getLogger(__name__)
_REGISTRY = Registry()


class ClientSession(_ClientSession):
    async def _validate_tool_result(self, name, result):
        # Preserve the SDK's cache refresh and missing structured-content rules.
        if name not in self._tool_output_schemas:
            await self.list_tools()
        if name not in self._tool_output_schemas:
            logger.warning(
                "Tool %s is not listed; no output schema available",
                name,
            )
            return
        schema = self._tool_output_schemas[name]
        if schema is None:
            return
        if result.structuredContent is None:
            raise RuntimeError(
                f"Tool {name} has an output schema but returned no structured content",
            )
        try:
            validate(result.structuredContent, schema, registry=_REGISTRY)
        except Unresolvable:
            raise RuntimeError(
                "Tool output schema reference is unavailable locally; "
                "the tool may have executed",
            ) from None
        except (SchemaError, ValidationError):
            raise RuntimeError(
                f"Invalid structured content or output schema for tool {name}",
            ) from None
