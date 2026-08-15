# -*- coding: utf-8 -*-
"""Atomic persistence primitives for provider JSON snapshots."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

from ..security.secret_store import (
    PROVIDER_SECRET_FIELDS,
    encrypt_dict_fields,
)
from ..utils.io_utils import get_sync_path_lock
from .provider import Provider


def replace_with_retry(
    src: str,
    dst: str,
    *,
    attempts: int = 5,
    delay: float = 0.1,
) -> None:
    """Atomically replace a path despite transient Windows file locks."""
    for attempt in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)


def write_provider_snapshot(
    provider: Provider,
    provider_path: Path,
) -> None:
    """Encrypt and atomically write one provider snapshot."""
    with get_sync_path_lock(provider_path):
        data = encrypt_dict_fields(
            provider.model_dump(exclude={"models_syncing"}),
            PROVIDER_SECRET_FIELDS,
        )
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{provider.id}.",
            suffix=".tmp",
            dir=provider_path.parent,
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            replace_with_retry(temp_name, str(provider_path))
            try:
                os.chmod(provider_path, 0o600)
            except OSError:
                pass
        finally:
            if os.path.exists(temp_name):
                try:
                    os.remove(temp_name)
                except OSError:
                    pass
