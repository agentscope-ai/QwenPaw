# -*- coding: utf-8 -*-
"""Logging setup for application logging and optional file output."""
import logging
import logging.handlers
import os
import platform
import sys
from pathlib import Path

from ..constant import PROJECT_NAME, WORKING_DIR

# Rotating file handler limits (idempotent add avoids duplicate handlers)
_LOG_MAX_BYTES = 5 * 1024 * 1024  # 5 MiB
_LOG_BACKUP_COUNT = 3


_LEVEL_MAP = {
    "critical": logging.CRITICAL,
    "error": logging.ERROR,
    "warning": logging.WARNING,
    "info": logging.INFO,
    "debug": logging.DEBUG,
}

# Top-level name for this package; only loggers under this name are shown.
LOG_NAMESPACE = PROJECT_NAME.lower()

# Canonical log file name and path — import these instead of reconstructing.
LOG_FILE_BASENAME = f"{LOG_NAMESPACE}.log"
LOG_FILE_PATH = WORKING_DIR / LOG_FILE_BASENAME


def _enable_windows_ansi() -> None:
    """Enable ANSI escape code support on Windows 10+."""
    if platform.system() != "Windows":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        # STD_OUTPUT_HANDLE = -11, ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_ulong()  # pylint: disable=no-value-for-parameter
        kernel32.GetConsoleMode(handle, ctypes.byref(mode))
        kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass


# Call once at import time
_enable_windows_ansi()


class ColorFormatter(logging.Formatter):
    COLORS = {
        logging.DEBUG: "\033[34m",
        logging.INFO: "\033[32m",
        logging.WARNING: "\033[33m",
        logging.ERROR: "\033[31m",
        logging.CRITICAL: "\033[41m\033[97m",
    }
    RESET = "\033[0m"

    def format(self, record):
        # Disable colors if output is not a terminal (e.g. piped/redirected)
        use_color = hasattr(sys.stderr, "isatty") and sys.stderr.isatty()
        color = self.COLORS.get(record.levelno, "") if use_color else ""
        reset = self.RESET if use_color else ""
        level = f"{color}{record.levelname}{reset}"

        full_path = record.pathname
        cwd = os.getcwd()
        # Use os.path for cross-platform path prefix stripping
        try:
            if os.path.commonpath([full_path, cwd]) == cwd:
                full_path = os.path.relpath(full_path, cwd)
        except ValueError:
            # Different drives on Windows (e.g., C: vs D:) are not comparable.
            pass

        prefix = f"{level} {full_path}:{record.lineno}"
        original_msg = super().format(record)

        return f"{prefix} | {original_msg}"


class PlainFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        full_path = record.pathname
        cwd = os.getcwd()
        try:
            if os.path.commonpath([full_path, cwd]) == cwd:
                full_path = os.path.relpath(full_path, cwd)
        except ValueError:
            pass

        prefix = f"{record.levelname} | {full_path}:{record.lineno}"
        formatted_time = self.formatTime(record, self.datefmt)
        msg = f"{formatted_time} | {prefix} | {record.getMessage()}"

        if record.exc_info and not record.exc_text:
            record.exc_text = self.formatException(record.exc_info)
        if record.exc_text:
            msg = msg + "\n" + record.exc_text
        if record.stack_info:
            msg = msg + "\n" + self.formatStack(record.stack_info)

        return msg


class SuppressPathAccessLogFilter(logging.Filter):
    """
    Filter out uvicorn access log lines whose message contains any of the
    given path substrings. path_substrings: list of substrings; if any
    appears in the log message, the record is suppressed.
    Empty list = allow all.
    """

    def __init__(self, path_substrings: list[str]) -> None:
        super().__init__()
        self.path_substrings = path_substrings

    def filter(self, record: logging.LogRecord) -> bool:
        if not self.path_substrings:
            return True
        try:
            msg = record.getMessage()
            return not any(s in msg for s in self.path_substrings)
        except Exception:
            return True


def setup_logger(level: int | str = logging.INFO):
    """Configure logging to only output from this package, not deps."""
    log_format = "%(asctime)s | %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    if isinstance(level, str):
        level = _LEVEL_MAP.get(level.lower(), logging.INFO)

    formatter = ColorFormatter(log_format, datefmt)

    # Suppress third-party: set root logger level and configure handlers.
    root = logging.getLogger()
    for handler in root.handlers:
        if isinstance(
            handler,
            (logging.FileHandler, logging.handlers.RotatingFileHandler),
        ):
            handler.setLevel(logging.INFO)
        else:
            handler.setLevel(logging.WARNING)

    # Only attach handler to the project namespace
    # so only app logs are printed.
    logger = logging.getLogger(LOG_NAMESPACE)
    logger.setLevel(level)
    logger.propagate = False
    if not logger.handlers:
        # Use sys.stderr directly. Wrapping sys.stderr.buffer in a
        # TextIOWrapper takes ownership of the buffer and closes it on GC,
        # which corrupts sys.stderr for subsequent tests/code.
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger


def add_project_file_handler(log_path: Path) -> None:
    """Add a file handler to the project logger for daemon logs.

    Windows/Linux: Uses simple FileHandler to avoid file locking issues.
    macOS: Uses RotatingFileHandler with automatic log rotation.

    Idempotent: if the logger already has a file handler for the same path,
    no new handler is added (avoids duplicate lines and leaked descriptors
    when lifespan runs multiple times in the same process).

    Args:
        log_path: Path to the log file.
    """
    log_path = Path(log_path).resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(LOG_NAMESPACE)
    for handler in logger.handlers:
        base = getattr(handler, "baseFilename", None)
        if base is not None and Path(base).resolve() == log_path:
            return

    is_windows_or_linux = platform.system() in ("Windows", "Linux")
    if is_windows_or_linux:
        file_handler = logging.FileHandler(
            log_path,
            encoding="utf-8",
            mode="a",
        )
    else:
        file_handler = logging.handlers.RotatingFileHandler(
            log_path,
            encoding="utf-8",
            maxBytes=_LOG_MAX_BYTES,
            backupCount=_LOG_BACKUP_COUNT,
        )

    file_handler.setLevel(logger.level or logging.INFO)

    file_handler.setFormatter(
        PlainFormatter("%(asctime)s | %(message)s", "%Y-%m-%d %H:%M:%S"),
    )
    logger.addHandler(file_handler)
