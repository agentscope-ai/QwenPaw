# -*- coding: utf-8 -*-
"""Keep native MCP result validation local to the received schema resources."""

from jsonschema import SchemaError, ValidationError, validate
from mcp import ClientSession as _ClientSession
from referencing import Registry
from referencing.exceptions import Unresolvable

_REGISTRY = Registry()


class ClientSession(_ClientSession):
    def __init__(self, read_stream, write_stream, *, logger):
        super().__init__(read_stream, write_stream)
        self._logger = logger

    async def _validate_tool_result(self, name, result):
        # Preserve the SDK's cache refresh and missing structured-content rules.
        if name not in self._tool_output_schemas:
            await self.list_tools()
        if name not in self._tool_output_schemas:
            self._logger.warning(
                "Tool %r is not listed; no output schema available",
                name,
            )
            return
        schema = self._tool_output_schemas[name]
        if schema is None:
            return
        if result.structuredContent is None:
            self._logger.warning(
                "Tool %r returned no structured content for its output schema",
                name,
            )
            raise RuntimeError(
                f"Tool {name} has an output schema but returned no structured content",
            )
        try:
            validate(result.structuredContent, schema, registry=_REGISTRY)
        except Unresolvable:
            self._logger.warning(
                "Tool %r output schema reference is unavailable locally",
                name,
            )
            raise RuntimeError(
                "Tool output schema reference is unavailable locally; "
                "the tool may have executed",
            ) from None
        except (SchemaError, ValidationError) as exc:
            self._logger.warning(
                "Tool %r output validation failed: %s",
                name,
                type(exc).__name__,
            )
            raise RuntimeError(
                f"Invalid structured content or output schema for tool {name}",
            ) from None
