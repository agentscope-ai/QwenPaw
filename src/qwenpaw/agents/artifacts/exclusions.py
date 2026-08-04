"""Default exclusions for bounded workspace artifact scans."""

from pathlib import Path

EXCLUDED_DIRECTORY_NAMES = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".qwenpaw",
        ".ruff_cache",
        "__pycache__",
        "node_modules",
    },
)

EXCLUDED_FILE_NAMES = frozenset(
    {
        "history.db",
        "history.db-shm",
        "history.db-wal",
    },
)

EXCLUDED_FILE_SUFFIXES = (
    ".lock",
    ".part",
    ".swp",
    ".swo",
    ".tmp",
    "~",
)


def is_excluded_directory(path: Path) -> bool:
    """Return whether a directory contains non-artifact runtime data."""
    return path.name in EXCLUDED_DIRECTORY_NAMES


def is_excluded_file(path: Path) -> bool:
    """Return whether a file is internal or temporary workspace state."""
    name = path.name
    return name in EXCLUDED_FILE_NAMES or name.endswith(
        EXCLUDED_FILE_SUFFIXES,
    )
