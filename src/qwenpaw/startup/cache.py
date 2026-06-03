# -*- coding: utf-8 -*-
"""Startup-time cache management for accelerating initialization.

This module provides caching mechanisms to reduce disk I/O and module
import overhead during application startup.
It is especially useful on Windows where file access can be slower.
"""

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class StartupCache:
    """Thread-safe cache for startup data with TTL and versioning."""

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        ttl_seconds: int = 3600,
    ):
        """Initialize startup cache.

        Args:
            cache_dir: Directory for persistent cache files.
            If None, uses temp.
            ttl_seconds: Time-to-live for cache entries in seconds.
        """
        self.cache_dir = cache_dir or Path(
            os.path.expanduser("~/.qwenpaw/.cache"),
        )
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.cache_dir.chmod(0o700)
        except OSError:
            pass
        self.ttl_seconds = ttl_seconds
        self._memory_cache: Dict[str, tuple[Any, float]] = {}
        self._lock = threading.Lock()

    def _get_cache_file(self, key: str) -> Path:
        """Get the file path for a cache key."""
        # Sanitize key to be filename-safe
        safe_key = "".join(
            c if c.isalnum() or c in "-_." else "_" for c in key
        )
        return self.cache_dir / f"{safe_key}.cache"

    def get(self, key: str, version: str = "1") -> Optional[Any]:
        """Get value from cache with version checking.

        Args:
            key: Cache key
            version: Version string to validate cached data

        Returns:
            Cached value if valid, None otherwise
        """
        with self._lock:
            # Check memory cache first (fast path)
            if key in self._memory_cache:
                value, timestamp = self._memory_cache[key]
                if time.time() - timestamp < self.ttl_seconds:
                    logger.debug(f"Cache hit (memory): {key}")
                    return value
                else:
                    del self._memory_cache[key]

            # Check disk cache
            cache_file = self._get_cache_file(key)
            if cache_file.exists():
                try:
                    with open(cache_file, "r", encoding="utf-8") as f:
                        data = json.load(f)

                    # Check version and TTL
                    if (
                        data.get("version") == version
                        and time.time() - data.get("timestamp", 0)
                        < self.ttl_seconds
                    ):
                        value = data.get("value")
                        # Cache in memory for next access
                        self._memory_cache[key] = (value, time.time())
                        logger.debug(f"Cache hit (disk): {key}")
                        return value
                    else:
                        # Stale cache, remove it
                        cache_file.unlink(missing_ok=True)
                except Exception as e:
                    logger.debug(f"Failed to read cache {key}: {e}")

        return None

    def set(self, key: str, value: Any, version: str = "1") -> None:
        """Set value in cache.

        Args:
            key: Cache key
            value: Value to cache (must be JSON-serializable)
            version: Version string for validation
        """
        with self._lock:
            try:
                # Update memory cache
                self._memory_cache[key] = (value, time.time())

                # Update disk cache
                cache_file = self._get_cache_file(key)
                data = {
                    "version": version,
                    "timestamp": time.time(),
                    "value": value,
                }
                cache_file.write_text(
                    json.dumps(data, ensure_ascii=False),
                    encoding="utf-8",
                )
                try:
                    cache_file.chmod(0o600)
                except OSError:
                    pass
                logger.debug(f"Cache set: {key}")
            except Exception as e:
                logger.warning(f"Failed to set cache {key}: {e}")

    def clear(self, key: Optional[str] = None) -> None:
        """Clear cache entry or all cache.

        Args:
            key: Specific key to clear, or None to clear all
        """
        with self._lock:
            if key is None:
                # Clear all
                self._memory_cache.clear()
                try:
                    for cache_file in self.cache_dir.glob("*.cache"):
                        cache_file.unlink(missing_ok=True)
                except Exception as e:
                    logger.warning(f"Failed to clear cache directory: {e}")
            else:
                # Clear specific key
                self._memory_cache.pop(key, None)
                cache_file = self._get_cache_file(key)
                cache_file.unlink(missing_ok=True)


# Global startup cache instance
_startup_cache: Optional[StartupCache] = None


def get_startup_cache() -> StartupCache:
    """Get or create the global startup cache instance."""
    global _startup_cache
    if _startup_cache is None:
        from ..constant import WORKING_DIR

        cache_dir = Path(WORKING_DIR) / ".cache" / "startup"
        _startup_cache = StartupCache(cache_dir=cache_dir)
    return _startup_cache
