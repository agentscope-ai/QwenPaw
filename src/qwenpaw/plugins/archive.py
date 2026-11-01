# -*- coding: utf-8 -*-
"""Shared bounded plugin archive extraction for HTTP and bundled sources."""

from pathlib import Path, PurePosixPath
import stat


def safe_extract_zip(archive, destination):
    """Reject duplicate, escaping, linked or oversized ZIP members."""
    root = Path(destination).resolve()
    entries = archive.infolist()
    if (
        len(entries) > 50000
        or sum(row.file_size for row in entries) > 256 * 1024 * 1024
    ):
        raise ValueError("Plugin archive exceeds limits")
    names = set()
    for row in entries:
        name = row.filename
        path = PurePosixPath(name)
        # pylint: disable=too-many-boolean-expressions
        if (
            not name
            or "\\" in name
            or ":" in name
            or path.is_absolute()
            or any(
                part in {"", ".", ".."} for part in name.rstrip("/").split("/")
            )
            or stat.S_ISLNK(row.external_attr >> 16)
            or name.casefold() in names
            or not (root / name).resolve().is_relative_to(root)
        ):
            raise ValueError("Zip Slip detected: unsafe plugin archive path")
        names.add(name.casefold())
    archive.extractall(root)
