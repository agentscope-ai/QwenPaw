# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Centralized logging configuration for the backend."""

from __future__ import annotations

import logging
import os
import sys
import threading
from collections.abc import Callable
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

_LOG_FORMAT = (
    "%(asctime)s | %(levelname)-8s | %(name)s | "
    "%(filename)s:%(lineno)d | %(message)s"
)
_REGISTERED_LOGGERS: set[str] = set()
_PROJECT_ID_RESOLVER: Callable[[], str | None] | None = None
_FILE_HANDLER: _CreatorRoutingFileHandler | None = None
_FILE_PATH: Path | None = None


class _SecureTimedRotatingFileHandler(TimedRotatingFileHandler):
    def _open(self):
        stream = super()._open()
        os.chmod(self.baseFilename, 0o600)
        return stream


class _CreatorRoutingFileHandler(logging.Handler):
    """Route contextual records to Project logs and the rest to system log."""

    def __init__(self, data_root: Path) -> None:
        super().__init__(logging.DEBUG)
        self.data_root = data_root.resolve(strict=False)
        self.system_path = creator_log_path(self.data_root)
        self._targets: dict[Path, _SecureTimedRotatingFileHandler] = {}
        self._targets_lock = threading.RLock()
        self._handler_for(self.system_path)

    def _handler_for(self, path: Path) -> _SecureTimedRotatingFileHandler:
        existing = self._targets.get(path)
        if existing is not None:
            return existing
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = _SecureTimedRotatingFileHandler(
            path,
            when="midnight",
            interval=1,
            backupCount=14,
            encoding="utf-8",
            delay=False,
            utc=True,
        )
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(_formatter())
        self._targets[path] = handler
        return handler

    def _path_for(self, record: logging.LogRecord) -> Path:
        project_id = getattr(record, "creator_project_id", None)
        if not project_id and _PROJECT_ID_RESOLVER is not None:
            project_id = _PROJECT_ID_RESOLVER()
        if project_id:
            try:
                return creator_log_path(
                    self.data_root,
                    project_id=str(project_id),
                )
            except Exception:
                # Invalid or deleted Project traffic is a system diagnostic.
                pass
        return self.system_path

    def emit(self, record: logging.LogRecord) -> None:
        try:
            with self._targets_lock:
                self._handler_for(self._path_for(record)).emit(record)
        except Exception:
            self.handleError(record)

    def flush(self) -> None:
        with self._targets_lock:
            for handler in self._targets.values():
                handler.flush()

    def close(self) -> None:
        with self._targets_lock:
            for handler in self._targets.values():
                handler.close()
            self._targets.clear()
        super().close()

    def close_project(self, project_id: str) -> None:
        """Close and forget one Project target before its tree is deleted."""

        # The id arrives from API path parameters; strip any directory
        # components before composing the log path so a crafted id can
        # never point the handler lookup outside the data root.
        safe_id = os.path.basename(project_id)
        if not safe_id or safe_id in {".", ".."}:
            return
        try:
            project_root = (self.data_root / safe_id).resolve(strict=False)
            if project_root.parent != self.data_root:
                return
            path = project_root / "observability" / "logs" / "creator.log"
        except (OSError, RuntimeError):
            return
        with self._targets_lock:
            handler = self._targets.pop(path, None)
            if handler is not None:
                handler.flush()
                handler.close()


def _formatter() -> logging.Formatter:
    return logging.Formatter(
        _LOG_FORMAT,
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _attach_file_handler(target: logging.Logger) -> None:
    if _FILE_HANDLER is not None and _FILE_HANDLER not in target.handlers:
        target.addHandler(_FILE_HANDLER)


def register_creator_log_project_resolver(
    resolver: Callable[[], str | None],
) -> None:
    """Register the trace-context accessor used by the routing handler."""

    global _PROJECT_ID_RESOLVER
    _PROJECT_ID_RESOLVER = resolver


def creator_log_path(
    data_root: Path | None = None,
    *,
    project_id: str | None = None,
) -> Path:
    """Return the canonical system or Project application log path."""

    if data_root is None:
        from services.storage_root import require_creator_data_root

        data_root = require_creator_data_root()
    if project_id:
        from services.observability.config import (
            project_observability_directory,
        )

        return (
            project_observability_directory(
                project_id,
                "logs",
                data_root=Path(data_root),
            )
            / "creator.log"
        )
    return (
        Path(data_root).resolve(strict=False)
        / "observability"
        / "logs"
        / "creator.log"
    )


def configure_creator_file_logging(
    data_root: Path | None = None,
) -> Path:
    """Persist Creator-owned loggers below the Creator Data Workspace.

    The PawApp imports most modules before its startup hook establishes
    ``CREATOR_DATA_ROOT``.  File logging therefore has to be attached after
    runtime-path provisioning instead of at module import time.
    """

    global _FILE_HANDLER, _FILE_PATH

    path = creator_log_path(data_root)
    if _FILE_HANDLER is not None and _FILE_PATH == path:
        return path

    previous = _FILE_HANDLER
    if previous is not None:
        for logger_name in (
            *_REGISTERED_LOGGERS,
            "qwenpaw.creator",
            "qwenpaw.plugin.qwenpaw_creator",
        ):
            logging.getLogger(logger_name).removeHandler(previous)
        previous.close()

    path.parent.mkdir(parents=True, exist_ok=True)
    handler = _CreatorRoutingFileHandler(Path(data_root or path.parents[2]))
    _FILE_HANDLER = handler
    _FILE_PATH = path

    for logger_name in _REGISTERED_LOGGERS:
        _attach_file_handler(logging.getLogger(logger_name))
    # These PawApp-owned logger families do not use ``setup_logger`` but carry
    # Creator startup, runtime-dependency, and structured-trace diagnostics.
    _attach_file_handler(logging.getLogger("qwenpaw.creator"))
    _attach_file_handler(logging.getLogger("qwenpaw.plugin.qwenpaw_creator"))
    return path


def shutdown_creator_file_logging() -> None:
    """Flush and detach the process-local Creator file handler."""

    global _FILE_HANDLER, _FILE_PATH

    handler = _FILE_HANDLER
    if handler is None:
        return
    for logger_name in (
        *_REGISTERED_LOGGERS,
        "qwenpaw.creator",
        "qwenpaw.plugin.qwenpaw_creator",
    ):
        logging.getLogger(logger_name).removeHandler(handler)
    handler.flush()
    handler.close()
    _FILE_HANDLER = None
    _FILE_PATH = None


def close_creator_project_logging(project_id: str) -> None:
    """Release a deleted Project's rotating log descriptor immediately."""

    if _FILE_HANDLER is not None:
        _FILE_HANDLER.close_project(project_id)


def setup_logger(
    name: str = "app",
    logging_level: str = "INFO",
) -> logging.Logger:
    _logger = logging.getLogger(name)
    _REGISTERED_LOGGERS.add(name)

    if _logger.handlers:
        _attach_file_handler(_logger)
        return _logger

    env_logging_level = os.environ.get("CREATOR_LOGGING_LEVEL", "").upper()
    if env_logging_level:
        logging_level = env_logging_level

    _logger.setLevel(logging_level)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging_level)
    handler.setFormatter(_formatter())
    _logger.addHandler(handler)
    _attach_file_handler(_logger)

    # Prevent propagation to root logger to avoid duplicate messages
    _logger.propagate = False

    return _logger


logger = setup_logger()


__all__ = [
    "configure_creator_file_logging",
    "close_creator_project_logging",
    "creator_log_path",
    "logger",
    "register_creator_log_project_resolver",
    "setup_logger",
    "shutdown_creator_file_logging",
]
