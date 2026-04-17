# -*- coding: utf-8 -*-
"""Shared ReMeLight helpers for context and memory managers."""
import importlib.metadata
import logging
import platform

from qwenpaw.config.config import load_agent_config
from qwenpaw.constant import EnvVarLoader

logger = logging.getLogger(__name__)

_EXPECTED_REME_VERSION = "0.3.1.8"


def _detect_memory_manager_backend() -> str:
    """Detect the memory store backend from environment variables.

    Resolves ``MEMORY_STORE_BACKEND`` with the following priority:
    - ``local``: always used on Windows
    - ``chroma``: used when ``chromadb`` is importable (non-Windows)
    - falls back to ``local`` when ``chromadb`` is unavailable

    Returns:
        Backend name string: ``"local"``, ``"chroma"``, or any explicitly
        configured value.
    """
    backend_env = EnvVarLoader.get_str("MEMORY_STORE_BACKEND", "auto")
    if backend_env != "auto":
        return backend_env

    if platform.system() == "Windows":
        return "local"

    try:
        import chromadb  # noqa: F401 pylint: disable=unused-import

        return "chroma"
    except Exception as e:
        logger.warning(
            f"""
chromadb import failed, falling back to `local` backend.
This is often caused by an outdated system SQLite (requires >= 3.35).
Please upgrade your system SQLite to >= 3.35.
See: https://docs.trychroma.com/docs/overview/troubleshooting#sqlite
| Error: {e}
            """,
        )
        return "local"


class ReMeLightMixin:
    """Mixin providing shared ReMeLight helpers.

    Both ``LightContextManager`` and ``ReMeLightMemoryManager`` use the
    same version-checking and embedding-config logic.
    This mixin centralizes that code to eliminate duplication.

    Concrete classes must expose the following attributes (either by
    inheriting from a base class or setting them in ``__init__``):
        agent_id: str
        _reme_version_ok: bool
    """

    agent_id: str
    _reme_version_ok: bool

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _mask_key(key: str) -> str:
        """Mask an API key, showing only the first 5 characters."""
        return key[:5] + "*" * (len(key) - 5) if len(key) > 5 else key

    @staticmethod
    def _check_reme_version() -> bool:
        """Return ``False`` (and warn) when the installed reme-ai version
        does not match the expected version."""
        try:
            installed = importlib.metadata.version("reme-ai")
        except importlib.metadata.PackageNotFoundError:
            return True
        if installed != _EXPECTED_REME_VERSION:
            logger.warning(
                f"reme-ai version mismatch: installed={installed}, "
                f"expected={_EXPECTED_REME_VERSION}. "
                f"Run `pip install reme-ai=={_EXPECTED_REME_VERSION}`"
                " to align.",
            )
            return False
        return True

    # ------------------------------------------------------------------
    # Instance helpers
    # ------------------------------------------------------------------

    def _warn_if_version_mismatch(self) -> None:
        """Warn once per call if the cached version check failed."""
        if not self._reme_version_ok:
            logger.warning(
                "reme-ai version mismatch, "
                f"expected={_EXPECTED_REME_VERSION}. "
                f"Run `pip install reme-ai=={_EXPECTED_REME_VERSION}`"
                " to align.",
            )

    def get_embedding_config(self) -> dict:
        """Return embedding config with priority: config > env var > default."""
        self._warn_if_version_mismatch()
        cfg = load_agent_config(self.agent_id).running.reme_light_memory_config.embedding_model_config
        return {
            "backend": cfg.backend,
            "api_key": cfg.api_key
            or EnvVarLoader.get_str("EMBEDDING_API_KEY"),
            "base_url": cfg.base_url
            or EnvVarLoader.get_str("EMBEDDING_BASE_URL"),
            "model_name": cfg.model_name
            or EnvVarLoader.get_str("EMBEDDING_MODEL_NAME"),
            "dimensions": cfg.dimensions,
            "enable_cache": cfg.enable_cache,
            "use_dimensions": cfg.use_dimensions,
            "max_cache_size": cfg.max_cache_size,
            "max_input_length": cfg.max_input_length,
            "max_batch_size": cfg.max_batch_size,
        }

