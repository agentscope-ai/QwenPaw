# -*- coding: utf-8 -*-
"""Plugin-owned market providers and request/unload coordination."""

from contextlib import contextmanager
from dataclasses import dataclass
from threading import RLock
from typing import Iterator

from .providers.base import MarketInstallProvider, MarketProvider


class MarketProviderBusyError(RuntimeError):
    """A hub plugin cannot be unloaded while serving a request."""


@dataclass(frozen=True)
class MarketRegistration:
    owner: str
    provider: MarketProvider
    priority: int


class MarketRegistry:
    def __init__(self) -> None:
        self._entries: dict[str, MarketRegistration] = {}
        self._active: dict[str, int] = {}
        self._unloading: set[str] = set()
        self._loading: set[str] = set()
        self._lock = RLock()

    def register(
        self,
        owner: str,
        provider: MarketProvider,
        priority: int = 100,
    ) -> None:
        if not isinstance(provider, MarketProvider) or not provider.key:
            raise ValueError("Hub must implement MarketProvider with a key")
        if not isinstance(provider, MarketInstallProvider) or not all(
            callable(getattr(provider, method, None))
            for method in (
                "available",
                "search",
                "matches_url",
                "fetch_bundle",
            )
        ):
            raise ValueError("Hub must implement search and download methods")
        with self._lock:
            if provider.key in self._entries:
                raise ValueError(f"Duplicate hub key: {provider.key!r}")
            if owner in self._unloading:
                raise ValueError(f"Hub plugin {owner!r} is unloading")
            self._entries[provider.key] = MarketRegistration(
                owner,
                provider,
                priority,
            )

    def snapshot(self) -> dict[str, MarketProvider]:
        with self._lock:
            ordered = sorted(
                self._entries.items(),
                key=lambda r: r[1].priority,
            )
            return {
                key: entry.provider
                for key, entry in ordered
                if entry.owner not in self._unloading | self._loading
            }

    @contextmanager
    def use(self, key: str) -> Iterator[MarketProvider]:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None or entry.owner in self._unloading | self._loading:
                raise ValueError(f"Hub {key!r} is not loaded")
            owner = entry.owner
            self._active[owner] = self._active.get(owner, 0) + 1
        try:
            yield entry.provider
        finally:
            with self._lock:
                self._active[owner] -= 1
                if not self._active[owner]:
                    del self._active[owner]

    def begin_load(self, owner: str) -> None:
        """Keep partial registrations invisible until plugin load succeeds."""
        with self._lock:
            self._loading.add(owner)

    def finish_load(self, owner: str) -> None:
        with self._lock:
            self._loading.discard(owner)

    def begin_unload(self, owner: str) -> None:
        with self._lock:
            if self._active.get(owner, 0):
                raise MarketProviderBusyError(
                    f"Hub plugin {owner!r} is in use; please retry later",
                )
            self._unloading.add(owner)

    def cancel_unload(self, owner: str) -> None:
        with self._lock:
            self._unloading.discard(owner)

    def unregister_owner(self, owner: str) -> None:
        with self._lock:
            self.begin_unload(owner)
            self._entries = {
                key: entry
                for key, entry in self._entries.items()
                if entry.owner != owner
            }
            self._unloading.discard(owner)
            self._loading.discard(owner)


market_registry = MarketRegistry()
