# -*- coding: utf-8 -*-
"""Suppress sandbox exit logs without affecting other execution contexts."""

from contextlib import contextmanager
from contextvars import ContextVar
import logging

_QUIET = ContextVar("sandbox_cleanup_quiet", default=False)


class _CleanupFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not _QUIET.get()


@contextmanager
def cleanup_logging(log_progress: bool):
    """Silence the loaded sandbox call chain before it reaches any handler."""
    if log_progress:
        yield
        return
    loggers = [
        value
        for name, value in list(logging.Logger.manager.loggerDict.items())
        if name.startswith("qwenpaw.sandbox.")
        and isinstance(value, logging.Logger)
    ]
    log_filter = _CleanupFilter()
    token = _QUIET.set(True)
    try:
        for logger in loggers:
            logger.addFilter(log_filter)
        yield
    finally:
        for logger in loggers:
            logger.removeFilter(log_filter)
        _QUIET.reset(token)
