# -*- coding: utf-8 -*-
"""Service management system for Workspace components.

Provides unified registration, lifecycle management, and dependency handling
for all workspace services (MemoryManager, ChatManager, etc.).
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import (
    TYPE_CHECKING,
    Any,
    Awaitable,
    Callable,
    Dict,
    List,
    Optional,
    Set,
    Union,
)

if TYPE_CHECKING:
    from .workspace import Workspace

logger = logging.getLogger(__name__)


@dataclass
class ServiceDescriptor:
    """Descriptor for a workspace service component.

    Defines metadata and lifecycle hooks for a service that can be
    managed by ServiceManager.

    Attributes:
        name: Unique service identifier (e.g., 'memory_manager')
        service_class: Class to instantiate (e.g., MemoryManager)
        init_args: Callable that returns init kwargs for the service
        post_init: Optional hook called after creation (for setup logic)
        start_method: Name of method to call after creation (e.g., 'start')
        stop_method: Name of method to call during shutdown (e.g., 'stop')
        reusable: Whether this service can be reused across reloads
        reload_func: Optional hook called when reusable service is reused
        dependencies: List of service names that must start before this one
        priority: Startup priority (lower = earlier, reversed for shutdown)
        concurrent_init: Whether this can be initialized concurrently
    """

    name: str
    service_class: Optional[Union[type, Callable[["Workspace"], type]]] = None
    init_args: Optional[Callable[[Workspace], dict]] = None
    post_init: Optional[
        Union[
            Callable[[Workspace, Any], None],
            Callable[[Workspace, Any], Awaitable[Any]],
        ]
    ] = None
    start_method: Optional[str] = None
    stop_method: Optional[str] = None
    reusable: bool = False
    reload_func: Optional[
        Union[
            Callable[[Workspace, Any], None],
            Callable[[Workspace, Any], Awaitable[Any]],
        ]
    ] = None
    dependencies: List[str] = field(default_factory=list)
    priority: int = 100
    concurrent_init: bool = True


class ServiceManager:
    """Unified manager for workspace service components.

    Handles registration, lifecycle (start/stop), dependency resolution,
    and component reuse during reload.
    """

    def __init__(self, workspace: Workspace):
        """Initialize service manager.

        Args:
            workspace: The Workspace instance that owns these services
        """
        self.workspace = workspace
        self.services: Dict[str, Any] = {}
        self.descriptors: Dict[str, ServiceDescriptor] = {}
        self.reused_services: Set[str] = set()

    def register(self, descriptor: ServiceDescriptor) -> None:
        """Register a service descriptor.

        Args:
            descriptor: Service descriptor to register
        """
        if descriptor.name in self.descriptors:
            logger.warning(
                f"Service '{descriptor.name}' already registered, "
                f"overwriting",
            )
        self.descriptors[descriptor.name] = descriptor
        logger.debug(f"Registered service: {descriptor.name}")

    async def set_reusable(self, name: str, instance: Any) -> None:
        """Mark a service instance as reused from previous workspace.

        Must be called before start_all(). If the service descriptor has a
        reload_func, it will be called with the workspace and instance.

        Args:
            name: Service name
            instance: Service instance to reuse
        """
        if name not in self.descriptors:
            logger.warning(
                f"Unknown service '{name}', cannot mark as reusable",
            )
            return

        descriptor = self.descriptors[name]
        if not descriptor.reusable:
            logger.warning(
                f"Service '{name}' is not marked as reusable "
                f"in its descriptor",
            )
            return

        self.services[name] = instance
        self.reused_services.add(name)
        logger.debug(f"Marked service '{name}' as reused")

        # Trigger reload_func if provided
        if descriptor.reload_func is not None:
            try:
                result = descriptor.reload_func(self.workspace, instance)
                if asyncio.iscoroutine(result):
                    await result
                logger.debug(f"Called reload_func for service '{name}'")
            except Exception as e:
                logger.warning(
                    f"Error calling reload_func for service '{name}': {e}",
                )

    def get_reusable_services(self) -> Dict[str, Any]:
        """Get all reusable service instances for transfer to new workspace.

        Returns:
            Dict mapping service names to instances
        """
        reusable = {}
        for name, descriptor in self.descriptors.items():
            if descriptor.reusable and name in self.services:
                reusable[name] = self.services[name]
        return reusable

    def _group_by_priority(self) -> Dict[int, List[ServiceDescriptor]]:
        """Group service descriptors by priority.

        Returns:
            Dict mapping priority to list of descriptors
        """
        groups: Dict[int, List[ServiceDescriptor]] = {}
        for descriptor in self.descriptors.values():
            if descriptor.priority not in groups:
                groups[descriptor.priority] = []
            groups[descriptor.priority].append(descriptor)
        return groups

    async def start_all(self) -> None:
        """Start all registered services in priority order.

        Services with same priority are started concurrently if allowed.
        Reused services are skipped.
        """
        logger.debug(
            f"Starting {len(self.descriptors)} services "
            f"({len(self.reused_services)} reused)",
        )

        priority_groups = self._group_by_priority()

        for priority in sorted(priority_groups.keys()):
            descriptors = priority_groups[priority]

            # Separate concurrent and sequential services
            concurrent = [d for d in descriptors if d.concurrent_init]
            sequential = [d for d in descriptors if not d.concurrent_init]

            # Start concurrent services in parallel
            if concurrent:
                await asyncio.gather(
                    *[self._start_service(desc) for desc in concurrent],
                )

            # Start sequential services one by one
            for desc in sequential:
                await self._start_service(desc)

    async def _start_service(self, descriptor: ServiceDescriptor) -> None:
        """Start a single service.

        Args:
            descriptor: Service descriptor
        """
        name = descriptor.name
        is_reused = name in self.reused_services

        if is_reused:
            logger.info(
                f"Reusing service '{name}' for {self.workspace.agent_id}",
            )

        try:
            service = await self._get_or_create_service(
                descriptor,
                is_reused,
            )
            service = await self._run_post_init(descriptor, service, name)
            await self._run_start_method(descriptor, service, is_reused)

        except Exception as e:
            logger.exception(
                f"Failed to start service '{name}' "
                f"for {self.workspace.agent_id}: {e}",
            )
            raise

    async def _get_or_create_service(
        self,
        descriptor: ServiceDescriptor,
        is_reused: bool,
    ) -> Any:
        """Get existing or create new service instance.

        Args:
            descriptor: Service descriptor
            is_reused: Whether service is being reused

        Returns:
            Service instance or None
        """
        if is_reused:
            return self.services.get(descriptor.name)

        logger.debug(f"Creating service '{descriptor.name}'...")

        if not descriptor.service_class:
            return None

        # service_class may be a callable that resolves to the actual class
        if not isinstance(descriptor.service_class, type):
            service_cls = descriptor.service_class(self.workspace)
        else:
            service_cls = descriptor.service_class

        # Get init args from callable
        init_kwargs = {}
        if descriptor.init_args:
            init_kwargs = descriptor.init_args(self.workspace)

        # Instantiate service
        service = service_cls(**init_kwargs)
        self.services[descriptor.name] = service
        return service

    async def _run_post_init(
        self,
        descriptor: ServiceDescriptor,
        service: Any,
        name: str,
    ) -> Any:
        """Run post_init hook and capture returned service.

        Args:
            descriptor: Service descriptor
            service: Current service instance (may be None)
            name: Service name

        Returns:
            Final service instance
        """
        if not descriptor.post_init:
            return service

        result = descriptor.post_init(self.workspace, service)
        if asyncio.iscoroutine(result):
            result = await result

        # Capture service from post_init return value or self.services
        if result is not None:
            service = result
            # Ensure it's registered in services dict
            if name not in self.services:
                self.services[name] = service
        elif service is None:
            # post_init might have registered service in self.services
            service = self.services.get(name)

        return service

    async def _run_start_method(
        self,
        descriptor: ServiceDescriptor,
        service: Any,
        is_reused: bool,
    ) -> None:
        """Run start method on service if applicable.

        Args:
            descriptor: Service descriptor
            service: Service instance
            is_reused: Whether service is being reused
        """
        if is_reused or not descriptor.start_method or not service:
            return

        start_fn = getattr(service, descriptor.start_method)
        if asyncio.iscoroutinefunction(start_fn):
            await start_fn()
        else:
            start_fn()

        logger.debug(
            f"Service '{descriptor.name}' started for "
            f"{self.workspace.agent_id}",
        )

    async def stop_all(self, final: bool = False) -> None:
        """Stop all services in reverse priority order.

        Args:
            final: If True, stop ALL services including reusable ones.
                   If False (default), skip reusable services (for reload).

        Reused services are skipped. Errors are logged but don't stop
        the shutdown process.
        """
        logger.debug(
            f"Stopping {len(self.services)} services "
            f"({len(self.reused_services)} reused, final={final})",
        )

        priority_groups = self._group_by_priority()

        # Stop in reverse priority order
        for priority in sorted(priority_groups.keys(), reverse=True):
            descriptors = priority_groups[priority]

            # Stop all services in this priority group concurrently
            results = await asyncio.gather(
                *[
                    self._stop_service(desc, final=final)
                    for desc in descriptors
                ],
                return_exceptions=True,
            )

            # Log any exceptions that occurred
            for desc, result in zip(descriptors, results):
                if isinstance(result, Exception):
                    logger.warning(
                        f"Error stopping service '{desc.name}': {result}",
                    )

    async def _stop_service(
        self,
        descriptor: ServiceDescriptor,
        final: bool = False,
    ) -> None:
        """Stop a single service.

        Args:
            descriptor: Service descriptor
            final: If True, stop service even if reusable.
                   If False, skip reusable services (for reload).
        """
        name = descriptor.name

        # Skip reusable services UNLESS this is final shutdown
        # (may be transferred to new instance during reload)
        if descriptor.reusable and not final:
            logger.debug(
                f"Skipped stopping reusable service '{name}' "
                f"for {self.workspace.agent_id} (will be reused)",
            )
            return

        # Skip services that were reused from previous instance
        # (they don't belong to this instance)
        if name in self.reused_services:
            logger.debug(
                f"Skipped stopping reused service '{name}' "
                f"(from previous instance) for {self.workspace.agent_id}",
            )
            return

        service = self.services.get(name)
        if not service:
            return

        try:
            if descriptor.stop_method:
                stop_fn = getattr(service, descriptor.stop_method, None)
                if stop_fn:
                    if asyncio.iscoroutinefunction(stop_fn):
                        await stop_fn()
                    else:
                        stop_fn()
                    logger.debug(
                        f"Service '{name}' stopped "
                        f"for {self.workspace.agent_id}",
                    )
        except Exception as e:
            logger.warning(
                f"Error stopping service '{name}' "
                f"for {self.workspace.agent_id}: {e}",
            )
            raise
