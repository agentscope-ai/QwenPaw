# -*- coding: utf-8 -*-
from __future__ import annotations

import threading


class ModelCapabilityCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: dict[str, dict[str, bool]] = {}

    def learn(self, model_key: str, capability: str, value: bool) -> None:
        with self._lock:
            self._data.setdefault(model_key, {})[capability] = value

    def get(
        self,
        model_key: str,
        capability: str,
        default: bool = False,
    ) -> bool:
        with self._lock:
            return self._data.get(model_key, {}).get(capability, default)

    def clear(self, model_key: str | None = None) -> None:
        with self._lock:
            if model_key:
                self._data.pop(model_key, None)
            else:
                self._data.clear()


_instance_lock = threading.Lock()
_instance: ModelCapabilityCache | None = None


def get_capability_cache() -> ModelCapabilityCache:
    global _instance
    if _instance is not None:
        return _instance
    with _instance_lock:
        if _instance is None:
            _instance = ModelCapabilityCache()
    return _instance
