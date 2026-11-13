# -*- coding: utf-8 -*-
"""Memory backend ownership, selection and construction reservations.

The registry stores factories and live owners without importing backend
implementations. Public memory contracts initialize built-in backends through
the existing agents.memory package.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from threading import RLock
from typing import TYPE_CHECKING, Any
from weakref import WeakValueDictionary

if TYPE_CHECKING:
    from ..agents.memory.base_memory_manager import (
        BaseMemoryManager,
        MemoryBackendContext,
    )


@dataclass(frozen=True)
class MemoryBackendRegistration:
    """One core or plugin-owned memory backend registration."""

    plugin_id: str
    backend_id: str
    factory: type[BaseMemoryManager]
    label: str
    config_schema: type[Any] | None
    metadata: Mapping[str, Any]


class _MemoryBackendSelectionLease:
    """Keep a selected plugin backend registered until reload handoff."""

    def __init__(
        self,
        registry: "MemoryBackendRegistry",
        registration: MemoryBackendRegistration,
        agent_id: str,
    ) -> None:
        self._registry = registry
        self.registration = registration
        self.agent_id = agent_id
        self._released = False

    def release(self) -> None:
        """Release this lease exactly once."""
        if self._released:
            return
        self._registry._release_selection(  # pylint: disable=protected-access
            self.registration.plugin_id,
            self.agent_id,
        )
        self._released = True


class MemoryBackendRegistry:  # pylint: disable=protected-access
    """Owner-aware registry used by core and memory plugins."""

    def __init__(self) -> None:
        self._registrations: dict[str, MemoryBackendRegistration] = {}
        self._instances: WeakValueDictionary[
            int,
            BaseMemoryManager,
        ] = WeakValueDictionary()
        self._unloading_owners: set[str] = set()
        self._constructing_agents: dict[str, dict[str, int]] = {}
        self._selecting_agents: dict[str, dict[str, int]] = {}
        # Construction runs in worker threads, while unload and close run on
        # the event loop. Short locked reservations close the unload race
        # without holding this lock while arbitrary plugin code executes.
        self._lock = RLock()

    def track_instance(self, instance: BaseMemoryManager) -> None:
        """Keep plugin ownership while a manager starts, runs, or drains."""
        with self._lock:
            matching_owners = {
                registration.plugin_id
                for registration in self._registrations.values()
                if isinstance(instance, registration.factory)
            }
            if len(matching_owners) == 1:
                instance._memory_backend_owner = matching_owners.pop()
            self._instances[id(instance)] = instance

    def release_instance(self, instance: BaseMemoryManager) -> None:
        """Release ownership only after the manager has closed cleanly."""
        with self._lock:
            self._instances.pop(id(instance), None)

    def active_agent_ids(self, plugin_id: str) -> list[str]:
        """Return agents with live instances from this plugin's factories."""
        with self._lock:
            if not any(
                registration.plugin_id == plugin_id
                for registration in self._registrations.values()
            ):
                return []
            instances = list(self._instances.values())
            constructing = set(self._constructing_agents.get(plugin_id, {}))
            selecting = set(self._selecting_agents.get(plugin_id, {}))
        return sorted(
            constructing
            | selecting
            | {
                instance.agent_id
                for instance in instances
                if getattr(instance, "_memory_backend_owner", None)
                == plugin_id
            },
        )

    def begin_owner_unload(
        self,
        plugin_id: str,
        selected_agent_ids: tuple[str, ...] = (),
    ) -> list[str]:
        """Reserve an owner unload and return agents that prevent it.

        Once reserved, new construction from this owner is rejected until its
        registrations are removed. The shared lock closes the gap between an
        unload check and a concurrent backend constructor.
        """
        with self._lock:
            if not any(
                registration.plugin_id == plugin_id
                for registration in self._registrations.values()
            ):
                return []
            instances = list(self._instances.values())
            in_use = set(selected_agent_ids)
            in_use.update(self._constructing_agents.get(plugin_id, {}))
            in_use.update(self._selecting_agents.get(plugin_id, {}))
            in_use.update(
                instance.agent_id
                for instance in instances
                if getattr(instance, "_memory_backend_owner", None)
                == plugin_id
            )
            if in_use:
                return sorted(in_use)
            self._unloading_owners.add(plugin_id)
            return []

    def cancel_owner_unload(self, plugin_id: str) -> None:
        """Allow construction again after an aborted unload."""
        with self._lock:
            self._unloading_owners.discard(plugin_id)

    def reserve_selection(
        self,
        backend_id: str,
        agent_id: str,
    ) -> _MemoryBackendSelectionLease:
        """Reserve a registered backend through durable reload handoff."""
        normalized = self._normalize(backend_id)
        with self._lock:
            registration = self._registrations.get(normalized)
            if (
                registration is None
                or registration.plugin_id in self._unloading_owners
            ):
                raise MemoryBackendUnavailableError(normalized)
            selecting = self._selecting_agents.setdefault(
                registration.plugin_id,
                {},
            )
            selecting[agent_id] = selecting.get(agent_id, 0) + 1
        return _MemoryBackendSelectionLease(self, registration, agent_id)

    def _release_selection(self, plugin_id: str, agent_id: str) -> None:
        """Release one selection reservation."""
        with self._lock:
            selecting = self._selecting_agents.get(plugin_id, {})
            remaining = selecting.get(agent_id, 0) - 1
            if remaining > 0:
                selecting[agent_id] = remaining
            else:
                selecting.pop(agent_id, None)
            if not selecting:
                self._selecting_agents.pop(plugin_id, None)

    def create(
        self,
        backend_id: str,
        context: MemoryBackendContext,
    ) -> BaseMemoryManager:
        """Resolve and construct a backend atomically with owner unload."""
        normalized = self._normalize(backend_id)
        with self._lock:
            registration = self._registrations.get(normalized)
            if (
                registration is None
                or registration.plugin_id in self._unloading_owners
            ):
                raise MemoryBackendUnavailableError(normalized)
            plugin_id = registration.plugin_id
            factory = registration.factory
            constructing = self._constructing_agents.setdefault(plugin_id, {})
            constructing[context.agent_id] = (
                constructing.get(context.agent_id, 0) + 1
            )
        try:
            instance = factory(context=context)
            instance._memory_backend_owner = plugin_id
            return instance
        finally:
            with self._lock:
                constructing = self._constructing_agents.get(plugin_id, {})
                remaining = constructing.get(context.agent_id, 0) - 1
                if remaining > 0:
                    constructing[context.agent_id] = remaining
                else:
                    constructing.pop(context.agent_id, None)
                if not constructing:
                    self._constructing_agents.pop(plugin_id, None)

    @staticmethod
    def _normalize(backend_id: str) -> str:
        normalized = backend_id.strip().lower()
        if not normalized:
            raise ValueError("Memory backend id must not be empty")
        return normalized

    def register(
        self,
        backend_id: str,
        *,
        owner: str = "core",
        label: str | None = None,
        config_schema: type[Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> Callable[[type[BaseMemoryManager]], type[BaseMemoryManager]]:
        """Register a class decorator, retained for core backends."""

        def decorator(
            factory: type[BaseMemoryManager],
        ) -> type[BaseMemoryManager]:
            self.register_backend(
                plugin_id=owner,
                backend_id=backend_id,
                factory=factory,
                label=label or backend_id,
                config_schema=config_schema,
                metadata=metadata,
            )
            return factory

        return decorator

    def register_backend(
        self,
        *,
        plugin_id: str,
        backend_id: str,
        factory: type[BaseMemoryManager],
        label: str,
        config_schema: type[Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> MemoryBackendRegistration:
        normalized = self._normalize(backend_id)
        registration = MemoryBackendRegistration(
            plugin_id=plugin_id,
            backend_id=normalized,
            factory=factory,
            label=label or normalized,
            config_schema=config_schema,
            metadata=dict(metadata or {}),
        )
        with self._lock:
            if plugin_id in self._unloading_owners:
                raise RuntimeError(f"Plugin '{plugin_id}' is being unloaded")
            existing = self._registrations.get(normalized)
            if existing is not None:
                if (
                    existing.plugin_id == plugin_id
                    and existing.factory is factory
                ):
                    return existing
                raise ValueError(
                    f"Memory backend '{normalized}' is already registered by "
                    f"'{existing.plugin_id}'",
                )
            self._registrations[normalized] = registration
        return registration

    def get(self, backend_id: str) -> type[BaseMemoryManager] | None:
        try:
            normalized = self._normalize(backend_id)
        except (AttributeError, ValueError):
            return None
        with self._lock:
            registration = self._registrations.get(normalized)
            if (
                registration is None
                or registration.plugin_id in self._unloading_owners
            ):
                return None
            return registration.factory

    def get_registration(
        self,
        backend_id: str,
    ) -> MemoryBackendRegistration | None:
        try:
            normalized = self._normalize(backend_id)
        except (AttributeError, ValueError):
            return None
        with self._lock:
            registration = self._registrations.get(normalized)
            if (
                registration is not None
                and registration.plugin_id in self._unloading_owners
            ):
                return None
            return registration

    def list_registered(self) -> list[str]:
        with self._lock:
            return [
                backend_id
                for backend_id, registration in self._registrations.items()
                if registration.plugin_id not in self._unloading_owners
            ]

    def describe(self) -> list[dict[str, Any]]:
        with self._lock:
            registrations = list(self._registrations.values())
            unloading = set(self._unloading_owners)
        return [
            {
                "id": item.backend_id,
                "label": item.label,
                "source": (
                    "core"
                    if item.plugin_id == "core"
                    else f"plugin:{item.plugin_id}"
                ),
                "available": True,
                "metadata": dict(item.metadata),
            }
            for item in registrations
            if item.plugin_id not in unloading
        ]

    def unregister(self, backend_id: str, *, expected_factory: type) -> bool:
        """Revoke one SDK contribution, preserving owner-use reservations."""
        normalized = self._normalize(backend_id)
        with self._lock:
            registration = self._registrations.get(normalized)
            if (
                registration is None
                or registration.factory is not expected_factory
            ):
                return False
            owner = registration.plugin_id
            agents = self.active_agent_ids(owner)
            if agents:
                raise RuntimeError(
                    f"Memory backend is in use by agents: {', '.join(agents)}",
                )
            del self._registrations[normalized]
            return True

    def unregister_owner(self, plugin_id: str) -> list[str]:
        with self._lock:
            removed = [
                backend_id
                for backend_id, registration in self._registrations.items()
                if registration.plugin_id == plugin_id
            ]
            for backend_id in removed:
                del self._registrations[backend_id]
            self._unloading_owners.discard(plugin_id)
            self._constructing_agents.pop(plugin_id, None)
            self._selecting_agents.pop(plugin_id, None)
            return removed

    def owned_by(self, plugin_id: str) -> list[str]:
        """Return backend ids owned by one plugin."""
        with self._lock:
            return [
                backend_id
                for backend_id, registration in self._registrations.items()
                if registration.plugin_id == plugin_id
            ]


class MemoryBackendUnavailableError(ValueError):
    """Raised when an explicitly selected backend is not registered."""

    def __init__(self, backend: str, reason: str = "plugin_not_installed"):
        self.backend = backend
        self.reason = reason
        super().__init__(
            f"Memory backend '{backend}' is unavailable ({reason})",
        )


memory_registry = MemoryBackendRegistry()
