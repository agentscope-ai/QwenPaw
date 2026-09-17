# -*- coding: utf-8 -*-
"""Process-local runtime projection of scoped tool credentials."""

from __future__ import annotations

import threading


class ToolCredentialRuntimeCache:
    """Keep decrypted tool fields isolated by Agent and tool."""

    def __init__(self) -> None:
        self._values: dict[tuple[str, str], dict[str, str]] = {}
        self._lock = threading.RLock()

    def get(self, agent_key: str, tool_name: str) -> dict[str, str]:
        with self._lock:
            return dict(self._values.get((agent_key, tool_name), {}))

    def replace(
        self,
        agent_key: str,
        tool_name: str,
        values: dict[str, str],
    ) -> None:
        with self._lock:
            key = (agent_key, tool_name)
            if values:
                self._values[key] = dict(values)
            else:
                self._values.pop(key, None)

    def set_field(
        self,
        agent_key: str,
        tool_name: str,
        field_name: str,
        value: str,
    ) -> None:
        with self._lock:
            values = dict(self._values.get((agent_key, tool_name), {}))
            values[field_name] = value
            self._values[(agent_key, tool_name)] = values

    def remove_field(
        self,
        agent_key: str,
        tool_name: str,
        field_name: str,
    ) -> None:
        with self._lock:
            key = (agent_key, tool_name)
            values = dict(self._values.get(key, {}))
            values.pop(field_name, None)
            if values:
                self._values[key] = values
            else:
                self._values.pop(key, None)

    def clear_agent(self, agent_key: str) -> None:
        with self._lock:
            for key in [key for key in self._values if key[0] == agent_key]:
                self._values.pop(key, None)


TOOL_CREDENTIAL_CACHE = ToolCredentialRuntimeCache()
