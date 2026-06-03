# -*- coding: utf-8 -*-
"""Optimized configuration loading with caching and lazy initialization.

Extends config.utils with startup optimizations specific to Windows.
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional, Tuple

from ..config.config import Config
from ..config.utils import load_config as _original_load_config
from ..envs import load_envs_into_environ as _original_load_envs
from ..startup.cache import get_startup_cache

logger = logging.getLogger(__name__)


class OptimizedConfigLoader:
    """Configuration loader with caching and parallel initialization."""

    def __init__(self):
        """Initialize optimized config loader."""
        self._cache = get_startup_cache()
        self._config_version = "1"

    def load_config_cached(self, config_path: Optional[Path] = None) -> Config:
        """Load configuration with disk cache support.

        This reduces repeated file I/O on Windows by caching the loaded
        config object.

        Args:
            config_path: Path to config file, or None for default

        Returns:
            Loaded Config object
        """
        if config_path is None:
            from ..config.utils import get_config_path

            config_path = get_config_path()

        cache_key = f"config_{config_path}"

        # Incorporate file mtime into cache version to invalidate on changes.
        try:
            config_mtime = (
                config_path.stat().st_mtime if config_path.is_file() else 0.0
            )
        except OSError:
            config_mtime = 0.0
        cache_version = f"{self._config_version}:{config_mtime}"

        # Try to get from cache first
        cached_payload = self._cache.get(cache_key, version=cache_version)
        if cached_payload is not None:
            logger.debug("Using cached configuration")
            return Config.model_validate(cached_payload)

        # Load from disk
        logger.debug("Loading configuration from disk")
        config = _original_load_config(config_path)

        # Cache for next time
        try:
            self._cache.set(
                cache_key,
                config.model_dump(),
                version=cache_version,
            )
        except Exception as e:
            logger.debug(f"Failed to cache config: {e}")

        return config

    def clear_config_cache(self, config_path: Optional[Path] = None) -> None:
        """Clear cached configuration (e.g., after config changes).

        Args:
            config_path: Path to config file, or None for default
        """
        cache_key = f"config_{str(config_path or 'default')}"
        self._cache.clear(cache_key)
        logger.debug("Cleared configuration cache")


async def parallel_load_envs_and_config(
    config_path: Optional[Path] = None,
) -> Tuple[Config, bool]:
    """Load environment variables and configuration in parallel.

    On Windows, this can provide measurable speedup by overlapping
    I/O operations.

    Args:
        config_path: Path to config file, or None for default

    Returns:
        Tuple of (config, envs_loaded)
    """
    loader = OptimizedConfigLoader()

    # Create tasks for parallel execution
    env_task = asyncio.create_task(_load_envs_async())
    config_task = asyncio.create_task(
        asyncio.to_thread(loader.load_config_cached, config_path),
    )

    # Wait for both to complete
    config, envs_loaded = await asyncio.gather(
        config_task,
        env_task,
    )

    logger.debug("Parallel config/env load completed")
    return config, envs_loaded


async def _load_envs_async() -> bool:
    """Load environment variables asynchronously.

    Returns:
        True if envs were loaded
    """
    try:
        await asyncio.to_thread(_original_load_envs)
        logger.debug("Environment variables loaded")
        return True
    except Exception as e:
        logger.debug(f"Failed to load environment variables: {e}")
        return False


# Global loader instance
_loader: Optional[OptimizedConfigLoader] = None


def get_config_loader() -> OptimizedConfigLoader:
    """Get or create the global config loader instance."""
    global _loader
    if _loader is None:
        _loader = OptimizedConfigLoader()
    return _loader
