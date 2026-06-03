# -*- coding: utf-8 -*-
"""Lazy loading and parallel initialization for startup optimization.

Provides utilities for deferring expensive operations until actually needed,
and for parallelizing independent initialization tasks.
"""

import asyncio
import functools
import logging
import threading
from typing import Any, Callable, Coroutine, Generic, List, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class LazyLoader(Generic[T]):
    """Deferred loading wrapper for expensive objects."""

    def __init__(self, loader_fn: Callable[[], T], name: str = ""):
        """Initialize lazy loader.

        Args:
            loader_fn: Function to call when value is first accessed
            name: Optional name for logging
        """
        self._loader_fn = loader_fn
        self._name = name
        self._value: Optional[T] = None
        self._loaded = False
        self._lock = threading.Lock()

    def get(self) -> T:
        """Get the value, loading if necessary.

        Returns:
            Loaded value
        """
        if self._loaded:
            assert self._value is not None
            return self._value

        with self._lock:
            if not self._loaded:
                try:
                    logger.debug(f"LazyLoader: Loading {self._name}")
                    self._value = self._loader_fn()
                    self._loaded = True
                except Exception as e:
                    logger.error(
                        f"LazyLoader: Failed to load {self._name}: {e}",
                    )
                    raise

        return self._value

    def is_loaded(self) -> bool:
        """Check if value has been loaded."""
        return self._loaded

    def __call__(self) -> T:
        """Allow using loader as callable."""
        return self.get()


def lazy_property(fn: Callable[..., T]) -> property:
    """Decorator to make a property lazy-loaded.

    Usage:
        class MyClass:
            @lazy_property
            def expensive_attribute(self):
                return expensive_operation()
    """

    @functools.wraps(fn)
    def wrapper(self):
        attr_name = f"_lazy_{fn.__name__}"
        if not hasattr(self, attr_name):
            setattr(self, attr_name, fn(self))
        return getattr(self, attr_name)

    return property(wrapper)


async def parallel_tasks(
    tasks: List[Coroutine[Any, Any, T]],
    max_concurrent: Optional[int] = None,
    name: str = "parallel_tasks",
) -> List[T]:
    """Execute coroutines in parallel with optional concurrency limit.

    Args:
        tasks: List of coroutines to execute
        max_concurrent: Max concurrent tasks, or None for unlimited
        name: Name for logging

    Returns:
        List of results in the same order as tasks
    """
    if not tasks:
        return []

    if max_concurrent is None or max_concurrent >= len(tasks):
        # Run all in parallel
        logger.debug(
            f"{name}: Running {len(tasks)} tasks in parallel (no limit)",
        )
        return await asyncio.gather(*tasks)
    else:
        # Run with semaphore to limit concurrency
        logger.debug(
            f"{name}: Running {len(tasks)} tasks "
            f"with max {max_concurrent} concurrent",
        )
        semaphore = asyncio.Semaphore(max_concurrent)

        async def bounded_task(task: Coroutine[Any, Any, T]) -> T:
            async with semaphore:
                return await task

        return await asyncio.gather(*[bounded_task(task) for task in tasks])


def parallel_sync_tasks(
    tasks: List[Callable[[], T]],
    max_workers: Optional[int] = None,
    name: str = "parallel_tasks",
) -> List[T]:
    """Execute sync functions in parallel using ThreadPoolExecutor.

    Args:
        tasks: List of callables to execute
        max_workers: Max worker threads, or None for default
        name: Name for logging

    Returns:
        List of results in the same order as tasks
    """
    if not tasks:
        return []

    from concurrent.futures import ThreadPoolExecutor

    logger.debug(
        f"{name}: Running {len(tasks)} sync tasks in parallel"
        f" (max_workers={max_workers})",
    )

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(task) for task in tasks]
        return [f.result() for f in futures]


class ProgressiveInitializer:
    """Manager for progressive initialization with priority levels.

    Allows organizing initialization tasks into phases (critical, important,
    background) so critical initialization happens first.
    """

    def __init__(self):
        """Initialize progressive initializer."""
        self._critical: List[Coroutine[Any, Any, Any]] = []
        self._important: List[Coroutine[Any, Any, Any]] = []
        self._background: List[Coroutine[Any, Any, Any]] = []

    def add_critical(self, coro: Coroutine[Any, Any, Any]) -> None:
        """Add critical initialization (must complete before startup)."""
        self._critical.append(coro)

    def add_important(self, coro: Coroutine[Any, Any, Any]) -> None:
        """Add important initialization (start early, background OK)."""
        self._important.append(coro)

    def add_background(self, coro: Coroutine[Any, Any, Any]) -> None:
        """Add background initialization (lowest priority)."""
        self._background.append(coro)

    async def initialize(self) -> tuple[List[Any], asyncio.Task[Any]]:
        """Execute initialization in priority order.

        Returns:
            Tuple of (critical_results, background_task)
            - critical_results: Results from critical phase
            - background_task: Async task for important/background phases
        """
        # Phase 1: Critical path (must complete)
        logger.debug(
            "ProgressiveInitializer: Critical phase (%s tasks)",
            len(self._critical),
        )
        critical_results = await parallel_tasks(self._critical)

        # Phase 2: Important + Background (run concurrently in background)
        async def deferred_init():
            logger.debug(
                "ProgressiveInitializer: "
                "Deferred phase (%s important, %s background)",
                len(self._important),
                len(self._background),
            )
            important_results = await parallel_tasks(self._important)
            background_results = await parallel_tasks(self._background)
            return important_results + background_results

        bg_task = asyncio.create_task(deferred_init())

        return critical_results, bg_task
