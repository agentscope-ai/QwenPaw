# -*- coding: utf-8 -*-
"""Generic registry for registering and retrieving implementations."""

from typing import Callable, Generic, Type, TypeVar

T = TypeVar("T")


class Registry(Generic[T]):
    """Generic registry for registering and retrieving implementations.

    Example:
        from qwenpaw.agents.context.base_context_manager import (
            context_registry,
        )

        @context_registry.register("light")
        class LightContextManager(BaseContextManager):
            ...

        cls = context_registry.get("light")
        instance = cls(working_dir=..., agent_id=...)
    """

    def __init__(self) -> None:
        self._registry: dict[str, Type[T]] = {}

    def register(self, name: str) -> Callable[[Type[T]], Type[T]]:
        """Decorator to register an implementation."""

        def decorator(impl_class: Type[T]) -> Type[T]:
            self._registry[name.lower()] = impl_class
            return impl_class

        return decorator

    def get(self, name: str) -> Type[T] | None:
        """Get registered implementation class by name."""
        return self._registry.get(name.lower())

    def list_registered(self) -> list[str]:
        """List all registered implementation names."""
        return list(self._registry.keys())

    def has(self, name: str) -> bool:
        """Check if an implementation is registered."""
        return name.lower() in self._registry
